import json
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from quant_trading.core.enums import Adjustment, Market
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import (
    AgentCandidateReviewORM,
    BacktestRunORM,
    BrokerOrderEventORM,
    PaperRunORM,
    ResearchValidationReportORM,
)
from quant_trading.storage.repositories import (
    AgentCandidateReviewRepository,
    AgentRunRepository,
    InstrumentRepository,
    MarketDataRepository,
)
from quant_trading.validation.research import (
    _determine_status,
    run_candidate_research_validation,
)


SYMBOL = "000001"


def _create_engine():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine


def _seed_weekday_bars(session, *, count: int = 300, invalid: bool = False) -> None:
    instrument = InstrumentRepository(session).upsert_symbol(
        symbol=SYMBOL,
        name="Validation Fixture",
        market=Market.A_STOCK,
        asset_type="stock",
        currency="CNY",
        exchange="SZSE",
    )
    repository = MarketDataRepository(session)
    current = date(2025, 1, 1)
    inserted = 0
    while inserted < count:
        if current.weekday() >= 5:
            current += timedelta(days=1)
            continue
        base = Decimal("10") + (Decimal(inserted) * Decimal("0.03"))
        close = base + Decimal("0.10")
        if invalid and inserted == 0:
            close = Decimal("-1")
        repository.upsert_daily_bar(
            instrument_id=instrument.id,
            timestamp=current,
            open=base,
            high=base + Decimal("0.30"),
            low=base - Decimal("0.20"),
            close=close,
            volume=Decimal("100000") + Decimal(inserted),
            source="fixture",
            adjusted=Adjustment.QFQ.value,
        )
        inserted += 1
        current += timedelta(days=1)


def _approved_payload() -> dict:
    return {
        "job_type": "backtest_ma_cross",
        "payload": {
            "symbol": SYMBOL,
            "short_window": 5,
            "long_window": 20,
            "order_size": 100,
            "initial_cash": "100000",
        },
    }


def _seed_approved_candidate_review(
    session,
    *,
    backtest_run_id: int | None = None,
) -> tuple[int, int]:
    now = datetime(2026, 6, 26, 9, 0, 0)
    source = AgentRunRepository(session).create_running(
        agent_type="strategy_idea",
        symbol=SYMBOL,
        model_name="fake-llm",
        request_payload="{}",
        job_run_id=None,
        started_at=now,
    )
    AgentRunRepository(session).mark_succeeded(
        source,
        metrics_payload="{}",
        result_payload=json.dumps(
            {
                "candidate_payload": {
                    "strategy_name": "ma_cross",
                    "symbol": SYMBOL,
                    "parameters": {
                        "short_window": 5,
                        "long_window": 20,
                        "order_size": 100,
                    },
                }
            },
            sort_keys=True,
        ),
        finished_at=now,
        duration_ms=1,
    )
    if backtest_run_id is None:
        backtest = BacktestRunORM(
            strategy_name="ma_cross",
            symbol=SYMBOL,
            initial_cash=Decimal("100000"),
            final_equity=Decimal("101000"),
            status="done",
            created_at=now,
        )
        session.add(backtest)
        session.flush()
        backtest_run_id = backtest.id
    candidate = AgentCandidateReviewRepository(session).create_decision(
        source_agent_run_id=source.id,
        status="backtest_succeeded",
        symbol=SYMBOL,
        strategy_name="ma_cross",
        candidate_payload=json.dumps(
            {
                "strategy_name": "ma_cross",
                "symbol": SYMBOL,
                "parameters": {
                    "short_window": 5,
                    "long_window": 20,
                    "order_size": 100,
                },
            },
            sort_keys=True,
        ),
        backtest_request_payload=json.dumps(_approved_payload(), sort_keys=True),
        operator="research lead",
        operator_note="approved",
        decided_at=now,
        created_at=now,
    )
    AgentCandidateReviewRepository(session).mark_backtest_succeeded(
        candidate,
        backtest_run_id=backtest_run_id,
        updated_at=now,
    )
    return candidate.id, backtest_run_id


