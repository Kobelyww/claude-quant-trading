from quant_trading.strategy.base import Strategy


class StrategyRegistry:
    def __init__(self) -> None:
        self._builtins: dict[str, type[Strategy]] = {}

    def register_builtin(self, name: str, strategy_cls: type[Strategy]) -> None:
        self._builtins[name] = strategy_cls

    def create(self, name: str, params: dict | None = None) -> Strategy:
        if name not in self._builtins:
            raise KeyError(f"unknown strategy: {name}")
        return self._builtins[name](**(params or {}))
