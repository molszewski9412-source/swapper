"""Market Matrix Engine - Core optimization for O(1) swap lookups."""

from typing import Optional, Iterator
import logging
import numpy as np
import numpy.typing as npt

from data.cache import DataCache
from core.models import SwapMatrix


logger = logging.getLogger(__name__)


class MarketMatrixEngine:
    """Pre-computes and caches 20x20 swap matrices for O(1) lookups.
    
    Core optimization that enables vectorized evaluation of all swap pairs
    simultaneously.
    """
    
    def __init__(
        self,
        cache: DataCache,
        precompute: bool = True,
        cache_enabled: bool = True
    ):
        """Initialize market matrix engine.
        
        Args:
            cache: DataCache with price data
            precompute: If True, pre-compute matrices on initialization
            cache_enabled: If True, cache computed matrices
        """
        self.cache = cache
        self._swap_matrices: dict[int, SwapMatrix] = {}
        self._cache_enabled = cache_enabled
        
        if precompute:
            self.precompute_all(progress_callback=self._log_progress)
    
    def _log_progress(self, current: int, total: int) -> None:
        """Log pre-computation progress."""
        if current % 50000 == 0:
            logger.info(f"Pre-computing matrices: {current}/{total} ({100*current/total:.1f}%)")
    
    def get_swap_matrix(self, record_idx: int) -> SwapMatrix:
        """Get swap matrix at record index.
        
        Args:
            record_idx: Index of the record
        
        Returns:
            SwapMatrix for that record
        """
        if self._cache_enabled and record_idx in self._swap_matrices:
            return self._swap_matrices[record_idx]
        
        # Compute on demand
        matrix = SwapMatrix.compute(
            self.cache.price_matrix,
            record_idx,
            fees=(self.cache._swap_fee, self.cache._swap_fee)
        )
        
        if self._cache_enabled:
            self._swap_matrices[record_idx] = matrix
        
        return matrix

    def precompute_all(
        self,
        start_idx: int = 0,
        end_idx: Optional[int] = None,
        progress_callback: Optional[callable] = None
    ) -> int:
        """Pre-compute all swap matrices.
        
        Args:
            start_idx: Starting record index
            end_idx: Ending record index (None for all)
            progress_callback: Optional callback(current, total)
        
        Returns:
            Number of matrices pre-computed
        """
        end_idx = end_idx or self.cache.n_records
        count = 0
        
        for i in range(start_idx, min(end_idx, self.cache.n_records)):
            self.get_swap_matrix(i)
            count += 1
            
            if progress_callback and (i - start_idx) % 10000 == 0:
                progress_callback(i - start_idx, end_idx - start_idx)
        
        if progress_callback:
            progress_callback(end_idx - start_idx, end_idx - start_idx)
        
        logger.info(f"Pre-computed {count} swap matrices")
        return count

    def compute_swap_vector(
        self,
        record_idx: int,
        from_token_idx: int
    ) -> npt.NDArray[np.float64]:
        """Compute swap gains vector for a specific source token.
        
        Args:
            record_idx: Current record index
            from_token_idx: Index of source token
        
        Returns:
            Array (n_tokens,) of tokens gained for each possible target
        """
        matrix = self.get_swap_matrix(record_idx)
        return matrix.matrix[from_token_idx].copy()

    def find_best_swap_from(
        self,
        record_idx: int,
        from_token: str
    ) -> tuple[str, float]:
        """Find best token to swap to from a given token.
        
        Args:
            record_idx: Current record index
            from_token: Source token
        
        Returns:
            Tuple of (target_token, tokens_gained)
        """
        matrix = self.get_swap_matrix(record_idx)
        
        if from_token not in matrix.token_index:
            return "", 0.0
        
        from_idx = matrix.token_index[from_token]
        gains = matrix.matrix[from_idx]
        
        best_target_idx = np.argmax(gains)
        return matrix.index_token[best_target_idx], gains[best_target_idx]

    def find_best_swap_for_holdings(
        self,
        record_idx: int,
        holdings_vector: npt.NDArray[np.float64],
        holding_idx: int
    ) -> tuple[int, float]:
        """Find best swap given current holdings.
        
        Args:
            record_idx: Current record index
            holdings_vector: Current holdings (n_tokens,)
            holding_idx: Index of currently held token
        
        Returns:
            Tuple of (best_target_idx, tokens_gained)
        """
        matrix = self.get_swap_matrix(record_idx)
        
        # Get swap gains from current holding
        gains = matrix.matrix[holding_idx]
        
        # Multiply by holdings to get actual amounts
        current_holding = holdings_vector[holding_idx]
        actual_gains = gains * current_holding
        
        best_target_idx = np.argmax(actual_gains)
        return best_target_idx, actual_gains[best_target_idx]

    def compute_all_swap_outcomes(
        self,
        record_idx: int,
        holdings_vector: npt.NDArray[np.float64]
    ) -> npt.NDArray[np.float64]:
        """Compute all swap outcomes for current holdings.
        
        Args:
            record_idx: Current record index
            holdings_vector: Current holdings (n_tokens,)
        
        Returns:
            Matrix (n_tokens, n_tokens) of actual token amounts after swap
        """
        matrix = self.get_swap_matrix(record_idx)
        
        # Multiply swap ratios by holdings
        # swap_matrix[i, j] = ratio from i to j
        # actual[i, j] = ratio * holdings[i] = actual tokens of j we'd get
        return matrix.matrix * holdings_vector.reshape(-1, 1)

    def get_price_vector(self, record_idx: int) -> tuple[
        npt.NDArray[np.float64],
        npt.NDArray[np.float64]
    ]:
        """Get bid and ask price vectors at record index.
        
        Args:
            record_idx: Current record index
        
        Returns:
            Tuple of (bid_vector, ask_vector)
        """
        return (
            self.cache.get_bid_vector(record_idx),
            self.cache.get_ask_vector(record_idx)
        )

    def enable_cache(self) -> None:
        """Enable matrix caching."""
        self._cache_enabled = True

    def disable_cache(self) -> None:
        """Disable matrix caching."""
        self._cache_enabled = False

    def clear_cache(self) -> int:
        """Clear cached matrices.
        
        Returns:
            Number of matrices cleared
        """
        count = len(self._swap_matrices)
        self._swap_matrices.clear()
        logger.info(f"Cleared {count} cached matrices")
        return count

    @property
    def cache_size(self) -> int:
        """Number of cached matrices."""
        return len(self._swap_matrices)

    @property
    def n_records(self) -> int:
        """Total number of records."""
        return self.cache.n_records

    @property
    def n_tokens(self) -> int:
        """Number of tokens."""
        return self.cache.n_tokens

    def iter_matrices(
        self,
        start_idx: int = 0,
        end_idx: Optional[int] = None
    ) -> Iterator[tuple[int, SwapMatrix]]:
        """Iterate over swap matrices.
        
        Args:
            start_idx: Starting index
            end_idx: Ending index
        
        Yields:
            Tuples of (record_idx, SwapMatrix)
        """
        end_idx = end_idx or self.cache.n_records
        
        for i in range(start_idx, min(end_idx, self.cache.n_records)):
            yield i, self.get_swap_matrix(i)

    def memory_usage(self) -> dict[str, int]:
        """Get memory usage statistics."""
        base_bytes = self.cache.price_matrix.bid_matrix.nbytes * 2
        
        swap_bytes = sum(
            m.matrix.nbytes for m in self._swap_matrices.values()
        )
        
        return {
            "price_matrix_bytes": base_bytes,
            "swap_matrix_bytes": swap_bytes,
            "total_bytes": base_bytes + swap_bytes,
            "cached_matrices": len(self._swap_matrices)
        }
