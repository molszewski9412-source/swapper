"""Base optimizer classes and interfaces."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
import time


@dataclass
class OptimizationResult:
    """Result of an optimization run."""
    best_params: dict[str, Any]
    best_score: float
    n_iterations: int
    elapsed_time: float
    all_results: list[dict[str, Any]] = field(default_factory=list)
    convergence_history: list[float] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        """Get summary of optimization result."""
        return {
            "best_params": self.best_params,
            "best_score": self.best_score,
            "n_iterations": self.n_iterations,
            "elapsed_time": self.elapsed_time,
            "iterations_per_second": self.n_iterations / self.elapsed_time if self.elapsed_time > 0 else 0,
            "metadata": self.metadata,
        }


class Optimizer(ABC):
    """Abstract base class for optimization algorithms."""

    def __init__(
        self,
        param_space: dict[str, Any],
        maximize: bool = True,
        early_stopping_patience: Optional[int] = None,
        progress_callback: Optional[Callable[[int, int, float], None]] = None
    ):
        """Initialize optimizer.
        
        Args:
            param_space: Dictionary defining parameter search space
            maximize: If True, maximize score; else minimize
            early_stopping_patience: Stop if no improvement for N iterations
            progress_callback: Optional callback(current, total, best_score)
        """
        self.param_space = param_space
        self.maximize = maximize
        self.early_stopping_patience = early_stopping_patience
        self.progress_callback = progress_callback
        
        self._best_params: Optional[dict[str, Any]] = None
        self._best_score: float = float('-inf') if maximize else float('inf')
        self._iterations: int = 0
        self._no_improvement_count: int = 0
        self._start_time: float = 0
        self._convergence_history: list[float] = []
        self._all_results: list[dict[str, Any]] = []

    @abstractmethod
    def _generate_params(self) -> dict[str, Any]:
        """Generate next parameter set to evaluate."""
        pass

    @abstractmethod
    def _should_stop(self) -> bool:
        """Check if optimization should stop."""
        pass

    def optimize(
        self,
        objective: Callable[[dict[str, Any]], float],
        n_iterations: int = None,
        **kwargs: Any
    ) -> OptimizationResult:
        """Run optimization.
        
        Args:
            objective: Function that takes params and returns score
            n_iterations: Maximum number of iterations (None for unlimited)
        
        Returns:
            OptimizationResult with best parameters and score
        """
        self._start_time = time.time()
        self._iterations = 0
        self._best_score = float('-inf') if self.maximize else float('inf')
        self._no_improvement_count = 0
        self._convergence_history = []
        self._all_results = []

        while not self._should_stop() and (n_iterations is None or self._iterations < n_iterations):
            params = self._generate_params()
            score = objective(params)
            
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
                self.progress_callback(self._iterations, n_iterations, self._best_score)

        elapsed = time.time() - self._start_time

        return OptimizationResult(
            best_params=self._best_params or {},
            best_score=self._best_score,
            n_iterations=self._iterations,
            elapsed_time=elapsed,
            all_results=self._all_results,
            convergence_history=self._convergence_history,
        )

    @property
    def best_params(self) -> Optional[dict[str, Any]]:
        """Get best parameters found so far."""
        return self._best_params

    @property
    def best_score(self) -> float:
        """Get best score found so far."""
        return self._best_score


def define_param_space(
    threshold: tuple[float, float] = (0.9, 2.0),
    min_swap_interval: tuple[int, int] = (1, 20),
    **extra_params: Any
) -> dict[str, Any]:
    """Helper to define common parameter spaces.
    
    Args:
        threshold: Min/max for threshold parameter
        min_swap_interval: Min/max for swap interval
        **extra_params: Additional parameter definitions
    
    Returns:
        Parameter space dictionary
    """
    space = {
        "threshold": threshold,
        "min_swap_interval": min_swap_interval,
    }
    space.update(extra_params)
    return space
