from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
import json
from time import perf_counter
from typing import Any

from sqlalchemy import Engine

from quant_trading.backtest.engine import BacktestEngine
from quant_trading.core.models import Bar
from quant_trading.data.quality import build_data_quality_report
from quant_trading.jobs.cancellation import CancellationToken
from quant_trading.security import sanitize_error_message
from quant_trading.storage.db import session_scope
from quant_trading.storage.models import AgentCandidateReviewORM, BacktestRunORM
from quant_trading.storage.repositories import (
    AgentCandidateReviewRepository,
    DataQualityReportRepository,
    MarketDataRepository,
    ResearchValidationReportRepository,
)
from quant_trading.strategy.builtin.ma_cross import MACrossStrategy
from quant_trading.validation.metrics import (
    buy_and_hold_benchmark,
    metric_payload_from_run,
)
from quant_trading.workflows.operations import (
    DEFAULT_COMMISSION_RATE,
    DEFAULT_SLIPPAGE_RATE,
)


class ResearchValidationError(ValueError):
    pass


class ResearchValidationNotFoundError(ResearchValidationError):
    pass


class ResearchValidationConflictError(ResearchValidationError):
    pass


ELIGIBLE_CANDIDATE_STATUSES = {
    "backtest_succeeded",
    "review_requested",
    "review_succeeded",
    "review_failed",
}


