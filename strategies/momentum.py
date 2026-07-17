"""Momentum-based trading strategies."""

from typing import Any
import numpy as np
import numpy.typing as npt

from strategies.base import Strategy, Signal, SignalType


class MomentumStrategy(Strategy):
    """Swap based on momentum indicators.
    
    Considers both immediate gain and momentum of the target token.
    """
    
    name: str = "MomentumStrategy"

    def __init__(self, **params: Any) -> None:
        self.threshold: float = params.get("threshold", 1.0)
        self.momentum_window: int = params.get("momentum_window", 20)
        self.momentum_weight: float = params.get("momentum_weight", 0.3)
        self.min_swap_interval: int = params.get("min_swap_interval", 1)
        super().__init__(**params)

    def _setup(self) -> None:
        """Setup tracking state."""
        self.last_swap_record: int = -1
        self.price_history: dict[str, list[float]] = {}

    def _calculate_momentum(self, token: str) -> float:
        """Calculate momentum for a token based on recent price changes."""
        if token not in self.price_history or len(self.price_history[token]) < 2:
            return 0.0
        
        prices = self.price_history[token]
        if len(prices) < self.momentum_window:
            return 0.0
        
        recent = prices[-self.momentum_window:]
        older = prices[-2*self.momentum_window:-self.momentum_window] if len(prices) >= 2*self.momentum_window else prices[:self.momentum_window]
        
        if not older:
            return 0.0
        
        recent_avg = np.mean(recent)
        older_avg = np.mean(older)
        
        return (recent_avg - older_avg) / older_avg if older_avg > 0 else 0.0

    def evaluate(
        self,
        record_idx: int,
        swap_matrix: npt.NDArray[np.float64],
        holdings_vector: npt.NDArray[np.float64],
        token_index: dict[str, int],
        index_token: dict[int, str],
        current_prices: dict[str, float] = None  # Optional price update
    ) -> Signal:
        """Evaluate momentum strategy."""
        if record_idx - self.last_swap_record < self.min_swap_interval:
            return Signal(signal_type=SignalType.SKIP, confidence=0.0)

        # Update price history if provided
        if current_prices:
            for token, price in current_prices.items():
                if token not in self.price_history:
                    self.price_history[token] = []
                self.price_history[token].append(price)

        holding_idx = -1
        for i, h in enumerate(holdings_vector):
            if h > 0:
                holding_idx = i
                break
        
        if holding_idx < 0:
            return Signal(signal_type=SignalType.HOLD, confidence=0.0)

        gains = swap_matrix[holding_idx]
        from_token = index_token[holding_idx]
        
        # Score each potential target
        best_score = 0.0
        best_target_idx = -1
        best_gain = 0.0
        
        for j, gain in enumerate(gains):
            if j == holding_idx:
                continue
            
            to_token = index_token[j]
            
            # Calculate momentum score
            momentum = self._calculate_momentum(to_token)
            
            # Combined score: gain * (1 + momentum_weight * momentum)
            score = gain * (1 + self.momentum_weight * momentum)
            
            if score > best_score:
                best_score = score
                best_target_idx = j
                best_gain = gain
        
        if best_target_idx < 0:
            return Signal(signal_type=SignalType.HOLD, confidence=0.0)
        
        to_token = index_token[best_target_idx]
        threshold_hit = best_gain > self.threshold
        
        return Signal(
            signal_type=SignalType.SWAP if threshold_hit else SignalType.HOLD,
            action=f"{from_token} -> {to_token}",
            confidence=min(best_gain / 2.0, 1.0),
            from_token=from_token,
            to_token=to_token,
            amount=holdings_vector[holding_idx],
            expected_gain=best_gain,
            threshold_hit=threshold_hit,
            metadata={
                "momentum_score": float(best_score),
                "momentum": float(self._calculate_momentum(to_token))
            }
        )

    def on_swap_executed(
        self,
        record_idx: int,
        from_token: str,
        to_token: str,
        amount_in: float,
        amount_out: float
    ) -> None:
        """Record swap."""
        self.last_swap_record = record_idx