def _seed_valid_candidate(engine) -> tuple[int, int]:
    with session_scope(engine) as session:
        _seed_weekday_bars(session, count=300)
        return _seed_approved_candidate_review(session)


def _paper_and_broker_counts(engine) -> tuple[int, int]:
    with session_scope(engine) as session:
        paper_run_count = session.scalar(select(func.count(PaperRunORM.id)))
        broker_event_count = session.scalar(select(func.count(BrokerOrderEventORM.id)))
    return int(paper_run_count or 0), int(broker_event_count or 0)


def _assert_backtest_sections_include_run_ids(report: ResearchValidationReportORM) -> None:
    in_sample = json.loads(report.in_sample_metrics_payload)
    out_of_sample = json.loads(report.out_of_sample_metrics_payload)
    walk_forward = json.loads(report.walk_forward_payload)
    sensitivity = json.loads(report.parameter_sensitivity_payload)

    assert in_sample["backtest_run_id"] > 0
    assert out_of_sample["backtest_run_id"] > 0
    assert walk_forward["windows"]
    assert all(item["backtest_run_id"] > 0 for item in walk_forward["windows"])
    assert sensitivity["runs"]
    assert all(item["backtest_run_id"] > 0 for item in sensitivity["runs"])


def test_run_candidate_research_validation_persists_passed_report():
    engine = _create_engine()
    candidate_review_id, backtest_run_id = _seed_valid_candidate(engine)

    result = run_candidate_research_validation(
        engine,
        candidate_review_id=candidate_review_id,
    )

    assert result["validation_status"] in {"passed", "needs_review"}
    assert result["candidate_review_id"] == candidate_review_id
    assert result["research_validation_report_id"] > 0
    assert result["data_quality_report_id"] > 0
    with session_scope(engine) as session:
        report = session.get(
            ResearchValidationReportORM,
            result["research_validation_report_id"],
        )
        assert report is not None
        assert report.source_backtest_run_id == backtest_run_id
        assert report.out_of_sample_metrics_payload != "{}"
        assert report.walk_forward_payload != "{}"
        assert report.parameter_sensitivity_payload != "{}"
        assert report.benchmark_payload != "{}"
        _assert_backtest_sections_include_run_ids(report)
        benchmark = json.loads(report.benchmark_payload)
        assert {
            "strategy_return_pct",
            "benchmark_return_pct",
            "excess_return_pct",
            "strategy_max_drawdown",
            "benchmark_max_drawdown",
            "passed",
        } <= set(benchmark)
        candidate = session.get(AgentCandidateReviewORM, candidate_review_id)
        assert candidate.data_quality_report_id == result["data_quality_report_id"]
        assert candidate.research_validation_report_id == report.id


def test_run_candidate_research_validation_fails_when_data_quality_fails():
    engine = _create_engine()
    with session_scope(engine) as session:
        _seed_weekday_bars(session, count=60)
        candidate_review_id, _ = _seed_approved_candidate_review(session)

    result = run_candidate_research_validation(
        engine,
        candidate_review_id=candidate_review_id,
    )

    assert result["validation_status"] == "failed"
    with session_scope(engine) as session:
        report = session.get(
            ResearchValidationReportORM,
            result["research_validation_report_id"],
        )
        assert report is not None
        assert report.in_sample_metrics_payload == "{}"
        assert report.out_of_sample_metrics_payload == "{}"
        assert report.walk_forward_payload == "{}"
        assert report.parameter_sensitivity_payload == "{}"
        summary = json.loads(report.summary_payload)
        assert summary["reasons"]
        assert {
            reason["code"] for reason in summary["reasons"]
        } >= {"data_quality_failed", "insufficient_bars"}


