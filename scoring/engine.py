"""Scoring engine for strategy evaluation and metrics."""

from dataclasses import dataclass, field
from typing import Any, Optional
import numpy as np


@dataclass
class ScoreResult:
    """Result of strategy scoring."""
    # Primary metrics
    final_token_count: float
    roi_percent: float
    
    # Risk metrics
    max_drawdown: float
    max_drawdown_percent: float
    
    # Trading metrics
    total_swaps: int
    win_rate: float
    avg_swap_gain: float
    swap_frequency: float  # swaps per 1000 records
    
    # Comparison metrics
    vs_hold_return: float
    opportunity_cost: float
    
    # Detailed metrics
    metrics: dict[str, Any] = field(default_factory=dict)
    
    def summary(self) -> dict[str, Any]:
        """Get summary dictionary."""
        return {
            "final_token_count": self.final_token_count,
            "roi_percent": self.roi_percent,
            "max_drawdown": self.max_drawdown,
            "max_drawdown_percent": self.max_drawdown_percent,
            "total_swaps": self.total_swaps,
            "win_rate": self.win_rate,
            "avg_swap_gain": self.avg_swap_gain,
            "vs_hold_return": self.vs_hold_return,
            "opportunity_cost": self.opportunity_cost,
        }


class ScoringEngine:
    """Evaluates strategy performance with comprehensive metrics.
    
    Computes all relevant metrics from backtest results.
    """

    def __init__(
        self,
        base_token: str = "BTCUSDT",
        initial_capital: float = 1.0
    ):
        """Initialize scoring engine.
        
        Args:
            base_token: Token to measure value against
            initial_capital: Starting capital
        """
        self.base_token = base_token
        self.initial_capital = initial_capital

    def score(
        self,
        backtest_result: dict[str, Any]
    ) -> ScoreResult:
        """Score a backtest result.
        
        Args:
            backtest_result: Dictionary containing:
                - final_holdings: {token: amount}
                - swap_history: [{from, to, amount_in, amount_out, ...}]
                - price_history: [{timestamp, prices: {token: price}}]
                - records: Number of records processed
        
        Returns:
            ScoreResult with all metrics
        """
        final_holdings = backtest_result.get("final_holdings", {})
        swap_history = backtest_result.get("swap_history", [])
        price_history = backtest_result.get("price_history", [])
        n_records = backtest_result.get("records", len(price_history))
        
        # Find final holding
        final_token = None
        final_amount = 0.0
        for token, amount in final_holdings.items():
            if amount > 0:
                final_token = token
                final_amount = amount
                break
        
        # Get final price
        if price_history and final_token:
            final_prices = price_history[-1].get("prices", {})
            final_price = final_prices.get(final_token, 1.0)
        else:
            final_price = 1.0
        
        # Calculate final value
        final_value = final_amount * final_price
        
        # Calculate ROI
        roi = (final_value - self.initial_capital) / self.initial_capital * 100
        
        # Calculate vs hold return
        vs_hold = self._calculate_vs_hold(
            price_history, swap_history, final_token, final_amount
        )
        
        # Calculate drawdown
        max_dd, max_dd_pct = self._calculate_drawdown(
            price_history, final_token
        )
        
        # Calculate trading metrics
        total_swaps = len(swap_history)
        win_rate = self._calculate_win_rate(swap_history)
        avg_swap_gain = self._calculate_avg_swap_gain(swap_history)
        swap_freq = (total_swaps / n_records * 1000) if n_records > 0 else 0
        
        # Calculate opportunity cost
        opp_cost = self._calculate_opportunity_cost(
            price_history, final_token, final_amount
        )
        
        return ScoreResult(
            final_token_count=final_amount,
            roi_percent=roi,
            max_drawdown=max_dd,
            max_drawdown_percent=max_dd_pct,
            total_swaps=total_swaps,
            win_rate=win_rate,
            avg_swap_gain=avg_swap_gain,
            swap_frequency=swap_freq,
            vs_hold_return=vs_hold,
            opportunity_cost=opp_cost,
            metrics={
                "final_token": final_token,
                "final_price": final_price,
                "final_value": final_value,
                "n_records": n_records,
            }
        )

    def _calculate_vs_hold(
        self,
        price_history: list,
        swap_history: list,
        final_token: str,
        final_amount: float
    ) -> float:
        """Calculate return vs simple hold strategy."""
        if not price_history:
            return 0.0
        
        # Get starting and ending prices for the starting token
        starting_token = swap_history[0]["from_token"] if swap_history else self.base_token
        start_price = price_history[0].get("prices", {}).get(starting_token, 1.0)
        end_price = price_history[-1].get("prices", {}).get(starting_token, 1.0)
        
        if start_price <= 0:
            return 0.0
        
        hold_return = (end_price - start_price) / start_price * 100
        
        # Get actual return
        current_price = price_history[-1].get("prices", {}).get(final_token, end_price)
        if current_price <= 0:
            return 0.0
        
        actual_return = (final_amount * current_price - self.initial_capital) / self.initial_capital * 100
        
        return actual_return - hold_return

    def _calculate_drawdown(
        self,
        price_history: list,
        current_token: str
    ) -> tuple[float, float]:
        """Calculate maximum drawdown."""
        if not price_history:
            return 0.0, 0.0
        
        peak = self.initial_capital
        max_dd = 0.0
        
        for snapshot in price_history:
            prices = snapshot.get("prices", {})
            if current_token in prices:
                # Estimate value at this point
                value = self.initial_capital * (prices.get(current_token, 1.0) / prices.get(current_token, 1.0))
                peak = max(peak, value)
                dd = peak - value
                max_dd = max(max_dd, dd)
        
        max_dd_pct = (max_dd / peak * 100) if peak > 0 else 0.0
        
        return max_dd, max_dd_pct

    def _calculate_win_rate(self, swap_history: list) -> float:
        """Calculate win rate (swaps that increased token count)."""
        if not swap_history:
            return 0.0
        
        wins = sum(1 for swap in swap_history if swap.get("amount_out", 0) > swap.get("amount_in", 0))
        return wins / len(swap_history) * 100

    def _calculate_avg_swap_gain(self, swap_history: list) -> float:
        """Calculate average swap gain percentage."""
        if not swap_history:
            return 0.0
        
        gains = []
        for swap in swap_history:
            amount_in = swap.get("amount_in", 0)
            amount_out = swap.get("amount_out", 0)
            if amount_in > 0:
                gain = (amount_out - amount_in) / amount_in * 100
                gains.append(gain)
        
        return np.mean(gains) if gains else 0.0

    def _calculate_opportunity_cost(
        self,
        price_history: list,
        current_token: str,
        current_amount: float
    ) -> float:
        """Calculate opportunity cost (missed gains from not holding best token)."""
        if not price_history:
            return 0.0
        
        # For each snapshot, calculate what we could have had in best token
        missed_gains = []
        
        for snapshot in price_history:
            prices = snapshot.get("prices", {})
            if not prices:
                continue
            
            # Find best potential (what we could have)
            best_potential = 0.0
            for token, price in prices.items():
                if price > 0:
                    potential = self.initial_capital / price
                    best_potential = max(best_potential, potential)
            
            # Calculate what we actually had
            if current_token in prices and prices[current_token] > 0:
                actual = self.initial_capital / prices.get(current_token, 1.0)
            else:
                actual = current_amount
            
            missed = best_potential - actual
            missed_gains.append(max(0, missed))
        
        return np.mean(missed_gains) if missed_gains else 0.0

    def compare_strategies(
        self,
        results: dict[str, ScoreResult]
    ) -> list[tuple[str, ScoreResult]]:
        """Compare multiple strategy results.
        
        Args:
            results: Dictionary of {strategy_name: ScoreResult}
        
        Returns:
            Sorted list of (name, result) by ROI
        """
        return sorted(
            results.items(),
            key=lambda x: x[1].roi_percent,
            reverse=True
        )

    def validate_out_of_sample(
        self,
        in_sample_result: ScoreResult,
        out_of_sample_result: ScoreResult
    ) -> dict[str, Any]:
        """Validate strategy robustness on out-of-sample data.
        
        Args:
            in_sample_result: In-sample backtest result
            out_of_sample_result: Out-of-sample backtest result
        
        Returns:
            Validation report
        """
        roi_diff = abs(in_sample_result.roi_percent - out_of_sample_result.roi_percent)
        roi_degradation = (in_sample_result.roi_percent - out_of_sample_result.roi_percent) / max(abs(in_sample_result.roi_percent), 0.001) * 100
        
        # Check for overfitting
        is_robust = roi_degradation < 50  # Less than 50% degradation
        
        return {
            "is_robust": is_robust,
            "in_sample_roi": in_sample_result.roi_percent,
            "out_of_sample_roi": out_of_sample_result.roi_percent,
            "roi_degradation_percent": roi_degradation,
            "validation_score": 100 - roi_degradation if is_robust else max(0, 50 - roi_degradation),
        }
