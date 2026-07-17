"""Strategy factory for creating and registering strategies."""

from typing import Type, Callable, Any
from strategies.base import Strategy


class StrategyRegistry:
    """Registry for trading strategies with factory pattern."""
    
    _strategies: dict[str, Type[Strategy]] = {}
    _creators: dict[str, Callable[..., Strategy]] = {}

    @classmethod
    def register(cls, name: str, strategy_class: Type[Strategy]) -> None:
        """Register a strategy class.
        
        Args:
            name: Strategy identifier
            strategy_class: Strategy class (must inherit from Strategy)
        """
        if not issubclass(strategy_class, Strategy):
            raise TypeError(f"{strategy_class} must inherit from Strategy")
        cls._strategies[name] = strategy_class

    @classmethod
    def register_creator(cls, name: str, creator: Callable[..., Strategy]) -> None:
        """Register a custom strategy creator.
        
        Args:
            name: Strategy identifier
            creator: Function that creates Strategy instances
        """
        cls._creators[name] = creator

    @classmethod
    def create(cls, name: str, **params: Any) -> Strategy:
        """Create a strategy instance by name.
        
        Args:
            name: Strategy identifier
            **params: Strategy parameters
        
        Returns:
            Strategy instance
        
        Raises:
            KeyError: If strategy not found
        """
        # Try custom creator first
        if name in cls._creators:
            return cls._creators[name](**params)
        
        # Try registered class
        if name not in cls._strategies:
            available = list(cls._strategies.keys())
            raise KeyError(f"Strategy '{name}' not found. Available: {available}")
        
        return cls._strategies[name](**params)

    @classmethod
    def list_strategies(cls) -> list[str]:
        """Get list of available strategy names."""
        strategies = list(cls._strategies.keys())
        strategies.extend(cls._creators.keys())
        return sorted(set(strategies))

    @classmethod
    def get_strategy_class(cls, name: str) -> Type[Strategy]:
        """Get strategy class by name."""
        if name in cls._strategies:
            return cls._strategies[name]
        if name in cls._creators:
            # Return a wrapper class
            creator = cls._creators[name]
            class WrapperStrategy(Strategy):
                name = name
                def evaluate(self, *args, **kwargs):
                    return self._strategy.evaluate(*args, **kwargs)
                def _setup(self):
                    self._strategy = creator(**self.params)
            return WrapperStrategy
        raise KeyError(f"Strategy '{name}' not found")


# Register built-in strategies
from strategies.hold import HoldStrategy, ThresholdHoldStrategy, DynamicHoldStrategy
from strategies.threshold import ThresholdStrategy, AdaptiveThresholdStrategy, MultiThresholdStrategy
from strategies.momentum import MomentumStrategy, RSIMomentumStrategy
from strategies.grid import GridStrategy, VolatilityGridStrategy

StrategyRegistry.register("hold", HoldStrategy)
StrategyRegistry.register("threshold_hold", ThresholdHoldStrategy)
StrategyRegistry.register("dynamic_hold", DynamicHoldStrategy)
StrategyRegistry.register("threshold", ThresholdStrategy)
StrategyRegistry.register("adaptive_threshold", AdaptiveThresholdStrategy)
StrategyRegistry.register("multi_threshold", MultiThresholdStrategy)
StrategyRegistry.register("momentum", MomentumStrategy)
StrategyRegistry.register("rsi_momentum", RSIMomentumStrategy)
StrategyRegistry.register("grid", GridStrategy)
StrategyRegistry.register("volatility_grid", VolatilityGridStrategy)


def create_strategy(name: str, **params: Any) -> Strategy:
    """Convenience function to create strategies.
    
    Args:
        name: Strategy name
        **params: Strategy parameters
    
    Returns:
        Strategy instance
    """
    return StrategyRegistry.create(name, **params)


def list_available_strategies() -> list[str]:
    """Get list of all available strategies."""
    return StrategyRegistry.list_strategies()
