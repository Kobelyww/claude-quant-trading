from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
import re
from typing import Any

from sqlalchemy import Engine, func, select

from quant_trading.storage.db import session_scope
from quant_trading.storage.models import (
    AgentCandidateReviewORM,
    AgentRunORM,
    BacktestEquityPointORM,
    BacktestOrderORM,
    BacktestRunORM,
)


ALLOWED_PAPER_TRADING_READINESS = {
    "not_ready",
    "needs_review",
    "ready_for_paper_research",
}
_SUMMARY_LIMIT = 500
_SAFE_MANUAL_REVIEW_STEP = (
    "review the backtest output manually before any further research action"
)
_UNSAFE_TEXT_PATTERNS = (
    re.compile(r"\b(?:buy|sell)\b", re.IGNORECASE),
    re.compile(r"\bpaper\s+(?:trading|trade|run|runs)\b", re.IGNORECASE),
    re.compile(r"\b(?:broker|brokers|exchange|exchanges)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:submit|place|send|create|execute)\b.{0,40}\b"
        r"(?:order|orders|market\s+order|market\s+orders)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:order|orders|market\s+order|market\s+orders)\b.{0,40}\b"
        r"(?:submit|place|send|create|execute)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\blive\s+(?:trading|order|orders|market\s+order|market\s+orders)\b", re.IGNORECASE),
    re.compile(r"\bmarket\s+orders?\b", re.IGNORECASE),
)


def build_backtest_review_prompt(context: dict[str, Any], max_chars: int) -> str:
    context_json = json.dumps(
        context,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        default=_json_default,
    )
    prompt = f"""You are reviewing a historical backtest for research only.

Safety constraints:
- do not claim future profitability
- do not give live trading instructions
- do not approve paper trading
- do not call brokers or exchanges
- do not output executable code
- do not provide buy or sell instructions

Return one JSON object with exactly these keys:
- summary
- risk_flags
- overfit_warnings
- paper_trading_readiness
- recommended_next_steps

Do not include executable code or trading instructions in any field. The parser
will add research_only=true to the stored review result.

Allowed paper_trading_readiness values:
- not_ready
- needs_review
- ready_for_paper_research

Use conservative research language. Treat ready_for_paper_research as only a
recommendation for further human-reviewed paper-research consideration, not as
approval to create a paper run or place orders.

JSON context:
{context_json}
"""
    return prompt[:max_chars]


def parse_backtest_review_response(
    content: str,
    candidate_review_id: int,
    backtest_run_id: int,
) -> dict[str, Any]:
    try:
        decoded = json.loads(content)
    except json.JSONDecodeError:
        return _fallback_review(content, candidate_review_id, backtest_run_id)

    if not isinstance(decoded, dict):
        return _fallback_review(content, candidate_review_id, backtest_run_id)

    raw_readiness = _clean_text(decoded.get("paper_trading_readiness"))
    readiness = raw_readiness
    summary = _bounded_summary(decoded.get("summary"))
    risk_flags = _string_list(decoded.get("risk_flags"))
    overfit_warnings = _string_list(decoded.get("overfit_warnings"))
    recommended_next_steps = _string_list(decoded.get("recommended_next_steps"))
    review_status = "completed"
    issues = []
    if readiness not in ALLOWED_PAPER_TRADING_READINESS:
        review_status = "needs_review"
        issues.append("invalid paper_trading_readiness value")
        readiness = "needs_review"
    if _contains_unsafe_text(
        [raw_readiness, summary, *risk_flags, *overfit_warnings, *recommended_next_steps]
    ):
        review_status = "needs_review"
        readiness = "needs_review"
        issues.append("unsafe trading or paper/order instruction text")

    if issues:
        summary = _bounded_summary("; ".join(issues))
        risk_flags = ["unsafe_structured_review_output"]
        overfit_warnings = []
        recommended_next_steps = [_SAFE_MANUAL_REVIEW_STEP]

    return {
        "candidate_review_id": candidate_review_id,
        "backtest_run_id": backtest_run_id,
        "review_status": review_status,
        "research_only": True,
        "summary": summary,
        "risk_flags": risk_flags,
        "overfit_warnings": overfit_warnings,
        "paper_trading_readiness": readiness,
        "recommended_next_steps": recommended_next_steps,
    }


def load_backtest_review_context(
    engine: Engine,
    candidate_review_id: int,
    backtest_run_id: int | None = None,
) -> dict[str, Any]:
    with session_scope(engine) as session:
        review = session.get(AgentCandidateReviewORM, candidate_review_id)
        if review is None:
            raise ValueError("candidate review not found")
        resolved_backtest_run_id = backtest_run_id if backtest_run_id is not None else review.backtest_run_id
        if resolved_backtest_run_id is None:
            raise ValueError("candidate review has no backtest_run_id")

        source_agent_run = session.get(AgentRunORM, review.source_agent_run_id)
        if source_agent_run is None:
            raise ValueError("source agent run not found")

        backtest_run = session.get(BacktestRunORM, resolved_backtest_run_id)
        if backtest_run is None:
            raise ValueError("backtest run not found")

        return {
            "candidate_review": _candidate_review_payload(review),
            "source_agent_run": _agent_run_payload(source_agent_run),
            "source_agent_result": _json_loads(source_agent_run.result_payload),
            "backtest_run": _backtest_run_payload(backtest_run),
            "metrics": _backtest_metrics(session, backtest_run),
        }


