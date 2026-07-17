"""Matrix-based swap simulator with realistic fee modeling."""

from dataclasses import dataclass
from typing import Optional
import numpy as np
import numpy.typing as npt

from config.settings import FeesConfig
from data.cache import DataCache


@dataclass
class SwapResult:
    """Result of a simulated swap operation."""
    success: bool
    from_token: str
    to_token: str
    amount_in: float
    amount_out: float
    fee: float
    price_in: float  # Bid price when selling
    price_out: float  # Ask price when buying
    slippage: float = 0.0
    error: Optional[str] = None

    def net_gain(self) -> float:
        """Calculate net gain (output - input in target token units)."""
        if not self.success:
            return 0.0
        return self.amount_out

    def net_gain_percent(self) -> float:
        """Calculate net gain percentage."""
        if not self.success or self.amount_in == 0:
            return 0.0
        return (self.amount_out - self.amount_in) / self.amount_in * 100


class SwapSimulator:
    """Simulates swap operations with realistic fee modeling.
    
    Uses vectorized NumPy operations for all 400 swap pair calculations.
    """
    
    def __init__(
        self,
        cache: DataCache,
        fees: Optional[FeesConfig] = None
    ):
        """Initialize simulator.
        
        Args:
            cache: DataCache with price data
            fees: Fee configuration (uses default if None)
        """
        self.cache = cache
        self.fees = fees or FeesConfig()
        self._last_swap_record_idx: int = -1
        
    @property
    def total_fee_rate(self) -> float:
        """Total fee rate for a round-trip swap (2 legs)."""
        return self.fees.swap_fee_per_leg * 2

    @property
    def fee_factor(self) -> float:
        """Fee factor to multiply by (1 - total_fee)."""
        return 1.0 - self.total_fee_rate

    def compute_swap_matrix(
        self,
        record_idx: int,
        holdings_vector: npt.NDArray[np.float64]
    ) -> npt.NDArray[np.float64]:
        """Compute all swap outcomes for current holdings.
        
        Args:
            record_idx: Current record index
            holdings_vector: Current holdings (n_tokens,)
        
        Returns:
            Matrix (n_tokens, n_tokens) of tokens gained for each swap pair
        """
        # Get price vectors
        bid_prices = self.cache.get_bid_vector(record_idx)
        ask_prices = self.cache.get_ask_vector(record_idx)
        
        n_tokens = self.cache.n_tokens
        
        # Compute swap matrix: swap[i,j] = how many token_j we get for 1 token_i
        # For A -> B: sell A for USDT at bid_A, buy B at ask_B
        # result = 1 * bid_A / ask_B * fee_factor
        
        # Create bid and ask matrices for broadcasting
        bid_row = bid_prices.reshape(-1, 1)  # (n, 1)
        ask_col = ask_prices.reshape(1, -1)  # (1, n)
        
        # Compute all swap ratios
        swap_matrix = np.zeros((n_tokens, n_tokens), dtype=np.float64)
        
        # Avoid division by zero
        with np.errstate(divide='ignore', invalid='ignore'):
            swap_matrix = (bid_row / ask_col) * self.fee_factor
            # Diagonal is 0 (no self-swaps)
            np.fill_diagonal(swap_matrix, 0.0)
            # Handle invalid values
            swap_matrix = np.where(np.isfinite(swap_matrix), swap_matrix, 0.0)
        
        # Multiply by holdings to get actual amounts
        # If we hold 1 BTC and swap BTC->ETH, we get swap_matrix[BTC_idx, ETH_idx] * 1 ETH
        result_matrix = swap_matrix * holdings_vector.reshape(-1, 1)
        
        return result_matrix

    def find_best_swap(
        self,
        record_idx: int,
        holdings: dict[str, float],
        holding_token: str
    ) -> tuple[str, str, float]:
        """Find best swap for given holdings.
        
        Args:
            record_idx: Current record index
            holdings: Current holdings {token: amount}
            holding_token: Currently held token
        
        Returns:
            Tuple of (from_token, to_token, amount_gained)
        """
        # Convert holdings to vector
        holdings_vector = np.zeros(self.cache.n_tokens, dtype=np.float64)
        for token, amount in holdings.items():
            if token in self.cache.price_matrix.token_index:
                idx = self.cache.price_matrix.token_index[token]
                holdings_vector[idx] = amount
        
        # Compute all swap outcomes
        swap_matrix = self.compute_swap_matrix(record_idx, holdings_vector)
        
        # Find best swap from current holding
        holding_idx = self.cache.price_matrix.token_index.get(holding_token, -1)
        if holding_idx < 0:
            return "", "", 0.0
        
        # Get gains from current holding token
        gains = swap_matrix[holding_idx]
        
        # Find best target
        best_target_idx = np.argmax(gains)
        best_gain = gains[best_target_idx]
        best_target = self.cache.price_matrix.index_token[best_target_idx]
        
        return holding_token, best_target, best_gain

    def execute_swap(
        self,
        record_idx: int,
        from_token: str,
        to_token: str,
        amount_in: float,
        min_amount_out: Optional[float] = None
    ) -> SwapResult:
        """Execute a simulated swap.
        
        Args:
            record_idx: Current record index
            from_token: Token to sell
            to_token: Token to buy
            amount_in: Amount of from_token to sell
            min_amount_out: Minimum output required (slippage protection)
        
        Returns:
            SwapResult with execution details
        """
        if amount_in <= 0:
            return SwapResult(
                success=False,
                from_token=from_token,
                to_token=to_token,
                amount_in=amount_in,
                amount_out=0.0,
                fee=0.0,
                price_in=0.0,
                price_out=0.0,
                error="Amount must be positive"
            )
        
        # Get prices
        price_in = self.cache.get_bid(record_idx, from_token)
        price_out = self.cache.get_ask(record_idx, to_token)
        
        if price_in <= 0 or price_out <= 0:
            return SwapResult(
                success=False,
                from_token=from_token,
                to_token=to_token,
                amount_in=amount_in,
                amount_out=0.0,
                fee=0.0,
                price_in=price_in,
                price_out=price_out,
                error="Invalid prices"
            )
        
        # Check minimum order value
        order_value = amount_in * price_in
        if order_value < self.fees.min_order_value:
            return SwapResult(
                success=False,
                from_token=from_token,
                to_token=to_token,
                amount_in=amount_in,
                amount_out=0.0,
                fee=0.0,
                price_in=price_in,
                price_out=price_out,
                error=f"Order value {order_value:.2f} below minimum {self.fees.min_order_value}"
            )
        
        # Calculate output with fees
        # Step 1: Convert to USDT at bid price
        usdt_out = amount_in * price_in * (1 - self.fees.swap_fee_per_leg)
        
        # Step 2: Convert USDT to target token at ask price
        amount_out = usdt_out / price_out * (1 - self.fees.swap_fee_per_leg)
        
        # Calculate total fee
        total_fee = amount_in * price_in * self.total_fee_rate
        
        # Check slippage
        slippage = 0.0
        if min_amount_out is not None and amount_out < min_amount_out:
            return SwapResult(
                success=False,
                from_token=from_token,
                to_token=to_token,
                amount_in=amount_in,
                amount_out=amount_out,
                fee=total_fee,
                price_in=price_in,
                price_out=price_out,
                slippage=slippage,
                error=f"Output {amount_out} below minimum {min_amount_out}"
            )
        
        self._last_swap_record_idx = record_idx
        
        return SwapResult(
            success=True,
            from_token=from_token,
            to_token=to_token,
            amount_in=amount_in,
            amount_out=amount_out,
            fee=total_fee,
            price_in=price_in,
            price_out=price_out,
            slippage=slippage
        )

    def can_swap(
        self,
        record_idx: int,
        from_token: str,
        to_token: str,
        min_interval: int = 1
    ) -> bool:
        """Check if a swap can be executed.
        
        Args:
            record_idx: Current record index
            from_token: Token to sell
            to_token: Token to buy
            min_interval: Minimum records between swaps
        
        Returns:
            True if swap is allowed
        """
        if from_token == to_token:
            return False
        
        if record_idx - self._last_swap_record_idx < min_interval:
            return False
        
        return True

    def compute_potential_gains(
        self,
        record_idx: int,
        holdings_vector: npt.NDArray[np.float64]
    ) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.intp]]:
        """Compute potential gains for all swap pairs.
        
        Args:
            record_idx: Current record index
            holdings_vector: Current holdings (n_tokens,)
        
        Returns:
            Tuple of (gains_matrix, best_targets) where:
            - gains_matrix[i] = array of gains when swapping token i
            - best_targets[i] = index of best target for token i
        """
        swap_matrix = self.compute_swap_matrix(record_idx, holdings_vector)
        
        # For each holding token, find the best target
        best_targets = np.argmax(swap_matrix, axis=1)
        
        return swap_matrix, best_targets
