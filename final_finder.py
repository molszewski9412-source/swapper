#!/usr/bin/env python3
"""
FINAL FINDER - Kompletny finder strategii z analizą

Testuje setki kombinacji i znajduje najlepsze strategie.
"""

import csv
import json
import time
from dataclasses import dataclass
from typing import List

FEE = 0.9996 * 0.9996  # 0.08% za swap


class DataLoader:
    def __init__(self, filepath="market.csv"):
        self.filepath = filepath
        self.tokens = []
        self.prices = {}
        self.n_records = 0
        
    def load(self):
        with open(self.filepath, 'r') as f:
            reader = csv.reader(f)
            header = next(reader)
            
            for i, col in enumerate(header):
                if col.endswith('_BID'):
                    t = col.replace('_BID', '')
                    self.tokens.append(t)
                    self.prices[t] = []
            
            for row in reader:
                for i, t in enumerate(self.tokens):
                    idx = 1 + i * 2
                    if idx < len(row):
                        try:
                            self.prices[t].append(float(row[idx]))
                        except:
                            pass
        
        min_len = min(len(self.prices[t]) for t in self.tokens)
        for t in self.tokens:
            self.prices[t] = self.prices[t][:min_len]
        
        self.n_records = min_len
    
    def momentum(self, token, idx, period):
        if idx < period:
            return 0.0
        return (self.prices[token][idx] - self.prices[token][idx - period]) / self.prices[token][idx - period]


def run_strategy(data, lookback, threshold, interval):
    """Uruchamia strategie Relative Strength."""
    holding = "BTCUSDT"
    amount = 1.0
    last_swap = 0
    swaps = []
    
    for idx in range(lookback, data.n_records - 1):
        if idx - last_swap < interval:
            continue
        
        holding_mom = data.momentum(holding, idx, lookback)
        best_token = None
        best_mom = 999
        
        for token in data.tokens:
            if token == holding:
                continue
            token_mom = data.momentum(token, idx, lookback)
            if token_mom < best_mom and token_mom < holding_mom:
                best_mom = token_mom
                best_token = token
        
        if best_token and (holding_mom - best_mom) > threshold:
            from_price = data.prices[holding][idx]
            to_price = data.prices[best_token][idx]
            usdt = amount * from_price * FEE
            amount = usdt / to_price
            swaps.append({
                'from': holding,
                'to': best_token,
                'diff': holding_mom - best_mom
            })
            holding = best_token
            last_swap = idx
    
    return {
        'holding': holding,
        'amount': amount,
        'swaps': swaps
    }


