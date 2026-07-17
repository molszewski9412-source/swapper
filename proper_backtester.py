#!/usr/bin/env python3
"""
Proper Backtester with Baseline, Top Equivalents, and Swap History

The user wants:
1. Baseline: Fixed initial amounts for all tokens (calculated from 1 BTC at first timestamp)
2. Top Equivalents: Best value each token reached (locked at swaps)
3. Actual Equivalents: Dynamic current values of all tokens
4. Swap History: Records of swaps with their top equivalents

Logic:
- Start: 1 BTC
- Calculate baseline for ALL 20 tokens as if we swapped: BTC -> USDT -> Token (with 0.04% fee each leg)
- Track top equivalents - these get "locked" when we do a swap
- After N swaps, the next swap won't beat top even if top < actual
- This ensures we don't chase after we've already captured the best
"""

import csv
from dataclasses import dataclass, field
from typing import Optional
import json


# Constants
SWAP_FEE = 0.0004  # 0.04% per leg
TOTAL_FEE = (1 - SWAP_FEE) ** 2  # Round trip fee


@dataclass
class TokenState:
    """State of a single token."""
    symbol: str
    baseline_amount: float = 0.0  # Fixed - what we could have had at start
    baseline_value: float = 0.0   # Fixed - USDT value at baseline
    top_amount: float = 0.0       # Best amount reached (locked at swaps)
    top_value: float = 0.0        # Best USDT value (locked at swaps)
    actual_amount: float = 0.0     # Current dynamic amount
    actual_value: float = 0.0      # Current dynamic USDT value
    top_recorded_at: int = -1      # Timestamp when top was recorded
    is_held: bool = False          # Are we holding this token?


@dataclass
class SwapRecord:
    """Record of a swap operation."""
    timestamp: int
    record_idx: int
    from_token: str
    to_token: str
    amount_in: float
    amount_out: float
    price_in: float  # Price when selling from_token
    price_out: float  # Price when buying to_token
    from_top_at_swap: float  # Top equivalent of from_token at swap time
    to_top_at_swap: float    # Top equivalent of to_token at swap time
    net_gain: float = 0.0


@dataclass
class PortfolioState:
    """Current state of the portfolio."""
    tokens: dict[str, TokenState] = field(default_factory=dict)
    holding_token: Optional[str] = None
    holding_amount: float = 0.0
    total_usdt_value: float = 0.0
    swaps: list[SwapRecord] = field(default_factory=list)
    
    def get_baseline_total(self) -> float:
        """Total baseline value in USDT."""
        return sum(t.baseline_value for t in self.tokens.values())
    
    def get_top_total(self) -> float:
        """Total of all top values."""
        return sum(t.top_value for t in self.tokens.values())
    
    def get_actual_total(self) -> float:
        """Total actual value in USDT."""
        return sum(t.actual_value for t in self.tokens.values())


