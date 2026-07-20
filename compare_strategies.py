#!/usr/bin/env python3
"""
Compare swap strategies:
A) Najgorszy token (traci najmniej)
B) Bliżej środka (np. median)
C) Top-3 (najlepsi)

Key metric: VS_BASELINE (buy & hold first token)
"""

import csv
import json
from dataclasses import dataclass
from typing import List, Tuple

FEE = 0.9996 * 0.9996  # ~0.08% total


@dataclass
class DataLoader:
    tokens: List[str]
    prices: dict
    n_records: int


def load_data(filepath="market.csv") -> DataLoader:
    tokens = []
    prices = {}
    
    with open(filepath, 'r') as f:
        reader = csv.reader(f)
        header = next(reader)
        
        for i, col in enumerate(header):
            if col.endswith('_BID'):
                t = col.replace('_BID', '')
                tokens.append(t)
                prices[t] = []
        
        for row in reader:
            for i, t in enumerate(tokens):
                idx = 1 + i * 2
                if idx < len(row):
                    try:
                        prices[t].append(float(row[idx]))
                    except:
                        pass
    
    min_len = min(len(prices[t]) for t in tokens)
    for t in tokens:
        prices[t] = prices[t][:min_len]
    
    return DataLoader(tokens=tokens, prices=prices, n_records=min_len)


def momentum(prices: dict, token: str, idx: int, period: int) -> float:
    if idx < period:
        return 0.0
    return (prices[token][idx] - prices[token][idx - period]) / prices[token][idx - period]


