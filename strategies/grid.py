"""Grid-based trading strategies."""

from typing import Any
import numpy as np
import numpy.typing as npt

from strategies.base import Strategy, Signal, SignalType


class GridStrategy(Strategy):
    """Grid-based strategy that considers multiple price levels.
    
    Maintains a grid of price levels and swaps when tokens cross grid boundaries.
    """
    
    name: str = "GridStrategy"

    def __init__(self, **params: Any) -> None:
        self.threshold: float = params.get("threshold", 1.0)
        self.grid_levels: int = params.get("grid_levels", 5)
        self.rebalance_threshold: float = params.get("rebalance_threshold", 0.2)
        self.min_swap_interval: int = params.get("min_swap_interval", 1)
        super().__init__(**params)

    def _setup(self) -> None:
        """Setup tracking state."""
        self.last_swap_record: int = -1
        self.grid_boundaries: dict[str, list[float]] = {}

    def _update_grid(self, token: str, price: float) -> None:
        """Update grid boundaries for a token."""
        if token not in self.grid_boundaries:
            self.grid_boundaries[token] = []
        
        boundaries = self.grid_boundaries[token]
        if len(boundaries) == 0:
            # Initialize grid centered on current price
            for i in range(self.grid_levels + 1):
                offset = (i - self.grid_levels // 2) * price * 0.1
                boundaries.append(price + offset)
        else:
            # Update last boundary
            boundaries[-1] = price

    def _crossed_grid_boundary(self, old_price: float, new_price: float, boundaries: list[float]) -> bool:
        """Check if price crossed a grid boundary."""
        for boundary in boundaries:
            if (old_price < boundary <= new_price) or (old_price > boundary >= new_price):
                return True
        return False

    def evaluate(
        self,
        record_idx: int,
        swap_matrix: npt.NDArray[np.float64],
        holdings_vector: npt.NDArray[np.float64],
        token_index: dict[str, int],
        index_token: dict[int, str]
    ) -> Signal:
        """Evaluate grid strategy."""
        if record_idx - self.last_swap_record < self.min_swap_interval:
            return Signal(signal_type=SignalType.SKIP, confidence=0.0)

        holding_idx = -1
        for i, h in enumerate(holdings_vector):
            if h > 0:
                holding_idx = i
                break
        
        if holding_idx < 0:
            return Signal(signal_type=SignalType.HOLD, confidence=0.0)

        gains = swap_matrix[holding_idx]
        best_target_idx = np.argmax(gains)
        best_gain = gains[best_target_idx]

        from_token = index_token[holding_idx]
        to_token = index_token[best_target_idx]
        threshold_hit = best_gain > self.threshold

        return Signal(
            signal_type=SignalType.SWAP if threshold_hit else SignalType.HOLD,
            action=f"{from_token} -> {to_token}",
            confidence=min(best_gain / 2.0, 1.0),
            from_token=from_token,
            to_token=to_token,
            amount=holdings_vector[holding_idx],
            expected_gain=best_gain,
            threshold_hit=threshold_hit,
            metadata={"grid_levels": self.grid_levels}
        )

    def on_swap_executed(
        self,
        record_idx: int,
        from_token: str,
        to_token: str,
        amount_in: float,
        amount_out: float
    ) -> None:
        """Record swap and reset grid."""
        self.last_swap_record = record_idx
        # Reset grid for new token
        if to_token in self.grid_boundaries:
            del self.grid_boundaries[to_token]


class VolatilityGridStrategy(Strategy):
    """Grid strategy with volatility-based spacing."""
    
    name: str = "VolatilityGridStrategy"

    def __init__(self, **params: Any) -> None:
        self.threshold: float = params.get("threshold", 1.0)
        self.volatility_window: int = params.get("volatility_window", 50)
        self.volatility_multiplier: float = params.get("volatility_multiplier", 2.0)
        self.min_swap_interval: int = params.get("min_swap_interval", 1)
        super().__init__(**params)

    def _setup(self) -> None:
        """Setup tracking state."""
        self.last_swap_record: int = -1
        self.price_history: dict[str, list[float]] = {}

    def _calculate_volatility(self, token: str) -> float:
        """Calculate rolling volatility for a token."""
        if token not in self.price_history or len(self.price_history[token]) < self.volatility_window:
            return 0.0
        
        prices = self.price_history[token][-self.volatility_window:]
        returns = np.diff(prices) / prices[:-1]
        return np.std(returns) if len(returns) > 0 else 0.0

    def evaluate(
        self,
        record_idx: int,
        swap_matrix: npt.NDArray[np.float64],
        holdings_vector: npt.NDArray[np.float64],
        token_index: dict[str, int],
        index_token: dict[int, str],
        current_prices: dict[str, float] = None
    ) -> Signal:
        """Evaluate volatility grid strategy."""
        if record_idx - self.last_swap_record < self.min_swap_interval:
            return Signal(signal_type=SignalType.SKIP, confidence=0.0)

        if current_prices:
            for token, price in current_prices.items():
                if token not in self.price_history:
                    self.price_history[token] = []
                self.price_history[token].append(price)

        holding_idx = -1
        for i, h in enumerate(holdings_vector):
            if h > 0:
                holding_idx = i
                break
        
        if holding_idx < 0:
            return Signal(signal_type=SignalType.HOLD, confidence=0.0)

        gains = swap_matrix[holding_idx]
        best_target_idx = np.argmax(gains)
        best_gain = gains[best_target_idx]

        from_token = index_token[holding_idx]
        to_token = index_token[best_target_idx]
        
        # Adjust threshold based on volatility
        volatility = self._calculate_volatility(to_token)
        adjusted_threshold = self.threshold + volatility * self.volatility_multiplier
        
        threshold_hit = best_gain > adjusted_threshold

        return Signal(
            signal_type=SignalType.SWAP if threshold_hit else SignalType.HOLD,
            action=f"{from_token} -> {to_token}",
            confidence=min(best_gain / 2.0, 1.0),
            from_token=from_token,
            to_token=to_token,
            amount=holdings_vector[holding_idx],
            expected_gain=best_gain,
            threshold_hit=threshold_hit,
            metadata={
                "volatility": float(volatility),
                "adjusted_threshold": adjusted_threshold
            }
        )

    def on_swap_executed(
        self,
        record_idx: int,
        from_token: str,
        to_token: str,
        amount_in: float,
        amount_out: float
    ) -> None:
        """Record swap."""
        self.last_swap_record = record_idx
