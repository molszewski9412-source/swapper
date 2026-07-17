"""Core data models for Swapper backtesting engine."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import numpy as np
import numpy.typing as npt


@dataclass(frozen=True)
class Token:
    """Represents a tradable token."""
    symbol: str
    decimals: int = 8

    def __post_init__(self) -> None:
        if not self.symbol.endswith("USDT"):
            object.__setattr__(self, "symbol", f"{self.symbol}USDT")


@dataclass
class PricePoint:
    """Single price observation for a token."""
    timestamp: datetime
    token: str
    bid: float
    ask: float

    @property
    def mid_price(self) -> float:
        """Calculate mid price (average of bid and ask)."""
        return (self.bid + self.ask) / 2

    @property
    def spread(self) -> float:
        """Calculate bid-ask spread."""
        return self.ask - self.bid

    @property
    def spread_bps(self) -> float:
        """Calculate spread in basis points."""
        return (self.spread / self.mid_price) * 10000


@dataclass
class MarketSnapshot:
    """Market state at a single point in time."""
    timestamp: datetime
    record_index: int
    prices: dict[str, PricePoint] = field(default_factory=dict)

    def get_price(self, token: str, use_bid: bool = True) -> Optional[float]:
        """Get price for a token. Returns None if token not available."""
        price_point = self.prices.get(token)
        if price_point is None:
            return None
        return price_point.bid if use_bid else price_point.ask

    def get_spread(self, token: str) -> Optional[float]:
        """Get spread for a token."""
        price_point = self.prices.get(token)
        return price_point.spread if price_point else None


@dataclass
class PriceMatrix:
    """NumPy-based matrix for vectorized price operations.
    
    Stores bid and ask prices as 2D arrays for O(1) lookups.
    Shape: (n_tokens,) for 1D, (n_tokens, n_tokens) for swap matrices.
    """
    bid_matrix: npt.NDArray[np.float64]
    ask_matrix: npt.NDArray[np.float64]
    timestamps: npt.NDArray[np.int64]
    token_index: dict[str, int]
    index_token: dict[int, str]

    @classmethod
    def create(
        cls,
        n_records: int,
        n_tokens: int,
        tokens: list[str]
    ) -> "PriceMatrix":
        """Create an empty PriceMatrix with specified dimensions."""
        bid_matrix = np.zeros((n_records, n_tokens), dtype=np.float64)
        ask_matrix = np.zeros((n_records, n_tokens), dtype=np.float64)
        timestamps = np.zeros(n_records, dtype=np.int64)
        token_index = {token: idx for idx, token in enumerate(tokens)}
        index_token = {idx: token for token, idx in token_index.items()}
        return cls(bid_matrix, ask_matrix, timestamps, token_index, index_token)

    def set_prices(
        self,
        record_idx: int,
        timestamp: int,
        prices: dict[str, tuple[float, float]]
    ) -> None:
        """Set bid/ask prices for a record. prices: {token: (bid, ask)}"""
        self.timestamps[record_idx] = timestamp
        for token, (bid, ask) in prices.items():
            if token in self.token_index:
                idx = self.token_index[token]
                self.bid_matrix[record_idx, idx] = bid
                self.ask_matrix[record_idx, idx] = ask

    def get_bid(self, record_idx: int, token: str) -> float:
        """Get bid price for token at record index."""
        return self.bid_matrix[record_idx, self.token_index[token]]

    def get_ask(self, record_idx: int, token: str) -> float:
        """Get ask price for token at record index."""
        return self.ask_matrix[record_idx, self.token_index[token]]

    def get_bid_vector(self, record_idx: int) -> npt.NDArray[np.float64]:
        """Get all bid prices at record index as vector."""
        return self.bid_matrix[record_idx]

    def get_ask_vector(self, record_idx: int) -> npt.NDArray[np.float64]:
        """Get all ask prices at record index as vector."""
        return self.ask_matrix[record_idx]

    @property
    def n_records(self) -> int:
        """Number of records in the matrix."""
        return self.bid_matrix.shape[0]

    @property
    def n_tokens(self) -> int:
        """Number of tokens in the matrix."""
        return self.bid_matrix.shape[1]

    @property
    def tokens(self) -> list[str]:
        """List of all tokens."""
        return list(self.token_index.keys())


@dataclass
class SwapMatrix:
    """Pre-computed 20x20 swap return matrix.
    
    swap_matrix[i, j] = number of token_j gained when swapping 1 unit of token_i.
    """
    matrix: npt.NDArray[np.float64]
    record_index: int
    timestamp: int
    token_index: dict[str, int]
    index_token: dict[int, str]

    @classmethod
    def compute(
        cls,
        price_matrix: PriceMatrix,
        record_idx: int,
        fees: tuple[float, float] = (0.0004, 0.0004)
    ) -> "SwapMatrix":
        """Compute swap matrix from price matrix at given record.
        
        Args:
            price_matrix: PriceMatrix with bid/ask prices
            record_idx: Index of the record
            fees: (swap_fee, additional_fee) per leg
        
        Returns:
            SwapMatrix where swap_matrix[i,j] = tokens gained from token_i to token_j
        """
        n_tokens = price_matrix.n_tokens
        swap_matrix = np.zeros((n_tokens, n_tokens), dtype=np.float64)
        
        # Get price vectors
        bid_prices = price_matrix.get_bid_vector(record_idx)
        ask_prices = price_matrix.get_ask_vector(record_idx)
        
        # For swap A -> B:
        # 1. Sell A for USDT at bid price
        # 2. Buy B with USDT at ask price
        # Result: amount_B = (amount_A * bid_A) / ask_B * (1 - fee_total)
        
        fee_factor = (1 - fees[0]) * (1 - fees[1])  # Combined fee factor
        
        # Compute all pairs: swap_matrix[i, j] = bid_i / ask_j * fee_factor
        # For each i (from token) and j (to token)
        for i in range(n_tokens):
            for j in range(n_tokens):
                if i != j and bid_prices[i] > 0 and ask_prices[j] > 0:
                    # 1 unit of token i -> USDT at bid -> token j at ask
                    swap_matrix[i, j] = (bid_prices[i] / ask_prices[j]) * fee_factor
        
        return cls(
            matrix=swap_matrix,
            record_index=record_idx,
            timestamp=price_matrix.timestamps[record_idx],
            token_index=price_matrix.token_index.copy(),
            index_token=price_matrix.index_token.copy()
        )

    def get_swap_return(self, from_token: str, to_token: str) -> float:
        """Get swap return ratio (tokens gained per unit swapped)."""
        i = self.token_index[from_token]
        j = self.token_index[to_token]
        return self.matrix[i, j]

    def find_best_swap(self, holding_token: str) -> tuple[str, float]:
        """Find the best token to swap to from holding_token."""
        i = self.token_index[holding_token]
        j_max = np.argmax(self.matrix[i])
        return self.index_token[j_max], self.matrix[i, j_max]
