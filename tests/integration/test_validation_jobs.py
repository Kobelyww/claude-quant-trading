import json
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from quant_trading.api.main import create_app
from quant_trading.config import AppSettings
from quant_trading.core.enums import Adjustment, Market
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.models import (
    AgentCandidateReviewORM,
    BacktestRunORM,
    BrokerOrderEventORM,
    DataQualityReportORM,
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


def make_client(engine=None, *, raise_server_exceptions: bool = True):
    engine = engine or _create_engine()
    settings = AppSettings(job_executor="inline")
    return (
        TestClient(
            create_app(engine=engine, settings=settings),
            raise_server_exceptions=raise_server_exceptions,
        ),
        engine,
    )


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


def _seed_passing_validation_candidate(engine) -> tuple[int, int]:
    with session_scope(engine) as session:
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
        while inserted < 420:
            if current.weekday() >= 5:
                current += timedelta(days=1)
                continue
            cycle = inserted % 80
            if cycle < 20:
                close = Decimal("10.00") - Decimal(cycle) * Decimal("0.03")
            else:
                close = Decimal("9.40") + Decimal(cycle - 20) * Decimal("0.035")
            close += Decimal(inserted // 80) * Decimal("0.10")
            repository.upsert_daily_bar(
                instrument_id=instrument.id,
                timestamp=current,
                open=close,
                high=close + Decimal("0.10"),
                low=close - Decimal("0.10"),
                close=close,
                volume=Decimal("100000"),
                source="fixture",
                adjusted=Adjustment.QFQ.value,
            )
            inserted += 1
            current += timedelta(days=1)

        candidate_review_id, backtest_run_id = _seed_approved_candidate_review(session)
        review = AgentCandidateReviewRepository(session).get(candidate_review_id)
        assert review is not None
        backtest_request = json.loads(review.backtest_request_payload)
        backtest_request["payload"]["order_size"] = 1000
        review.backtest_request_payload = json.dumps(backtest_request, sort_keys=True)
        review.candidate_payload = json.dumps(
            {
                "strategy_name": "ma_cross",
                "symbol": SYMBOL,
                "parameters": {
                    "short_window": 5,
                    "long_window": 20,
                    "order_size": 1000,
                },
            },
            sort_keys=True,
        )
        session.flush()
        return candidate_review_id, backtest_run_id


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


def test_data_quality_report_job_api_persists_report():
    engine = _create_engine()
    candidate_review_id, backtest_run_id = _seed_passing_validation_candidate(engine)
    client, _ = make_client(engine)

    response = client.post(
        "/jobs/data-quality/report",
        json={
            "symbol": SYMBOL,
            "candidate_review_id": candidate_review_id,
            "backtest_run_id": backtest_run_id,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_type"] == "data_quality_report"
    assert payload["status"] in {"queued", "running", "succeeded"}
    report_id = payload["result_payload"]["report_id"]
    report_response = client.get(f"/data-quality-reports/{report_id}")
    assert report_response.status_code == 200
    report_payload = report_response.json()
    assert report_payload["id"] == report_id
    assert report_payload["job_run_id"] == payload["id"]
    assert report_payload["candidate_review_id"] == candidate_review_id
    assert report_payload["backtest_run_id"] == backtest_run_id
    assert report_payload["findings_payload"]["findings"] == []


def test_research_validation_job_api_persists_report():
    engine = _create_engine()
    candidate_review_id, _ = _seed_passing_validation_candidate(engine)
    client, _ = make_client(engine)

    response = client.post(
        "/jobs/validation/research",
        json={"candidate_review_id": candidate_review_id},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_type"] == "research_validation"
    assert payload["status"] in {"queued", "running", "succeeded"}
    report_id = payload["result_payload"]["research_validation_report_id"]
    validation_response = client.get(f"/research-validation-reports/{report_id}")
    assert validation_response.status_code == 200
    validation_payload = validation_response.json()
    assert validation_payload["id"] == report_id
    assert validation_payload["job_run_id"] == payload["id"]
    assert validation_payload["candidate_review_id"] == candidate_review_id
    assert validation_payload["summary_payload"]["reasons"] == []


def test_report_read_apis_return_decoded_payloads():
    engine = _create_engine()
    candidate_review_id, backtest_run_id = _seed_passing_validation_candidate(engine)
    dq_result = run_candidate_research_validation(
        engine,
        candidate_review_id=candidate_review_id,
    )
    client, _ = make_client(engine)

    report_response = client.get(f"/data-quality-reports/{dq_result['data_quality_report_id']}")
    validation_response = client.get(
        f"/research-validation-reports/{dq_result['research_validation_report_id']}"
    )
    missing_report_response = client.get("/data-quality-reports/999")
    missing_validation_response = client.get("/research-validation-reports/999")

    assert report_response.status_code == 200
    report_payload = report_response.json()
    assert report_payload["backtest_run_id"] == backtest_run_id
    assert isinstance(report_payload["findings_payload"], dict)
    assert report_payload["findings_payload"]["findings"] == []
    assert validation_response.status_code == 200
    validation_payload = validation_response.json()
    assert isinstance(validation_payload["in_sample_metrics_payload"], dict)
    assert isinstance(validation_payload["out_of_sample_metrics_payload"], dict)
    assert isinstance(validation_payload["walk_forward_payload"], dict)
    assert isinstance(validation_payload["parameter_sensitivity_payload"], dict)
    assert isinstance(validation_payload["benchmark_payload"], dict)
    assert isinstance(validation_payload["summary_payload"], dict)
    assert validation_payload["summary_payload"]["reasons"] == []
    assert missing_report_response.status_code == 404
    assert missing_report_response.json() == {"detail": "data quality report not found"}
    assert missing_validation_response.status_code == 404
    assert missing_validation_response.json() == {
        "detail": "research validation report not found"
    }


def test_data_quality_report_read_api_tolerates_malformed_payload():
    engine = _create_engine()
    with session_scope(engine) as session:
        row = DataQualityReportORM(
            symbol=SYMBOL,
            findings_payload="{malformed-json",
            status="passed",
            severity="none",
        )
        session.add(row)
        session.flush()
        report_id = row.id
    client, _ = make_client(engine, raise_server_exceptions=False)

    response = client.get(f"/data-quality-reports/{report_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == report_id
    assert isinstance(payload["findings_payload"], dict)


def test_research_validation_report_read_api_tolerates_malformed_payload():
    engine = _create_engine()
    candidate_review_id, backtest_run_id = _seed_passing_validation_candidate(engine)
    with session_scope(engine) as session:
        row = ResearchValidationReportORM(
            candidate_review_id=candidate_review_id,
            source_backtest_run_id=backtest_run_id,
            symbol=SYMBOL,
            strategy_name="ma_cross",
            validation_status="passed",
            readiness_floor="ready_for_paper_research",
            in_sample_metrics_payload="{malformed-json",
            out_of_sample_metrics_payload="{}",
            walk_forward_payload="{}",
            parameter_sensitivity_payload="{}",
            benchmark_payload="{}",
            summary_payload="{}",
        )
        session.add(row)
        session.flush()
        report_id = row.id
    client, _ = make_client(engine, raise_server_exceptions=False)

    response = client.get(f"/research-validation-reports/{report_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == report_id
    assert isinstance(payload["in_sample_metrics_payload"], dict)


def test_report_read_apis_filter_recent_reports():
    engine = _create_engine()
    candidate_review_id, _ = _seed_passing_validation_candidate(engine)
    result = run_candidate_research_validation(
        engine,
        candidate_review_id=candidate_review_id,
    )
    client, _ = make_client(engine)
    report_id = result["data_quality_report_id"]
    validation_report_id = result["research_validation_report_id"]

    report_response = client.get(
        "/data-quality-reports",
        params={
            "symbol": SYMBOL,
            "status": "passed",
            "severity": "none",
            "candidate_review_id": candidate_review_id,
        },
    )
    validation_response = client.get(
        "/research-validation-reports",
        params={
            "candidate_review_id": candidate_review_id,
            "symbol": SYMBOL,
            "validation_status": result["validation_status"],
        },
    )

    assert report_response.status_code == 200
    listed = report_response.json()
    assert listed[0]["id"] == report_id
    assert validation_response.status_code == 200
    validation_listed = validation_response.json()
    assert validation_listed[0]["id"] == validation_report_id
