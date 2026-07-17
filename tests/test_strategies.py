"""Tests for trading strategies."""

import pytest
import numpy as np

from strategies.base import Strategy, Signal, SignalType
from strategies.hold import HoldStrategy, ThresholdHoldStrategy
from strategies.threshold import ThresholdStrategy
from strategies.factory import create_strategy, list_available_strategies


@pytest.fixture
def basic_swap_matrix():
    """Create a basic swap matrix for testing."""
    # 2 tokens: BTC, ETH
    # Swap matrix where BTC->ETH gives 50, ETH->BTC gives 0.02
    matrix = np.array([
        [0.0, 50.0],   # BTC -> BTC=0, BTC->ETH=50
        [0.02, 0.0],   # ETH -> BTC=0.02, ETH->ETH=0
    ])
    return matrix


@pytest.fixture
def holdings_vector():
    """Create holdings vector."""
    return np.array([1.0, 0.0])  # 1 BTC


@pytest.fixture
def token_mapping():
    """Create token mapping."""
    return {
        "BTCUSDT": 0,
        "ETHUSDT": 1,
    }, {
        0: "BTCUSDT",
        1: "ETHUSDT"
    }


class TestHoldStrategy:
    """Tests for HoldStrategy."""

    def test_hold_strategy_always_holds(self, basic_swap_matrix, holdings_vector, token_mapping):
        """Test that hold strategy always returns HOLD signal."""
        strategy = HoldStrategy()
        token_index, index_token = token_mapping
        
        signal = strategy.evaluate(
            record_idx=0,
            swap_matrix=basic_swap_matrix,
            holdings_vector=holdings_vector,
            token_index=token_index,
            index_token=index_token
        )
        
        assert signal.signal_type == SignalType.HOLD
        assert signal.confidence == 1.0

    def test_hold_strategy_repr(self):
        """Test hold strategy representation."""
        strategy = HoldStrategy()
        assert "HoldStrategy" in repr(strategy)


class TestThresholdStrategy:
    """Tests for ThresholdStrategy."""

    def test_threshold_below_swap(self, basic_swap_matrix, holdings_vector, token_mapping):
        """Test when gain is below threshold."""
        strategy = ThresholdStrategy(threshold=100.0)
        token_index, index_token = token_mapping
        
        signal = strategy.evaluate(
            record_idx=0,
            swap_matrix=basic_swap_matrix,
            holdings_vector=holdings_vector,
            token_index=token_index,
            index_token=index_token
        )
        
        assert signal.signal_type == SignalType.HOLD
        assert not signal.threshold_hit

    def test_threshold_above_swap(self, basic_swap_matrix, holdings_vector, token_mapping):
        """Test when gain is above threshold."""
        strategy = ThresholdStrategy(threshold=10.0)
        token_index, index_token = token_mapping
        
        signal = strategy.evaluate(
            record_idx=0,
            swap_matrix=basic_swap_matrix,
            holdings_vector=holdings_vector,
            token_index=token_index,
            index_token=index_token
        )
        
        assert signal.signal_type == SignalType.SWAP
        assert signal.threshold_hit
        assert signal.from_token == "BTCUSDT"
        assert signal.to_token == "ETHUSDT"

    def test_threshold_cooldown(self, basic_swap_matrix, holdings_vector, token_mapping):
        """Test cooldown between swaps."""
        strategy = ThresholdStrategy(threshold=10.0, min_swap_interval=5)
        token_index, index_token = token_mapping
        
        # Record a previous swap to activate cooldown
        strategy.last_swap_record = 0
        
        # Should be in cooldown
        signal = strategy.evaluate(
            record_idx=1,
            swap_matrix=basic_swap_matrix,
            holdings_vector=holdings_vector,
            token_index=token_index,
            index_token=index_token
        )
        assert signal.signal_type == SignalType.SKIP
        
        # After cooldown period, should swap
        signal = strategy.evaluate(
            record_idx=10,
            swap_matrix=basic_swap_matrix,
            holdings_vector=holdings_vector,
            token_index=token_index,
            index_token=index_token
        )
        assert signal.signal_type == SignalType.SWAP

    def test_threshold_records_swap(self, basic_swap_matrix, holdings_vector, token_mapping):
        """Test that strategy records when swap happens."""
        strategy = ThresholdStrategy(threshold=10.0, min_swap_interval=5)
        token_index, index_token = token_mapping
        
        strategy.evaluate(
            record_idx=0,
            swap_matrix=basic_swap_matrix,
            holdings_vector=holdings_vector,
            token_index=token_index,
            index_token=index_token
        )
        
        strategy.on_swap_executed(0, "BTCUSDT", "ETHUSDT", 1.0, 50.0)
        
        # Next evaluation should be in cooldown
        signal = strategy.evaluate(
            record_idx=1,
            swap_matrix=basic_swap_matrix,
            holdings_vector=np.array([0.0, 50.0]),  # Now holding ETH
            token_index=token_index,
            index_token=index_token
        )
        assert signal.signal_type == SignalType.SKIP
        
        # After cooldown, should be able to swap
        signal = strategy.evaluate(
            record_idx=10,
            swap_matrix=basic_swap_matrix,
            holdings_vector=np.array([0.0, 50.0]),  # Still holding ETH
            token_index=token_index,
            index_token=index_token
        )
        # Should return SWAP or HOLD depending on gain
        assert signal.signal_type in [SignalType.SWAP, SignalType.HOLD]


class TestStrategyFactory:
    """Tests for strategy factory."""

    def test_create_threshold_strategy(self):
        """Test creating threshold strategy."""
        strategy = create_strategy("threshold", threshold=1.5, min_swap_interval=5)
        assert isinstance(strategy, ThresholdStrategy)
        assert strategy.threshold == 1.5
        assert strategy.min_swap_interval == 5

    def test_create_hold_strategy(self):
        """Test creating hold strategy."""
        strategy = create_strategy("hold")
        assert isinstance(strategy, HoldStrategy)

    def test_list_strategies(self):
        """Test listing available strategies."""
        strategies = list_available_strategies()
        assert "hold" in strategies
        assert "threshold" in strategies
        assert "momentum" in strategies

    def test_create_unknown_strategy_raises(self):
        """Test that creating unknown strategy raises error."""
        with pytest.raises(KeyError):
            create_strategy("unknown_strategy")


class TestSignal:
    """Tests for Signal class."""

    def test_signal_creation(self):
        """Test signal creation."""
        signal = Signal(
            signal_type=SignalType.SWAP,
            from_token="BTC",
            to_token="ETH",
            amount=1.0,
            expected_gain=50.0,
            threshold_hit=True
        )
        
        assert signal.signal_type == SignalType.SWAP
        assert signal.from_token == "BTC"
        assert signal.threshold_hit

    def test_should_execute(self):
        """Test should_execute logic."""
        signal = Signal(
            signal_type=SignalType.SWAP,
            threshold_hit=True,
            confidence=0.8
        )
        
        assert signal.should_execute(min_threshold=0.5)
        assert not signal.should_execute(min_threshold=0.9)

    def test_should_not_execute_on_hold(self):
        """Test that HOLD signals don't execute."""
        signal = Signal(signal_type=SignalType.HOLD)
        assert not signal.should_execute()

    def test_should_not_execute_when_threshold_not_hit(self):
        """Test that signals without threshold hit don't execute."""
        signal = Signal(
            signal_type=SignalType.SWAP,
            threshold_hit=False,
            confidence=1.0
        )
        assert not signal.should_execute()
