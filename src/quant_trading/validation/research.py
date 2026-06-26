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
from quant_trading.storage.db import session_scope
from quant_trading.storage.models import AgentCandidateReviewORM, BacktestRunORM
from quant_trading.storage.repositories import (
    AgentCandidateReviewRepository,
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

        benchmark_payload = buy_and_hold_benchmark(
            bars,
            initial_cash=initial_cash,
            commission_rate=DEFAULT_COMMISSION_RATE,
            slippage_rate=DEFAULT_SLIPPAGE_RATE,
        )
        validation_status, readiness_floor = _determine_status(
            out_of_sample_metrics=out_of_sample_metrics,
            walk_forward_payload=walk_forward_payload,
        )
        summary_payload = {
            "candidate_review_id": candidate_review_id,
            "source_backtest_run_id": source_backtest_run_id,
            "data_quality_status": dq_result["status"],
            "data_quality_report_id": dq_report_id,
            "validation_status": validation_status,
            "readiness_floor": readiness_floor,
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
                        str(exc),
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
                    "error": str(exc)[:500],
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
    out_of_sample_metrics: dict[str, Any],
    walk_forward_payload: dict[str, Any],
) -> tuple[str, str]:
    return_pct = _decimal(out_of_sample_metrics.get("return_pct"))
    if return_pct < Decimal("0") or walk_forward_payload.get("failures", 0) > 0:
        return "needs_review", "needs_review"
    return "passed", "ready_for_paper_research"


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


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _duration_ms(started_counter: float) -> int:
    return int((perf_counter() - started_counter) * 1000)
