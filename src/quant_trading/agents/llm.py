from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from quant_trading.config import AppSettings


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMClient(Protocol):
    def complete(self, prompt: str) -> LLMResponse:
        raise NotImplementedError


class FakeLLMClient:
    def __init__(self, content: str, model: str = "fake-llm"):
        self.content = content
        self.model = model
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> LLMResponse:
        self.prompts.append(prompt)
        return LLMResponse(content=self.content, model=self.model)


@dataclass(frozen=True)
class DeepSeekLLMClient:
    api_key: str
    api_base: str
    model: str

    @classmethod
    def from_settings(cls, settings: AppSettings) -> "DeepSeekLLMClient":
        if not settings.deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY is required for agent jobs")
        return cls(
            api_key=settings.deepseek_api_key,
            api_base=settings.deepseek_api_base,
            model=settings.deepseek_model,
        )

    def complete(self, prompt: str) -> LLMResponse:
        try:
            from langchain_deepseek import ChatDeepSeek
        except ImportError as exc:
            raise RuntimeError("Install langchain-deepseek to use agent jobs") from exc

        llm = ChatDeepSeek(
            model=self.model,
            api_key=self.api_key,
            api_base=self.api_base,
        )
        response = llm.invoke(prompt)
        return LLMResponse(content=str(response.content), model=self.model)
