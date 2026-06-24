from datetime import date
from decimal import Decimal
import json

from quant_trading.core.enums import Market, OrderSide, OrderStatus, OrderType
from quant_trading.core.models import Bar, OrderIntent
from quant_trading.execution.broker import (
    BrokerExecutionMode,
    BrokerOrderResult,
    broker_order_request_from_intent,
)
from quant_trading.storage.db import create_all, make_engine, session_scope
from quant_trading.storage.repositories import BrokerOrderEventRepository


def make_engine_with_schema():
    engine = make_engine("sqlite+pysqlite:///:memory:")
    create_all(engine)
    return engine


def test_broker_order_event_repository_records_request_and_result_payloads():
    engine = make_engine_with_schema()
    bar = Bar(
        instrument_id=1,
        symbol="000001",
        market=Market.A_STOCK,
        timestamp=date(2026, 5, 8),
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10"),
        volume=Decimal("100000"),
    )
    intent = OrderIntent(
        instrument_id=1,
        symbol="000001",
        side=OrderSide.BUY,
        quantity=100,
        reason="audit_test",
        order_type=OrderType.MARKET,
    )
    request = broker_order_request_from_intent(intent, bar, "client-1")
    result = BrokerOrderResult(
        broker_order_id="dry-run-client-1",
        status=OrderStatus.SUBMITTED,
        mode=BrokerExecutionMode.DRY_RUN,
        accepted=True,
        message="dry-run accepted",
    )

    with session_scope(engine) as session:
        row = BrokerOrderEventRepository(session).record_from_broker_result(
            run_id=11,
            order_id=22,
            request=request,
            result=result,
            created_at=date(2026, 5, 8),
        )
        event_id = row.id

    with session_scope(engine) as session:
        repo = BrokerOrderEventRepository(session)
        rows = repo.list_for_order(22)
        row = repo.get(event_id)

        assert len(rows) == 1
        assert row.broker_mode == "dry_run"
        assert row.client_order_id == "client-1"
        assert row.broker_order_id == "dry-run-client-1"
        assert row.status == "submitted"
        assert row.accepted is True
        assert json.loads(row.request_payload)["symbol"] == "000001"
        assert json.loads(row.result_payload)["has_fill"] is False
