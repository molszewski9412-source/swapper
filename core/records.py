"""Record tracking system for benchmark and swap history."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import numpy as np
import numpy.typing as npt


@dataclass
class SwapRecord:
    """Record of a single swap operation."""
    timestamp: int  # Unix timestamp in milliseconds
    record_index: int
    from_token: str
    to_token: str
    amount_in: float
    amount_out: float
    fee: float
    price_in: float  # Bid price when selling
    price_out: float  # Ask price when buying
    potential_before: float  # Potential value before swap
    potential_after: float  # Potential value after swap

    def to_dict(self) -> dict:
        """Convert to dictionary for export."""
        return {
            "timestamp": self.timestamp,
            "record_index": self.record_index,
            "from_token": self.from_token,
            "to_token": self.to_token,
            "amount_in": self.amount_in,
            "amount_out": self.amount_out,
            "fee": self.fee,
            "price_in": self.price_in,
            "price_out": self.price_out,
            "potential_before": self.potential_before,
            "potential_after": self.potential_after,
        }


@dataclass
class BenchmarkSnapshot:
    """Snapshot of benchmark values at a point in time.
    
    Tracks "could have had" (potential_best) and "actually had" (actual_had)
    for each token.
    """
    timestamp: int
    record_index: int
    potential: dict[str, float]  # Best potential value for each token
    actual: dict[str, Optional[float]]  # Actual value held for each token
    holding_token: Optional[str] = None  # Currently held token
    holding_amount: Optional[float] = None  # Amount held

    def to_dict(self) -> dict:
        """Convert to dictionary for export."""
        return {
            "timestamp": self.timestamp,
            "record_index": self.record_index,
            "potential": self.potential.copy(),
            "actual": {k: v for k, v in self.actual.items()},
            "holding_token": self.holding_token,
            "holding_amount": self.holding_amount,
        }


@dataclass
class RecordHistory:
    """Complete history of swap records and benchmark snapshots.
    
    Maintains the "could have had" vs "actually had" tracking system.
    """
    tokens: list[str]
    
    # Swap history
    swaps: list[SwapRecord] = field(default_factory=list)
    
    # Benchmark snapshots (sampled)
    snapshots: list[BenchmarkSnapshot] = field(default_factory=list)
    snapshot_interval: int = 100  # Record snapshot every N records
    
    # Current state
    _current_potential: dict[str, float] = field(default_factory=dict)
    _current_actual: dict[str, Optional[float]] = field(default_factory=dict)
    _holding_token: Optional[str] = None
    _holding_amount: float = 0.0
    _last_swap_record: Optional[SwapRecord] = None
    
    def __post_init__(self) -> None:
        """Initialize tracking state."""
        for token in self.tokens:
            self._current_potential[token] = 0.0
            self._current_actual[token] = None

    def set_initial_holding(self, token: str, amount: float) -> None:
        """Set initial holding and initialize actual values."""
        self._holding_token = token
        self._holding_amount = amount
        self._current_actual[token] = amount
        
        # Set initial potential to the starting amount for all tokens
        for t in self.tokens:
            self._current_potential[t] = amount

    def update_potential(
        self,
        record_index: int,
        timestamp: int,
        prices: dict[str, float],
        base_token: str = "BTCUSDT"
    ) -> None:
        """Update potential values based on current prices.
        
        For each token, calculate what the holding would be worth
        if we had started with 1 unit of base_token and optimally swapped.
        
        Args:
            record_index: Current record index
            timestamp: Current timestamp
            prices: Current prices {token: usdt_value}
            base_token: Token we measure value against
        """
        base_price = prices.get(base_token, 0)
        if base_price <= 0:
            return
        
        # Update potential for each token
        for token in self.tokens:
            if token in prices and prices[token] > 0:
                # How many units of this token equals our base unit value
                self._current_potential[token] = base_price / prices[token]
            else:
                self._current_potential[token] = self._current_potential.get(token, 0)

    def record_swap(
        self,
        record_index: int,
        timestamp: int,
        from_token: str,
        to_token: str,
        amount_in: float,
        amount_out: float,
        fee: float,
        price_in: float,
        price_out: float
    ) -> SwapRecord:
        """Record a swap operation.
        
        Args:
            record_index: Current record index
            timestamp: Current timestamp
            from_token: Token being sold
            to_token: Token being bought
            amount_in: Amount of from_token sold
            amount_out: Amount of to_token received
            fee: Total fee paid
            price_in: Bid price of from_token
            price_out: Ask price of to_token
        
        Returns:
            SwapRecord created
        """
        # Calculate potential values
        potential_before = self._current_potential.get(from_token, 0)
        potential_after = self._current_potential.get(to_token, 0)
        
        # Create swap record
        swap = SwapRecord(
            timestamp=timestamp,
            record_index=record_index,
            from_token=from_token,
            to_token=to_token,
            amount_in=amount_in,
            amount_out=amount_out,
            fee=fee,
            price_in=price_in,
            price_out=price_out,
            potential_before=potential_before,
            potential_after=potential_after,
        )
        
        # Update internal state
        self.swaps.append(swap)
        self._last_swap_record = swap
        self._holding_token = to_token
        self._holding_amount = amount_out
        self._current_actual[from_token] = None
        self._current_actual[to_token] = amount_out
        
        return swap

    def record_snapshot(
        self,
        record_index: int,
        timestamp: int
    ) -> BenchmarkSnapshot:
        """Record current state as a benchmark snapshot."""
        snapshot = BenchmarkSnapshot(
            timestamp=timestamp,
            record_index=record_index,
            potential=self._current_potential.copy(),
            actual=self._current_actual.copy(),
            holding_token=self._holding_token,
            holding_amount=self._holding_amount,
        )
        self.snapshots.append(snapshot)
        return snapshot

    def should_record_snapshot(self, record_index: int) -> bool:
        """Check if we should record a snapshot at this index."""
        return record_index % self.snapshot_interval == 0

    def get_current_holding(self) -> tuple[Optional[str], float]:
        """Get current holding token and amount."""
        return self._holding_token, self._holding_amount

    def get_potential_value(self, token: str) -> float:
        """Get potential value for a token."""
        return self._current_potential.get(token, 0.0)

    def get_actual_value(self, token: str) -> Optional[float]:
        """Get actual value for a token."""
        return self._current_actual.get(token)

    def get_potential_improvement(self, token: str) -> float:
        """Calculate potential improvement (potential - actual) for a token."""
        potential = self._current_potential.get(token, 0)
        actual = self._current_actual.get(token) or 0
        return potential - actual

    def get_total_opportunity_cost(self) -> float:
        """Calculate total opportunity cost across all tokens."""
        total = 0.0
        for token in self.tokens:
            total += self.get_potential_improvement(token)
        return total

    def get_swap_count(self) -> int:
        """Get number of swaps performed."""
        return len(self.swaps)

    def export_swaps(self) -> list[dict]:
        """Export all swap records as list of dicts."""
        return [s.to_dict() for s in self.swaps]

    def export_snapshots(self) -> list[dict]:
        """Export all snapshots as list of dicts."""
        return [s.to_dict() for s in self.snapshots]

    def get_summary(self) -> dict:
        """Get summary statistics."""
        if not self.swaps:
            return {
                "swap_count": 0,
                "total_fees": 0.0,
                "avg_swap_size": 0.0,
                "opportunity_cost": self.get_total_opportunity_cost(),
            }
        
        total_fees = sum(s.fee for s in self.swaps)
        avg_amount = np.mean([s.amount_in for s in self.swaps])
        
        return {
            "swap_count": len(self.swaps),
            "total_fees": total_fees,
            "avg_swap_size": avg_amount,
            "opportunity_cost": self.get_total_opportunity_cost(),
            "first_swap_timestamp": self.swaps[0].timestamp if self.swaps else None,
            "last_swap_timestamp": self.swaps[-1].timestamp if self.swaps else None,
        }


@dataclass 
class MatrixRecordTracker:
    """Optimized record tracker using NumPy arrays for vectorized operations.
    
    Uses 2D arrays for O(1) lookups instead of dict-based tracking.
    """
    n_tokens: int
    token_index: dict[str, int]
    index_token: dict[int, str]
    
    # Arrays for tracking
    potential_matrix: npt.NDArray[np.float64]  # (n_tokens,) current potential per token
    actual_vector: npt.NDArray[np.float64]  # (n_tokens,) actual held per token (-1 = no holding)
    
    # History
    swap_history: list[SwapRecord] = field(default_factory=list)
    
    # Current state
    _holding_idx: int = -1  # Index of currently held token
    _holding_amount: float = 0.0
    _record_count: int = 0  # Records processed
    
    @classmethod
    def create(cls, tokens: list[str]) -> "MatrixRecordTracker":
        """Create tracker with token list."""
        token_index = {t: i for i, t in enumerate(tokens)}
        index_token = {i: t for i, t in enumerate(tokens)}
        n_tokens = len(tokens)
        
        return cls(
            n_tokens=n_tokens,
            token_index=token_index,
            index_token=index_token,
            potential_matrix=np.zeros(n_tokens, dtype=np.float64),
            actual_vector=np.full(n_tokens, -1.0, dtype=np.float64),  # -1 = no holding
        )

    def set_initial(self, token: str, amount: float) -> None:
        """Set initial holding."""
        self._holding_idx = self.token_index.get(token, -1)
        self._holding_amount = amount
        if self._holding_idx >= 0:
            self.actual_vector[self._holding_idx] = amount
            self.potential_matrix[:] = amount  # All potentials start equal

    def update_potential_vector(self, prices: npt.NDArray[np.float64]) -> None:
        """Update all potential values from price vector.
        
        Args:
            prices: Array of USDT values for each token (n_tokens,)
        """
        holding_value = self._holding_amount * prices[self._holding_idx] if self._holding_idx >= 0 else 0
        # potential[i] = holding_value / prices[i] = how many of token i we could have
        with np.errstate(divide='ignore', invalid='ignore'):
            self.potential_matrix = np.where(
                prices > 0,
                holding_value / prices,
                self.potential_matrix
            )

    def record_swap(
        self,
        record_index: int,
        timestamp: int,
        from_idx: int,
        to_idx: int,
        amount_out: float,
        fee: float,
        price_in: float,
        price_out: float
    ) -> SwapRecord:
        """Record swap operation with indices."""
        from_token = self.index_token[from_idx]
        to_token = self.index_token[to_idx]
        
        swap = SwapRecord(
            timestamp=timestamp,
            record_index=record_index,
            from_token=from_token,
            to_token=to_token,
            amount_in=self._holding_amount,
            amount_out=amount_out,
            fee=fee,
            price_in=price_in,
            price_out=price_out,
            potential_before=self.potential_matrix[from_idx],
            potential_after=self.potential_matrix[to_idx],
        )
        
        # Update state
        self.actual_vector[from_idx] = -1.0
        self.actual_vector[to_idx] = amount_out
        self._holding_idx = to_idx
        self._holding_amount = amount_out
        self.swap_history.append(swap)
        
        return swap

    @property
    def holding_token(self) -> Optional[str]:
        """Get currently held token symbol."""
        if self._holding_idx < 0:
            return None
        return self.index_token[self._holding_idx]

    @property
    def holding_amount(self) -> float:
        """Get current holding amount."""
        return self._holding_amount

    def get_potential(self, token: str) -> float:
        """Get potential value for token."""
        return self.potential_matrix[self.token_index[token]]

    def get_actual(self, token: str) -> Optional[float]:
        """Get actual value for token."""
        val = self.actual_vector[self.token_index[token]]
        return None if val < 0 else val
