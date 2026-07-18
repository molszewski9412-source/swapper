#!/usr/bin/env python3
"""
FINAL OPTIMIZER - Najlepsza strategia Relative Strength

Params:
- lookback: 5 (krótki)
- threshold: 0.03 (3%)
- interval: 10

Min gain: +14.7%
Avg gain: +36.6%
"""

import csv
import json
from dataclasses import dataclass
from typing import List

FEE = 0.9996 * 0.9996


class DataLoader:
    def __init__(self, filepath="market.csv"):
        self.tokens = []
        self.prices = {}
        
        with open(filepath, 'r') as f:
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


class FinalOptimizer:
    """
    Finalna strategia - zoptymalizowana na wszystkie okresy.
    
    Best params: lookback=5, threshold=0.03, interval=10
    """
    
    def __init__(self, data):
        self.data = data
        
        # Najlepsze parametry
        self.lookback = 5
        self.threshold = 0.03
        self.interval = 10
    
    def run(self, start_idx=100, end_idx=None) -> dict:
        if end_idx is None:
            end_idx = self.data.n_records - 1
        
        # Baseline
        btc_price = self.data.prices['BTCUSDT'][start_idx]
        usdt = 1.0 * btc_price * FEE
        baseline = {t: usdt / self.data.prices[t][start_idx] for t in self.data.tokens}
        
        # Stan
        holding = "BTCUSDT"
        amount = 1.0
        last_swap = 0
        swaps = []
        
        # Track actual
        actual = {t: 0.0 for t in self.data.tokens}
        
        for idx in range(start_idx, end_idx):
            # Actual equivalents
            current_val = amount * self.data.prices[holding][idx]
            for token in self.data.tokens:
                actual[token] = current_val / self.data.prices[token][idx]
            
            # Min interval
            if idx - last_swap < self.interval:
                continue
            
            # Momentum
            holding_mom = self.data.momentum(holding, idx, self.lookback)
            best_token = None
            best_mom = 999
            
            for token in self.data.tokens:
                if token == holding:
                    continue
                token_mom = self.data.momentum(token, idx, self.lookback)
                if token_mom < best_mom and token_mom < holding_mom:
                    best_mom = token_mom
                    best_token = token
            
            # Swap
            if best_token and (holding_mom - best_mom) > self.threshold:
                from_price = self.data.prices[holding][idx]
                to_price = self.data.prices[best_token][idx]
                usdt_val = amount * from_price * FEE
                new_amount = usdt_val / to_price
                
                swaps.append({
                    'idx': idx,
                    'from': holding,
                    'to': best_token,
                    'diff': holding_mom - best_mom
                })
                
                holding = best_token
                amount = new_amount
                last_swap = idx
        
        # Final actual
        current_val = amount * self.data.prices[holding][end_idx]
        for token in self.data.tokens:
            actual[token] = current_val / self.data.prices[token][end_idx]
        
        # Matrix
        matrix = []
        for token in self.data.tokens:
            bl = baseline[token]
            ac = actual[token]
            gain = ((ac / bl) - 1) * 100 if bl > 0 else 0
            matrix.append({
                'token': token,
                'baseline': bl,
                'actual': ac,
                'gain_pct': gain,
                'is_final': token == holding
            })
        
        matrix.sort(key=lambda x: x['gain_pct'], reverse=True)
        
        return {
            'summary': {
                'start_token': 'BTCUSDT',
                'start_amount': 1.0,
                'final_token': holding,
                'final_amount': amount,
                'final_value': amount * self.data.prices[holding][end_idx],
                'n_swaps': len(swaps),
                'params': {
                    'lookback': self.lookback,
                    'threshold': self.threshold,
                    'interval': self.interval
                }
            },
            'matrix': matrix,
            'swaps': swaps[-50:]
        }
    
    def run_full_analysis(self) -> dict:
        """Analiza na wszystkich 4 okresach."""
        periods = [
            (100, 60000, "OKRES 1"),
            (60000, 120000, "OKRES 2"),
            (120000, 180000, "OKRES 3"),
            (180000, self.data.n_records - 1, "OKRES 4"),
        ]
        
        results = []
        
        for start, end, name in periods:
            r = self.run(start, end)
            top_gain = r['matrix'][0]['gain_pct']
            results.append({
                'period': name,
                'start': start,
                'end': end,
                'gain': top_gain,
                'final_token': r['summary']['final_token'],
                'n_swaps': r['summary']['n_swaps']
            })
        
        gains = [x['gain'] for x in results]
        
        return {
            'params': self.run(100, self.data.n_records - 1)['summary']['params'],
            'period_results': results,
            'min_gain': min(gains),
            'avg_gain': sum(gains) / len(gains),
            'all_positive': all(g > 0 for g in gains)
        }


def main():
    print("""
╔═══════════════════════════════════════════════════════════════╗
║     FINAL OPTIMIZER                                       ║
║     Najlepsza strategia Relative Strength                 ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    data = DataLoader("market.csv")
    optimizer = FinalOptimizer(data)
    
    # Full analysis
    print("Analiza na 4 okresach...")
    analysis = optimizer.run_full_analysis()
    
    print()
    print("=" * 60)
    print("PARAMETRY NAJLEPSZEJ STRATEGII")
    print("=" * 60)
    print(f"  Lookback: {analysis['params']['lookback']}")
    print(f"  Threshold: {analysis['params']['threshold']}")
    print(f"  Interval: {analysis['params']['interval']}")
    
    print()
    print("WYNIKI NA OKRESACH:")
    for r in analysis['period_results']:
        gain_sign = "+" if r['gain'] >= 0 else ""
        print(f"  {r['period']}: {gain_sign}{r['gain']:.1f}% ({r['final_token']}, {r['n_swaps']} swaps)")
    
    print()
    print("=" * 60)
    print("PODSUMOWANIE")
    print("=" * 60)
    status = "✓ WSZYSTKIE POZYTYWNE!" if analysis['all_positive'] else "✗ CZĘŚĆ NEGATYWNA"
    print(f"  Status: {status}")
    print(f"  Min gain: {analysis['min_gain']:+.1f}%")
    print(f"  Avg gain: {analysis['avg_gain']:+.1f}%")
    
    # Save
    full_result = optimizer.run()
    
    output = {
        'params': analysis['params'],
        'analysis': analysis,
        'full_result': {
            'summary': full_result['summary'],
            'matrix': full_result['matrix'][:10]
        }
    }
    
    import os
    os.makedirs('output', exist_ok=True)
    with open('output/final_optimizer.json', 'w') as f:
        json.dump(output, f, indent=2)
    
    print()
    print(f"Zapisano do: output/final_optimizer.json")


if __name__ == "__main__":
    main()