def run_candidate_research_validation(
    engine: Engine,
    *,
    candidate_review_id: int,
    job_run_id: int | None = None,
    cancellation_token: CancellationToken | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    started_counter = perf_counter()
    started_at = _utcnow()
    report_id: int | None = None

    def checkpoint(progress: int, message: str) -> None:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        if progress_callback is not None:
            progress_callback(progress, message)

    try:
        checkpoint(0, "starting research validation")
        with session_scope(engine) as session:
            review_repo = AgentCandidateReviewRepository(session)
            report_repo = ResearchValidationReportRepository(session)
            review = review_repo.get(candidate_review_id)
            if review is None:
                raise ResearchValidationNotFoundError(
                    f"candidate review not found: {candidate_review_id}"
                )
            payload = _parse_payload(review)
            source_backtest = _validate_candidate_review(session, review)
            report = report_repo.create_or_reset_running(
                candidate_review_id=review.id,
                source_backtest_run_id=source_backtest.id,
                data_quality_report_id=None,
                job_run_id=job_run_id,
                symbol=review.symbol,
                strategy_name=review.strategy_name,
                started_at=started_at,
            )
            review_repo.link_research_validation_report(
                review,
                research_validation_report_id=report.id,
                updated_at=started_at,
            )
            report_id = report.id
            source_backtest_run_id = source_backtest.id
            symbol = review.symbol

        checkpoint(10, "loaded candidate review")
        dq_result = build_data_quality_report(
            engine,
            symbol=symbol,
            candidate_review_id=candidate_review_id,
            backtest_run_id=source_backtest_run_id,
            job_run_id=job_run_id,
        )
        dq_report_id = int(dq_result["report_id"])
        checkpoint(25, "completed data quality report")

        with session_scope(engine) as session:
            review = AgentCandidateReviewRepository(session).get(candidate_review_id)
            if review is not None:
                AgentCandidateReviewRepository(session).link_data_quality_report(
                    review,
                    data_quality_report_id=dq_report_id,
                    updated_at=_utcnow(),
                )
            report = ResearchValidationReportRepository(session).get(report_id)
            if report is None:
                raise ResearchValidationNotFoundError(
                    f"research validation report not found: {report_id}"
                )
            report.data_quality_report_id = dq_report_id
            session.flush()

        if dq_result["status"] == "failed":
            return _complete_failed_data_quality_report(
                engine,
                report_id=report_id,
                dq_report_id=dq_report_id,
                candidate_review_id=candidate_review_id,
                dq_result=dq_result,
                started_counter=started_counter,
            )

        checkpoint(30, "loading market bars")
        with session_scope(engine) as session:
            bars = MarketDataRepository(session).list_bars(symbol)
        if not bars:
            raise ResearchValidationConflictError(
                f"no market bars found for symbol: {symbol}"
            )
        in_sample_bars, out_of_sample_bars = _split_70_30(bars)
        short_window = _positive_int(payload.get("short_window"), "short_window")
        long_window = _positive_int(payload.get("long_window"), "long_window")
        order_size = _positive_int(payload.get("order_size"), "order_size")
        initial_cash = _positive_decimal(payload.get("initial_cash"), "initial_cash")

        in_sample_metrics = _run_ma_cross_metrics(
            engine,
            symbol=symbol,
            short_window=short_window,
            long_window=long_window,
            order_size=order_size,
            initial_cash=initial_cash,
            start=in_sample_bars[0].timestamp,
            end=in_sample_bars[-1].timestamp,
        )
        out_of_sample_metrics = _run_ma_cross_metrics(
            engine,
            symbol=symbol,
            short_window=short_window,
            long_window=long_window,
            order_size=order_size,
            initial_cash=initial_cash,
            start=out_of_sample_bars[0].timestamp,
            end=out_of_sample_bars[-1].timestamp,
        )
        checkpoint(45, "completed sample split backtests")

        walk_forward_payload = _build_walk_forward_payload(
            engine,
            bars=bars,
            symbol=symbol,
            short_window=short_window,
            long_window=long_window,
            order_size=order_size,
            initial_cash=initial_cash,
        )
        checkpoint(70, "completed walk-forward validation")

        parameter_sensitivity_payload = _build_parameter_sensitivity_payload(
            engine,
            bars=bars,
            symbol=symbol,
            short_window=short_window,
            long_window=long_window,
            order_size=order_size,
            initial_cash=initial_cash,
        )
        checkpoint(85, "completed parameter sensitivity")

        benchmark_payload = _benchmark_comparison_payload(
            out_of_sample_bars,
            out_of_sample_metrics=out_of_sample_metrics,
            initial_cash=initial_cash,
        )
        validation_status, readiness_floor, reasons = _determine_status(
            data_quality_status=dq_result["status"],
            out_of_sample_metrics=out_of_sample_metrics,
            walk_forward_payload=walk_forward_payload,
            parameter_sensitivity_payload=parameter_sensitivity_payload,
            benchmark_payload=benchmark_payload,
            short_window=short_window,
            long_window=long_window,
        )
        summary_payload = {
            "candidate_review_id": candidate_review_id,
            "source_backtest_run_id": source_backtest_run_id,
            "data_quality_status": dq_result["status"],
            "data_quality_report_id": dq_report_id,
            "validation_status": validation_status,
            "readiness_floor": readiness_floor,
            "reasons": reasons,
            "research_only": True,
        }

        finished_at = _utcnow()
        with session_scope(engine) as session:
            report_repo = ResearchValidationReportRepository(session)
            report = report_repo.get(report_id)
            if report is None:
                raise ResearchValidationNotFoundError(
                    f"research validation report not found: {report_id}"
                )
            report_repo.mark_completed(
                report,
                validation_status=validation_status,
                readiness_floor=readiness_floor,
                data_quality_report_id=dq_report_id,
                in_sample_metrics_payload=_json_dumps(in_sample_metrics),
                out_of_sample_metrics_payload=_json_dumps(out_of_sample_metrics),
                walk_forward_payload=_json_dumps(walk_forward_payload),
                parameter_sensitivity_payload=_json_dumps(parameter_sensitivity_payload),
                benchmark_payload=_json_dumps(benchmark_payload),
                summary_payload=_json_dumps(summary_payload),
                finished_at=finished_at,
                duration_ms=_duration_ms(started_counter),
            )
        checkpoint(95, "persisted research validation report")
        return _result_payload(
            candidate_review_id=candidate_review_id,
            report_id=report_id,
            dq_report_id=dq_report_id,
            validation_status=validation_status,
            readiness_floor=readiness_floor,
        )
    except Exception as exc:
        if report_id is not None:
            finished_at = _utcnow()
            with session_scope(engine) as session:
                report = ResearchValidationReportRepository(session).get(report_id)
                if report is not None:
                    ResearchValidationReportRepository(session).mark_failed(
                        report,
                        sanitize_error_message(exc),
                        finished_at=finished_at,
                        duration_ms=_duration_ms(started_counter),
                    )
        raise


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ResearchValidationConflictError("stored JSON payload is invalid") from exc
    if not isinstance(payload, dict):
        raise ResearchValidationConflictError("stored JSON payload must be an object")
    return payload


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )


