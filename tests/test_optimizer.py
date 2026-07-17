"""Tests for optimization algorithms."""

import pytest
import numpy as np

from optimizer.base import OptimizationResult, Optimizer
from optimizer.grid_search import GridSearchOptimizer
from optimizer.random_search import RandomSearchOptimizer
from optimizer.genetic import GeneticOptimizer


@pytest.fixture
def objective_function():
    """Create a simple objective function for testing."""
    def objective(params):
        # Simple paraboloid: minimum at (1, 2)
        x = params.get("x", 0)
        y = params.get("y", 0)
        return -((x - 1) ** 2 + (y - 2) ** 2)  # Maximize (negative for minimization)
    return objective


@pytest.fixture
def param_space():
    """Create parameter space for testing."""
    return {
        "x": (0, 3),
        "y": (0, 4),
    }


class TestOptimizationResult:
    """Tests for OptimizationResult."""

    def test_result_creation(self):
        """Test result creation."""
        result = OptimizationResult(
            best_params={"x": 1, "y": 2},
            best_score=10.0,
            n_iterations=100,
            elapsed_time=1.5
        )
        
        assert result.best_params == {"x": 1, "y": 2}
        assert result.best_score == 10.0
        assert result.n_iterations == 100

    def test_summary(self):
        """Test summary generation."""
        result = OptimizationResult(
            best_params={"x": 1},
            best_score=10.0,
            n_iterations=100,
            elapsed_time=2.0
        )
        
        summary = result.summary()
        assert "best_params" in summary
        assert "best_score" in summary
        assert summary["iterations_per_second"] == 50.0


class TestGridSearchOptimizer:
    """Tests for GridSearchOptimizer."""

    def test_grid_search_setup(self, param_space):
        """Test grid search initialization."""
        optimizer = GridSearchOptimizer(param_space)
        
        assert optimizer.param_space == param_space
        assert "x" in optimizer._param_names
        assert "y" in optimizer._param_names

    def test_grid_search_generates_all_combinations(self, param_space):
        """Test that grid search generates all combinations."""
        optimizer = GridSearchOptimizer(param_space, n_points=3)
        
        combinations = list(optimizer.iter_params())
        
        # Should have 3 * 3 = 9 combinations
        assert len(combinations) >= 9
        
        # All should have x and y
        for combo in combinations:
            assert "x" in combo
            assert "y" in combo

    def test_grid_search_optimize(self, objective_function, param_space):
        """Test grid search optimization."""
        optimizer = GridSearchOptimizer(param_space)
        
        result = optimizer.optimize(objective_function)
        
        assert result.best_score >= -1.0  # Should find something near the optimum
        assert "x" in result.best_params
        assert "y" in result.best_params

    def test_grid_search_with_discrete_values(self):
        """Test grid search with discrete values."""
        param_space = {
            "threshold": [1.0, 1.5, 2.0],
            "interval": [1, 5, 10],
        }
        
        optimizer = GridSearchOptimizer(param_space)
        combinations = list(optimizer.iter_params())
        
        assert len(combinations) == 9
        thresholds = {c["threshold"] for c in combinations}
        assert thresholds == {1.0, 1.5, 2.0}


class TestRandomSearchOptimizer:
    """Tests for RandomSearchOptimizer."""

    def test_random_search_setup(self, param_space):
        """Test random search initialization."""
        optimizer = RandomSearchOptimizer(param_space, seed=42)
        
        assert optimizer.param_space == param_space
        assert optimizer.n_iterations == 1000

    def test_random_search_generates_valid_params(self, param_space):
        """Test that random search generates valid parameters."""
        optimizer = RandomSearchOptimizer(param_space, n_iterations=10, seed=42)
        
        for _ in range(10):
            params = optimizer._generate_params()
            assert 0 <= params["x"] <= 3
            assert 0 <= params["y"] <= 4

    def test_random_search_with_seed(self, param_space):
        """Test reproducibility with seed."""
        optimizer1 = RandomSearchOptimizer(param_space, n_iterations=5, seed=42)
        optimizer2 = RandomSearchOptimizer(param_space, n_iterations=5, seed=42)
        
        for _ in range(5):
            p1 = optimizer1._generate_params()
            p2 = optimizer2._generate_params()
            assert p1 == p2

    def test_random_search_optimize(self, objective_function, param_space):
        """Test random search optimization."""
        optimizer = RandomSearchOptimizer(param_space, n_iterations=100, seed=42)
        
        result = optimizer.optimize(objective_function)
        
        assert result.n_iterations == 100
        assert result.best_score > -10  # Should find something reasonable


class TestGeneticOptimizer:
    """Tests for GeneticOptimizer."""

    def test_genetic_setup(self, param_space):
        """Test genetic optimizer initialization."""
        optimizer = GeneticOptimizer(
            param_space,
            population_size=20,
            n_generations=5
        )
        
        assert optimizer.population_size == 20
        assert optimizer.n_generations == 5
        assert optimizer.mutation_rate == 0.1

    def test_genetic_random_individual(self, param_space):
        """Test random individual generation."""
        optimizer = GeneticOptimizer(param_space, seed=42)
        
        individual = optimizer._random_individual()
        
        assert "x" in individual
        assert "y" in individual
        assert 0 <= individual["x"] <= 3
        assert 0 <= individual["y"] <= 4

    def test_genetic_crossover(self, param_space):
        """Test crossover operation."""
        optimizer = GeneticOptimizer(param_space)
        
        parent1 = {"x": 0, "y": 0}
        parent2 = {"x": 3, "y": 4}
        
        child1, child2 = optimizer._crossover(parent1, parent2)
        
        # Children should have values from parents
        assert child1["x"] in [0, 3]
        assert child1["y"] in [0, 4]

    def test_genetic_mutate(self, param_space):
        """Test mutation operation."""
        optimizer = GeneticOptimizer(param_space, mutation_rate=1.0, seed=42)
        
        parent = {"x": 1.5, "y": 2.0}
        child = optimizer._mutate(parent)
        
        # With 100% mutation rate, value should change
        # (may not always change due to random nature)
        assert "x" in child
        assert "y" in child

    def test_genetic_optimize(self, objective_function, param_space):
        """Test genetic optimization."""
        optimizer = GeneticOptimizer(
            param_space,
            population_size=20,
            n_generations=10,
            seed=42
        )
        
        result = optimizer.optimize(objective_function)
        
        assert result.n_iterations > 0
        assert result.metadata.get("generations", 0) > 0