def run_strategy_fast(
    data: DataLoader,
    strategy: str,
    lookback: int = 5,
    threshold: float = 0.0,
    interval: int = 10,
    start_idx: int = 100,
    end_idx: int = None
) -> dict:
    """Fast version with subsampling inside."""
    if end_idx is None:
        end_idx = data.n_records - 1
    
    n_tokens = len(data.tokens)
    prices = data.prices
    
    # Initialize
    holding_idx = 0
    holding = data.tokens[0]
    amount = 1.0
    last_swap = 0
    swaps = 0
    
    # Top tracking (per Google Apps Script logic)
    top = [0.0] * n_tokens
    
    results = []
    
    # Pre-calc tops at start
    for i, t in enumerate(data.tokens):
        top[i] = amount * prices[t][start_idx] / prices[t][start_idx]
    
    for idx in range(start_idx, end_idx):
        if idx - last_swap < interval:
            continue
        
        # Current USD value
        current_usd = amount * prices[holding][idx]
        
        # Calculate momentum for all tokens
        moments = []
        for i, t in enumerate(data.tokens):
            m = momentum(prices, t, idx, lookback)
            moments.append((i, t, m))
        
        # Skip if holding has negative momentum
        holding_momentum = moments[holding_idx][2]
        if holding_momentum < 0:
            # Find candidates (lower momentum than current = losing less or gaining more)
            candidates = [(i, t, m) for i, t, m in moments if i != holding_idx and m < holding_momentum]
            
            if not candidates:
                continue
            
            # Select target based on strategy
            if strategy == 'worst':
                # Token with LOWEST momentum (losing the most)
                target_idx, target, _ = min(candidates, key=lambda x: x[2])
            elif strategy == 'lose_least':
                # Token with HIGHEST momentum among those still losing
                target_idx, target, _ = max(candidates, key=lambda x: x[2])
            elif strategy == 'median':
                # Middle of the pack
                candidates.sort(key=lambda x: x[2])
                target_idx, target, _ = candidates[len(candidates) // 2]
            elif strategy == 'top3':
                # Best momentum (closest to 0 or positive)
                candidates.sort(key=lambda x: x[2], reverse=True)
                target_idx, target, _ = candidates[0]
            elif strategy == 'top_half':
                # Upper half
                candidates.sort(key=lambda x: x[2], reverse=True)
                mid = len(candidates) // 2
                target_idx, target, _ = candidates[mid]
            else:
                continue
            
            # Calculate equivalent
            new_eq = current_usd / prices[target][idx]
            
            # Gain vs top
            prev_top = top[target_idx]
            gain = (new_eq - prev_top) / prev_top if prev_top > 0 else 1.0
            
            # Execute if gain > threshold
            if gain > threshold:
                swaps += 1
                last_swap = idx
                
                # Update tops
                new_value = new_eq * prices[target][idx]
                for i, t in enumerate(data.tokens):
                    eq = new_value / prices[t][idx]
                    if eq > top[i]:
                        top[i] = eq
                
                results.append({
                    'idx': idx,
                    'from': holding,
                    'to': target,
                    'gain': gain * 100
                })
                
                amount = new_eq
                holding = target
                holding_idx = target_idx
    
    # Final values
    final_value = amount * prices[holding][end_idx]
    
    # Baseline: buy & hold first token
    baseline_start = prices[data.tokens[0]][start_idx]
    baseline_end = prices[data.tokens[0]][end_idx]
    baseline_value = baseline_start / baseline_end
    
    return {
        'strategy': strategy,
        'lookback': lookback,
        'threshold': threshold,
        'interval': interval,
        'final_value': final_value,
        'baseline': baseline_value,
        'roi': (final_value - 1.0) * 100,
        'vs_baseline': (final_value / baseline_value - 1) * 100,
        'total_swaps': swaps,
        'log': results
    }


def run_walk_forward(
    data: DataLoader,
    strategy: str,
    lookback: int = 5,
    threshold: float = 0.0,
    interval: int = 10,
    n_periods: int = 4
) -> dict:
    """Run walk-forward validation."""
    total_len = data.n_records - 100
    period_len = total_len // n_periods
    
    periods = []
    for i in range(n_periods):
        start = 100 + i * period_len
        end = start + period_len if i < n_periods - 1 else data.n_records - 1
        
        result = run_strategy_fast(data, strategy, lookback, threshold, interval, start, end)
        periods.append({
            'period': f'P{i+1}',
            'start': start,
            'end': end,
            'roi': result['roi'],
            'vs_baseline': result['vs_baseline'],
            'swaps': result['total_swaps']
        })
    
    return {
        'strategy': strategy,
        'lookback': lookback,
        'threshold': threshold,
        'interval': interval,
        'periods': periods,
        'avg_roi': sum(p['roi'] for p in periods) / len(periods),
        'avg_vs_baseline': sum(p['vs_baseline'] for p in periods) / len(periods),
        'min_roi': min(p['roi'] for p in periods),
        'min_vs_baseline': min(p['vs_baseline'] for p in periods),
        'max_roi': max(p['roi'] for p in periods),
        'all_positive': all(p['roi'] > 0 for p in periods),
        'beats_baseline': sum(1 for p in periods if p['vs_baseline'] > 0)
    }


def main():
    print("📊 Loading data...")
    data = load_data()
    print(f"   Tokens: {len(data.tokens)}, Records: {data.n_records}")
    
    # Use subsampled data for speed
    sample_rate = 100  # Every 100th record for speed
    for t in data.tokens:
        data.prices[t] = data.prices[t][::sample_rate]
    data.n_records = len(data.prices[data.tokens[0]])
    print(f"   Subsampled to: {data.n_records} records (every {sample_rate}th)")
    
    # Test different strategies
    strategies = ['worst', 'lose_least', 'median', 'top3', 'top_half']
    intervals = [5, 10, 20]
    lookbacks = [3, 5, 10]
    thresholds = [0.0, 0.02, 0.05]
    
    results = []
    
    print("\n🔄 Testing strategies...")
    total = len(strategies) * len(intervals) * len(lookbacks) * len(thresholds)
    count = 0
    
    for strat in strategies:
        for interval in intervals:
            for lookback in lookbacks:
                for thresh in thresholds:
                    wf = run_walk_forward(data, strat, lookback, thresh, interval, n_periods=4)
                    results.append(wf)
                    count += 1
                    if count % 30 == 0:
                        print(f"   Progress: {count}/{total}")
    
    # Sort by avg_vs_baseline (key metric!)
    results.sort(key=lambda x: x['avg_vs_baseline'], reverse=True)
    
    print("\n" + "="*80)
    print("WALK-FORWARD RESULTS (sorted by AVG VS BASELINE)")
    print("="*80)
    
    for r in results[:20]:
        status = "✅" if r['all_positive'] else "❌"
        beats = f"{r['beats_baseline']}/4"
        print(f"\n{status} {r['strategy'].upper():12} | lb={r['lookback']} | int={r['interval']} | thresh={r['threshold']:.0%}")
        print(f"   Avg ROI: {r['avg_roi']:+.1f}% | Avg vs Bsl: {r['avg_vs_baseline']:+.1f}% ({beats} periods)")
        print(f"   Min ROI: {r['min_roi']:+.1f}% | Min vs Bsl: {r['min_vs_baseline']:+.1f}%")
        for p in r['periods']:
            print(f"      {p['period']}: ROI={p['roi']:+.1f}%, vsBsl={p['vs_baseline']:+.1f}% ({p['swaps']} swaps)")
    
    # Summary by strategy
    print("\n" + "="*80)
    print("SUMMARY BY STRATEGY (avg of all configs)")
    print("="*80)
    
    strategy_stats = {}
    for r in results:
        s = r['strategy']
        if s not in strategy_stats:
            strategy_stats[s] = {'vs_baseline': [], 'beats': 0, 'positive': 0, 'total': 0}
        strategy_stats[s]['vs_baseline'].append(r['avg_vs_baseline'])
        strategy_stats[s]['beats'] += r['beats_baseline']
        strategy_stats[s]['positive'] += 1 if r['all_positive'] else 0
        strategy_stats[s]['total'] += 1
    
    for s, stats in sorted(strategy_stats.items(), key=lambda x: max(x[1]['vs_baseline']), reverse=True):
        avg = sum(stats['vs_baseline']) / len(stats['vs_baseline'])
        max_val = max(stats['vs_baseline'])
        beats_pct = stats['beats'] / (stats['total'] * 4) * 100
        print(f"{s.upper():12}: avg_vs_bsl={avg:+.1f}%, max={max_val:+.1f}%, beats_BSL={beats_pct:.0f}%, all_pos={stats['positive']}/{stats['total']}")
    
    # Save to JSON
    output = {
        'all_results': results,
        'top_10': results[:10],
        'strategy_summary': {s: {
            'avg_vs_baseline': sum(v['vs_baseline'])/len(v['vs_baseline']),
            'max_vs_baseline': max(v['vs_baseline']),
            'beats_baseline_pct': v['beats'] / (v['total'] * 4) * 100
        } for s, v in strategy_stats.items()}
    }
    
    with open('output/strategy_comparison.json', 'w') as f:
        json.dump(output, f, indent=2)
    
    print("\n✅ Results saved to output/strategy_comparison.json")


if __name__ == '__main__':
    main()
