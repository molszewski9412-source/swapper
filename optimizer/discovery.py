"""Strategy discovery engine using AI and genetic programming."""

from typing import Any, Callable, Optional
from dataclasses import dataclass
import numpy as np
import logging


logger = logging.getLogger(__name__)


@dataclass
class DiscoveredStrategy:
    """A discovered trading strategy."""
    name: str
    params: dict[str, Any]
    score: float
    description: str = ""
    rules: list[str] = None

    def __post_init__(self) -> None:
        if self.rules is None:
            self.rules = []


class StrategyGene:
    """Gene representation for genetic strategy evolution."""
    
    GENE_TYPES = [
        "threshold",
        "interval", 
        "momentum_weight",
        "volatility_weight",
        "rsi_oversold",
        "rsi_overbought",
        "pair_threshold",
        "rebalance_ratio",
    ]

    def __init__(
        self,
        gene_type: str,
        value: Any,
        mutation_range: tuple[Any, Any] = None
    ):
        self.gene_type = gene_type
        self.value = value
        self.mutation_range = mutation_range

    def mutate(self, rate: float = 0.1) -> "StrategyGene":
        """Create mutated copy."""
        if np.random.random() > rate:
            return StrategyGene(self.gene_type, self.value, self.mutation_range)
        
        if self.mutation_range:
            min_val, max_val = self.mutation_range
            if isinstance(min_val, int):
                new_value = int(min_val + np.random.random() * (max_val - min_val))
            else:
                new_value = min_val + np.random.random() * (max_val - min_val)
        else:
            # Gene-specific mutations
            if self.gene_type == "threshold":
                new_value = self.value * (1 + np.random.uniform(-0.2, 0.2))
            elif self.gene_type == "interval":
                new_value = max(1, int(self.value + np.random.randint(-2, 3)))
            else:
                new_value = self.value
        
        return StrategyGene(self.gene_type, new_value, self.mutation_range)


class StrategyChromosome:
    """Chromosome representing a complete strategy."""

    def __init__(self, genes: list[StrategyGene] = None):
        self.genes = genes or []

    @classmethod
    def random(cls) -> "StrategyChromosome":
        """Create random chromosome."""
        genes = [
            StrategyGene("threshold", 1.0 + np.random.random(), (0.5, 3.0)),
            StrategyGene("interval", np.random.randint(1, 20), (1, 50)),
            StrategyGene("momentum_weight", np.random.random() * 0.5, (0, 1)),
            StrategyGene("volatility_weight", np.random.random() * 0.5, (0, 1)),
            StrategyGene("rsi_oversold", 30, (10, 40)),
            StrategyGene("rsi_overbought", 70, (60, 90)),
        ]
        return cls(genes)

    def to_params(self) -> dict[str, Any]:
        """Convert chromosome to strategy parameters."""
        params = {}
        for gene in self.genes:
            if gene.gene_type == "threshold":
                params["threshold"] = gene.value
            elif gene.gene_type == "interval":
                params["min_swap_interval"] = gene.value
            elif gene.gene_type == "momentum_weight":
                params["momentum_weight"] = gene.value
            elif gene.gene_type == "volatility_weight":
                params["volatility_multiplier"] = gene.value
            elif gene.gene_type == "rsi_oversold":
                params["rsi_oversold"] = gene.value
            elif gene.gene_type == "rsi_overbought":
                params["rsi_overbought"] = gene.value
        return params

    def crossover(self, other: "StrategyChromosome") -> tuple["StrategyChromosome", "StrategyChromosome"]:
        """Crossover with another chromosome."""
        # Single-point crossover
        point = np.random.randint(1, len(self.genes))
        
        child1_genes = self.genes[:point] + other.genes[point:]
        child2_genes = other.genes[:point] + self.genes[point:]
        
        return StrategyChromosome(child1_genes), StrategyChromosome(child2_genes)

    def mutate(self, rate: float = 0.1) -> "StrategyChromosome":
        """Create mutated copy."""
        return StrategyChromosome([g.mutate(rate) for g in self.genes])