def test_run_candidate_research_validation_updates_existing_report_on_rerun():
    engine = _create_engine()
    candidate_review_id, _ = _seed_valid_candidate(engine)

    first = run_candidate_research_validation(
        engine,
        candidate_review_id=candidate_review_id,
    )
    second = run_candidate_research_validation(
        engine,
        candidate_review_id=candidate_review_id,
    )

    assert second["research_validation_report_id"] == first["research_validation_report_id"]
    with session_scope(engine) as session:
        assert session.scalar(select(func.count(ResearchValidationReportORM.id))) == 1


def test_run_candidate_research_validation_creates_no_paper_or_broker_rows():
    engine = _create_engine()
    candidate_review_id, _ = _seed_valid_candidate(engine)
    before_papers, before_broker_events = _paper_and_broker_counts(engine)

    run_candidate_research_validation(engine, candidate_review_id=candidate_review_id)

    paper_run_count, broker_event_count = _paper_and_broker_counts(engine)
    assert before_papers == 0
    assert before_broker_events == 0
    assert paper_run_count == 0
    assert broker_event_count == 0


def test_determine_status_negative_oos_return_caps_to_not_ready():
    validation_status, readiness_floor, reasons = _determine_status(
        data_quality_status="passed",
        out_of_sample_metrics={
            "return_pct": "-0.1",
            "max_drawdown": "0.10",
        },
        walk_forward_payload={
            "windows": [
                {"return_pct": "1.0"},
                {"return_pct": "1.0"},
            ],
            "failures": 0,
        },
        parameter_sensitivity_payload={
            "runs": [
                {"short_window": 3, "long_window": 15, "return_pct": "1.0"},
                {"short_window": 5, "long_window": 20, "return_pct": "1.0"},
                {"short_window": 7, "long_window": 25, "return_pct": "1.0"},
            ]
        },
        benchmark_payload={
            "strategy_return_pct": "1.0",
            "benchmark_return_pct": "1.0",
        },
        short_window=5,
        long_window=20,
    )

    assert validation_status == "needs_review"
    assert readiness_floor == "not_ready"
    assert {reason["code"] for reason in reasons} == {"negative_oos_return"}


def test_determine_status_requires_at_least_two_walk_forward_folds():
    validation_status, readiness_floor, reasons = _determine_status(
        data_quality_status="passed",
        out_of_sample_metrics={
            "return_pct": "1.0",
            "max_drawdown": "0.10",
        },
        walk_forward_payload={
            "windows": [{"return_pct": "1.0"}],
            "failures": 0,
        },
        parameter_sensitivity_payload={
            "runs": [
                {"short_window": 3, "long_window": 15, "return_pct": "1.0"},
                {"short_window": 5, "long_window": 20, "return_pct": "1.0"},
                {"short_window": 7, "long_window": 25, "return_pct": "1.0"},
            ]
        },
        benchmark_payload={
            "strategy_return_pct": "1.0",
            "benchmark_return_pct": "1.0",
        },
        short_window=5,
        long_window=20,
    )

    assert validation_status == "needs_review"
    assert readiness_floor == "not_ready"
    assert {reason["code"] for reason in reasons} == {"insufficient_walk_forward_folds"}


def test_determine_status_benchmark_underperformance_caps_to_needs_review():
    validation_status, readiness_floor, reasons = _determine_status(
        data_quality_status="passed",
        out_of_sample_metrics={
            "return_pct": "4.0",
            "max_drawdown": "0.10",
        },
        walk_forward_payload={
            "windows": [
                {"return_pct": "1.0"},
                {"return_pct": "1.0"},
            ],
            "failures": 0,
        },
        parameter_sensitivity_payload={
            "runs": [
                {"short_window": 3, "long_window": 15, "return_pct": "1.0"},
                {"short_window": 5, "long_window": 20, "return_pct": "1.0"},
                {"short_window": 7, "long_window": 25, "return_pct": "1.0"},
            ]
        },
        benchmark_payload={
            "strategy_return_pct": "4.0",
            "benchmark_return_pct": "10.0",
        },
        short_window=5,
        long_window=20,
    )

    assert validation_status == "needs_review"
    assert readiness_floor == "needs_review"
    assert {reason["code"] for reason in reasons} == {"benchmark_underperformance"}