class ProperBacktester:
    """
    Backtester with proper baseline, top equivalents, and swap tracking.
    
    Key concepts:
    - Baseline (fixed): What we could have had of each token at start
    - Top (locked): Best value reached, locked at swaps
    - Actual (dynamic): Current value at any moment
    """
    
    def __init__(self, data_path: str = "market.csv", use_mid_prices: bool = True, 
                 lookback_period: int = 100, momentum_threshold: float = 0.02):
        self.data_path = data_path
        self.use_mid_prices = use_mid_prices
        self.lookback_period = lookback_period  # Period for momentum calculation
        self.momentum_threshold = momentum_threshold  # Min momentum to consider swap
        self.tokens = []
        self.prices = {}  # token -> list of (bid, ask)
        self.mid_prices = {}  # token -> list of mid prices
        self.momentum = {}  # token -> list of momentum values
        self.portfolio = PortfolioState()
        
    def load_data(self) -> None:
        """Load market data from CSV."""
        print("Loading market data...")
        
        token_cols = {}
        
        with open(self.data_path, 'r') as f:
            reader = csv.reader(f)
            header = next(reader)
            
            # Parse header
            for i, col in enumerate(header):
                if col.endswith("_BID"):
                    token = col.replace("_BID", "")
                    self.tokens.append(token)
                    token_cols[token] = i
                    self.prices[token] = []
            
            # Load all prices
            for row_idx, row in enumerate(reader):
                try:
                    for token, idx in token_cols.items():
                        bid_str = row[idx].strip()
                        ask_str = row[idx + 1].strip()
                        
                        if not bid_str or not ask_str:
                            continue
                            
                        bid = float(bid_str)
                        ask = float(ask_str)
                        self.prices[token].append((bid, ask))
                except (ValueError, IndexError) as e:
                    # Skip malformed rows
                    continue
        
        # Calculate mid prices and momentum for each token
        print("Calculating momentum indicators...")
        for token in self.tokens:
            bids = [p[0] for p in self.prices[token]]
            asks = [p[1] for p in self.prices[token]]
            mids = [(b + a) / 2 for b, a in zip(bids, asks)]
            self.mid_prices[token] = mids
            
            # Calculate momentum: % change over lookback_period
            momentums = []
            for i in range(len(mids)):
                if i < self.lookback_period:
                    momentums.append(0.0)
                else:
                    mom = (mids[i] - mids[i - self.lookback_period]) / mids[i - self.lookback_period]
                    momentums.append(mom)
            self.momentum[token] = momentums
        
        print(f"Loaded {len(self.prices[self.tokens[0]])} records for {len(self.tokens)} tokens")
        
    def initialize_portfolio(self, start_token: str = "BTCUSDT", start_amount: float = 1.0):
        """
        Initialize portfolio with baseline calculation.
        
        For each token, calculate what we could have had at start:
        1 BTC -> USDT (sell BTC at bid, 0.04% fee) -> Token (buy at ask, 0.04% fee)
        """
        print(f"\nInitializing portfolio: {start_amount} {start_token}")
        
        # Get starting price of start_token
        start_bid = self.prices[start_token][0][0]  # Bid price
        start_ask = self.prices[start_token][0][1]  # Ask price
        
        # Convert to USDT (sell at bid)
        usdt_after_fee = start_amount * start_bid * (1 - SWAP_FEE)
        
        # Initialize all tokens
        for token in self.tokens:
            ask_price = self.prices[token][0][1]  # Ask price at start
            
            # Calculate baseline amount (how much we could have bought)
            baseline_amount = usdt_after_fee / ask_price
            
            # Calculate baseline USDT value (what this is worth now)
            bid_price = self.prices[token][0][0]  # Current bid for valuation
            baseline_value = baseline_amount * bid_price
            
            # Initialize token state
            self.portfolio.tokens[token] = TokenState(
                symbol=token,
                baseline_amount=baseline_amount,
                baseline_value=baseline_value,
                top_amount=baseline_amount,
                top_value=baseline_value,
                actual_amount=baseline_amount,
                actual_value=baseline_value,
                top_recorded_at=0,
                is_held=(token == start_token)
            )
        
        # Set current holding
        self.portfolio.holding_token = start_token
        self.portfolio.holding_amount = start_amount
        
        # Calculate totals
        self.portfolio.total_usdt_value = self._calculate_total_value()
        
        print(f"Baseline total USDT value: ${self.portfolio.get_baseline_total():,.2f}")
        print("\nBaseline Matrix (what we could have had of each token):")
        self._print_baseline_matrix()
        
    def _calculate_total_value(self) -> float:
        """Calculate total USDT value of current holding."""
        if not self.portfolio.holding_token:
            return 0.0
        
        holding = self.portfolio.tokens[self.portfolio.holding_token]
        # Use bid price for valuation
        bid = self.prices[self.portfolio.holding_token][0][0]
        return self.portfolio.holding_amount * bid
    
    def _update_actual_values(self, record_idx: int) -> None:
        """Update actual values for all tokens at current price."""
        for token in self.tokens:
            ts = self.portfolio.tokens[token]
            
            if token == self.portfolio.holding_token:
                # We hold this token
                ts.actual_amount = self.portfolio.holding_amount
                bid = self.prices[token][record_idx][0]
                ts.actual_value = self.portfolio.holding_amount * bid
            else:
                # Calculate what we would have if we had this token
                # Convert from holding -> USDT -> this token
                holding_bid = self.prices[self.portfolio.holding_token][record_idx][0]
                usdt_value = self.portfolio.holding_amount * holding_bid * (1 - SWAP_FEE)
                
                token_ask = self.prices[token][record_idx][1]
                ts.actual_amount = usdt_value / token_ask
                
                # Value if we sold now
                token_bid = self.prices[token][record_idx][0]
                ts.actual_value = ts.actual_amount * token_bid
                
    def _update_tops_if_needed(self, record_idx: int) -> None:
        """Update top equivalents if actual beats top."""
        for token in self.tokens:
            ts = self.portfolio.tokens[token]
            
            if ts.actual_value > ts.top_value:
                ts.top_amount = ts.actual_amount
                ts.top_value = ts.actual_value
                ts.top_recorded_at = record_idx
                
    def _get_price(self, token: str, idx: int) -> tuple[float, float]:
        """Get price for token at index (bid, ask). Uses mid if configured."""
        bid, ask = self.prices[token][idx]
        if self.use_mid_prices:
            mid = (bid + ask) / 2
            return mid, mid
        return bid, ask

    def _find_best_swap_candidate(self, current_idx: int) -> tuple[Optional[str], Optional[str], float]:
        """
        Find the best token to swap to based on momentum.
        
        Returns: (from_token, to_token, momentum_score)
        """
        if not self.portfolio.holding_token:
            return None, None, 0.0
        
        holding_token = self.portfolio.holding_token
        
        # Get momentum of current holding
        holding_momentum = self.momentum[holding_token][current_idx]
        
        best_candidate = None
        best_relative_momentum = float('-inf')
        
        for token in self.tokens:
            if token == holding_token:
                continue
            
            # Get momentum of this token
            token_momentum = self.momentum[token][current_idx]
            
            # Calculate relative momentum (token momentum - holding momentum)
            # This shows which is gaining faster
            relative_momentum = token_momentum - holding_momentum
            
            # Only consider if above threshold and positive
            if relative_momentum > best_relative_momentum and relative_momentum > self.momentum_threshold:
                best_relative_momentum = relative_momentum
                best_candidate = token
        
        return holding_token, best_candidate, best_relative_momentum
    
    def execute_swap(self, to_token: str, record_idx: int) -> SwapRecord:
        """Execute a swap from holding_token to to_token."""
        from_token = self.portfolio.holding_token
        
        # Get mid prices
        holding_bid, _ = self._get_price(from_token, record_idx)
        _, token_ask = self._get_price(to_token, record_idx)
        
        # Calculate swap with fees
        usdt_value = self.portfolio.holding_amount * holding_bid
        after_fees = usdt_value * (1 - SWAP_FEE)
        amount_out = after_fees / token_ask
        
        # Record the swap
        swap = SwapRecord(
            timestamp=record_idx,
            record_idx=record_idx,
            from_token=from_token,
            to_token=to_token,
            amount_in=self.portfolio.holding_amount,
            amount_out=amount_out,
            price_in=holding_bid,
            price_out=token_ask,
            from_top_at_swap=self.portfolio.tokens[from_token].top_value,
            to_top_at_swap=self.portfolio.tokens[to_token].top_value,
            net_gain=0.0
        )
        
        # Update portfolio
        self.portfolio.holding_token = to_token
        self.portfolio.holding_amount = amount_out
        
        self.portfolio.swaps.append(swap)
        
        return swap
    
    def run_backtest(self, strategy_threshold: float = 0.01) -> dict:
        """
        Run backtest with the given strategy.
        
        Strategy: Swap if expected gain > threshold
        """
        print(f"\n{'='*60}")
        print(f"Running backtest (threshold: {strategy_threshold*100:.2f}%)")
        print(f"{'='*60}")
        
        n_records = len(self.prices[self.tokens[0]])
        
        # Re-initialize for fresh run
        self.portfolio = PortfolioState()
        self.initialize_portfolio()
        
        # Track progress
        swaps_count = 0
        
        for idx in range(n_records):
            # Update actual values
            self._update_actual_values(idx)
            
            # Update tops if needed
            self._update_tops_if_needed(idx)
            
            # Check for swap opportunity
            from_token, to_token, expected_gain = self._find_best_swap_candidate(idx)
            
            if to_token and expected_gain > strategy_threshold:
                # Execute swap
                swap = self.execute_swap(to_token, idx)
                swaps_count += 1
                
                print(f"  Swap #{swaps_count} at record {idx}: "
                      f"{from_token} -> {to_token} "
                      f"(gain: {expected_gain*100:.4f}%)")
                
                # Print current state
                print(f"    Now holding: {self.portfolio.holding_amount:.6f} {self.portfolio.holding_token}")
        
        # Final results
        return self._generate_results()
    
    def _generate_results(self) -> dict:
        """Generate final results."""
        final_token = self.portfolio.holding_token
        final_amount = self.portfolio.holding_amount
        
        # Get final price
        final_bid = self.prices[final_token][-1][0]
        final_value = final_amount * final_bid
        
        # Baseline comparison
        btc_baseline = self.portfolio.tokens["BTCUSDT"]
        btc_final = 1.0 * self.prices["BTCUSDT"][-1][0]
        
        results = {
            "initial_token": "BTCUSDT",
            "initial_amount": 1.0,
            "initial_usdt_value": btc_baseline.baseline_value,
            "final_token": final_token,
            "final_amount": final_amount,
            "final_usdt_value": final_value,
            "total_gain_pct": ((final_value / btc_baseline.baseline_value) - 1) * 100,
            "total_swaps": len(self.portfolio.swaps),
            "swap_history": [
                {
                    "idx": s.record_idx,
                    "from": s.from_token,
                    "to": s.to_token,
                    "amount_in": s.amount_in,
                    "amount_out": s.amount_out
                }
                for s in self.portfolio.swaps
            ],
            "baseline_matrix": [
                {
                    "token": token,
                    "baseline_amount": ts.baseline_amount,
                    "baseline_value": ts.baseline_value,
                    "baseline_gain_pct": ((ts.baseline_value / self.portfolio.tokens["BTCUSDT"].baseline_value) - 1) * 100
                }
                for token, ts in self.portfolio.tokens.items()
            ],
            "top_matrix": [
                {
                    "token": token,
                    "top_amount": ts.top_amount,
                    "top_value": ts.top_value,
                    "top_recorded_at": ts.top_recorded_at
                }
                for token, ts in self.portfolio.tokens.items()
            ]
        }
        
        return results
    
    def _print_baseline_matrix(self) -> None:
        """Print baseline matrix."""
        print(f"\n{'Token':<12} {'Baseline Amt':>15} {'Baseline Value':>15} {'Gain %':>10}")
        print("-" * 55)
        
        sorted_tokens = sorted(
            self.portfolio.tokens.items(),
            key=lambda x: x[1].baseline_value,
            reverse=True
        )
        
        btc_value = self.portfolio.tokens["BTCUSDT"].baseline_value
        
        for token, ts in sorted_tokens:
            gain = ((ts.baseline_value / btc_value) - 1) * 100
            print(f"{token:<12} {ts.baseline_amount:>15.6f} ${ts.baseline_value:>14,.2f} {gain:>+9.2f}%")


def main():
    """Run the backtester."""
    backtester = ProperBacktester("market.csv")
    backtester.load_data()
    
    # Run with different thresholds
    for threshold in [0.001, 0.005, 0.01, 0.02]:
        results = backtester.run_backtest(strategy_threshold=threshold)
        
        print(f"\n{'='*60}")
        print("RESULTS")
        print(f"{'='*60}")
        print(f"Strategy threshold: {threshold*100:.2f}%")
        print(f"Total swaps: {results['total_swaps']}")
        print(f"Final: {results['final_amount']:.6f} {results['final_token']}")
        print(f"Final value: ${results['final_usdt_value']:,.2f}")
        print(f"Total gain: {results['total_gain_pct']:+.2f}%")
        
        # Save to JSON
        with open(f"results_threshold_{int(threshold*1000)}.json", "w") as f:
            json.dump(results, f, indent=2)
        
        print(f"\nResults saved to results_threshold_{int(threshold*1000)}.json")


if __name__ == "__main__":
    main()
