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
