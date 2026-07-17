"""Core backtesting engine orchestrating all components."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Callable
import logging
import numpy as np

from config.settings import Settings, FeesConfig, SimulationConfig
from data.loader import DataLoader
from data.cache import DataCache
from core.models import SwapMatrix
from core.portfolio import VectorizedPortfolio
from core.records import RecordHistory, MatrixRecordTracker
from core.simulator import SwapSimulator
from core.market_matrix import MarketMatrixEngine
from strategies.base import Strategy, Signal
from scoring.engine import ScoringEngine, ScoreResult
from reports.generator import ReportGenerator, BacktestReport


logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """Result of a backtest run."""
    strategy_name: str
    params: dict[str, Any]
    final_holdings: dict[str, float]
    swap_history: list[dict[str, Any]]
    benchmark_history: list[dict[str, Any]]
    price_history: list[dict[str, Any]]
    n_records: int
    elapsed_time: float
    score_result: Optional[ScoreResult] = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BacktestEngine:
    """Main backtesting engine orchestrating all components.
    
    Coordinates data loading, simulation, strategy execution, and scoring.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        data_path: Optional[Any] = None,
    ):
        """Initialize backtest engine.
        
        Args:
            settings: Configuration settings
            data_path: Path to market.csv data file
        """
        self.settings = settings or Settings()
        self.data_path = Path(data_path) if data_path else self.settings.data_path
        
        # Components (initialized in setup)
        self.data_loader: Optional[DataLoader] = None
        self.cache: Optional[DataCache] = None
        self.matrix_engine: Optional[MarketMatrixEngine] = None
        self.simulator: Optional[SwapSimulator] = None
        self.portfolio: Optional[VectorizedPortfolio] = None
        self.record_tracker: Optional[MatrixRecordTracker] = None
        self.scoring_engine: Optional[ScoringEngine] = None
        
        self._initialized = False
        self._current_strategy: Optional[Strategy] = None

    def setup(self, max_records: Optional[int] = None) -> None:
        """Setup engine components.
        
        Args:
            max_records: Maximum records to load (None for all)
        """
        if self._initialized:
            logger.warning("Engine already initialized")
            return
        
        logger.info(f"Setting up engine with data: {self.data_path}")
        
        # Initialize data loader
        self.data_loader = DataLoader(self.data_path)
        
        # Load data into cache
        logger.info("Loading market data...")
        price_matrix = self.data_loader.load_to_matrix(
            max_records=max_records,
            progress_callback=lambda curr, total: logger.info(f"Loading: {curr}/{total}")
        )
        
        # Initialize cache
        self.cache = DataCache(price_matrix, swap_fee=self.settings.fees.swap_fee_per_leg)
        
        # Initialize matrix engine
        self.matrix_engine = MarketMatrixEngine(self.cache, precompute=True)
        
        # Initialize simulator
        self.simulator = SwapSimulator(self.cache, self.settings.fees)
        
        # Initialize portfolio
        self.portfolio = VectorizedPortfolio(
            tokens=price_matrix.tokens,
            initial_capital=self.settings.simulation.initial_capital,
            starting_token=self.settings.simulation.starting_token,
        )
        
        # Initialize record tracker
        self.record_tracker = MatrixRecordTracker.create(price_matrix.tokens)
        self.record_tracker.set_initial(
            self.settings.simulation.starting_token,
            self.settings.simulation.initial_capital
        )
        
        # Initialize scoring engine
        self.scoring_engine = ScoringEngine(
            base_token=self.settings.simulation.starting_token,
            initial_capital=self.settings.simulation.initial_capital,
        )
        
        self._initialized = True
        logger.info(f"Engine setup complete: {price_matrix.n_records} records, {price_matrix.n_tokens} tokens")

    def run(
        self,
        strategy: Strategy,
        start_idx: int = 0,
        end_idx: Optional[int] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> BacktestResult:
        """Run backtest with given strategy.
        
        Args:
            strategy: Strategy to evaluate
            start_idx: Starting record index
            end_idx: Ending record index (None for all)
            progress_callback: Optional callback(processed, total)
        
        Returns:
            BacktestResult with all metrics and history
        """
        if not self._initialized:
            self.setup()
        
        import time
        start_time = time.time()
        
        self._current_strategy = strategy
        strategy.reset()
        
        end_idx = end_idx or self.cache.n_records
        n_records = min(end_idx, self.cache.n_records) - start_idx
        
        # History
        swap_history: list[dict[str, Any]] = []
        benchmark_history: list[dict[str, Any]] = []
        price_history: list[dict[str, Any]] = []
        
        # Reset state
        self.portfolio.reset()
        self.record_tracker.set_initial(
            self.settings.simulation.starting_token,
            self.settings.simulation.initial_capital
        )
        self.record_tracker._record_count = 0
        
        logger.info(f"Running backtest: {strategy.name} on {n_records} records")
        
        # Main loop
        for record_idx in range(start_idx, end_idx):
            # 1. Get swap matrix (O(1) lookup)
            swap_matrix = self.matrix_engine.get_swap_matrix(record_idx)
            
            # 2. Get current holdings
            holdings_vector = self.portfolio.get_holdings_vector()
            holding_idx = self.portfolio._holding_idx
            
            # 3. Get price vector for record tracking
            bid_prices = self.cache.get_bid_vector(record_idx)
            prices_dict = {
                token: bid_prices[idx]
                for token, idx in self.cache.price_matrix.token_index.items()
            }
            
            # 4. Update potential values
            self.record_tracker.update_potential_vector(bid_prices)
            
            # 5. Record price history periodically
            if record_idx % 100 == 0:
                price_history.append({
                    "timestamp": self.cache.price_matrix.timestamps[record_idx],
                    "record_index": record_idx,
                    "prices": prices_dict,
                })
            
            # 6. Strategy evaluation
            signal = strategy.evaluate(
                record_idx=record_idx,
                swap_matrix=swap_matrix.matrix,
                holdings_vector=holdings_vector,
                token_index=self.cache.price_matrix.token_index,
                index_token=self.cache.price_matrix.index_token,
            )
            
            # 7. Execute swap if signal
            if signal.should_execute():
                from_idx = self.cache.price_matrix.token_index[signal.from_token]
                to_idx = self.cache.price_matrix.token_index[signal.to_token]
                
                # Execute swap
                result = self.simulator.execute_swap(
                    record_idx=record_idx,
                    from_token=signal.from_token,
                    to_token=signal.to_token,
                    amount_in=signal.amount or self.portfolio.holding_amount,
                )
                
                if result.success:
                    # Update portfolio
                    self.portfolio.perform_swap(
                        from_idx=from_idx,
                        to_idx=to_idx,
                        amount_in=result.amount_in,
                        amount_out=result.amount_out,
                    )
                    
                    # Record swap
                    swap_record = self.record_tracker.record_swap(
                        record_index=record_idx,
                        timestamp=self.cache.price_matrix.timestamps[record_idx],
                        from_idx=from_idx,
                        to_idx=to_idx,
                        amount_out=result.amount_out,
                        fee=result.fee,
                        price_in=result.price_in,
                        price_out=result.price_out,
                    )
                    
                    swap_history.append(swap_record.to_dict())
                    
                    # Notify strategy
                    strategy.on_swap_executed(
                        record_idx=record_idx,
                        from_token=signal.from_token,
                        to_token=signal.to_token,
                        amount_in=result.amount_in,
                        amount_out=result.amount_out,
                    )
            
            # 8. Record benchmark snapshot periodically
            self.record_tracker._record_count += 1
            if self.record_tracker._record_count % 100 == 0:
                benchmark_history.append({
                    "timestamp": self.cache.price_matrix.timestamps[record_idx],
                    "record_index": record_idx,
                    "potential": {
                        token: self.record_tracker.get_potential(token)
                        for token in self.cache.price_matrix.tokens
                    },
                    "actual": {
                        token: self.record_tracker.get_actual(token)
                        for token in self.cache.price_matrix.tokens
                    },
                    "holding_token": self.record_tracker.holding_token,
                    "holding_amount": self.record_tracker.holding_amount,
                })
            
            self.portfolio.increment_record()
            
            if progress_callback and record_idx % 1000 == 0:
                progress_callback(record_idx - start_idx, n_records)
        
        elapsed = time.time() - start_time
        
        # Get final holdings
        final_holdings = {
            token: float(self.portfolio.get_holdings_vector()[idx])
            for token, idx in self.portfolio._token_index.items()
        }
        
        # Score result
        backtest_data = {
            "final_holdings": final_holdings,
            "swap_history": swap_history,
            "price_history": price_history,
            "records": n_records,
        }
        
        score_result = self.scoring_engine.score(backtest_data)
        
        result = BacktestResult(
            strategy_name=strategy.name,
            params=strategy.get_params(),
            final_holdings=final_holdings,
            swap_history=swap_history,
            benchmark_history=benchmark_history,
            price_history=price_history,
            n_records=n_records,
            elapsed_time=elapsed,
            score_result=score_result,
        )
        
        logger.info(f"Backtest complete: {len(swap_history)} swaps, ROI={score_result.roi_percent:.2f}%, elapsed={elapsed:.2f}s")
        
        return result

    def run_optimization(
        self,
        strategy_class: type,
        param_space: dict[str, Any],
        n_iterations: int = 100,
        method: str = "random",
    ) -> dict[str, Any]:
        """Run optimization over strategy parameters.
        
        Args:
            strategy_class: Strategy class to optimize
            param_space: Parameter search space
            n_iterations: Number of iterations
            method: Optimization method
        
        Returns:
            Optimization results
        """
        from optimizer.orchestrator import OptimizerOrchestrator
        from optimizer.base import OptimizationResult
        
        def objective(params: dict[str, Any]) -> float:
            strategy = strategy_class(**params)
            result = self.run(strategy)
            return result.score_result.roi_percent if result.score_result else 0.0
        
        orchestrator = OptimizerOrchestrator()
        opt_result = orchestrator.optimize(
            param_space=param_space,
            objective=objective,
            n_iterations=n_iterations,
        )
        
        return {
            "best_params": opt_result.best_params,
            "best_score": opt_result.best_score,
            "all_results": opt_result.all_results,
        }

    def generate_report(
        self,
        result: BacktestResult,
        formats: list[str] = None,
    ) -> dict[str, Path]:
        """Generate report from backtest result.
        
        Args:
            result: BacktestResult to report
            formats: Output formats
        
        Returns:
            Dictionary of output paths
        """
        generator = ReportGenerator(self.settings.output_dir)
        
        report = BacktestReport(
            strategy_name=result.strategy_name,
            params=result.params,
            start_time=datetime.now().isoformat(),
            end_time=datetime.now().isoformat(),
            n_records=result.n_records,
            score_result=result.score_result.summary() if result.score_result else {},
            swap_history=result.swap_history,
            benchmark_history=result.benchmark_history,
            metadata=result.metadata,
        )
        
        return generator.generate(report, formats)

    @property
    def n_records(self) -> int:
        """Get number of records in cache."""
        return self.cache.n_records if self.cache else 0

    @property
    def tokens(self) -> list[str]:
        """Get list of tokens."""
        return self.cache.tokens if self.cache else []
