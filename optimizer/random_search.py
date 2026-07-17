"""Random search optimizer with adaptive sampling."""

from typing import Any
import numpy as np

from optimizer.base import Optimizer


class RandomSearchOptimizer(Optimizer):
    """Random search optimization with uniform and adaptive sampling.
    
    Samples parameters randomly from the search space.
    """

    def __init__(
        self,
        param_space: dict[str, Any],
        n_iterations: int = 1000,
        sampling: str = "uniform",  # "uniform" or "gaussian"
        maximize: bool = True,
        early_stopping_patience: int = None,
        seed: int = None,
        progress_callback=None
    ):
        """Initialize random search optimizer.
        
        Args:
            param_space: Dictionary of {param_name: (min, max)} or {param_name: [values]}
            n_iterations: Number of random samples to evaluate
            sampling: "uniform" for uniform distribution, "gaussian" for adaptive
            maximize: If True, maximize; else minimize
            early_stopping_patience: Stop after N iterations without improvement
            seed: Random seed for reproducibility
            progress_callback: Optional progress callback
        """
        super().__init__(
            param_space,
            maximize=maximize,
            early_stopping_patience=early_stopping_patience,
            progress_callback=progress_callback
        )
        self.n_iterations = n_iterations
        self.sampling = sampling
        self.seed = seed
        
        self._param_names: list[str] = []
        self._param_ranges: list[tuple[Any, Any]] = []
        self._param_types: list[type] = []
        self._param_values: list[list[Any]] = []
        self._rng = np.random.default_rng(seed)
        
        self._setup_param_space()

    def _setup_param_space(self) -> None:
        """Setup parameter space for random sampling."""
        self._param_names = list(self.param_space.keys())
        
        for name in self._param_names:
            values = self.param_space[name]
            
            if isinstance(values, (list, tuple)) and len(values) == 2:
                min_val, max_val = values
                self._param_ranges.append((min_val, max_val))
                self._param_types.append(type(min_val))
                
                # Check for discrete values
                if isinstance(min_val, int) and isinstance(max_val, int) and max_val - min_val < 100:
                    self._param_values.append(list(range(min_val, max_val + 1)))
                else:
                    self._param_values.append(None)
            elif isinstance(values, list):
                # Discrete values
                self._param_ranges.append((0, len(values) - 1))
                self._param_types.append(int)
                self._param_values.append(values)
            else:
                raise ValueError(f"Invalid param space for {name}: {values}")

    def _generate_params(self) -> dict[str, Any]:
        """Generate random parameter set."""
        params = {}
        
        for i, name in enumerate(self._param_names):
            min_val, max_val = self._param_ranges[i]
            param_type = self._param_types[i]
            
            if self._param_values[i] is not None:
                # Discrete values
                idx = self._rng.integers(0, len(self._param_values[i]))
                params[name] = self._param_values[i][idx]
            elif param_type == int:
                params[name] = self._rng.integers(min_val, max_val + 1)
            elif param_type == float:
                if self.sampling == "gaussian":
                    # Sample from truncated normal
                    mean = (min_val + max_val) / 2
                    std = (max_val - min_val) / 6
                    value = self._rng.normal(mean, std)
                    value = max(min_val, min(max_val, value))
                    params[name] = float(value)
                else:
                    params[name] = self._rng.uniform(min_val, max_val)
            else:
                params[name] = self._rng.uniform(min_val, max_val)
        
        return params

    def _should_stop(self) -> bool:
        """Check if we've completed all iterations."""
        if self.early_stopping_patience and self._no_improvement_count >= self.early_stopping_patience:
            return True
        if self.n_iterations is not None and self._iterations >= self.n_iterations:
            return True
        return False


class AdaptiveRandomSearchOptimizer(RandomSearchOptimizer):
    """Random search with adaptive sampling focusing on promising regions."""
    
    def __init__(
        self,
        *args,
        adaptation_factor: float = 1.5,
        **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.adaptation_factor = adaptation_factor
        self._best_region: dict[str, tuple[Any, Any]] = {}
        self._iteration_in_region: int = 0

    def _setup_param_space(self) -> None:
        """Setup parameter space with region tracking."""
        super()._setup_param_space()
        self._best_region = {name: (lo, hi) for name, (lo, hi) in zip(
            self._param_names, self._param_ranges
        )}

    def _generate_params(self) -> dict[str, Any]:
        """Generate parameters with adaptation toward promising regions."""
        self._iteration_in_region += 1
        
        # Shrink search region periodically
        if self._iteration_in_region % 100 == 0 and self._best_params:
            self._shrink_region()
        
        params = {}
        
        for i, name in enumerate(self._param_names):
            min_val, max_val = self._best_region[name]
            param_type = self._param_types[i]
            
            if self._param_values[i] is not None:
                idx = self._rng.integers(0, len(self._param_values[i]))
                params[name] = self._param_values[i][idx]
            elif param_type == int:
                params[name] = self._rng.integers(int(min_val), int(max_val) + 1)
            else:
                params[name] = self._rng.uniform(min_val, max_val)
        
        return params

    def _shrink_region(self) -> None:
        """Shrink search region around best parameters."""
        shrink = 1.0 / self.adaptation_factor
        
        for i, name in enumerate(self._param_names):
            if name in self._best_params:
                best_val = self._best_params[name]
                lo, hi = self._param_ranges[i]
                original_lo, original_hi = lo, hi
                
                # Shrink toward best value
                range_size = (hi - lo) * shrink
                new_lo = max(original_lo, best_val - range_size / 2)
                new_hi = min(original_hi, best_val + range_size / 2)
                
                self._best_region[name] = (new_lo, new_hi)
