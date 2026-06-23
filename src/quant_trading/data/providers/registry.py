from __future__ import annotations

from collections.abc import Iterable

from quant_trading.data.providers.akshare_provider import AkshareProvider
from quant_trading.data.providers.base import MarketDataProvider


class ProviderRegistry:
    def __init__(self, providers: Iterable[MarketDataProvider]):
        self._providers = {self._normalize(provider.name): provider for provider in providers}

    def get(self, name: str) -> MarketDataProvider:
        normalized = self._normalize(name)
        try:
            return self._providers[normalized]
        except KeyError as exc:
            raise ValueError(f"unknown market data provider: {normalized}") from exc

    def names(self) -> list[str]:
        return sorted(self._providers)

    def _normalize(self, name: str) -> str:
        normalized = str(name or "").strip().lower()
        if not normalized:
            raise ValueError("market data provider is required")
        return normalized


def build_default_provider_registry() -> ProviderRegistry:
    return ProviderRegistry([AkshareProvider()])
