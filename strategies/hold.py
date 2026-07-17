"""Hold strategy - baseline that never swaps."""

from typing import Any
import numpy as np
import numpy.typing as npt

from strategies.base import Strategy, Signal, SignalType


class HoldStrategy(Strategy):
    """Baseline strategy that never swaps.
    
    Used as benchmark for comparing other strategies.
    """
    
    name: str = "HoldStrategy"

    def evaluate(
        self,
        record_idx: int,
        swap_matrix: npt.NDArray[np.float64],
        holdings_vector: npt.NDArray[np.float64],
        token_index: dict[str, int],
        index_token: dict[int, str]
    ) -> Signal:
        """Always return HOLD signal."""
        return Signal(
            signal_type=SignalType.HOLD,
            confidence=1.0,
            metadata={"strategy": self.name}
        )


class ThresholdHoldStrategy(Strategy):
    """Hold strategy with threshold - holds unless gain exceeds threshold."""
    
    name: str = "ThresholdHoldStrategy"

    def __init__(self, **params: Any) -> None:
        self.min_gain_threshold: float = params.get("min_gain_threshold", 0.0)
        super().__init__(**params)

    def _setup(self) -> None:
        """Setup tracking state."""
        self.last_swap_idx: int = -1

    def evaluate(
        self,
        record_idx: int,
        swap_matrix: npt.NDArray[np.float64],
        holdings_vector: npt.NDArray[np.float64],
        token_index: dict[str, int],
        index_token: dict[int, str]
    ) -> Signal:
        """Evaluate - only swap if gain exceeds threshold."""
        # Find currently held token
        holding_idx = np.argmax(holdings_vector > 0) if np.any(holdings_vector > 0) else -1
        
        if holding_idx < 0:
            return Signal(
                signal_type=SignalType.HOLD,
                confidence=0.0,
                metadata={"reason": "no_holding"}
            )
        
        # Get gains from current holding
        gains = swap_matrix[holding_idx]
        best_target_idx = np.argmax(gains)
        best_gain = gains[best_target_idx]
        
        from_token = index_token[holding_idx]
        to_token = index_token[best_target_idx]
        
        # Check if gain exceeds threshold
        threshold_hit = best_gain > self.min_gain_threshold
        
        return Signal(
            signal_type=SignalType.SWAP if threshold_hit else SignalType.HOLD,
            action=f"{from_token} -> {to_token}",
            confidence=min(best_gain / 2.0, 1.0) if threshold_hit else 0.0,
            from_token=from_token,
            to_token=to_token,
            expected_gain=best_gain,
            threshold_hit=threshold_hit,
            metadata={
                "strategy": self.name,
                "best_gain": float(best_gain),
                "threshold": self.min_gain_threshold
            }
        )


class DynamicHoldStrategy(Strategy):
    """Hold with dynamic threshold based on recent performance."""
    
    name: str = "DynamicHoldStrategy"

    def __init__(self, **params: Any) -> None:
        self.base_threshold: float = params.get("base_threshold", 0.0)
        self.adjustment_window: int = params.get("adjustment_window", 100)
        self.cooldown: int = params.get("cooldown", 10)
        super().__init__(**params)

    def _setup(self) -> None:
        """Setup tracking state."""
        self.price_history: list[float] = []
        self.last_swap_idx: int = -1
        self.swap_gains: list[float] = []

    def evaluate(
        self,
        record_idx: int,
        swap_matrix: npt.NDArray[np.float64],
        holdings_vector: npt.NDArray[np.float64],
        token_index: dict[str, int],
        index_token: dict[int, str]
    ) -> Signal:
        """Evaluate with dynamic threshold."""
        # Find currently held token
        holding_idx = np.argmax(holdings_vector > 0) if np.any(holdings_vector > 0) else -1
        
        if holding_idx < 0:
            return Signal(signal_type=SignalType.HOLD, confidence=0.0)
        
        # Get best swap
        gains = swap_matrix[holding_idx]
        best_target_idx = np.argmax(gains)
        best_gain = gains[best_target_idx]
        
        # Calculate dynamic threshold based on recent performance
        dynamic_threshold = self.base_threshold
        if len(self.swap_gains) > 0:
            recent_avg = np.mean(self.swap_gains[-self.adjustment_window:])
            dynamic_threshold = max(self.base_threshold, recent_avg * 0.9)
        
        from_token = index_token[holding_idx]
        to_token = index_token[best_target_idx]
        threshold_hit = best_gain > dynamic_threshold
        
        return Signal(
            signal_type=SignalType.SWAP if threshold_hit else SignalType.HOLD,
            action=f"{from_token} -> {to_token}",
            confidence=min(best_gain / 2.0, 1.0),
            from_token=from_token,
            to_token=to_token,
            expected_gain=best_gain,
            threshold_hit=threshold_hit,
            metadata={"dynamic_threshold": dynamic_threshold}
        )

    def on_swap_executed(
        self,
        record_idx: int,
        from_token: str,
        to_token: str,
        amount_in: float,
        amount_out: float
    ) -> None:
        """Track swap gains for dynamic threshold."""
        self.last_swap_idx = record_idx
        self.swap_gains.append(amount_out / amount_in if amount_in > 0 else 0)