def _parse_payload(review: AgentCandidateReviewORM) -> dict[str, Any]:
    request = _json_loads(review.backtest_request_payload)
    if request.get("job_type") != "backtest_ma_cross":
        raise ResearchValidationConflictError(
            "candidate backtest job_type must be backtest_ma_cross"
        )
    payload = request.get("payload")
    if not isinstance(payload, dict):
        raise ResearchValidationConflictError(
            "candidate backtest payload must be an object"
        )
    return payload


def _split_70_30(bars: list[Bar]) -> tuple[list[Bar], list[Bar]]:
    sorted_bars = sorted(bars, key=lambda bar: bar.timestamp)
    if len(sorted_bars) <= 1:
        return sorted_bars, sorted_bars
    split_index = int(len(sorted_bars) * 0.7)
    split_index = max(1, min(split_index, len(sorted_bars) - 1))
    return sorted_bars[:split_index], sorted_bars[split_index:]


def _walk_forward_windows(bars: list[Bar]) -> list[tuple[date, date]]:
    sorted_bars = sorted(bars, key=lambda bar: bar.timestamp)
    windows: list[tuple[date, date]] = []
    train_size = 180
    test_size = 60
    step = 60
    for start_index in range(0, len(sorted_bars), step):
        test_start = start_index + train_size
        test_end = test_start + test_size - 1
        if test_end >= len(sorted_bars):
            break
        windows.append(
            (
                sorted_bars[test_start].timestamp,
                sorted_bars[test_end].timestamp,
            )
        )
    return windows


def _parameter_grid(short_window: int, long_window: int) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    for short_delta in [-2, 0, 2]:
        for long_delta in [-5, 0, 5]:
            short = short_window + short_delta
            long = long_window + long_delta
            if short <= 0 or long <= 0 or short >= long:
                continue
            pair = (short, long)
            if pair not in pairs:
                pairs.append(pair)
    return pairs[:9]


def _validate_candidate_review(session, review: AgentCandidateReviewORM) -> BacktestRunORM:
    if review.status not in ELIGIBLE_CANDIDATE_STATUSES:
        raise ResearchValidationConflictError(
            f"candidate status is not eligible: {review.status}"
        )
    if review.strategy_name != "ma_cross":
        raise ResearchValidationConflictError("candidate strategy_name must be ma_cross")
    if review.backtest_run_id is None:
        raise ResearchValidationConflictError("candidate has no source backtest_run_id")
    source_backtest = session.get(BacktestRunORM, review.backtest_run_id)
    if source_backtest is None:
        raise ResearchValidationNotFoundError(
            f"source backtest not found: {review.backtest_run_id}"
        )
    if source_backtest.strategy_name != "ma_cross":
        raise ResearchValidationConflictError(
            "source backtest strategy_name must be ma_cross"
        )
    return source_backtest


