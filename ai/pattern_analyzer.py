"""Pattern analyzer for finding winning strategy patterns."""

from dataclasses import dataclass
from typing import Any
import numpy as np
import logging


logger = logging.getLogger(__name__)


@dataclass
class Pattern:
    """Identified pattern in strategies."""
    name: str
    description: str
    parameters: dict[str, Any]
    correlation: float  # How strongly this pattern correlates with success
    frequency: float  # How often this pattern appears in top performers
    examples: list[dict]  # Example strategies with this pattern


class PatternAnalyzer:
    """Analyzes backtest results to find winning patterns."""

    def __init__(self):
        self.patterns: list[Pattern] = []
        self.history: list[dict] = []

    def analyze(
        self,
        results: list[dict],
        top_percent: float = 0.2
    ) -> list[Pattern]:
        """Analyze results and find patterns.
        
        Args:
            results: List of backtest results with params and scores
            top_percent: Percentage of top performers to analyze
        
        Returns:
            List of identified patterns
        """
        if not results:
            return []
        
        self.history.extend(results)
        
        # Sort by score
        sorted_results = sorted(results, key=lambda x: x.get("score", 0), reverse=True)
        
        # Get top performers
        n_top = max(1, int(len(sorted_results) * top_percent))
        top_results = sorted_results[:n_top]
        
        # Find patterns
        patterns = []
        
        # Pattern 1: Threshold ranges
        threshold_pattern = self._find_threshold_pattern(top_results, sorted_results)
        if threshold_pattern:
            patterns.append(threshold_pattern)
        
        # Pattern 2: Interval patterns
        interval_pattern = self._find_interval_pattern(top_results, sorted_results)
        if interval_pattern:
            patterns.append(interval_pattern)
        
        # Pattern 3: Parameter correlations
        correlation_patterns = self._find_correlations(results)
        patterns.extend(correlation_patterns)
        
        # Pattern 4: Winning combinations
        combo_pattern = self._find_combinations(top_results)
        if combo_pattern:
            patterns.append(combo_pattern)
        
        self.patterns = patterns
        return patterns

    def _find_threshold_pattern(
        self,
        top_results: list[dict],
        all_results: list[dict]
    ) -> Pattern | None:
        """Find optimal threshold range."""
        top_thresholds = []
        all_thresholds = []
        
        for r in top_results:
            params = r.get("params", {})
            if "threshold" in params:
                top_thresholds.append(params["threshold"])
        
        for r in all_results:
            params = r.get("params", {})
            if "threshold" in params:
                all_thresholds.append(params["threshold"])
        
        if not top_thresholds or not all_thresholds:
            return None
        
        top_avg = np.mean(top_thresholds)
        all_avg = np.mean(all_thresholds)
        
        # Calculate frequency
        freq = len(top_thresholds) / len(all_results)
        
        # Calculate correlation
        correlation = (top_avg - all_avg) / (all_avg + 1e-6)
        
        return Pattern(
            name="threshold_range",
            description=f"Optimal threshold range: {min(top_thresholds):.2f}-{max(top_thresholds):.2f}",
            parameters={
                "optimal_range": (min(top_thresholds), max(top_thresholds)),
                "average_in_top": top_avg,
                "average_all": all_avg
            },
            correlation=correlation,
            frequency=freq,
            examples=top_thresholds[:5]
        )

    def _find_interval_pattern(
        self,
        top_results: list[dict],
        all_results: list[dict]
    ) -> Pattern | None:
        """Find optimal swap interval."""
        top_intervals = []
        
        for r in top_results:
            params = r.get("params", {})
            if "min_swap_interval" in params:
                top_intervals.append(params["min_swap_interval"])
        
        if not top_intervals:
            return None
        
        freq = len(top_intervals) / len(all_results)
        
        return Pattern(
            name="swap_interval",
            description=f"Optimal swap interval: {np.median(top_intervals):.0f}",
            parameters={
                "optimal_interval": int(np.median(top_intervals)),
                "range": (min(top_intervals), max(top_intervals)),
                "mode": max(set(top_intervals), key=top_intervals.count)
            },
            correlation=0.1,  # Less predictive
            frequency=freq,
            examples=top_intervals[:5]
        )

    def _find_correlations(self, results: list[dict]) -> list[Pattern]:
        """Find parameter correlations with success."""
        patterns = []
        
        param_scores: dict[str, list[tuple]] = {}
        
        for r in results:
            params = r.get("params", {})
            score = r.get("score", 0)
            
            for key, value in params.items():
                if isinstance(value, (int, float)):
                    if key not in param_scores:
                        param_scores[key] = []
                    param_scores[key].append((value, score))
        
        for param_name, values_scores in param_scores.items():
            if len(values_scores) < 10:
                continue
            
            values = [v for v, s in values_scores]
            scores = [s for v, s in values_scores]
            
            # Calculate correlation
            correlation = np.corrcoef(values, scores)[0, 1]
            
            if abs(correlation) > 0.1:  # Threshold for relevance
                patterns.append(Pattern(
                    name=f"correlation_{param_name}",
                    description=f"{param_name} has {correlation:.2f} correlation with score",
                    parameters={
                        "correlation": correlation,
                        "mean_when_high": np.mean([s for v, s in values_scores if v > np.median(values)]),
                        "mean_when_low": np.mean([s for v, s in values_scores if v <= np.median(values)])
                    },
                    correlation=correlation,
                    frequency=1.0,
                    examples=[{"param": param_name, "values": values[:10]}]
                ))
        
        return patterns

    def _find_combinations(self, top_results: list[dict]) -> Pattern | None:
        """Find winning parameter combinations."""
        if len(top_results) < 3:
            return None
        
        # Get most common parameter ranges in top performers
        common_params = {}
        
        for r in top_results:
            params = r.get("params", {})
            for key, value in params.items():
                if isinstance(value, (int, float)):
                    bucket = self._bucket_value(value)
                    key_bucket = f"{key}_{bucket}"
                    common_params[key_bucket] = common_params.get(key_bucket, 0) + 1
        
        if not common_params:
            return None
        
        # Find most common combinations
        sorted_params = sorted(common_params.items(), key=lambda x: x[1], reverse=True)
        
        return Pattern(
            name="winning_combination",
            description=f"Most common parameters in top {len(top_results)} strategies",
            parameters={"top_combinations": sorted_params[:5]},
            correlation=0.0,
            frequency=len(top_results) / max(1, sum(common_params.values())),
            examples=top_results[:3]
        )

    def _bucket_value(self, value: float) -> str:
        """Bucket continuous values."""
        if value < 1.0:
            return "<1.0"
        elif value < 1.5:
            return "1.0-1.5"
        elif value < 2.0:
            return "1.5-2.0"
        elif value < 3.0:
            return "2.0-3.0"
        else:
            return ">3.0"

    def get_best_parameters(self) -> dict[str, Any]:
        """Get best parameters found so far."""
        if not self.history:
            return {}
        
        best = max(self.history, key=lambda x: x.get("score", 0))
        return best.get("params", {})

    def get_best_score(self) -> float:
        """Get best score achieved."""
        if not self.history:
            return 0.0
        return max(r.get("score", 0) for r in self.history)

    def get_convergence(self) -> float:
        """Calculate convergence (how much scores are improving)."""
        if len(self.history) < 10:
            return 0.0
        
        # Compare recent vs older scores
        recent = self.history[-100:]
        older = self.history[-200:-100] if len(self.history) >= 200 else self.history[:100]
        
        recent_avg = np.mean([r.get("score", 0) for r in recent])
        older_avg = np.mean([r.get("score", 0) for r in older])
        
        if older_avg == 0:
            return 0.0
        
        return (recent_avg - older_avg) / abs(older_avg)

    def get_summary(self) -> dict:
        """Get analysis summary."""
        return {
            "total_strategies": len(self.history),
            "patterns_found": len(self.patterns),
            "best_score": self.get_best_score(),
            "best_params": self.get_best_parameters(),
            "convergence": self.get_convergence(),
            "patterns": [
                {"name": p.name, "description": p.description, "correlation": p.correlation}
                for p in self.patterns
            ]
        }
