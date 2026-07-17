"""Base strategy classes and interfaces."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Any
import numpy as np
import numpy.typing as npt


class SignalType(Enum):
    """Types of trading signals."""
    HOLD = "hold"
    SWAP = "swap"
    SKIP = "skip"


@dataclass
class Signal:
    """Trading signal with execution details."""
    signal_type: SignalType
    action: str = ""  # e.g., "BTCUSDT -> ETHUSDT"
    confidence: float = 0.0  # 0.0 to 1.0
    from_token: Optional[str] = None
    to_token: Optional[str] = None
    amount: Optional[float] = None
    expected_gain: float = 0.0
    threshold_hit: bool = False
    metadata: dict[str, Any] = None

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}

    def should_execute(self, min_threshold: float = 0.0) -> bool:
        """Check if signal should be executed."""
        return (
            self.signal_type == SignalType.SWAP and
            self.threshold_hit and
            self.confidence >= min_threshold
        )


class Strategy(ABC):
    """Abstract base class for trading strategies."""

    name: str = "BaseStrategy"

    def __init__(self, **params: Any) -> None:
        """Initialize strategy with parameters."""
        self.params = params
        self._setup()

    def _setup(self) -> None:
        """Setup strategy-specific state."""
        pass

    @abstractmethod
    def evaluate(
        self,
        record_idx: int,
        swap_matrix: npt.NDArray[np.float64],
        holdings_vector: npt.NDArray[np.float64],
        token_index: dict[str, int],
        index_token: dict[int, str]
    ) -> Signal:
        """Evaluate strategy and generate signal.
        
        Args:
            record_idx: Current record index
            swap_matrix: Pre-computed swap matrix (n_tokens, n_tokens)
            holdings_vector: Current holdings (n_tokens,)
            token_index: Token to index mapping
            index_token: Index to token mapping
        
        Returns:
            Trading signal
        """
        pass

    def on_swap_executed(
        self,
        record_idx: int,
        from_token: str,
        to_token: str,
        amount_in: float,
        amount_out: float
    ) -> None:
        """Hook called after a swap is executed."""
        pass

    def reset(self) -> None:
        """Reset strategy state."""
        self._setup()

    def get_params(self) -> dict[str, Any]:
        """Get strategy parameters."""
        return self.params.copy()

    def set_params(self, **params: Any) -> None:
        """Set strategy parameters."""
        self.params.update(params)
        self._setup()

    def __repr__(self) -> str:
        return f"{self.name}({self.params})"