def _run_ma_cross_metrics(
    engine: Engine,
    *,
    symbol: str,
    short_window: int,
    long_window: int,
    order_size: int,
    initial_cash: Decimal,
    start: date,
    end: date,
) -> dict[str, Any]:
    backtest = BacktestEngine(
        engine=engine,
        initial_cash=initial_cash,
        commission_rate=DEFAULT_COMMISSION_RATE,
        slippage_rate=DEFAULT_SLIPPAGE_RATE,
    )
    summary = backtest.run(
        symbol=symbol,
        strategy=MACrossStrategy(
            short_window=short_window,
            long_window=long_window,
            order_size=order_size,
        ),
        strategy_name="ma_cross",
        start=start,
        end=end,
    )
    with session_scope(engine) as session:
        run = session.get(BacktestRunORM, summary.run_id)
        if run is None:
            raise ResearchValidationNotFoundError(
                f"backtest run not found: {summary.run_id}"
            )
        return metric_payload_from_run(session, run)


def _build_walk_forward_payload(
    engine: Engine,
    *,
    bars: list[Bar],
    symbol: str,
    short_window: int,
    long_window: int,
    order_size: int,
    initial_cash: Decimal,
) -> dict[str, Any]:
    windows = []
    for index, (start, end) in enumerate(_walk_forward_windows(bars), start=1):
        try:
            metrics = _run_ma_cross_metrics(
                engine,
                symbol=symbol,
                short_window=short_window,
                long_window=long_window,
                order_size=order_size,
                initial_cash=initial_cash,
                start=start,
                end=end,
            )
            windows.append({"index": index, "start": start, "end": end, **metrics})
        except Exception as exc:
            windows.append(
                {
                    "index": index,
                    "start": start,
                    "end": end,
                    "status": "failed",
                    "error": sanitize_error_message(exc, max_chars=500),
                }
            )
    return {
        "window_count": len(windows),
        "failures": sum(1 for item in windows if item.get("status") == "failed"),
        "windows": windows,
    }


def _build_parameter_sensitivity_payload(
    engine: Engine,
    *,
    bars: list[Bar],
    symbol: str,
    short_window: int,
    long_window: int,
    order_size: int,
    initial_cash: Decimal,
) -> dict[str, Any]:
    runs = []
    start = bars[0].timestamp
    end = bars[-1].timestamp
    for short, long in _parameter_grid(short_window, long_window):
        metrics = _run_ma_cross_metrics(
            engine,
            symbol=symbol,
            short_window=short,
            long_window=long,
            order_size=order_size,
            initial_cash=initial_cash,
            start=start,
            end=end,
        )
        runs.append(
            {
                "short_window": short,
                "long_window": long,
                **metrics,
            }
        )
    return {
        "base": {"short_window": short_window, "long_window": long_window},
        "run_count": len(runs),
        "runs": runs,
    }


