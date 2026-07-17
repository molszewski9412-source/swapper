"""Data cache for fast market data access."""

from typing import Optional
import logging
import numpy as np
import numpy.typing as npt

from core.models import PriceMatrix, SwapMatrix, MarketSnapshot


logger = logging.getLogger(__name__)


class DataCache:
    """High-performance cache for market data with O(1) lookups.
    
    Provides fast access to:
    - Bid/ask prices by record index and token
    - Pre-computed swap matrices
    - Market snapshots
    """
    
    def __init__(self, price_matrix: PriceMatrix, swap_fee: float = 0.0004):
        """Initialize cache with price matrix.
        
        Args:
            price_matrix: PriceMatrix with all bid/ask prices
            swap_fee: Fee per swap leg (0.04% = 0.0004)
        """
        self._price_matrix = price_matrix
        self._swap_fee = swap_fee
        self._swap_cache: dict[int, SwapMatrix] = {}
        self._cache_enabled = True
        
        logger.info(
            f"Cache initialized: {price_matrix.n_records} records, "
            f"{price_matrix.n_tokens} tokens"
        )

    @property
    def price_matrix(self) -> PriceMatrix:
        """Access underlying price matrix."""
        return self._price_matrix

    @property
    def n_records(self) -> int:
        """Number of cached records."""
        return self._price_matrix.n_records

    @property
    def n_tokens(self) -> int:
        """Number of tokens."""
        return self._price_matrix.n_tokens

    @property
    def tokens(self) -> list[str]:
        """List of all tokens."""
        return self._price_matrix.tokens

    def enable_cache(self) -> None:
        """Enable swap matrix caching."""
        self._cache_enabled = True

    def disable_cache(self) -> None:
        """Disable swap matrix caching (save memory)."""
        self._cache_enabled = False
        self._swap_cache.clear()

    def clear_cache(self) -> None:
        """Clear swap matrix cache."""
        self._swap_cache.clear()

    def get_snapshot(self, record_idx: int) -> MarketSnapshot:
        """Get market snapshot at record index.
        
        Args:
            record_idx: Index of the record
        
        Returns:
            MarketSnapshot with all available prices
        """
        if record_idx < 0 or record_idx >= self.n_records:
            raise IndexError(f"Record index {record_idx} out of range [0, {self.n_records})")
        
        timestamp = self._price_matrix.timestamps[record_idx]
        prices: dict[str, tuple[float, float]] = {}
        
        for token in self.tokens:
            bid = self._price_matrix.bid_matrix[record_idx, self._price_matrix.token_index[token]]
            ask = self._price_matrix.ask_matrix[record_idx, self._price_matrix.token_index[token]]
            if bid > 0 and ask > 0:
                prices[token] = (bid, ask)
        
        return MarketSnapshot(
            timestamp=timestamp,
            record_index=record_idx,
            prices={}
        )

    def get_swap_matrix(self, record_idx: int, compute_on_miss: bool = True) -> Optional[SwapMatrix]:
        """Get pre-computed swap matrix at record index.
        
        Args:
            record_idx: Index of the record
            compute_on_miss: If True, compute and cache on cache miss
        
        Returns:
            SwapMatrix or None if not cached and compute_on_miss=False
        """
        if not self._cache_enabled:
            return SwapMatrix.compute(
                self._price_matrix,
                record_idx,
                fees=(self._swap_fee, self._swap_fee)
            )
        
        if record_idx not in self._swap_cache:
            if compute_on_miss:
                self._swap_cache[record_idx] = SwapMatrix.compute(
                    self._price_matrix,
                    record_idx,
                    fees=(self._swap_fee, self._swap_fee)
                )
            else:
                return None
        
        return self._swap_cache[record_idx]

    def precompute_swap_matrices(
        self,
        start_idx: int = 0,
        end_idx: Optional[int] = None,
        progress_callback: Optional[callable] = None
    ) -> None:
        """Pre-compute and cache swap matrices for a range.
        
        Args:
            start_idx: Starting record index (default 0)
            end_idx: Ending record index (None for all)
            progress_callback: Optional callback(loaded, total) for progress
        """
        end_idx = end_idx or self.n_records
        
        for i in range(start_idx, min(end_idx, self.n_records)):
            self.get_swap_matrix(i, compute_on_miss=True)
            
            if progress_callback and (i - start_idx) % 10000 == 0:
                progress_callback(i - start_idx, end_idx - start_idx)
        
        if progress_callback:
            progress_callback(end_idx - start_idx, end_idx - start_idx)
        
        logger.info(f"Pre-computed {len(self._swap_cache)} swap matrices")

    def get_bid(self, record_idx: int, token: str) -> float:
        """Get bid price for token at record index."""
        return self._price_matrix.get_bid(record_idx, token)

    def get_ask(self, record_idx: int, token: str) -> float:
        """Get ask price for token at record index."""
        return self._price_matrix.get_ask(record_idx, token)

    def get_bid_vector(self, record_idx: int) -> npt.NDArray[np.float64]:
        """Get all bid prices at record index."""
        return self._price_matrix.get_bid_vector(record_idx)

    def get_ask_vector(self, record_idx: int) -> npt.NDArray[np.float64]:
        """Get all ask prices at record index."""
        return self._price_matrix.get_ask_vector(record_idx)

    def compute_swap_returns(
        self,
        record_idx: int,
        holdings_vector: npt.NDArray[np.float64]
    ) -> npt.NDArray[np.float64]:
        """Compute all swap returns given current holdings.
        
        Args:
            record_idx: Index of the record
            holdings_vector: Current holdings (n_tokens,)
        
        Returns:
            Array of potential gains for each swap from holding token i
            Shape: (n_tokens, n_tokens) where [i,j] = tokens of j gained from swapping i
        """
        swap_matrix = self.get_swap_matrix(record_idx)
        if swap_matrix is None:
            return np.zeros((self.n_tokens, self.n_tokens))
        
        # Multiply swap ratios by holdings to get actual amounts
        return swap_matrix.matrix * holdings_vector[:, np.newaxis]

    def find_best_swap_for_holdings(
        self,
        record_idx: int,
        holdings: dict[str, float]
    ) -> tuple[str, str, float]:
        """Find the best swap given current holdings.
        
        Args:
            record_idx: Index of the record
            holdings: Current token holdings {token: amount}
        
        Returns:
            Tuple of (from_token, to_token, tokens_gained)
        """
        swap_matrix = self.get_swap_matrix(record_idx)
        if swap_matrix is None:
            return "", "", 0.0
        
        best_gain = 0.0
        best_from = ""
        best_to = ""
        
        for from_token, amount in holdings.items():
            if from_token not in swap_matrix.token_index:
                continue
            if amount <= 0:
                continue
            
            i = swap_matrix.token_index[from_token]
            for j in range(self.n_tokens):
                to_token = swap_matrix.index_token[j]
                if to_token == from_token:
                    continue
                
                # Compute actual gain in target token
                tokens_gained = swap_matrix.matrix[i, j] * amount
                if tokens_gained > best_gain:
                    best_gain = tokens_gained
                    best_from = from_token
                    best_to = to_token
        
        return best_from, best_to, best_gain

    def memory_usage(self) -> dict[str, int]:
        """Get memory usage statistics."""
        price_bytes = (
            self._price_matrix.bid_matrix.nbytes +
            self._price_matrix.ask_matrix.nbytes +
            self._price_matrix.timestamps.nbytes
        )
        
        swap_bytes = sum(
            m.matrix.nbytes + m.matrix.nbytes
            for m in self._swap_cache.values()
        )
        
        return {
            "price_matrix_bytes": price_bytes,
            "swap_cache_bytes": swap_bytes,
            "total_bytes": price_bytes + swap_bytes,
            "swap_cache_entries": len(self._swap_cache)
        }
