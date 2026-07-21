#!/usr/bin/env python3
"""
Backtest Matrix Swap using market.csv data.
Find optimal threshold.
"""

import csv
import json
from dataclasses import dataclass
from typing import List, Dict, Tuple

FEE = 0.0004  # 0.04% per side
INITIAL_USDT = 1000.0


@dataclass
class BacktestResult:
    threshold: float
    total_swaps: int
    final_qty: float
    final_token: str
    final_baseline: float
    final_actual_eq: float
    overall_gain_pct: float
    swap_log: List[dict]
    equity_curve: List[dict]


def load_market_data(filepath: str = "market.csv", sample_rate: int = 10) -> Dict:
    """Load market data from CSV."""
    tokens = []
    prices = {}
    
    with open(filepath, 'r') as f:
        reader = csv.reader(f)
        header = next(reader)
        
        # Extract token names from BID columns
        for i, col in enumerate(header):
            if col.endswith('_BID'):
                t = col.replace('_BID', '')
                tokens.append(t)
                prices[t] = {'bid': [], 'ask': []}
        
        # Load prices
        for row in reader:
            for i, t in enumerate(tokens):
                bid_idx = 1 + i * 2
                ask_idx = bid_idx + 1
                if bid_idx < len(row) and ask_idx < len(row):
                    try:
                        prices[t]['bid'].append(float(row[bid_idx]))
                        prices[t]['ask'].append(float(row[ask_idx]))
                    except:
                        prices[t]['bid'].append(0)
                        prices[t]['ask'].append(0)
    
    # Trim to minimum length
    min_len = min(len(prices[t]['bid']) for t in tokens)
    for t in tokens:
        prices[t]['bid'] = prices[t]['bid'][:min_len]
        prices[t]['ask'] = prices[t]['ask'][:min_len]
    
    # Sample
    for t in tokens:
        prices[t]['bid'] = prices[t]['bid'][::sample_rate]
        prices[t]['ask'] = prices[t]['ask'][:min_len:sample_rate]
    
    n_records = len(prices[tokens[0]]['bid'])
    
    return {'tokens': tokens, 'prices': prices, 'n_records': n_records}


