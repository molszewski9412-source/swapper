"""Threshold-based trading strategies."""

from typing import Any
import numpy as np
import numpy.typing as npt

from strategies.base import Strategy, Signal, SignalType


class ThresholdStrategy(Strategy):
    """Swap when swap gain exceeds configurable threshold.
    
    Most common and effective strategy for backtesting.
    """
    
    name: str = "ThresholdStrategy"

    def __init__(self, **params: Any) -> None:
        self.threshold: float = params.get("threshold", 1.0)  # Minimum gain multiplier
        self.min_swap_interval: int = params.get("min_swap_interval", 1)  # Cooldown
        super().__init__(**params)

    def _setup(self) -> None:
        """Setup tracking state."""
        self.last_swap_record: int = -1

    def evaluate(
        self,
        record_idx: int,
        swap_matrix: npt.NDArray[np.float64],
        holdings_vector: npt.NDArray[np.float64],
        token_index: dict[str, int],
        index_token: dict[int, str]
    ) -> Signal:
        """Evaluate threshold strategy."""
        # Check cooldown
        if record_idx - self.last_swap_record < self.min_swap_interval:
            return Signal(
                signal_type=SignalType.SKIP,
                confidence=0.0,
                metadata={"reason": "cooldown", "records_remaining": self.min_swap_interval - (record_idx - self.last_swap_record)}
            )

        # Find currently held token
        holding_idx = -1
        for i, h in enumerate(holdings_vector):
            if h > 0:
                holding_idx = i
                break
        
        if holding_idx < 0:
            return Signal(signal_type=SignalType.HOLD, confidence=0.0)
        
        # Get gains from current holding
        gains = swap_matrix[holding_idx]
        best_target_idx = np.argmax(gains)
        best_gain = gains[best_target_idx]
        
        from_token = index_token[holding_idx]
        to_token = index_token[best_target_idx]
        
        # Check threshold
        threshold_hit = best_gain > self.threshold
        
        return Signal(
            signal_type=SignalType.SWAP if threshold_hit else SignalType.HOLD,
            action=f"{from_token} -> {to_token}",
            confidence=min(best_gain / 2.0, 1.0) if threshold_hit else 0.0,
            from_token=from_token,
            to_token=to_token,
            amount=holdings_vector[holding_idx],
            expected_gain=best_gain,
            threshold_hit=threshold_hit,
            metadata={"threshold": self.threshold, "gain": float(best_gain)}
        )

    def on_swap_executed(
        self,
        record_idx: int,
        from_token: str,
        to_token: str,
        amount_in: float,
        amount_out: float
    ) -> None:
        """Record swap for cooldown tracking."""
        self.last_swap_record = record_idx


class AdaptiveThresholdStrategy(Strategy):
    """Threshold with adaptive adjustment based on volatility."""
    
    name: str = "AdaptiveThresholdStrategy"

    def __init__(self, **params: Any) -> None:
        self.base_threshold: float = params.get("base_threshold", 1.0)
        self.volatility_window: int = params.get("volatility_window", 50)
        self.volatility_multiplier: float = params.get("volatility_multiplier", 2.0)
        self.min_swap_interval: int = params.get("min_swap_interval", 1)
        super().__init__(**params)

    def _setup(self) -> None:
        """Setup tracking state."""
        self.last_swap_record: int = -1
        self.gain_history: list[float] = []

    def evaluate(
        self,
        record_idx: int,
        swap_matrix: npt.NDArray[np.float64],
        holdings_vector: npt.NDArray[np.float64],
        token_index: dict[str, int],
        index_token: dict[int, str]
    ) -> Signal:
        """Evaluate with adaptive threshold."""
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

        # Calculate adaptive threshold
        adaptive_threshold = self.base_threshold
        if len(self.gain_history) >= self.volatility_window:
            recent_gains = self.gain_history[-self.volatility_window:]
            volatility = np.std(recent_gains)
            adaptive_threshold = self.base_threshold + volatility * self.volatility_multiplier

        from_token = index_token[holding_idx]
        to_token = index_token[best_target_idx]
        threshold_hit = best_gain > adaptive_threshold

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
                "threshold": adaptive_threshold,
                "gain": float(best_gain),
                "is_adaptive": True
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
        """Track gains for volatility calculation."""
        self.last_swap_record = record_idx
        self.gain_history.append(amount_out / amount_in if amount_in > 0 else 0)


class MultiThresholdStrategy(Strategy):
    """Multiple thresholds for different token pairs."""
    
    name: str = "MultiThresholdStrategy"

    def __init__(self, **params: Any) -> None:
        self.default_threshold: float = params.get("default_threshold", 1.0)
        self.pair_thresholds: dict[str, float] = params.get("pair_thresholds", {})
        self.min_swap_interval: int = params.get("min_swap_interval", 1)
        super().__init__(**params)

    def _setup(self) -> None:
        """Setup tracking state."""
        self.last_swap_record: int = -1
        self.last_swap_pair: str = ""

    def _get_threshold(self, from_token: str, to_token: str) -> float:
        """Get threshold for specific token pair."""
        pair_key = f"{from_token}_{to_token}"
        reverse_key = f"{to_token}_{from_token}"
        return self.pair_thresholds.get(pair_key, self.pair_thresholds.get(reverse_key, self.default_threshold))

    def evaluate(
        self,
        record_idx: int,
        swap_matrix: npt.NDArray[np.float64],
        holdings_vector: npt.NDArray[np.float64],
        token_index: dict[str, int],
        index_token: dict[int, str]
    ) -> Signal:
        """Evaluate with pair-specific thresholds."""
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
        
        # Find best target considering pair-specific thresholds
        best_target_idx = -1
        best_adjusted_gain = 0.0
        from_token = index_token[holding_idx]
        
        for j, gain in enumerate(gains):
            if j == holding_idx:
                continue
            to_token = index_token[j]
            threshold = self._get_threshold(from_token, to_token)
            adjusted_gain = gain / threshold  # Higher if gain exceeds threshold
            if adjusted_gain > best_adjusted_gain:
                best_adjusted_gain = adjusted_gain
                best_target_idx = j
        
        if best_target_idx < 0:
            return Signal(signal_type=SignalType.HOLD, confidence=0.0)
        
        best_gain = gains[best_target_idx]
        to_token = index_token[best_target_idx]
        threshold = self._get_threshold(from_token, to_token)
        threshold_hit = best_gain > threshold

        return Signal(
            signal_type=SignalType.SWAP if threshold_hit else SignalType.HOLD,
            action=f"{from_token} -> {to_token}",
            confidence=min(best_gain / 2.0, 1.0),
            from_token=from_token,
            to_token=to_token,
            amount=holdings_vector[holding_idx],
            expected_gain=best_gain,
            threshold_hit=threshold_hit,
            metadata={"threshold": threshold, "gain": float(best_gain)}
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
        self.last_swap_pair = f"{from_token}_{to_token}"