def _determine_status(
    *,
    data_quality_status: str,
    out_of_sample_metrics: dict[str, Any],
    walk_forward_payload: dict[str, Any],
    parameter_sensitivity_payload: dict[str, Any],
    benchmark_payload: dict[str, Any],
    short_window: int,
    long_window: int,
) -> tuple[str, str, list[dict[str, Any]]]:
    reasons: list[dict[str, Any]] = []
    if data_quality_status == "failed":
        reasons.append({"code": "data_quality_failed", "status": data_quality_status})
    elif data_quality_status != "passed":
        reason_code = (
            "data_quality_needs_review"
            if data_quality_status == "needs_review"
            else "data_quality_not_passed"
        )
        reasons.append({"code": reason_code, "status": data_quality_status})

    oos_return = _decimal(out_of_sample_metrics.get("return_pct"))
    if oos_return < Decimal("0"):
        reasons.append(
            {
                "code": "negative_oos_return",
                "return_pct": str(oos_return),
            }
        )

    oos_max_drawdown = _decimal(out_of_sample_metrics.get("max_drawdown"))
    if oos_max_drawdown > Decimal("0.20"):
        reasons.append(
            {
                "code": "oos_drawdown_gt_20pct",
                "max_drawdown": str(oos_max_drawdown),
                "threshold": "0.20",
            }
        )

    windows = list(walk_forward_payload.get("windows") or [])
    failures = int(walk_forward_payload.get("failures") or 0)
    if failures > 0:
        reasons.append(
            {
                "code": "walk_forward_execution_failures",
                "failure_count": failures,
            }
        )
    if len(windows) < 2:
        reasons.append(
            {
                "code": "insufficient_walk_forward_folds",
                "fold_count": len(windows),
                "minimum": 2,
            }
        )

    negative_fold_count = sum(
        1 for window in windows if _decimal(window.get("return_pct")) < Decimal("0")
    )
    if windows and negative_fold_count > (len(windows) / 2):
        reasons.append(
            {
                "code": "majority_negative_walk_forward_returns",
                "negative_fold_count": negative_fold_count,
                "fold_count": len(windows),
            }
        )

    sensitivity_runs = list(parameter_sensitivity_payload.get("runs") or [])
    sensitivity_returns = [
        _decimal(run.get("return_pct"))
        for run in sensitivity_runs
        if "return_pct" in run
    ]
    median_grid_return = _median_decimal(sensitivity_returns)
    if median_grid_return is not None and median_grid_return < Decimal("0"):
        reasons.append(
            {
                "code": "negative_parameter_sensitivity_median",
                "median_return_pct": str(median_grid_return),
            }
        )
    original_return = _original_parameter_return(
        sensitivity_runs,
        short_window=short_window,
        long_window=long_window,
    )
    if (
        original_return is not None
        and median_grid_return is not None
        and median_grid_return < Decimal("0")
        and _is_top_decile(original_return, sensitivity_returns)
    ):
        reasons.append(
            {
                "code": "overfit_parameter_top_decile_negative_median",
                "original_return_pct": str(original_return),
                "median_return_pct": str(median_grid_return),
            }
        )

    strategy_benchmark_return = _decimal(benchmark_payload.get("strategy_return_pct"))
    buy_hold_return = _decimal(benchmark_payload.get("benchmark_return_pct"))
    if "excess_return_pct" in benchmark_payload:
        excess_return = _decimal(benchmark_payload.get("excess_return_pct"))
    else:
        excess_return = strategy_benchmark_return - buy_hold_return
    if excess_return < Decimal("-5"):
        reasons.append(
            {
                "code": "benchmark_underperformance",
                "strategy_return_pct": str(strategy_benchmark_return),
                "benchmark_return_pct": str(buy_hold_return),
                "excess_return_pct": str(excess_return),
                "threshold": "-5",
            }
        )

    if any(reason["code"] == "data_quality_failed" for reason in reasons):
        return "failed", "not_ready", reasons
    if any(reason["code"].startswith("data_quality_") for reason in reasons):
        return "needs_review", "not_ready", reasons
    if not reasons:
        return "passed", "ready_for_paper_research", reasons
    if all(reason["code"] == "benchmark_underperformance" for reason in reasons):
        return "needs_review", "needs_review", reasons
    return "needs_review", "not_ready", reasons


def _complete_failed_data_quality_report(
    engine: Engine,
    *,
    report_id: int,
    dq_report_id: int,
    candidate_review_id: int,
    dq_result: dict[str, Any],
    started_counter: float,
) -> dict[str, Any]:
    summary_payload = {
        "candidate_review_id": candidate_review_id,
        "data_quality_report_id": dq_report_id,
        "data_quality_status": dq_result["status"],
        "data_quality_severity": dq_result.get("severity"),
        "validation_status": "failed",
        "readiness_floor": "not_ready",
        "error": "data quality failed",
        "reasons": _data_quality_reasons(engine, dq_report_id),
        "research_only": True,
    }
    with session_scope(engine) as session:
        report = ResearchValidationReportRepository(session).get(report_id)
        if report is None:
            raise ResearchValidationNotFoundError(
                f"research validation report not found: {report_id}"
            )
        ResearchValidationReportRepository(session).mark_completed(
            report,
            validation_status="failed",
            readiness_floor="not_ready",
            data_quality_report_id=dq_report_id,
            in_sample_metrics_payload="{}",
            out_of_sample_metrics_payload="{}",
            walk_forward_payload="{}",
            parameter_sensitivity_payload="{}",
            benchmark_payload="{}",
            summary_payload=_json_dumps(summary_payload),
            finished_at=_utcnow(),
            duration_ms=_duration_ms(started_counter),
        )
    return _result_payload(
        candidate_review_id=candidate_review_id,
        report_id=report_id,
        dq_report_id=dq_report_id,
        validation_status="failed",
        readiness_floor="not_ready",
    )


