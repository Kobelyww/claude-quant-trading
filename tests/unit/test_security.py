from quant_trading.config import AppSettings
from quant_trading.security import sanitize_error_message


def test_sanitize_error_message_redacts_configured_settings_secrets():
    settings = AppSettings(
        require_auth=True,
        api_token="tok",
        deepseek_api_key="sk-configured-secret-123",
        redis_url="redis://user:redis-pass@example.invalid:6379/0",
        database_url="postgresql://dbuser:db-pass@example.invalid/quant",
    )

    message = sanitize_error_message(
        "failed with sk-configured-secret-123 tok redis-pass db-pass",
        settings=settings,
    )

    assert "sk-configured-secret-123" not in message
    assert "tok" not in message
    assert "redis-pass" not in message
    assert "db-pass" not in message
    assert message.count("[REDACTED]") == 4


def test_sanitize_error_message_redacts_key_like_patterns():
    message = sanitize_error_message(
        "Authorization: Bearer abcdefghijk Bearer bare-token api_key=secret-value"
    )

    assert "abcdefghijk" not in message
    assert "bare-token" not in message
    assert "secret-value" not in message
    assert "[REDACTED]" in message


def test_sanitize_error_message_does_not_redact_parser_token_diagnostics():
    message = sanitize_error_message("unexpected token: } at position 3")

    assert message == "unexpected token: } at position 3"


def test_sanitize_error_message_redacts_short_environment_secrets(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env")

    message = sanitize_error_message("provider returned env")

    assert "env" not in message
    assert "[REDACTED]" in message


def test_sanitize_error_message_redacts_decoded_url_credentials():
    settings = AppSettings(redis_url="redis://user:p%40ss@example.invalid:6379/0")

    message = sanitize_error_message("driver failed for p@ss", settings=settings)

    assert "p@ss" not in message
    assert "[REDACTED]" in message


def test_sanitize_error_message_does_not_redact_short_secret_inside_words():
    settings = AppSettings(require_auth=True, api_token="tok")

    message = sanitize_error_message("unexpected token: } at position 3", settings=settings)

    assert message == "unexpected token: } at position 3"
