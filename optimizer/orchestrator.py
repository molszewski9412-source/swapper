"""Optimizer orchestrator for unified optimization interface."""

from typing import Any, Callable, Optional
from dataclasses import dataclass

from optimizer.base import OptimizationResult, Optimizer
from optimizer.grid_search import GridSearchOptimizer
from optimizer.random_search import RandomSearchOptimizer, AdaptiveRandomSearchOptimizer
from optimizer.genetic import GeneticOptimizer


@dataclass
class OptimizerConfig:
    """Configuration for optimizer selection."""
    method: str = "auto"  # "auto", "grid", "random", "genetic", "adaptive"
    max_iterations: int = 1000
    parallel_workers: int = 1
    early_stopping_patience: int = 10
    seed: Optional[int] = None


class OptimizerOrchestrator:
    """Unified interface for optimization algorithms.
    
    Automatically selects and configures the appropriate optimizer
    based on the problem characteristics.
    """

    OPTIMIZER_MAP = {
        "grid": GridSearchOptimizer,
        "random": RandomSearchOptimizer,
        "adaptive": AdaptiveRandomSearchOptimizer,
        "genetic": GeneticOptimizer,
    }

    def __init__(self, config: Optional[OptimizerConfig] = None):
        """Initialize orchestrator.
        
        Args:
            config: Optimizer configuration
        """
        self.config = config or OptimizerConfig()

    def select_optimizer(self, param_space: dict[str, Any]) -> Optimizer:
        """Select appropriate optimizer based on parameter space.
        
        Args:
            param_space: Parameter search space
        
        Returns:
            Configured optimizer instance
        """
        method = self.config.method
        
        if method == "auto":
            # Auto-select based on search space size
            total_combinations = 1
            for values in param_space.values():
                if isinstance(values, (list, tuple)) and len(values) == 2:
                    min_val, max_val = values
                    if isinstance(min_val, int) and isinstance(max_val, int):
                        total_combinations *= (max_val - min_val + 1)
                    else:
                        total_combinations *= 100  # Assume 100 points for continuous
                elif isinstance(values, list):
                    total_combinations *= len(values)
            
            if total_combinations <= 1000:
                method = "grid"
            elif total_combinations <= 50000:
                method = "random"
            else:
                method = "genetic"
        
        optimizer_class = self.OPTIMIZER_MAP.get(method, RandomSearchOptimizer)
        
        # Configure optimizer
        if method == "grid":
            return optimizer_class(
                param_space=param_space,
                maximize=True,
                early_stopping_patience=self.config.early_stopping_patience,
            )
        elif method == "genetic":
            return optimizer_class(
                param_space=param_space,
                population_size=min(100, self.config.max_iterations // 10),
                n_generations=min(50, self.config.max_iterations // 10),
                maximize=True,
                early_stopping_patience=self.config.early_stopping_patience,
                seed=self.config.seed,
            )
        elif method in ("random", "adaptive"):
            return optimizer_class(
                param_space=param_space,
                n_iterations=self.config.max_iterations,
                sampling="uniform" if method == "random" else "gaussian",
                maximize=True,
                early_stopping_patience=self.config.early_stopping_patience,
                seed=self.config.seed,
            )
        else:
            return RandomSearchOptimizer(
                param_space=param_space,
                n_iterations=self.config.max_iterations,
                maximize=True,
                seed=self.config.seed,
            )

    def optimize(
        self,
        param_space: dict[str, Any],
        objective: Callable[[dict[str, Any]], float],
        n_iterations: Optional[int] = None,
        progress_callback: Optional[Callable[[int, int, float], None]] = None,
    ) -> OptimizationResult:
        """Run optimization with auto-selected optimizer.
        
        Args:
            param_space: Parameter search space
            objective: Objective function
            n_iterations: Override max iterations
            progress_callback: Progress callback
        
        Returns:
            OptimizationResult
        """
        optimizer = self.select_optimizer(param_space)
        
        if n_iterations:
            self.config.max_iterations = n_iterations
        
        if progress_callback:
            optimizer.progress_callback = progress_callback
        
        if hasattr(optimizer, 'n_iterations'):
            optimizer.n_iterations = self.config.max_iterations
        if hasattr(optimizer, 'n_points'):
            optimizer.n_points = min(optimizer.n_points, self.config.max_iterations)
        
        return optimizer.optimize(objective, self.config.max_iterations)

    def optimize_multi_objective(
        self,
        param_space: dict[str, Any],
        objectives: dict[str, Callable[[dict[str, Any]], float]],
        weights: Optional[dict[str, float]] = None,
        n_iterations: Optional[int] = None,
    ) -> dict[str, OptimizationResult]:
        """Run multi-objective optimization.
        
        Args:
            param_space: Parameter search space
            objectives: Dictionary of {name: objective_function}
            weights: Weights for combining objectives
            n_iterations: Override max iterations
        
        Returns:
            Dictionary of {objective_name: OptimizationResult}
        """
        weights = weights or {name: 1.0 for name in objectives}
        
        # Normalize weights
        total_weight = sum(weights.values())
        normalized_weights = {name: w / total_weight for name, w in weights.items()}
        
        # Combined objective
        def combined_objective(params: dict[str, Any]) -> float:
            return sum(
                normalized_weights[name] * obj(params)
                for name, obj in objectives.items()
            )
        
        result = self.optimize(param_space, combined_objective, n_iterations)
        
        # Return results for each objective
        results = {}
        for name, obj in objectives.items():
            # Re-evaluate best params for each objective
            score = obj(result.best_params)
            results[name] = OptimizationResult(
                best_params=result.best_params,
                best_score=score,
                n_iterations=result.n_iterations,
                elapsed_time=result.elapsed_time,
            )
        
        return results

    @staticmethod
    def list_methods() -> list[str]:
        """List available optimization methods."""
        return ["auto", "grid", "random", "adaptive", "genetic"]