def _result_payload(
    *,
    candidate_review_id: int,
    report_id: int,
    dq_report_id: int,
    validation_status: str,
    readiness_floor: str,
) -> dict[str, Any]:
    return {
        "candidate_review_id": candidate_review_id,
        "research_validation_report_id": report_id,
        "data_quality_report_id": dq_report_id,
        "validation_status": validation_status,
        "readiness_floor": readiness_floor,
    }


def _positive_int(value: Any, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ResearchValidationConflictError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ResearchValidationConflictError(f"{name} must be positive")
    return parsed


def _positive_decimal(value: Any, name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ResearchValidationConflictError(f"{name} must be decimal") from exc
    if parsed <= Decimal("0"):
        raise ResearchValidationConflictError(f"{name} must be positive")
    return parsed


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _benchmark_comparison_payload(
    bars: list[Bar],
    *,
    out_of_sample_metrics: dict[str, Any],
    initial_cash: Decimal,
) -> dict[str, Any]:
    benchmark = buy_and_hold_benchmark(
        bars,
        initial_cash=initial_cash,
        commission_rate=DEFAULT_COMMISSION_RATE,
        slippage_rate=DEFAULT_SLIPPAGE_RATE,
    )
    strategy_return = _decimal(out_of_sample_metrics.get("return_pct"))
    benchmark_return = _decimal(benchmark.get("return_pct"))
    excess_return = strategy_return - benchmark_return
    strategy_drawdown = _decimal(out_of_sample_metrics.get("max_drawdown"))
    benchmark_drawdown = _decimal(benchmark.get("max_drawdown"))
    return {
        **benchmark,
        "strategy_return_pct": str(strategy_return),
        "benchmark_return_pct": str(benchmark_return),
        "excess_return_pct": str(excess_return),
        "strategy_max_drawdown": str(strategy_drawdown),
        "benchmark_max_drawdown": str(benchmark_drawdown),
        "passed": excess_return >= Decimal("-5"),
    }


def _data_quality_reasons(engine: Engine, report_id: int) -> list[dict[str, Any]]:
    reasons = [{"code": "data_quality_failed", "data_quality_report_id": report_id}]
    with session_scope(engine) as session:
        report = DataQualityReportRepository(session).get(report_id)
        if report is None:
            return reasons
        findings_payload = _json_loads(report.findings_payload)
    for finding in findings_payload.get("findings", []):
        if isinstance(finding, dict) and finding.get("code"):
            reasons.append(
                {
                    "code": str(finding["code"]),
                    "severity": finding.get("severity"),
                    "count": finding.get("count"),
                }
            )
    return reasons


def _median_decimal(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")


def _original_parameter_return(
    runs: list[dict[str, Any]],
    *,
    short_window: int,
    long_window: int,
) -> Decimal | None:
    for run in runs:
        if (
            int(run.get("short_window", -1)) == short_window
            and int(run.get("long_window", -1)) == long_window
        ):
            return _decimal(run.get("return_pct"))
    return None


def _is_top_decile(value: Decimal, values: list[Decimal]) -> bool:
    if not values:
        return False
    better_or_equal = sum(1 for candidate in values if candidate >= value)
    return (Decimal(better_or_equal) / Decimal(len(values))) <= Decimal("0.10")


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _duration_ms(started_counter: float) -> int:
    return int((perf_counter() - started_counter) * 1000)
