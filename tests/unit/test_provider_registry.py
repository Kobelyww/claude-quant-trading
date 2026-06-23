import pytest

from quant_trading.data.providers.registry import (
    ProviderRegistry,
    build_default_provider_registry,
)


class FakeProvider:
    name = "fake"


def test_provider_registry_normalizes_names():
    registry = ProviderRegistry([FakeProvider()])

    assert registry.get(" FAKE ") is registry.get("fake")
    assert registry.names() == ["fake"]


def test_provider_registry_rejects_unknown_provider():
    registry = ProviderRegistry([FakeProvider()])

    with pytest.raises(ValueError, match="unknown market data provider: missing"):
        registry.get("missing")


def test_default_provider_registry_contains_akshare_without_importing_network_client():
    registry = build_default_provider_registry()

    assert "akshare" in registry.names()
