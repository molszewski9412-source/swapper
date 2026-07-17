"""Grid search optimizer with vectorized evaluation."""

from typing import Any, Iterator
from itertools import product
import numpy as np

from optimizer.base import Optimizer


class GridSearchOptimizer(Optimizer):
    """Exhaustive grid search optimization.
    
    Evaluates all combinations of parameters at specified grid points.
    """

    def __init__(
        self,
        param_space: dict[str, Any],
        n_points: int = 10,
        maximize: bool = True,
        early_stopping_patience: int = None,
        progress_callback=None
    ):
        """Initialize grid search optimizer.
        
        Args:
            param_space: Dictionary of {param_name: (min, max)} or {param_name: [values]}
            n_points: Number of points per dimension (if range given)
            maximize: If True, maximize; else minimize
            early_stopping_patience: Stop after N iterations without improvement
            progress_callback: Optional progress callback
        """
        super().__init__(
            param_space,
            maximize=maximize,
            early_stopping_patience=early_stopping_patience,
            progress_callback=progress_callback
        )
        self.n_points = n_points
        self._param_names: list[str] = []
        self._param_values: list[list[Any]] = []
        self._grid: Iterator[tuple] = None
        self._grid_size: int = 0
        self._setup_grid()

    def _setup_grid(self) -> None:
        """Setup grid of parameter combinations."""
        self._param_names = list(self.param_space.keys())
        self._param_values = []
        
        for name in self._param_names:
            values = self.param_space[name]
            if isinstance(values, (list, tuple)) and len(values) == 2 and isinstance(values[0], (int, float)):
                # Range specified as (min, max)
                min_val, max_val = values
                if isinstance(min_val, int) and isinstance(max_val, int):
                    self._param_values.append(list(range(min_val, max_val + 1)))
                else:
                    self._param_values.append(np.linspace(min_val, max_val, self.n_points).tolist())
            else:
                # Explicit list of values
                self._param_values.append(list(values))
        
        self._grid = product(*self._param_values)
        self._grid_size = np.prod([len(v) for v in self._param_values])

    def _generate_params(self) -> dict[str, Any]:
        """Generate next parameter set from grid."""
        try:
            values = next(self._grid)
            return dict(zip(self._param_names, values))
        except StopIteration:
            return {}

    def _should_stop(self) -> bool:
        """Check if we've exhausted the grid."""
        return self._iterations >= self._grid_size

    def optimize(
        self,
        objective,
        n_iterations: int = None,
        **kwargs
    ):
        """Run grid search optimization.
        
        Args:
            objective: Function(params) -> score
            n_iterations: Not used (uses grid size)
        
        Returns:
            OptimizationResult
        """
        return super().optimize(objective, self._grid_size)

    def iter_params(self) -> Iterator[dict[str, Any]]:
        """Iterate over all parameter combinations.
        
        Yields:
            Parameter dictionaries
        """
        for values in product(*self._param_values):
            yield dict(zip(self._param_names, values))


class BatchGridSearchOptimizer(GridSearchOptimizer):
    """Grid search with batch evaluation for efficiency."""
    
    def __init__(self, *args, batch_size: int = 100, **kwargs):
        super().__init__(*args, **kwargs)
        self.batch_size = batch_size

    def optimize(
        self,
        objective_batch: callable,
        objective_single: callable = None,
        n_iterations: int = None,
        **kwargs
    ):
        """Run batch grid search.
        
        Args:
            objective_batch: Function(list[params]) -> list[scores]
            objective_single: Fallback for single evaluation
            n_iterations: Not used
        
        Returns:
            OptimizationResult
        """
        self._start_time = __import__('time').time()
        self._iterations = 0
        self._best_score = float('-inf') if self.maximize else float('inf')
        self._no_improvement_count = 0
        self._convergence_history = []
        self._all_results = []
        
        # Process in batches
        batch: list[dict[str, Any]] = []
        for params in self.iter_params():
            batch.append(params)
            
            if len(batch) >= self.batch_size:
                self._process_batch(batch, objective_batch, objective_single)
                batch = []
        
        # Process remaining
        if batch:
            self._process_batch(batch, objective_batch, objective_single)
        
        elapsed = time.time() - self._start_time
        
        return __import__('optimizer.base').OptimizationResult(
            best_params=self._best_params or {},
            best_score=self._best_score,
            n_iterations=self._iterations,
            elapsed_time=elapsed,
            all_results=self._all_results,
            convergence_history=self._convergence_history,
        )

    def _process_batch(
        self,
        batch: list[dict[str, Any]],
        objective_batch: callable,
        objective_single: callable
    ):
        """Process a batch of parameter evaluations."""
        try:
            scores = objective_batch(batch)
        except Exception:
            # Fallback to single evaluation
            if objective_single:
                scores = [objective_single(params) for params in batch]
            else:
                raise
        
        for params, score in zip(batch, scores):
            self._iterations += 1
            self._all_results.append({"params": params, "score": score})
            self._convergence_history.append(score)
            
            is_improvement = (
                (self.maximize and score > self._best_score) or
                (not self.maximize and score < self._best_score)
            )
            
            if is_improvement:
                self._best_params = params.copy()
                self._best_score = score
                self._no_improvement_count = 0
            else:
                self._no_improvement_count += 1
            
            if self.progress_callback:
                self.progress_callback(self._iterations, self._grid_size, self._best_score)


import time  # Import for use in BatchGridSearchOptimizer
