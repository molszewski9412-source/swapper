"""Tests for swap simulator."""

import pytest
import numpy as np

from config.settings import FeesConfig
from core.models import PriceMatrix
from core.simulator import SwapSimulator, SwapResult


@pytest.fixture
def price_matrix():
    """Create a test price matrix."""
    tokens = ["BTCUSDT", "ETHUSDT"]
    matrix = PriceMatrix.create(n_records=1, n_tokens=2, tokens=tokens)
    matrix.set_prices(0, 1000, {
        "BTCUSDT": (50000.0, 50001.0),
        "ETHUSDT": (1000.0, 1001.0)
    })
    return matrix


@pytest.fixture
def mock_cache(price_matrix):
    """Create a mock cache with price matrix."""
    from data.cache import DataCache
    cache = DataCache(price_matrix)
    return cache


@pytest.fixture
def simulator(mock_cache):
    """Create a swap simulator."""
    return SwapSimulator(mock_cache)


class TestSwapSimulator:
    """Tests for SwapSimulator."""

    def test_total_fee_rate(self, simulator):
        """Test total fee rate calculation."""
        # 0.04% per leg = 0.08% total
        assert abs(simulator.total_fee_rate - 0.0008) < 0.00001

    def test_fee_factor(self, simulator):
        """Test fee factor calculation."""
        expected = (1 - 0.0004) * (1 - 0.0004)
        assert abs(simulator.fee_factor - expected) < 0.00001

    def test_compute_swap_matrix_shape(self, simulator):
        """Test swap matrix has correct shape."""
        holdings = np.array([1.0, 0.0])  # 1 BTC
        swap_matrix = simulator.compute_swap_matrix(0, holdings)
        
        assert swap_matrix.shape == (2, 2)

    def test_compute_swap_matrix_values(self, simulator):
        """Test swap matrix values are reasonable."""
        holdings = np.array([1.0, 0.0])
        swap_matrix = simulator.compute_swap_matrix(0, holdings)
        
        # BTC -> ETH should give us ETH
        btc_to_eth = swap_matrix[0, 1]
        assert btc_to_eth > 40  # BTC is ~50x ETH, so ~50 ETH before fees

    def test_find_best_swap(self, simulator):
        """Test finding best swap."""
        holdings = {"BTCUSDT": 1.0}
        from_token, to_token, amount = simulator.find_best_swap(0, holdings, "BTCUSDT")
        
        assert from_token == "BTCUSDT"
        assert to_token == "ETHUSDT"
        assert amount > 40

    def test_execute_swap_success(self, simulator):
        """Test successful swap execution."""
        result = simulator.execute_swap(0, "BTCUSDT", "ETHUSDT", 1.0)
        
        assert result.success
        assert result.from_token == "BTCUSDT"
        assert result.to_token == "ETHUSDT"
        assert result.amount_in == 1.0
        assert result.amount_out > 40
        assert result.fee > 0

    def test_execute_swap_negative_amount(self, simulator):
        """Test swap with negative amount fails."""
        result = simulator.execute_swap(0, "BTCUSDT", "ETHUSDT", -1.0)
        
        assert not result.success
        assert "positive" in result.error.lower()

    def test_execute_swap_zero_amount(self, simulator):
        """Test swap with zero amount fails."""
        result = simulator.execute_swap(0, "BTCUSDT", "ETHUSDT", 0.0)
        
        assert not result.success

    def test_execute_swap_same_token(self, simulator):
        """Test swapping same token."""
        result = simulator.execute_swap(0, "BTCUSDT", "BTCUSDT", 1.0)
        
        # Should succeed but with no gain
        assert result.success
        # amount_out should be 0 since it's the same token (matrix[0,0] = 0)

    def test_net_gain(self, simulator):
        """Test net gain calculation."""
        result = simulator.execute_swap(0, "BTCUSDT", "ETHUSDT", 1.0)
        
        assert result.success
        assert result.net_gain() == result.amount_out

    def test_net_gain_percent(self, simulator):
        """Test net gain percentage."""
        result = simulator.execute_swap(0, "BTCUSDT", "ETHUSDT", 1.0)
        
        assert result.success
        gain_pct = result.net_gain_percent()
        assert gain_pct > 0  # Should be positive gain (ETH is cheaper)


class TestSwapResult:
    """Tests for SwapResult dataclass."""

    def test_successful_result(self):
        """Test successful swap result."""
        result = SwapResult(
            success=True,
            from_token="BTC",
            to_token="ETH",
            amount_in=1.0,
            amount_out=50.0,
            fee=0.04,
            price_in=50000.0,
            price_out=1000.0
        )
        
        assert result.success
        assert result.net_gain() == 50.0
        assert result.net_gain_percent() > 0

    def test_failed_result(self):
        """Test failed swap result."""
        result = SwapResult(
            success=False,
            from_token="BTC",
            to_token="ETH",
            amount_in=1.0,
            amount_out=0.0,
            fee=0.0,
            price_in=0.0,
            price_out=0.0,
            error="Invalid prices"
        )
        
        assert not result.success
        assert result.net_gain() == 0.0
        assert result.net_gain_percent() == 0.0
