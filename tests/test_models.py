"""Tests for core data models."""

import pytest
import numpy as np
from datetime import datetime

from core.models import Token, PricePoint, MarketSnapshot, PriceMatrix, SwapMatrix


class TestToken:
    """Tests for Token dataclass."""

    def test_token_creation(self):
        """Test token creation with defaults."""
        token = Token("BTC")
        assert token.symbol == "BTCUSDT"
        assert token.decimals == 8

    def test_token_explicit_decimals(self):
        """Test token with explicit decimals."""
        token = Token("ETH", decimals=18)
        assert token.symbol == "ETHUSDT"
        assert token.decimals == 18

    def test_token_already_has_usdt(self):
        """Test token that already has USDT suffix."""
        token = Token("BTCUSDT")
        assert token.symbol == "BTCUSDT"


class TestPricePoint:
    """Tests for PricePoint."""

    def test_price_point_creation(self):
        """Test price point creation."""
        pp = PricePoint(
            timestamp=datetime.now(),
            token="BTCUSDT",
            bid=50000.0,
            ask=50001.0
        )
        assert pp.token == "BTCUSDT"
        assert pp.bid == 50000.0
        assert pp.ask == 50001.0

    def test_mid_price(self):
        """Test mid price calculation."""
        pp = PricePoint(
            timestamp=datetime.now(),
            token="BTCUSDT",
            bid=50000.0,
            ask=50002.0
        )
        assert pp.mid_price == 50001.0

    def test_spread(self):
        """Test spread calculation."""
        pp = PricePoint(
            timestamp=datetime.now(),
            token="BTCUSDT",
            bid=50000.0,
            ask=50002.0
        )
        assert pp.spread == 2.0

    def test_spread_bps(self):
        """Test spread in basis points."""
        pp = PricePoint(
            timestamp=datetime.now(),
            token="BTCUSDT",
            bid=50000.0,
            ask=50010.0
        )
        assert abs(pp.spread_bps - 2.0) < 0.01


class TestPriceMatrix:
    """Tests for PriceMatrix."""

    def test_matrix_creation(self):
        """Test matrix creation."""
        tokens = ["BTCUSDT", "ETHUSDT"]
        matrix = PriceMatrix.create(n_records=10, n_tokens=2, tokens=tokens)
        
        assert matrix.n_records == 10
        assert matrix.n_tokens == 2
        assert matrix.tokens == tokens
        assert "BTCUSDT" in matrix.token_index
        assert matrix.token_index["BTCUSDT"] == 0

    def test_set_prices(self):
        """Test setting prices in matrix."""
        tokens = ["BTCUSDT", "ETHUSDT"]
        matrix = PriceMatrix.create(n_records=10, n_tokens=2, tokens=tokens)
        
        matrix.set_prices(
            record_idx=0,
            timestamp=1000000,
            prices={"BTCUSDT": (50000.0, 50001.0), "ETHUSDT": (3000.0, 3001.0)}
        )
        
        assert matrix.get_bid(0, "BTCUSDT") == 50000.0
        assert matrix.get_ask(0, "BTCUSDT") == 50001.0
        assert matrix.get_bid(0, "ETHUSDT") == 3000.0

    def test_bid_vector(self):
        """Test getting bid vector."""
        tokens = ["BTCUSDT", "ETHUSDT"]
        matrix = PriceMatrix.create(n_records=10, n_tokens=2, tokens=tokens)
        
        matrix.set_prices(0, 1000, {"BTCUSDT": (50000.0, 50001.0), "ETHUSDT": (3000.0, 3001.0)})
        matrix.set_prices(1, 2000, {"BTCUSDT": (51000.0, 51001.0), "ETHUSDT": (3100.0, 3101.0)})
        
        bid_vec = matrix.get_bid_vector(0)
        assert bid_vec[0] == 50000.0
        assert bid_vec[1] == 3000.0


class TestSwapMatrix:
    """Tests for SwapMatrix computation."""

    def test_swap_matrix_computation(self):
        """Test swap matrix computation."""
        tokens = ["BTCUSDT", "ETHUSDT"]
        price_matrix = PriceMatrix.create(n_records=1, n_tokens=2, tokens=tokens)
        
        # Set prices: BTC=50, ETH=1 (BTC/ETH = 50)
        price_matrix.set_prices(0, 1000, {
            "BTCUSDT": (50000.0, 50001.0),
            "ETHUSDT": (1000.0, 1001.0)
        })
        
        swap_matrix = SwapMatrix.compute(price_matrix, 0)
        
        # BTC -> ETH: sell BTC at bid (50000), buy ETH at ask (1001)
        # With 0.04% fee per leg, fee_factor = 0.9996 * 0.9996 ≈ 0.9992
        expected_rate = (50000.0 / 1001.0) * 0.9992
        
        assert swap_matrix.matrix[0, 1] > 0
        assert swap_matrix.matrix[1, 0] > 0
        assert abs(swap_matrix.matrix[0, 1] - expected_rate) < 1.0

    def test_swap_matrix_self_swap_zero(self):
        """Test that self-swaps are zero."""
        tokens = ["BTCUSDT", "ETHUSDT"]
        price_matrix = PriceMatrix.create(n_records=1, n_tokens=2, tokens=tokens)
        price_matrix.set_prices(0, 1000, {"BTCUSDT": (50000.0, 50001.0), "ETHUSDT": (1000.0, 1001.0)})
        
        swap_matrix = SwapMatrix.compute(price_matrix, 0)
        
        assert swap_matrix.matrix[0, 0] == 0.0
        assert swap_matrix.matrix[1, 1] == 0.0

    def test_find_best_swap(self):
        """Test finding best swap."""
        tokens = ["BTCUSDT", "ETHUSDT"]
        price_matrix = PriceMatrix.create(n_records=1, n_tokens=2, tokens=tokens)
        price_matrix.set_prices(0, 1000, {
            "BTCUSDT": (50000.0, 50001.0),
            "ETHUSDT": (1000.0, 1001.0)
        })
        
        swap_matrix = SwapMatrix.compute(price_matrix, 0)
        
        # BTC is worth more ETH
        best_token, best_gain = swap_matrix.find_best_swap("BTCUSDT")
        assert best_token == "ETHUSDT"
        assert best_gain > 1.0
