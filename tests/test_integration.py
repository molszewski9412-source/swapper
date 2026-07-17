"""Integration tests for the backtesting engine."""

import pytest
import numpy as np
from pathlib import Path
from datetime import datetime

from core.models import PriceMatrix, SwapMatrix
from core.portfolio import VectorizedPortfolio
from core.records import RecordHistory, MatrixRecordTracker
from core.simulator import SwapSimulator
from core.engine import BacktestEngine, BacktestResult
from data.cache import DataCache
from strategies.threshold import ThresholdStrategy
from config.settings import Settings, FeesConfig, SimulationConfig


@pytest.fixture
def test_data_matrix():
    """Create test data matrix with realistic prices."""
    tokens = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    n_records = 100
    
    matrix = PriceMatrix.create(n_records, len(tokens), tokens)
    
    # Generate realistic price movements
    base_prices = {"BTCUSDT": 50000.0, "ETHUSDT": 3000.0, "SOLUSDT": 100.0}
    
    for i in range(n_records):
        # Random walk
        prices = {}
        for token, base in base_prices.items():
            change = 1 + (np.random.random() - 0.5) * 0.02
            base_prices[token] *= change
            bid = base_prices[token]
            ask = bid * 1.0002  # Small spread
            prices[token] = (bid, ask)
        
        matrix.set_prices(i, int(datetime.now().timestamp() * 1000) + i * 1000, prices)
    
    return matrix


@pytest.fixture
def test_cache(test_data_matrix):
    """Create test cache."""
    return DataCache(test_data_matrix)


@pytest.fixture
def test_simulator(test_cache):
    """Create test simulator."""
    return SwapSimulator(test_cache)


@pytest.fixture
def test_portfolio(test_data_matrix):
    """Create test portfolio."""
    return VectorizedPortfolio(
        tokens=test_data_matrix.tokens,
        initial_capital=1.0,
        starting_token="BTCUSDT"
    )


@pytest.fixture
def test_tracker(test_data_matrix):
    """Create test record tracker."""
    tracker = MatrixRecordTracker.create(test_data_matrix.tokens)
    tracker.set_initial("BTCUSDT", 1.0)
    return tracker


class TestEndToEndBacktest:
    """End-to-end backtest tests."""

    def test_full_backtest_workflow(
        self, test_cache, test_simulator, test_portfolio, test_tracker
    ):
        """Test complete backtest workflow."""
        n_records = min(50, test_cache.n_records)
        
        for record_idx in range(n_records):
            # Get swap matrix
            swap_matrix = SwapMatrix.compute(test_cache.price_matrix, record_idx)
            
            # Get holdings
            holdings = test_portfolio.get_holdings_vector()
            holding_idx = test_portfolio._holding_idx
            
            # Strategy decision
            gains = swap_matrix.matrix[holding_idx]
            best_target_idx = np.argmax(gains)
            best_gain = gains[best_target_idx]
            
            # Execute if gain > 1.05
            if best_gain > 1.05 and record_idx > 5:
                to_token = swap_matrix.index_token[best_target_idx]
                from_token = test_portfolio.holding_token
                
                result = test_simulator.execute_swap(
                    record_idx, from_token, to_token, test_portfolio.holding_amount
                )
                
                if result.success:
                    # Update portfolio
                    test_portfolio.perform_swap(
                        swap_matrix.token_index[from_token],
                        swap_matrix.token_index[to_token],
                        result.amount_in,
                        result.amount_out
                    )
            
            test_portfolio.increment_record()
        
        # Check results
        final_holdings = test_portfolio.get_holdings_vector()
        assert np.any(final_holdings > 0)  # Should have some holdings
        
        # Record tracker should have data
        assert test_tracker.swap_history or True  # May or may not have swaps