def main():
    print("""
╔═══════════════════════════════════════════════════════════════╗
║     FINAL FINDER - Kompletna analiza strategii          ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    # Load data
    print("Ładowanie danych...")
    data = DataLoader("market.csv")
    data.load()
    
    btc_final = data.prices['BTCUSDT'][-1]
    btc_start = data.prices['BTCUSDT'][100]
    btc_change = ((btc_final - btc_start) / btc_start) * 100
    
    print(f"Rekordow: {data.n_records}")
    print(f"Tokenow: {len(data.tokens)}")
    print(f"BTC change: {btc_change:+.1f}%")
    print()
    
    # Calculate baselines
    usdt_start = btc_start * FEE
    baselines = {}
    for token in data.tokens:
        baselines[token] = {
            'amount': usdt_start / data.prices[token][100],
            'final_price': data.prices[token][-1],
            'final_value': (usdt_start / data.prices[token][100]) * data.prices[token][-1]
        }
    
    # Optimize
    print("Optymalizacja...")
    results = []
    start = time.time()
    
    lookbacks = [20, 50, 75, 100]
    thresholds = [0.010, 0.015, 0.020, 0.025, 0.030, 0.050]
    intervals = [10, 20, 30]
    
    for lb in lookbacks:
        for th in thresholds:
            for iv in intervals:
                r = run_strategy(data, lb, th, iv)
                value = r['amount'] * data.prices[r['holding']][-1]
                gain = ((value / btc_final) - 1) * 100
                
                # vs baseline
                bl = baselines.get(r['holding'], {})
                baseline_amount = bl.get('amount', 1)
                vs_baseline = ((r['amount'] / baseline_amount) - 1) * 100 if baseline_amount > 0 else 0
                
                results.append({
                    'lookback': lb,
                    'threshold': th,
                    'interval': iv,
                    'holding': r['holding'],
                    'amount': r['amount'],
                    'value': value,
                    'gain_vs_btc': gain,
                    'vs_baseline': vs_baseline,
                    'n_swaps': len(r['swaps'])
                })
    
    elapsed = time.time() - start
    
    # Sort by gain
    results.sort(key=lambda x: x['gain_vs_btc'], reverse=True)
    
    print(f"Przetestowano: {len(results)} kombinacji w {elapsed:.1f}s")
    print()
    
    # Best results
    print("=" * 80)
    print("NAJLEPSZE STRATEGIE (TOP 30)")
    print("=" * 80)
    print()
    print(f"{'#':<3} {'Gain %':<10} {'vs Baseline':<12} {'Token':<12} {'Amount':<18} {'Swaps':<6} {'Params':<25}")
    print("-" * 80)
    
    for i, r in enumerate(results[:30]):
        params = f"L{r['lookback']} T{r['threshold']:.3f} I{r['interval']}"
        vs_bl = f"{r['vs_baseline']:+.1f}%"
        gain = f"{r['gain_vs_btc']:+.1f}%"
        
        if r['vs_baseline'] > 0:
            vs_bl = "✓ " + vs_bl
        else:
            vs_bl = "✗ " + vs_bl
        
        amount_str = f"{r['amount']:,.0f}"
        
        print(f"{i+1:<3} {gain:<10} {vs_bl:<12} {r['holding']:<12} {amount_str:<18} {r['n_swaps']:<6} {params:<25}")
    
    # Summary by token
    print()
    print("=" * 80)
    print("SREDNI GAIN PER TOKEN")
    print("=" * 80)
    
    token_gains = {}
    for r in results:
        t = r['holding']
        if t not in token_gains:
            token_gains[t] = []
        token_gains[t].append(r['gain_vs_btc'])
    
    avg_gains = [(t, sum(g)/len(g), max(g), len(g)) for t, g in token_gains.items()]
    avg_gains.sort(key=lambda x: x[1], reverse=True)
    
    print()
    print(f"{'Token':<12} {'Avg Gain':<12} {'Max Gain':<12} {'Count':<6}")
    print("-" * 45)
    for t, avg, mx, cnt in avg_gains:
        print(f"{t:<12} {avg:>+8.1f}%   {mx:>+8.1f}%   {cnt:<6}")
    
    # Save results
    output = {
        'summary': {
            'n_tested': len(results),
            'elapsed_seconds': elapsed,
            'btc_change': btc_change
        },
        'best_overall': results[0],
        'top_50': results[:50],
        'all_results': results
    }
    
    import os
    os.makedirs('output', exist_ok=True)
    with open('output/final_results.json', 'w') as f:
        json.dump(output, f, indent=2)
    
    print()
    print(f"Zapisano do: output/final_results.json")
    
    # Best params
    best = results[0]
    print()
    print("=" * 80)
    print("NAJLEPSZA STRATEGIA")
    print("=" * 80)
    print(f"Gain vs BTC: +{best['gain_vs_btc']:.1f}%")
    print(f"Token: {best['holding']}")
    print(f"Amount: {best['amount']:,.0f}")
    print(f"Value: ${best['value']:,.2f}")
    print(f"vs Baseline: {best['vs_baseline']:+.1f}%")
    print(f"Swaps: {best['n_swaps']}")
    print(f"Params: lookback={best['lookback']}, threshold={best['threshold']}, interval={best['interval']}")


if __name__ == "__main__":
    main()
