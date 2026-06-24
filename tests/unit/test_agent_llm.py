import pytest

from quant_trading.agents.llm import DeepSeekLLMClient, FakeLLMClient, LLMResponse
from quant_trading.config import AppSettings


def test_fake_llm_client_returns_deterministic_response_and_records_prompt():
    client = FakeLLMClient("hello")

    response = client.complete("prompt text")

    assert response == LLMResponse(content="hello", model="fake-llm")
    assert client.prompts == ["prompt text"]


def test_deepseek_client_requires_api_key():
    with pytest.raises(ValueError) as exc_info:
        DeepSeekLLMClient.from_settings(AppSettings(deepseek_api_key=None))

    assert "DEEPSEEK_API_KEY is required for agent jobs" in str(exc_info.value)


def test_deepseek_client_import_error_is_clear(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "langchain_deepseek":
            raise ImportError("missing package")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    client = DeepSeekLLMClient.from_settings(AppSettings(deepseek_api_key="key"))

    with pytest.raises(RuntimeError) as exc_info:
        client.complete("prompt")

    assert "Install langchain-deepseek to use agent jobs" in str(exc_info.value)
