"""Main evolution loop - the heart of autonomous optimization."""

import time
import logging
import json
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Callable
import threading
import signal
import sys

from core.engine import BacktestEngine
from strategies.factory import create_strategy
from ai.llm_engine import LLMEngine, LLMProvider
from ai.strategy_evolver import StrategyEvolver, EvolutionConfig
from ai.pattern_analyzer import PatternAnalyzer


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("evolution.log")
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class EvolutionStats:
    """Statistics for the evolution process."""
    start_time: float = field(default_factory=time.time)
    generation: int = 0
    total_backtests: int = 0
    best_score: float = 0.0
    best_params: dict = field(default_factory=dict)
    current_population_best: float = 0.0
    no_improvement_runs: int = 0
    llm_calls: int = 0
    llm_cost: float = 0.0
    status: str = "initializing"
    error_count: int = 0
    last_update: float = field(default_factory=time.time)


class EvolutionLoop:
    """Main loop for autonomous strategy evolution.
    
    This is the core of the application - it runs continuously,
    testing strategies and using AI to evolve them.
    """

    def __init__(
        self,
        data_path: str = "market.csv",
        llm_provider: LLMProvider = LLMProvider.MOCK,
        output_dir: str = "output/evolution",
        max_generations: int = 10000,
        population_size: int = 20,
        generations_between_save: int = 5,
        checkpoint_interval: int = 50,
    ):
        """Initialize evolution loop.
        
        Args:
            data_path: Path to market data CSV
            llm_provider: LLM provider to use
            output_dir: Directory for output files
            max_generations: Maximum generations to run (0 = infinite)
            population_size: Population size per generation
            generations_between_save: Save results every N generations
            checkpoint_interval: Save checkpoint every N generations
        """
        self.data_path = data_path
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.max_generations = max_generations
        self.generations_between_save = generations_between_save
        self.checkpoint_interval = checkpoint_interval
        
        # Initialize components
        self.llm_engine = LLMEngine(provider=llm_provider)
        self.evolver_config = EvolutionConfig(
            population_size=population_size,
            llm_guidance=llm_provider != LLMProvider.MOCK,
            llm_interval=10,
            max_no_improvement=100,
        )
        self.evolver = StrategyEvolver(
            llm_engine=self.llm_engine,
            config=self.evolver_config
        )
        
        # Backtest engine
        self.backtest_engine: Optional[BacktestEngine] = None
        
        # Stats
        self.stats = EvolutionStats()
        
        # Control flags
        self._running = False
        self._paused = False
        self._stop_requested = False
        
        # History
        self.all_results: list[dict] = []
        self.generation_history: list[dict] = []

    def setup(self) -> None:
        """Setup backtest engine."""
        logger.info("Setting up backtest engine...")
        
        from config.settings import Settings
        settings = Settings()
        settings.data_path = self.data_path
        
        self.backtest_engine = BacktestEngine(settings)
        self.backtest_engine.setup()
        
        logger.info(f"Engine ready: {self.backtest_engine.n_records} records, {len(self.backtest_engine.tokens)} tokens")

    def run(self) -> None:
        """Run the evolution loop.
        
        This is the main entry point - call this to start the evolution.
        It will run until stopped or max_generations reached.
        """
        self._running = True
        self._stop_requested = False
        self.stats.status = "running"
        
        logger.info("=" * 60)
        logger.info("STARTING AUTONOMOUS STRATEGY EVOLUTION")
        logger.info("=" * 60)
        logger.info(f"LLM Provider: {self.llm_engine.llm.name()}")
        logger.info(f"Population size: {self.evolver_config.population_size}")
        logger.info(f"Max generations: {self.max_generations or 'infinite'}")
        logger.info("=" * 60)
        
        try:
            # Initialize population
            self.evolver.initialize_population()
            
            while not self._stop_requested:
                # Check if paused
                while self._paused:
                    time.sleep(1)
                    if self._stop_requested:
                        break
                
                if self._stop_requested:
                    break
                
                # Run one generation
                self._run_generation()
                
                # Check stop conditions
                if self.max_generations > 0 and self.stats.generation >= self.max_generations:
                    logger.info("Max generations reached")
                    break
                
                if self.evolver.should_stop():
                    logger.info("Evolution converged - stopping")
                    break
                
                # Save checkpoint
                if self.stats.generation % self.checkpoint_interval == 0:
                    self._save_checkpoint()
            
            self.stats.status = "completed"
            
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            self.stats.status = "interrupted"
        except Exception as e:
            logger.error(f"Error in evolution loop: {e}", exc_info=True)
            self.stats.status = "error"
            self.stats.error_count += 1
        finally:
            self._running = False
            self._save_final_results()
            
            logger.info("=" * 60)
            logger.info("EVOLUTION COMPLETE")
            logger.info("=" * 60)
            self._print_summary()

    def _run_generation(self) -> None:
        """Run one generation of backtests."""
        self.stats.generation += 1
        generation_start = time.time()
        
        logger.info("")
        logger.info(f"─── Generation {self.stats.generation} ───")
        
        # Evaluate population
        evaluated = []
        
        for i, individual in enumerate(self.evolver.population):
            try:
                result = self._backtest_strategy(individual["params"])
                result["generation"] = self.stats.generation
                evaluated.append(result)
                self.all_results.append(result)
                
                logger.info(
                    f"  [{i+1}/{len(self.evolver.population)}] "
                    f"Score: {result['score']:.4f} | {result.get('params', {})}"
                )
                
            except Exception as e:
                logger.error(f"  Backtest error: {e}")
                evaluated.append({
                    "params": individual["params"],
                    "score": 0.0,
                    "error": str(e)
                })
                self.stats.error_count += 1
        
        # Evolve to next generation
        self.evolver.evolve(evaluated)
        
        # Update stats
        gen_best = max(e["score"] for e in evaluated)
        if gen_best > self.stats.best_score:
            self.stats.best_score = gen_best
            self.stats.no_improvement_runs = 0
            # Find best params
            for e in evaluated:
                if e["score"] == gen_best:
                    self.stats.best_params = e.get("params", {})
                    break
        else:
            self.stats.no_improvement_runs += 1
        
        self.stats.current_population_best = gen_best
        self.stats.total_backtests += len(evaluated)
        self.stats.last_update = time.time()
        
        # Save generation history
        self.generation_history.append({
            "generation": self.stats.generation,
            "best_score": gen_best,
            "avg_score": sum(e["score"] for e in evaluated) / len(evaluated),
            "worst_score": min(e["score"] for e in evaluated),
            "time_taken": time.time() - generation_start
        })
        
        # Log generation summary
        elapsed = time.time() - self.stats.start_time
        gen_time = time.time() - generation_start
        
        logger.info(
            f"  Gen stats: best={gen_best:.4f}, "
            f"avg={self.stats.current_population_best:.4f}, "
            f"time={gen_time:.1f}s, "
            f"total_time={elapsed/60:.1f}min"
        )

    def _backtest_strategy(self, params: dict) -> dict:
        """Run a single backtest."""
        # Create strategy
        strategy = create_strategy("threshold", **params)
        
        # Run backtest
        result = self.backtest_engine.run(
            strategy=strategy,
            start_idx=0,
            end_idx=min(10000, self.backtest_engine.n_records)  # Use subset for speed
        )
        
        # Extract score
        score = 0.0
        if result.score_result:
            # Use ROI as primary score
            score = result.score_result.roi_percent
        
        return {
            "params": params,
            "score": score,
            "strategy_name": result.strategy_name,
            "n_swaps": result.score_result.total_swaps if result.score_result else 0,
            "win_rate": result.score_result.win_rate if result.score_result else 0,
            "final_tokens": result.score_result.final_token_count if result.score_result else 0,
        }

    def _save_checkpoint(self) -> None:
        """Save checkpoint."""
        checkpoint = {
            "timestamp": datetime.now().isoformat(),
            "generation": self.stats.generation,
            "stats": {
                "best_score": self.stats.best_score,
                "best_params": self.stats.best_params,
                "total_backtests": self.stats.total_backtests,
                "no_improvement_runs": self.stats.no_improvement_runs,
            },
            "generation_history": self.generation_history[-100:],  # Last 100
        }
        
        checkpoint_file = self.output_dir / f"checkpoint_gen{self.stats.generation}.json"
        with open(checkpoint_file, "w") as f:
            json.dump(checkpoint, f, indent=2)
        
        logger.info(f"Checkpoint saved: {checkpoint_file}")

    def _save_final_results(self) -> None:
        """Save final results."""
        results_file = self.output_dir / f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        results = {
            "timestamp": datetime.now().isoformat(),
            "final_stats": {
                "generations": self.stats.generation,
                "total_backtests": self.stats.total_backtests,
                "best_score": self.stats.best_score,
                "best_params": self.stats.best_params,
                "elapsed_minutes": (time.time() - self.stats.start_time) / 60,
                "llm_stats": self.llm_engine.get_stats() if self.llm_engine else {},
            },
            "generation_history": self.generation_history,
            "all_results": self.all_results[-1000:],  # Last 1000
        }
        
        with open(results_file, "w") as f:
            json.dump(results, f, indent=2)
        
        logger.info(f"Results saved: {results_file}")

    def _print_summary(self) -> None:
        """Print final summary."""
        elapsed = time.time() - self.stats.start_time
        
        print("\n" + "=" * 60)
        print("EVOLUTION SUMMARY")
        print("=" * 60)
        print(f"Generations:        {self.stats.generation}")
        print(f"Total backtests:    {self.stats.total_backtests}")
        print(f"Elapsed time:       {elapsed/60:.1f} minutes")
        print(f"Backtests/sec:     {self.stats.total_backtests/elapsed:.2f}")
        print()
        print(f"Best Score:        {self.stats.best_score:.4f}")
        print(f"Best Parameters:")
        for k, v in self.stats.best_params.items():
            print(f"  {k}: {v}")
        print()
        
        llm_stats = self.llm_engine.get_stats() if self.llm_engine else {}
        print(f"LLM Stats:")
        print(f"  Provider:         {llm_stats.get('provider', 'N/A')}")
        print(f"  API Calls:       {llm_stats.get('total_calls', 0)}")
        print(f"  Tokens Used:     {llm_stats.get('total_tokens', 0)}")
        print(f"  Est. Cost:        ${llm_stats.get('total_cost', 0):.4f}")
        print("=" * 60)

    def pause(self) -> None:
        """Pause the evolution."""
        self._paused = True
        self.stats.status = "paused"
        logger.info("Evolution paused")

    def resume(self) -> None:
        """Resume the evolution."""
        self._paused = False
        self.stats.status = "running"
        logger.info("Evolution resumed")

    def stop(self) -> None:
        """Stop the evolution."""
        self._stop_requested = True
        self.stats.status = "stopping"
        logger.info("Stop requested...")

    def get_status(self) -> dict:
        """Get current status."""
        elapsed = time.time() - self.stats.start_time
        
        return {
            "status": self.stats.status,
            "generation": self.stats.generation,
            "total_backtests": self.stats.total_backtests,
            "best_score": self.stats.best_score,
            "current_best": self.stats.current_population_best,
            "no_improvement": self.stats.no_improvement_runs,
            "elapsed_minutes": elapsed / 60,
            "llm_calls": self.llm_engine.get_stats().get("total_calls", 0) if self.llm_engine else 0,
        }

    def is_running(self) -> bool:
        """Check if evolution is running."""
        return self._running and not self._paused
