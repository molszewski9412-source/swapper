"""Portfolio model for tracking token holdings."""

from dataclasses import dataclass, field
from typing import Optional
import numpy as np
import numpy.typing as npt


@dataclass
class Portfolio:
    """Portfolio tracking token holdings and value.
    
    Tracks holdings in both token amounts and USDT value.
    """
    tokens: list[str]
    initial_capital: float = 1.0
    starting_token: str = "BTCUSDT"
    
    # Holdings (token -> amount)
    _holdings: dict[str, float] = field(default_factory=dict)
    
    # Current state
    _holding_token: Optional[str] = None
    _record_count: int = 0
    
    def __post_init__(self) -> None:
        """Initialize portfolio with starting capital."""
        self._holdings = {token: 0.0 for token in self.tokens}
        self._holding_token = self.starting_token
        self._holdings[self.starting_token] = self.initial_capital

    def get_holding(self, token: str) -> float:
        """Get amount held of a token."""
        return self._holdings.get(token, 0.0)

    def set_holding(self, token: str, amount: float) -> None:
        """Set amount held of a token."""
        if token not in self._holdings:
            self._holdings[token] = 0.0
        self._holdings[token] = amount

    @property
    def holding_token(self) -> Optional[str]:
        """Get currently held token."""
        return self._holding_token

    @property
    def holding_amount(self) -> float:
        """Get amount of currently held token."""
        if self._holding_token:
            return self._holdings.get(self._holding_token, 0.0)
        return 0.0

    @property
    def all_holdings(self) -> dict[str, float]:
        """Get copy of all holdings."""
        return self._holdings.copy()

    def value_in_token(self, token: str, prices: dict[str, float]) -> float:
        """Calculate total portfolio value in a specific token.
        
        Args:
            token: Token to measure value in
            prices: Current prices {token: usdt_value}
        
        Returns:
            Portfolio value in specified token
        """
        target_price = prices.get(token, 0)
        if target_price <= 0:
            return 0.0
        
        usdt_value = self.value_in_usdt(prices)
        return usdt_value / target_price

    def value_in_usdt(self, prices: dict[str, float]) -> float:
        """Calculate total portfolio value in USDT.
        
        Args:
            prices: Current prices {token: usdt_value}
        
        Returns:
            Portfolio value in USDT
        """
        total = 0.0
        for token, amount in self._holdings.items():
            if amount > 0 and token in prices:
                total += amount * prices[token]
        return total

    def perform_swap(
        self,
        from_token: str,
        to_token: str,
        amount_in: float,
        amount_out: float,
        fee: float
    ) -> None:
        """Execute a swap operation.
        
        Args:
            from_token: Token being sold
            to_token: Token being bought
            amount_in: Amount of from_token sold
            amount_out: Amount of to_token received (after fee)
            fee: Fee paid
        """
        # Update holdings
        self._holdings[from_token] = max(0, self._holdings.get(from_token, 0) - amount_in)
        self._holdings[to_token] = self._holdings.get(to_token, 0) + amount_out
        
        # Update holding token
        if self._holdings.get(from_token, 0) <= 0:
            self._holding_token = to_token
        elif self._holdings.get(to_token, 0) > 0:
            self._holding_token = to_token

    def reset(self) -> None:
        """Reset portfolio to initial state."""
        self._holdings = {token: 0.0 for token in self.tokens}
        self._holding_token = self.starting_token
        self._holdings[self.starting_token] = self.initial_capital
        self._record_count = 0

    def increment_record(self) -> None:
        """Increment record counter."""
        self._record_count += 1

    @property
    def record_count(self) -> int:
        """Get number of records processed."""
        return self._record_count


@dataclass
class VectorizedPortfolio:
    """Portfolio optimized with NumPy for vectorized operations."""
    tokens: list[str]
    initial_capital: float = 1.0
    starting_token: str = "BTCUSDT"
    
    _token_index: dict[str, int] = field(init=False)
    _holdings: npt.NDArray[np.float64] = field(init=False)
    _holding_idx: int = field(init=False, default=-1)
    _record_count: int = field(init=False, default=0)
    
    def __post_init__(self) -> None:
        """Initialize vectorized portfolio."""
        self._token_index = {t: i for i, t in enumerate(self.tokens)}
        self._holdings = np.zeros(len(self.tokens), dtype=np.float64)
        
        if self.starting_token in self._token_index:
            self._holding_idx = self._token_index[self.starting_token]
            self._holdings[self._holding_idx] = self.initial_capital

    def get_holding(self, token: str) -> float:
        """Get holding amount for token."""
        return self._holdings[self._token_index.get(token, -1)]

    def set_holding(self, token: str, amount: float) -> None:
        """Set holding amount for token."""
        idx = self._token_index.get(token, -1)
        if idx >= 0:
            self._holdings[idx] = amount

    @property
    def holding_token(self) -> Optional[str]:
        """Get currently held token."""
        if self._holding_idx < 0:
            return None
        return self.tokens[self._holding_idx]

    @property
    def holding_amount(self) -> float:
        """Get amount of currently held token."""
        return self._holdings[self._holding_idx]

    def get_holdings_vector(self) -> npt.NDArray[np.float64]:
        """Get copy of holdings vector."""
        return self._holdings.copy()

    def value_in_usdt(self, prices: npt.NDArray[np.float64]) -> float:
        """Calculate portfolio value in USDT using vectorized ops.
        
        Args:
            prices: Price vector (n_tokens,) with USDT values
        
        Returns:
            Portfolio value in USDT
        """
        return float(np.dot(self._holdings, prices))

    def value_in_token_vectorized(
        self,
        prices: npt.NDArray[np.float64],
        target_idx: int
    ) -> float:
        """Calculate portfolio value in a specific token using vectorized ops.
        
        Args:
            prices: Price vector (n_tokens,)
            target_idx: Index of target token
        
        Returns:
            Portfolio value in target token
        """
        target_price = prices[target_idx]
        if target_price <= 0:
            return 0.0
        return self.value_in_usdt(prices) / target_price

    def perform_swap(
        self,
        from_idx: int,
        to_idx: int,
        amount_in: float,
        amount_out: float
    ) -> None:
        """Execute swap using token indices."""
        self._holdings[from_idx] = max(0, self._holdings[from_idx] - amount_in)
        self._holdings[to_idx] = self._holdings[to_idx] + amount_out
        self._holding_idx = to_idx

    def reset(self) -> None:
        """Reset portfolio to initial state."""
        self._holdings = np.zeros(len(self.tokens), dtype=np.float64)
        self._holding_idx = self._token_index.get(self.starting_token, -1)
        if self._holding_idx >= 0:
            self._holdings[self._holding_idx] = self.initial_capital
        self._record_count = 0

    def increment_record(self) -> None:
        """Increment record counter."""
        self._record_count += 1

    @property
    def record_count(self) -> int:
        """Get number of records processed."""
        return self._record_count