class RSIMomentumStrategy(Strategy):
    """Momentum strategy using RSI indicator."""
    
    name: str = "RSIMomentumStrategy"

    def __init__(self, **params: Any) -> None:
        self.threshold: float = params.get("threshold", 1.0)
        self.rsi_window: int = params.get("rsi_window", 14)
        self.rsi_oversold: float = params.get("rsi_oversold", 30)
        self.rsi_overbought: float = params.get("rsi_overbought", 70)
        self.min_swap_interval: int = params.get("min_swap_interval", 1)
        super().__init__(**params)

    def _setup(self) -> None:
        """Setup tracking state."""
        self.last_swap_record: int = -1
        self.price_history: dict[str, list[float]] = {}

    def _calculate_rsi(self, token: str) -> float:
        """Calculate RSI for a token."""
        if token not in self.price_history or len(self.price_history[token]) < self.rsi_window + 1:
            return 50.0  # Neutral
        
        prices = self.price_history[token][-(self.rsi_window + 1):]
        deltas = np.diff(prices)
        
        gains = deltas[deltas > 0]
        losses = -deltas[deltas < 0]
        
        avg_gain = np.mean(gains) if len(gains) > 0 else 0.0
        avg_loss = np.mean(losses) if len(losses) > 0 else 0.0
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def evaluate(
        self,
        record_idx: int,
        swap_matrix: npt.NDArray[np.float64],
        holdings_vector: npt.NDArray[np.float64],
        token_index: dict[str, int],
        index_token: dict[int, str],
        current_prices: dict[str, float] = None
    ) -> Signal:
        """Evaluate RSI momentum strategy."""
        if record_idx - self.last_swap_record < self.min_swap_interval:
            return Signal(signal_type=SignalType.SKIP, confidence=0.0)

        if current_prices:
            for token, price in current_prices.items():
                if token not in self.price_history:
                    self.price_history[token] = []
                self.price_history[token].append(price)

        holding_idx = -1
        for i, h in enumerate(holdings_vector):
            if h > 0:
                holding_idx = i
                break
        
        if holding_idx < 0:
            return Signal(signal_type=SignalType.HOLD, confidence=0.0)

        gains = swap_matrix[holding_idx]
        from_token = index_token[holding_idx]
        
        best_score = 0.0
        best_target_idx = -1
        best_gain = 0.0
        
        for j, gain in enumerate(gains):
            if j == holding_idx:
                continue
            
            to_token = index_token[j]
            rsi = self._calculate_rsi(to_token)
            
            # Prefer tokens in oversold territory (likely to bounce)
            rsi_score = 1.0 if rsi < self.rsi_oversold else (0.5 if rsi < self.rsi_overbought else 0.0)
            
            score = gain * (1 + rsi_score)
            
            if score > best_score:
                best_score = score
                best_target_idx = j
                best_gain = gain
        
        if best_target_idx < 0:
            return Signal(signal_type=SignalType.HOLD, confidence=0.0)
        
        to_token = index_token[best_target_idx]
        threshold_hit = best_gain > self.threshold
        
        return Signal(
            signal_type=SignalType.SWAP if threshold_hit else SignalType.HOLD,
            action=f"{from_token} -> {to_token}",
            confidence=min(best_gain / 2.0, 1.0),
            from_token=from_token,
            to_token=to_token,
            amount=holdings_vector[holding_idx],
            expected_gain=best_gain,
            threshold_hit=threshold_hit,
            metadata={"rsi": float(self._calculate_rsi(to_token))}
        )

    def on_swap_executed(
        self,
        record_idx: int,
        from_token: str,
        to_token: str,
        amount_in: float,
        amount_out: float
    ) -> None:
        """Record swap."""
        self.last_swap_record = record_idx