def _backtest_metrics(session, run: BacktestRunORM) -> dict[str, Any]:
    initial_cash = _decimal(run.initial_cash)
    final_equity = _decimal(run.final_equity)
    absolute_pnl = final_equity - initial_cash
    return_pct = Decimal("0")
    if initial_cash != Decimal("0"):
        return_pct = (absolute_pnl / initial_cash) * Decimal("100")

    metrics: dict[str, Any] = {
        "initial_cash": _decimal_string(initial_cash),
        "final_equity": _decimal_string(final_equity),
        "absolute_pnl": _decimal_string(absolute_pnl),
        "return_pct": _decimal_string(return_pct),
        "status": run.status,
        "symbol": run.symbol,
        "strategy_name": run.strategy_name,
    }

    equity_point_count = session.scalar(
        select(func.count(BacktestEquityPointORM.id)).where(
            BacktestEquityPointORM.run_id == run.id
        )
    )
    max_drawdown = session.scalar(
        select(func.max(BacktestEquityPointORM.drawdown)).where(
            BacktestEquityPointORM.run_id == run.id
        )
    )
    order_count = session.scalar(
        select(func.count(BacktestOrderORM.id)).where(BacktestOrderORM.run_id == run.id)
    )
    metrics["equity_point_count"] = int(equity_point_count or 0)
    metrics["max_drawdown"] = _decimal_string(_decimal(max_drawdown or 0))
    metrics["order_count"] = int(order_count or 0)
    return metrics


def _candidate_review_payload(row: AgentCandidateReviewORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "source_agent_run_id": row.source_agent_run_id,
        "status": row.status,
        "symbol": row.symbol,
        "strategy_name": row.strategy_name,
        "candidate_payload": _json_loads(row.candidate_payload),
        "backtest_request_payload": _json_loads(row.backtest_request_payload),
        "operator": row.operator,
        "operator_note": row.operator_note,
        "backtest_job_run_id": row.backtest_job_run_id,
        "backtest_run_id": row.backtest_run_id,
        "review_agent_run_id": row.review_agent_run_id,
        "error_message": row.error_message,
        "decided_at": _isoformat(row.decided_at),
        "created_at": _isoformat(row.created_at),
        "updated_at": _isoformat(row.updated_at),
    }


def _agent_run_payload(row: AgentRunORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "agent_type": row.agent_type,
        "status": row.status,
        "symbol": row.symbol,
        "model_name": row.model_name,
        "request_payload": _json_loads(row.request_payload),
        "metrics_payload": _json_loads(row.metrics_payload),
        "job_run_id": row.job_run_id,
        "error_message": row.error_message,
        "started_at": _isoformat(row.started_at),
        "finished_at": _isoformat(row.finished_at),
        "duration_ms": row.duration_ms,
        "created_at": _isoformat(row.created_at),
    }


def _backtest_run_payload(row: BacktestRunORM) -> dict[str, Any]:
    return {
        "id": row.id,
        "strategy_name": row.strategy_name,
        "symbol": row.symbol,
        "initial_cash": _decimal_string(_decimal(row.initial_cash)),
        "final_equity": _decimal_string(_decimal(row.final_equity)),
        "status": row.status,
        "created_at": _isoformat(row.created_at),
    }


def _fallback_review(
    content: str,
    candidate_review_id: int,
    backtest_run_id: int,
) -> dict[str, Any]:
    return {
        "candidate_review_id": candidate_review_id,
        "backtest_run_id": backtest_run_id,
        "review_status": "needs_review",
        "research_only": True,
        "summary": _bounded_summary(content),
        "risk_flags": ["unstructured_review_output"],
        "overfit_warnings": [],
        "paper_trading_readiness": "needs_review",
        "recommended_next_steps": [],
    }


def _json_loads(value: str | None) -> Any:
    if not value:
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {"unparsed": _bounded_summary(value)}


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _decimal_string(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _decimal_string(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001")), "f")


def _isoformat(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _clean_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _bounded_summary(value: Any) -> str:
    if isinstance(value, str):
        text = value.strip()
    elif value is None:
        text = ""
    else:
        text = str(value).strip()
    return text[:_SUMMARY_LIMIT]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if isinstance(item, str):
            cleaned = item.strip()
        else:
            cleaned = str(item).strip()
        if cleaned:
            result.append(cleaned[:200])
    return result


def _contains_unsafe_text(values: list[str]) -> bool:
    for value in values:
        if any(pattern.search(value) for pattern in _UNSAFE_TEXT_PATTERNS):
            return True
    return False