def run_backtest(
    data: Dict,
    threshold: float,
    start_idx: int = 10,
    end_idx: int = None
) -> BacktestResult:
    """
    Run backtest with given threshold.
    Always stay in a token (never USDT).
    """
    tokens = data['tokens']
    prices = data['prices']
    
    if end_idx is None:
        end_idx = data['n_records'] - 1
    
    n_records = end_idx - start_idx
    
    # Initialize
    initial_token = tokens[0]
    
    # Calculate baselines at start
    baselines = {}
    for t in tokens:
        if prices[t]['ask'][start_idx] > 0:
            baselines[t] = INITIAL_USDT / (prices[t]['ask'][start_idx] * (1 + FEE))
        else:
            baselines[t] = 0
    
    # Start with first token
    holding = initial_token
    qty = baselines[holding]
    top_eq = {t: baselines[t] for t in tokens}  # Start with baselines as tops
    
    swaps = []
    last_swap_idx = start_idx
    
    # For equity curve
    equity_curve = []
    
    for idx in range(start_idx, end_idx):
        # Calculate actual_eq for all tokens
        current_bid = prices[holding]['bid'][idx]
        if current_bid <= 0:
            continue
        
        usdt_value = qty * current_bid * (1 - FEE)
        
        best_candidate = None
        best_gain = threshold / 100.0  # Convert percentage to decimal
        
        for t in tokens:
            if t == holding:
                continue
            if prices[t]['ask'][idx] <= 0:
                continue
            
            # actual_eq if we swapped
            actual_eq = usdt_value / (prices[t]['ask'][idx] * (1 + FEE))
            
            # Gain vs top_eq
            prev_top = top_eq[t]
            if prev_top > 0:
                gain = (actual_eq - prev_top) / prev_top
            else:
                gain = 0
            
            if gain > best_gain:
                best_gain = gain
                best_candidate = (t, actual_eq, gain)
        
        # Execute swap if better candidate found
        if best_candidate and idx - last_swap_idx >= 1:  # Min 1 tick between swaps
            target, actual_eq, gain = best_candidate
            
            # Execute swap
            new_qty = actual_eq
            
            # Update top_eq for ALL tokens
            # Using BID with fee (realistic)
            target_bid = prices[target]['bid'][idx]
            if target_bid > 0:
                usdt_after_swap = new_qty * target_bid * (1 - FEE)
                
                for t in tokens:
                    if prices[t]['ask'][idx] > 0:
                        potential = usdt_after_swap / (prices[t]['ask'][idx] * (1 + FEE))
                        if potential > top_eq[t]:
                            top_eq[t] = potential
                
                # Set top_eq for target = new_qty (record for this token)
                top_eq[target] = new_qty
            
            swaps.append({
                'idx': idx,
                'from': holding,
                'to': target,
                'from_qty': qty,
                'to_qty': new_qty,
                'gain_pct': gain * 100
            })
            
            holding = target
            qty = new_qty
            last_swap_idx = idx
        
        # Record equity at intervals
        if (idx - start_idx) % 100 == 0:
            current_actual_eq = {}
            for t in tokens:
                if prices[t]['ask'][idx] > 0:
                    current_actual_eq[t] = usdt_value / (prices[t]['ask'][idx] * (1 + FEE))
            
            equity_curve.append({
                'idx': idx,
                'holding': holding,
                'qty': qty,
                'usdt_value': usdt_value
            })
    
    # Final values
    initial_token = tokens[0]
    initial_baseline = baselines[initial_token]
    
    # Calculate final value in terms of INITIAL TOKEN
    # (how many initial tokens could we buy if we converted everything at the end)
    final_prices = prices[initial_token]
    if final_prices['ask'][-1] > 0:
        # Convert our final holding to USDT, then buy initial token
        if holding != initial_token:
            final_usdt = qty * prices[holding]['bid'][-1] * (1 - FEE)
            final_initial_tokens = final_usdt / (final_prices['ask'][-1] * (1 + FEE))
        else:
            # We still hold initial token
            final_initial_tokens = qty
        
        # Overall gain = how many initial tokens we have now vs at start
        overall_gain_pct = ((final_initial_tokens - initial_baseline) / initial_baseline) * 100
    else:
        final_initial_tokens = qty
        overall_gain_pct = 0
    
    return BacktestResult(
        threshold=threshold,
        total_swaps=len(swaps),
        final_qty=qty,
        final_token=holding,
        final_baseline=initial_baseline,  # For INITIAL token
        final_actual_eq=final_initial_tokens,  # In terms of initial token
        overall_gain_pct=overall_gain_pct,
        swap_log=swaps,
        equity_curve=equity_curve
    )


def optimize_threshold(data: Dict, thresholds: List[float]) -> List[BacktestResult]:
    """Test multiple thresholds and return results."""
    results = []
    
    for thresh in thresholds:
        result = run_backtest(data, thresh)
        results.append(result)
        print(f"  Threshold {thresh:.4f}: {result.total_swaps} swaps, gain={result.overall_gain_pct:+.2f}%")
    
    return results


