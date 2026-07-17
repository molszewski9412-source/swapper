"""Strategy evolver - combines pattern analysis with LLM for intelligent evolution."""

import random
import logging
from typing import Any, Optional
from dataclasses import dataclass

from ai.pattern_analyzer import PatternAnalyzer, Pattern
from ai.llm_engine import LLMEngine


logger = logging.getLogger(__name__)


@dataclass
class EvolutionConfig:
    """Configuration for strategy evolution."""
    population_size: int = 20
    elite_count: int = 5
    mutation_rate: float = 0.2
    crossover_rate: float = 0.3
    llm_guidance: bool = True
    llm_interval: int = 10  # generations between LLM calls
    max_no_improvement: int = 50
    convergence_threshold: float = 0.001


class StrategyEvolver:
    """Intelligently evolves strategy parameters using patterns and LLM."""

    def __init__(
        self,
        llm_engine: Optional[LLMEngine] = None,
        config: EvolutionConfig = None
    ):
        """Initialize strategy evolver."""
        self.llm_engine = llm_engine or LLMEngine()
        self.config = config or EvolutionConfig()
        self.pattern_analyzer = PatternAnalyzer()
        
        self.generation = 0
        self.population: list[dict] = []
        self.elite: list[dict] = []
        self.best_ever: Optional[dict] = None
        self.no_improvement_count = 0
        
        # Parameter ranges
        self.param_ranges = {
            "threshold": (0.9, 3.0),
            "min_swap_interval": (1, 50),
            "momentum_weight": (0.0, 1.0),
            "volatility_weight": (0.0, 1.0),
            "rsi_oversold": (10, 40),
            "rsi_overbought": (60, 90),
        }

    def initialize_population(self, base_params: dict = None) -> list[dict]:
        """Initialize random population."""
        base = base_params or {
            "threshold": 1.05,
            "min_swap_interval": 5,
        }
        
        self.population = []
        
        for _ in range(self.config.population_size):
            params = self._random_params(base)
            self.population.append({
                "params": params,
                "score": 0.0,
                "generation": 0
            })
        
        return self.population

    def evolve(
        self,
        evaluated_population: list[dict]
    ) -> list[dict]:
        """Evolve population to next generation.
        
        Args:
            evaluated_population: List of dicts with 'params' and 'score'
        
        Returns:
            New population
        """
        self.generation += 1
        
        # Update with scores
        for ind, result in zip(self.population, evaluated_population):
            ind["score"] = result.get("score", 0)
            ind["params"] = result.get("params", ind["params"])
        
        # Find elite
        sorted_pop = sorted(self.population, key=lambda x: x["score"], reverse=True)
        self.elite = sorted_pop[:self.config.elite_count]
        
        # Track best ever
        if not self.best_ever or sorted_pop[0]["score"] > self.best_ever["score"]:
            self.best_ever = sorted_pop[0].copy()
            self.no_improvement_count = 0
        else:
            self.no_improvement_count += 1
        
        # Analyze patterns
        self.pattern_analyzer.analyze(self.population)
        
        # Check convergence
        convergence = self.pattern_analyzer.get_convergence()
        if abs(convergence) < self.config.convergence_threshold:
            logger.info(f"Generation {self.generation}: Low convergence ({convergence:.4f})")
        
        # Generate new population
        new_population = []
        
        # Keep elite
        new_population.extend([e.copy() for e in self.elite])
        
        # Fill rest with evolved strategies
        while len(new_population) < self.config.population_size:
            # Decide how to generate
            if self.config.llm_guidance and self.generation % self.config.llm_interval == 0:
                # Use LLM guidance
                child = self._llm_guided_evolution()
            elif random.random() < self.config.crossover_rate:
                # Crossover
                child = self._crossover()
            else:
                # Mutation
                child = self._mutate(random.choice(self.population))
            
            child["generation"] = self.generation
            new_population.append(child)
        
        self.population = new_population
        return new_population

    def _random_params(self, base: dict = None) -> dict:
        """Generate random parameters within ranges."""
        params = {}
        base = base or {}
        
        for name, (min_val, max_val) in self.param_ranges.items():
            # Start from base if available
            start = base.get(name, (min_val + max_val) / 2)
            
            if isinstance(min_val, int):
                params[name] = random.randint(int(min_val), int(max_val))
            else:
                params[name] = random.uniform(min_val, max_val)
                # Round to 4 decimal places
                params[name] = round(params[name], 4)
        
        return params

    def _mutate(self, individual: dict) -> dict:
        """Mutate an individual's parameters."""
        params = individual["params"].copy()
        
        for name, value in params.items():
            if name not in self.param_ranges:
                continue
            
            min_val, max_val = self.param_ranges[name]
            
            if random.random() < self.config.mutation_rate:
                # Gaussian mutation
                range_size = max_val - min_val
                std = range_size * 0.1
                new_value = value + random.gauss(0, std)
                new_value = max(min_val, min(max_val, new_value))
                
                if isinstance(value, int):
                    new_value = int(new_value)
                else:
                    new_value = round(new_value, 4)
                
                params[name] = new_value
        
        return {"params": params, "score": 0.0}

    def _crossover(self) -> dict:
        """Crossover two parents."""
        parent1 = random.choice(self.population)
        parent2 = random.choice(self.population)
        
        child_params = {}
        for name in self.param_ranges.keys():
            if name in parent1["params"] and name in parent2["params"]:
                if random.random() < 0.5:
                    child_params[name] = parent1["params"][name]
                else:
                    child_params[name] = parent2["params"][name]
            elif name in parent1["params"]:
                child_params[name] = parent1["params"][name]
            elif name in parent2["params"]:
                child_params[name] = parent2["params"][name]
        
        # Mutate the child
        child = {"params": child_params, "score": 0.0}
        return self._mutate(child)

    def _llm_guided_evolution(self) -> dict:
        """Use LLM to guide evolution."""
        try:
            # Get context from patterns
            best_params = self.pattern_analyzer.get_best_parameters()
            best_score = self.pattern_analyzer.get_best_score()
            
            # Get LLM suggestion
            history = [
                {"params": e["params"], "score": e["score"]}
                for e in self.population
            ]
            
            suggested_params = self.llm_engine.evolve_parameters(
                history=history,
                best_params=best_params,
                best_score=best_score
            )
            
            # Validate and clip to ranges
            validated_params = {}
            for name, value in suggested_params.items():
                if name in self.param_ranges:
                    min_val, max_val = self.param_ranges[name]
                    if isinstance(min_val, int):
                        validated_params[name] = int(max(min_val, min(max_val, value)))
                    else:
                        validated_params[name] = round(max(min_val, min(max_val, value)), 4)
                else:
                    validated_params[name] = value
            
            logger.info(f"LLM suggested: {validated_params}")
            
            return {"params": validated_params, "score": 0.0, "llm_guided": True}
            
        except Exception as e:
            logger.warning(f"LLM guidance failed: {e}, falling back to mutation")
            return self._mutate(random.choice(self.population))

    def should_stop(self) -> bool:
        """Check if evolution should stop."""
        # Max no improvement reached
        if self.no_improvement_count >= self.config.max_no_improvement:
            logger.info("Stopping: max no improvement reached")
            return True
        
        # Perfect score (if applicable)
        if self.best_ever and self.best_ever["score"] >= 100:  # Arbitrary threshold
            logger.info("Stopping: excellent score achieved")
            return True
        
        return False

    def get_best(self) -> dict:
        """Get best individual found."""
        return self.best_ever or self.elite[0] if self.elite else None

    def get_stats(self) -> dict:
        """Get evolution statistics."""
        return {
            "generation": self.generation,
            "population_size": len(self.population),
            "elite_best_score": self.elite[0]["score"] if self.elite else 0,
            "best_ever_score": self.best_ever["score"] if self.best_ever else 0,
            "no_improvement_count": self.no_improvement_count,
            "llm_calls": self.llm_engine.total_calls if self.llm_engine else 0,
            "patterns_found": len(self.pattern_analyzer.patterns),
            "convergence": self.pattern_analyzer.get_convergence()
        }
