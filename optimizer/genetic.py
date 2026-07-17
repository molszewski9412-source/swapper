"""Genetic algorithm optimizer for strategy optimization."""

from typing import Any, Callable, Optional
import numpy as np


class GeneticOptimizer:
    """Genetic algorithm optimizer for finding optimal strategy parameters.
    
    Uses evolutionary principles: selection, crossover, mutation.
    """

    def __init__(
        self,
        param_space: dict[str, Any],
        population_size: int = 100,
        n_generations: int = 50,
        mutation_rate: float = 0.1,
        crossover_rate: float = 0.7,
        elite_ratio: float = 0.1,
        maximize: bool = True,
        early_stopping_patience: int = 10,
        seed: int = None,
        progress_callback=None
    ):
        """Initialize genetic optimizer.
        
        Args:
            param_space: Dictionary of {param_name: (min, max)} or {param_name: [values]}
            population_size: Size of population
            n_generations: Number of generations
            mutation_rate: Probability of mutation
            crossover_rate: Probability of crossover
            elite_ratio: Ratio of best individuals to keep unchanged
            maximize: If True, maximize fitness; else minimize
            early_stopping_patience: Stop after N generations without improvement
            seed: Random seed for reproducibility
            progress_callback: Optional progress callback
        """
        self.param_space = param_space
        self.maximize = maximize
        self.early_stopping_patience = early_stopping_patience
        self.progress_callback = progress_callback
        
        self.population_size = population_size
        self.n_generations = n_generations
        self.mutation_rate = mutation_rate
        self.crossover_rate = crossover_rate
        self.elite_ratio = elite_ratio
        self.seed = seed
        
        self._param_names: list[str] = []
        self._param_ranges: list[tuple[Any, Any]] = []
        self._param_types: list[type] = []
        self._param_values: list[list[Any]] = []
        self._rng = np.random.default_rng(seed)
        
        self._population: list[dict[str, Any]] = []
        self._fitness: list[float] = []
        self._generation: int = 0
        self._elite: list[dict[str, Any]] = []
        
        self._best_params: Optional[dict[str, Any]] = None
        self._best_score: float = float('-inf') if maximize else float('inf')
        self._iterations: int = 0
        self._no_improvement_count: int = 0
        self._start_time: float = 0
        self._convergence_history: list[float] = []
        self._all_results: list[dict[str, Any]] = []
        
        self._setup_param_space()

    def _generate_params(self) -> dict[str, Any]:
        """Generate params (not used in genetic algorithm)."""
        return self._best_params or {}

    def _should_stop(self) -> bool:
        """Check if optimization should stop."""
        return self._no_improvement_count >= self.early_stopping_patience

    def _setup_param_space(self) -> None:
        """Setup parameter space representation."""
        self._param_names = list(self.param_space.keys())
        
        for name in self._param_names:
            values = self.param_space[name]
            
            if isinstance(values, (list, tuple)) and len(values) == 2:
                min_val, max_val = values
                self._param_ranges.append((min_val, max_val))
                self._param_types.append(type(min_val))
                
                if isinstance(min_val, int) and isinstance(max_val, int) and max_val - min_val < 100:
                    self._param_values.append(list(range(min_val, max_val + 1)))
                else:
                    self._param_values.append(None)
            elif isinstance(values, list):
                self._param_ranges.append((0, len(values) - 1))
                self._param_types.append(int)
                self._param_values.append(values)
            else:
                raise ValueError(f"Invalid param space for {name}: {values}")

    def _random_individual(self) -> dict[str, Any]:
        """Create random individual."""
        individual = {}
        
        for i, name in enumerate(self._param_names):
            min_val, max_val = self._param_ranges[i]
            param_type = self._param_types[i]
            
            if self._param_values[i] is not None:
                idx = self._rng.integers(0, len(self._param_values[i]))
                individual[name] = self._param_values[i][idx]
            elif param_type == int:
                individual[name] = self._rng.integers(int(min_val), int(max_val) + 1)
            else:
                individual[name] = self._rng.uniform(min_val, max_val)
        
        return individual

    def _initialize_population(self) -> None:
        """Initialize random population."""
        self._population = [self._random_individual() for _ in range(self.population_size)]

    def _evaluate_population(
        self,
        objective: Callable[[dict[str, Any]], float]
    ) -> list[float]:
        """Evaluate fitness for entire population."""
        return [objective(ind) for ind in self._population]

    def _selection(self) -> list[dict[str, Any]]:
        """Tournament selection."""
        selected = []
        tournament_size = 3
        
        for _ in range(self.population_size):
            # Pick tournament participants
            indices = self._rng.integers(0, self.population_size, tournament_size)
            if self.maximize:
                winner_idx = max(indices, key=lambda i: self._fitness[i])
            else:
                winner_idx = min(indices, key=lambda i: self._fitness[i])
            selected.append(self._population[winner_idx].copy())
        
        return selected

    def _crossover(
        self,
        parent1: dict[str, Any],
        parent2: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Single-point crossover."""
        if self._rng.random() > self.crossover_rate:
            return parent1.copy(), parent2.copy()
        
        child1, child2 = {}, {}
        crossover_point = self._rng.integers(1, len(self._param_names))
        
        for i, name in enumerate(self._param_names):
            if i < crossover_point:
                child1[name] = parent1[name]
                child2[name] = parent2[name]
            else:
                child1[name] = parent2[name]
                child2[name] = parent1[name]
        
        return child1, child2

    def _mutate(self, individual: dict[str, Any]) -> dict[str, Any]:
        """Apply mutation to individual."""
        mutated = individual.copy()
        
        for i, name in enumerate(self._param_names):
            if self._rng.random() < self.mutation_rate:
                min_val, max_val = self._param_ranges[i]
                param_type = self._param_types[i]
                
                if self._param_values[i] is not None:
                    idx = self._rng.integers(0, len(self._param_values[i]))
                    mutated[name] = self._param_values[i][idx]
                elif param_type == int:
                    mutated[name] = self._rng.integers(int(min_val), int(max_val) + 1)
                else:
                    # Gaussian mutation
                    current = individual[name]
                    std = (max_val - min_val) / 10
                    new_val = current + self._rng.normal(0, std)
                    mutated[name] = max(min_val, min(max_val, new_val))
        
        return mutated

    def _elitism(self) -> list[dict[str, Any]]:
        """Keep best individuals unchanged."""
        n_elite = max(1, int(self.population_size * self.elite_ratio))
        
        if self.maximize:
            elite_indices = np.argsort(self._fitness)[-n_elite:]
        else:
            elite_indices = np.argsort(self._fitness)[:n_elite]
        
        return [self._population[i].copy() for i in elite_indices]

    def _generate_new_generation(
        self,
        objective: Callable[[dict[str, Any]], float]
    ) -> None:
        """Generate new population."""
        # Selection
        selected = self._selection()
        
        # Crossover and mutation
        new_population = []
        
        for i in range(0, self.population_size - len(self._elite) * 2, 2):
            if i + 1 < len(selected):
                child1, child2 = self._crossover(selected[i], selected[i + 1])
                new_population.extend([self._mutate(child1), self._mutate(child2)])
        
        # Fill remaining slots
        while len(new_population) < self.population_size - len(self._elite):
            new_population.append(self._mutate(self._random_individual()))
        
        # Add elites
        new_population.extend(self._elite)
        
        self._population = new_population[:self.population_size]

    def optimize(
        self,
        objective: Callable[[dict[str, Any]], float],
        n_iterations: int = None,
        **kwargs
    ):
        """Run genetic optimization.
        
        Args:
            objective: Function(params) -> fitness score
            n_iterations: Not used (uses n_generations)
        
        Returns:
            OptimizationResult
        """
        import time
        self._start_time = time.time()
        self._generation = 0
        self._iterations = 0
        
        # Initialize
        self._initialize_population()
        self._fitness = self._evaluate_population(objective)
        self._iterations += self.population_size
        
        # Find initial best
        if self.maximize:
            best_idx = np.argmax(self._fitness)
        else:
            best_idx = np.argmin(self._fitness)
        self._best_params = self._population[best_idx].copy()
        self._best_score = self._fitness[best_idx]
        
        # Evolution loop
        for gen in range(self.n_generations):
            self._generation = gen
            self._elite = self._elitism()
            
            # Generate new population
            self._generate_new_generation(objective)
            
            # Evaluate
            self._fitness = self._evaluate_population(objective)
            self._iterations += self.population_size
            
            # Track convergence
            self._convergence_history.append(np.mean(self._fitness))
            
            # Update best
            if self.maximize:
                gen_best_idx = np.argmax(self._fitness)
                if self._fitness[gen_best_idx] > self._best_score:
                    self._best_params = self._population[gen_best_idx].copy()
                    self._best_score = self._fitness[gen_best_idx]
                    self._no_improvement_count = 0
                else:
                    self._no_improvement_count += 1
            else:
                gen_best_idx = np.argmin(self._fitness)
                if self._fitness[gen_best_idx] < self._best_score:
                    self._best_params = self._population[gen_best_idx].copy()
                    self._best_score = self._fitness[gen_best_idx]
                    self._no_improvement_count = 0
                else:
                    self._no_improvement_count += 1
            
            # Record all results
            for ind, fitness in zip(self._population, self._fitness):
                self._all_results.append({"params": ind.copy(), "score": fitness, "generation": gen})
            
            if self.progress_callback:
                self.progress_callback(self._iterations, self.n_generations * self.population_size, self._best_score)
            
            # Check early stopping
            if self._should_stop():
                break
        
        elapsed = time.time() - self._start_time
        
        from optimizer.base import OptimizationResult
        return OptimizationResult(
            best_params=self._best_params or {},
            best_score=self._best_score,
            n_iterations=self._iterations,
            elapsed_time=elapsed,
            all_results=self._all_results,
            convergence_history=self._convergence_history,
            metadata={"generations": self._generation + 1, "elite_ratio": self.elite_ratio}
        )

    @property
    def best_params(self) -> Optional[dict[str, Any]]:
        """Get best parameters found so far."""
        return self._best_params

    @property
    def best_score(self) -> float:
        """Get best score found so far."""
        return self._best_score
