import pytest
from pydantic import ValidationError

from quant_trading.config import AppSettings


def test_settings_default_to_local_unauthenticated(monkeypatch):
    for key in (
        "QUANT_APP_ENV",
        "DATABASE_URL",
        "QUANT_REQUIRE_AUTH",
        "QUANT_API_TOKEN",
        "QUANT_AUTH_HEADER",
        "QUANT_PUBLIC_ROUTES",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = AppSettings()

    assert settings.app_env == "local"
    assert settings.database_url == "sqlite+pysqlite:///quant_trading.db"
    assert settings.require_auth is False
    assert settings.api_token is None
    assert settings.auth_header == "Authorization"
    assert settings.public_routes == ["/health"]


def test_settings_require_token_when_auth_enabled():
    with pytest.raises(ValidationError) as exc_info:
        AppSettings(require_auth=True, api_token="")

    assert "QUANT_API_TOKEN is required when QUANT_REQUIRE_AUTH=true" in str(exc_info.value)


def test_settings_repr_redacts_token():
    settings = AppSettings(require_auth=True, api_token="super-secret")

    rendered = repr(settings)

    assert "super-secret" not in rendered
    assert "api_token" not in rendered


def test_settings_parse_comma_separated_public_routes():
    settings = AppSettings(public_routes="/health,/ready")

    assert settings.public_routes == ["/health", "/ready"]


def test_settings_default_to_inline_job_executor(monkeypatch):
    monkeypatch.delenv("QUANT_JOB_EXECUTOR", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)

    settings = AppSettings()

    assert settings.job_executor == "inline"
    assert settings.redis_url == "redis://localhost:6379/0"


def test_settings_accept_rq_job_executor():
    settings = AppSettings(job_executor="RQ", redis_url="redis://redis:6379/0")

    assert settings.job_executor == "rq"
    assert settings.redis_url == "redis://redis:6379/0"


def test_settings_reject_unknown_job_executor():
    with pytest.raises(ValidationError) as exc_info:
        AppSettings(job_executor="celery")

    assert "QUANT_JOB_EXECUTOR must be inline or rq" in str(exc_info.value)


def test_settings_default_trading_is_disabled():
    settings = AppSettings()

    assert settings.trading_enabled is False
    assert settings.broker_mode == "simulated"


def test_settings_accepts_dry_run_broker_mode_and_rejects_unknown():
    settings = AppSettings(broker_mode="dry_run")

    assert settings.broker_mode == "dry_run"

    with pytest.raises(ValidationError) as exc_info:
        AppSettings(broker_mode="live")

    assert "QUANT_BROKER_MODE must be simulated or dry_run" in str(exc_info.value)