class StrategyDiscoveryEngine:
    """AI-powered strategy discovery using genetic programming.
    
    Evolves strategies by combining and mutating successful ones.
    """

    def __init__(
        self,
        backtest_func: Callable[[dict[str, Any]], float],
        population_size: int = 50,
        generations: int = 20,
        mutation_rate: float = 0.15,
        elite_ratio: float = 0.1,
        seed: int = None
    ):
        """Initialize discovery engine.
        
        Args:
            backtest_func: Function that evaluates strategy params and returns score
            population_size: Size of strategy population
            generations: Number of evolution generations
            mutation_rate: Probability of mutation
            elite_ratio: Ratio of best strategies to keep
            seed: Random seed
        """
        self.backtest_func = backtest_func
        self.population_size = population_size
        self.generations = generations
        self.mutation_rate = mutation_rate
        self.elite_ratio = elite_ratio
        self.rng = np.random.default_rng(seed)
        
        self.population: list[StrategyChromosome] = []
        self.fitness: list[float] = []
        self.best_strategies: list[DiscoveredStrategy] = []

    def _initialize_population(self) -> None:
        """Initialize random population."""
        self.population = [StrategyChromosome.random() for _ in range(self.population_size)]

    def _evaluate_population(self) -> list[float]:
        """Evaluate fitness for all strategies."""
        self.fitness = []
        for chrom in self.population:
            params = chrom.to_params()
            score = self.backtest_func(params)
            self.fitness.append(score)
        return self.fitness

    def _select(self) -> list[StrategyChromosome]:
        """Tournament selection."""
        tournament_size = 3
        selected = []
        
        for _ in range(self.population_size):
            indices = self.rng.integers(0, self.population_size, tournament_size)
            best_idx = max(indices, key=lambda i: self.fitness[i])
            selected.append(self.population[best_idx])
        
        return selected

    def _evolve_generation(self) -> None:
        """Create next generation."""
        # Elites
        n_elite = max(1, int(self.population_size * self.elite_ratio))
        elite_indices = np.argsort(self.fitness)[-n_elite:]
        elites = [self.population[i] for i in elite_indices]
        
        # Selection
        selected = self._select()
        
        # Crossover and mutation
        new_population = []
        
        for i in range(0, self.population_size - n_elite, 2):
            if i + 1 < len(selected):
                child1, child2 = selected[i].crossover(selected[i + 1])
                new_population.append(child1.mutate(self.mutation_rate))
                new_population.append(child2.mutate(self.mutation_rate))
        
        # Fill remaining
        while len(new_population) < self.population_size - n_elite:
            new_population.append(StrategyChromosome.random().mutate(self.mutation_rate))
        
        self.population = new_population + elites

    def discover(
        self,
        progress_callback: Optional[Callable[[int, int, float], None]] = None
    ) -> list[DiscoveredStrategy]:
        """Run strategy discovery.
        
        Args:
            progress_callback: Optional callback(generation, total, best_score)
        
        Returns:
            List of discovered strategies
        """
        logger.info("Initializing strategy discovery...")
        self._initialize_population()
        
        best_score = float('-inf')
        patience = 0
        max_patience = 5
        
        for gen in range(self.generations):
            # Evaluate
            self.fitness = self._evaluate_population()
            
            # Track best
            gen_best_idx = np.argmax(self.fitness)
            gen_best_score = self.fitness[gen_best_idx]
            gen_best_chrom = self.population[gen_best_idx]
            
            if gen_best_score > best_score:
                best_score = gen_best_score
                patience = 0
                
                # Record discovered strategy
                strategy = DiscoveredStrategy(
                    name=f"discovered_gen{gen}",
                    params=gen_best_chrom.to_params(),
                    score=gen_best_score,
                    rules=self._extract_rules(gen_best_chrom)
                )
                self.best_strategies.append(strategy)
            else:
                patience += 1
            
            if progress_callback:
                progress_callback(gen + 1, self.generations, best_score)
            
            logger.info(f"Generation {gen + 1}: best={gen_best_score:.4f}, patience={patience}")
            
            # Early stopping
            if patience >= max_patience:
                logger.info(f"Early stopping at generation {gen + 1}")
                break
            
            # Evolve
            self._evolve_generation()
        
        return self.best_strategies

    def _extract_rules(self, chrom: StrategyChromosome) -> list[str]:
        """Extract human-readable rules from chromosome."""
        rules = []
        params = chrom.to_params()
        
        if "threshold" in params:
            rules.append(f"Swap when gain > {params['threshold']:.2f}")
        if "min_swap_interval" in params:
            rules.append(f"Cooldown: {params['min_swap_interval']} records")
        if "momentum_weight" in params:
            rules.append(f"Momentum weight: {params['momentum_weight']:.2f}")
        if "rsi_oversold" in params:
            rules.append(f"RSI oversold: {params['rsi_oversold']}")
        
        return rules


class RuleBasedDiscovery:
    """Discovery using rule combination and testing."""

    def __init__(
        self,
        backtest_func: Callable[[dict[str, Any]], float]
    ):
        self.backtest_func = backtest_func
        self.rules: list[dict[str, Any]] = []

    def add_rule(self, rule: dict[str, Any]) -> None:
        """Add a rule to the rule base."""
        self.rules.append(rule)

    def combine_rules(
        self,
        n_rules: int = 3,
        max_combinations: int = 100
    ) -> list[dict[str, Any]]:
        """Generate rule combinations and test them.
        
        Args:
            n_rules: Number of rules per combination
            max_combinations: Maximum combinations to test
        
        Returns:
            List of parameter dictionaries that worked well
        """
        from itertools import combinations
        
        results = []
        
        for i, rule_combo in enumerate(combinations(self.rules, n_rules)):
            if i >= max_combinations:
                break
            
            # Combine rules
            combined_params = {}
            for rule in rule_combo:
                combined_params.update(rule["params"])
            
            # Test
            score = self.backtest_func(combined_params)
            results.append({
                "params": combined_params,
                "score": score,
                "rules": [r["name"] for r in rule_combo]
            })
        
        # Sort by score
        results.sort(key=lambda x: x["score"], reverse=True)
        return results

    def generate_hypothesis(
        self,
        historical_results: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Generate hypothesis from historical results.
        
        Analyzes successful strategies to generate new hypotheses.
        
        Args:
            historical_results: List of {params, score} from past runs
        
        Returns:
            Hypothesis parameters to test
        """
        if not historical_results:
            return {}
        
        # Analyze parameter distributions of top strategies
        top_10_percent = int(len(historical_results) * 0.1)
        top_results = sorted(historical_results, key=lambda x: x["score"], reverse=True)[:top_10_percent]
        
        if not top_results:
            return {}
        
        # Calculate mean parameters of top performers
        hypothesis = {}
        all_params = set()
        for r in top_results:
            all_params.update(r["params"].keys())
        
        for param in all_params:
            values = [r["params"].get(param) for r in top_results if param in r["params"]]
            if values:
                if all(isinstance(v, int) for v in values):
                    hypothesis[param] = int(np.median(values))
                elif all(isinstance(v, float) for v in values):
                    hypothesis[param] = float(np.median(values))
        
        return hypothesis