def main():
    print("=" * 70)
    print("MATRIX SWAP BACKTEST - Full Matrix Analysis")
    print("=" * 70)
    
    # Load data
    print("\n📊 Loading market data...")
    data = load_market_data("market.csv", sample_rate=10)  # More data points
    print(f"   Tokens: {len(data['tokens'])}")
    print(f"   Records: {data['n_records']}")
    
    # Extended threshold testing
    print("\n🔍 Testing thresholds...")
    thresholds = [0.1, 0.2, 0.3, 0.5, 0.7, 1.0, 1.5, 2.0, 2.5, 3.0, 5.0, 7.0, 10.0]
    
    all_results = {}
    
    for thresh in thresholds:
        result = run_backtest(data, thresh)
        all_results[thresh] = result
        print(f"  Threshold {thresh:.1f}%: {result.total_swaps} swaps, gain={result.overall_gain_pct:+.2f}%")
    
    # Find best threshold by average gain across all tokens
    print("\n" + "=" * 70)
    print("FULL MATRIX RESULTS BY THRESHOLD")
    print("=" * 70)
    
    for thresh in thresholds:
        r = all_results[thresh]
        print(f"\n🎯 THRESHOLD: {thresh:.1f}% | Swaps: {r.total_swaps} | Overall Gain: {r.overall_gain_pct:+.2f}%")
        print("-" * 70)
        
        # Calculate final values for each token
        tokens = data['tokens']
        baselines = {}
        final_values = {}
        
        # Get baselines at start
        for t in tokens:
            if data['prices'][t]['ask'][0] > 0:
                baselines[t] = INITIAL_USDT / (data['prices'][t]['ask'][0] * (1 + FEE))
            else:
                baselines[t] = 0
        
        # Calculate final value in terms of each token
        for t in tokens:
            if baselines[t] > 0 and data['prices'][t]['bid'][-1] > 0:
                # If we ended in this token, how many would we have?
                # Convert final USDT to this token
                if r.final_token == t:
                    final_values[t] = r.final_actual_eq * (data['prices'][r.final_token]['bid'][-1] / data['prices'][t]['ask'][-1]) if r.final_token != t else r.final_actual_eq
                else:
                    # We hold r.final_token, convert to t
                    final_usdt = r.final_qty * data['prices'][r.final_token]['bid'][-1] * (1 - FEE)
                    final_values[t] = final_usdt / (data['prices'][t]['ask'][-1] * (1 + FEE))
            else:
                final_values[t] = 0
        
        # Print matrix
        print(f"{'Token':<12} {'Baseline':>15} {'Final (in token)':>18} {'Gain %':>10}")
        print("-" * 70)
        
        for t in tokens:
            base = baselines[t]
            final = final_values.get(t, 0)
            gain = ((final - base) / base * 100) if base > 0 else 0
            marker = " ◄" if t == r.final_token else ""
            print(f"{t.replace('USDT',''):<12} {base:>15.4f} {final:>18.4f} {gain:>+10.2f}%{marker}")
    
    # Find optimal threshold
    print("\n" + "=" * 70)
    print("THRESHOLD RANKING (by average gain across all tokens)")
    print("=" * 70)
    
    threshold_scores = []
    for thresh in thresholds:
        r = all_results[thresh]
        # Score = overall gain (final in terms of initial token)
        threshold_scores.append((thresh, r.total_swaps, r.overall_gain_pct))
    
    # Sort by overall gain
    threshold_scores.sort(key=lambda x: x[2], reverse=True)
    
    print(f"\n{'Rank':<6} {'Threshold':<12} {'Swaps':<10} {'Gain %':<12} {'Assessment'}")
    print("-" * 70)
    
    for i, (thresh, swaps, gain) in enumerate(threshold_scores):
        if gain > 100:
            assessment = "🔥 EXCELLENT"
        elif gain > 50:
            assessment = "✅ GOOD"
        elif gain > 0:
            assessment = "⚠️ MODERATE"
        else:
            assessment = "❌ POOR"
        print(f"{i+1:<6} {thresh:<12.1f}% {swaps:<10} {gain:>+10.2f}% {assessment}")
    
    # Best threshold
    best_thresh = threshold_scores[0][0]
    best_result = all_results[best_thresh]
    
    print("\n" + "=" * 70)
    print(f"🏆 RECOMMENDED THRESHOLD: {best_thresh:.1f}%")
    print("=" * 70)
    print(f"   Swaps: {best_result.total_swaps}")
    print(f"   Overall Gain: {best_result.overall_gain_pct:+.2f}%")
    
    # Buy & Hold comparison
    initial_token = data['tokens'][0]
    initial_price = data['prices'][initial_token]['ask'][0]
    final_price = data['prices'][initial_token]['bid'][-1]
    buy_hold_gain = ((final_price - initial_price) / initial_price) * 100
    
    print(f"\n   Buy & Hold {initial_token}: {buy_hold_gain:+.2f}%")
    print(f"   Matrix Swap Advantage: {best_result.overall_gain_pct - buy_hold_gain:+.2f}%")
    
    # Save results
    output = {
        'tokens': data['tokens'],
        'thresholds_tested': thresholds,
        'best_threshold': best_thresh,
        'threshold_rankings': [
            {'threshold': t, 'swaps': all_results[t].total_swaps, 'gain': all_results[t].overall_gain_pct}
            for t in thresholds
        ],
        'buy_hold_gain': buy_hold_gain,
        'all_results': {
            str(t): {
                'swaps': all_results[t].total_swaps,
                'final_token': all_results[t].final_token,
                'gain': all_results[t].overall_gain_pct
            }
            for t in thresholds
        }
    }
    
    with open('matrix_swap/backtest_results.json', 'w') as f:
        json.dump(output, f, indent=2)
    
    print("\n✅ Results saved to matrix_swap/backtest_results.json")


if __name__ == '__main__':
    main()