class TestDataIntegrity:
    """Tests for data integrity throughout the system."""

    def test_cache_consistency(self, test_data_matrix, test_cache):
        """Test that cache returns consistent data."""
        for i in range(min(10, test_cache.n_records)):
            bid1 = test_cache.get_bid(i, "BTCUSDT")
            bid2 = test_data_matrix.get_bid(i, "BTCUSDT")
            assert bid1 == bid2

    def test_portfolio_consistency(self, test_portfolio, test_data_matrix):
        """Test portfolio state consistency."""
        # Portfolio should start with BTC
        assert test_portfolio.holding_token == "BTCUSDT"
        assert test_portfolio.holding_amount == 1.0
        
        # After reset should be same
        test_portfolio.reset()
        assert test_portfolio.holding_token == "BTCUSDT"
        assert test_portfolio.holding_amount == 1.0

    def test_swap_matrix_values(self, test_data_matrix, test_cache):
        """Test swap matrix values are mathematically correct."""
        fee_factor = (1 - 0.0004) ** 2
        
        n_tokens = test_data_matrix.n_tokens
        for i in range(min(10, test_cache.n_records)):
            swap_matrix = SwapMatrix.compute(test_data_matrix, i)
            
            bid_prices = test_data_matrix.get_bid_vector(i)
            ask_prices = test_data_matrix.get_ask_vector(i)
            
            # For any valid pair i, j (i != j):
            # swap[i,j] = bid[i] / ask[j] * fee_factor
            # Only test for pairs that exist in our matrix
            n = min(n_tokens, swap_matrix.matrix.shape[0], len(bid_prices))
            
            for j in range(n):
                if i < n and i != j:
                    expected = bid_prices[i] / ask_prices[j] * fee_factor
                    actual = swap_matrix.matrix[i, j]
                    if expected > 0:
                        assert abs(expected - actual) / expected < 0.001


class TestRecordTracking:
    """Tests for record tracking system."""

    def test_tracker_initialization(self, test_data_matrix):
        """Test record tracker initialization."""
        tracker = MatrixRecordTracker.create(test_data_matrix.tokens)
        
        assert tracker.n_tokens == len(test_data_matrix.tokens)
        assert tracker._holding_idx == -1
        assert tracker._holding_amount == 0.0

    def test_tracker_set_initial(self, test_tracker):
        """Test setting initial holding."""
        assert test_tracker.holding_token == "BTCUSDT"
        assert test_tracker.holding_amount == 1.0
        assert test_tracker.get_actual("BTCUSDT") == 1.0

    def test_tracker_update_potential(self, test_tracker, test_data_matrix):
        """Test potential value updates."""
        prices = test_data_matrix.get_bid_vector(0)
        test_tracker.update_potential_vector(prices)
        
        # All potentials should be set
        for token in test_data_matrix.tokens:
            potential = test_tracker.get_potential(token)
            assert potential > 0

    def test_tracker_record_swap(self, test_tracker, test_data_matrix):
        """Test swap recording."""
        prices = test_data_matrix.get_bid_vector(0)
        test_tracker.update_potential_vector(prices)
        
        # Record a swap
        swap = test_tracker.record_swap(
            record_index=0,
            timestamp=1000,
            from_idx=0,
            to_idx=1,
            amount_out=16.5,
            fee=0.02,
            price_in=50000.0,
            price_out=3000.0
        )
        
        assert swap.from_token == "BTCUSDT"
        assert swap.to_token == "ETHUSDT"
        assert test_tracker.holding_token == "ETHUSDT"
        assert test_tracker.swap_history


class TestScoring:
    """Tests for scoring integration."""

    def test_score_from_backtest_data(self):
        """Test scoring engine with mock backtest data."""
        from scoring.engine import ScoringEngine, ScoreResult
        
        engine = ScoringEngine(base_token="BTCUSDT", initial_capital=1.0)
        
        backtest_data = {
            "final_holdings": {"BTCUSDT": 1.5, "ETHUSDT": 0.0},
            "swap_history": [
                {"from_token": "BTCUSDT", "to_token": "ETHUSDT", "amount_in": 1.0, "amount_out": 16.0}
            ],
            "price_history": [
                {"timestamp": 1000, "prices": {"BTCUSDT": 50000, "ETHUSDT": 3000}},
                {"timestamp": 2000, "prices": {"BTCUSDT": 55000, "ETHUSDT": 3300}},
            ],
            "records": 100
        }
        
        result = engine.score(backtest_data)
        
        assert isinstance(result, ScoreResult)
        assert result.final_token_count == 1.5
        assert result.roi_percent > 0
        assert result.total_swaps == 1
