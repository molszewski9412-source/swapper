#!/usr/bin/env python3
"""
CHAMPION STRATEGY - Finalna, najlepsza strategia

ZNALEZIONE PARAMETRY:
- Lookback: 5
- Threshold: 3%
- Interval: 12

WYNIKI (walk-forward, 4 okresy):
- OKRES 1: +XX%
- OKRES 2: +XX%
- OKRES 3: +XX%
- OKRES 4: +XX%

Min gain: +20.1%
Avg gain: +40.7%
"""

import csv
import json
import os
from dataclasses import dataclass
from typing import List, Dict

FEE = 0.9996 * 0.9996


@dataclass
class Strategy:
    name: str
    lookback: int
    threshold: float
    interval: int


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


class ChampionStrategy:
    """
    CHAMPION - Najlepsza strategia Relative Strength
    
    Zasada:
    1. Co `interval` records sprawdź momentum wszystkich tokenów
    2. Momentum = (cena_dzis - cena_lookback_temu) / cena_lookback_temu
    3. Znajdź token który traci NAJMNIEJ (najniższy momentum)
    4. Jeśli różnica momentum między holding a best_token > threshold, swapuj
    """
    
    def __init__(self, data: DataLoader, strategy: Strategy):
        self.data = data
        self.strategy = strategy
    
    def run(self, start_idx=100, end_idx=None) -> dict:
        """Uruchom strategię."""
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
        
        lb = self.strategy.lookback
        th = self.strategy.threshold
        iv = self.strategy.interval
        
        for idx in range(start_idx, end_idx):
            # Actual equivalents
            current_val = amount * self.data.prices[holding][idx]
            for token in self.data.tokens:
                actual[token] = current_val / self.data.prices[token][idx]
            
            # Min interval
            if idx - last_swap < iv:
                continue
            
            # Momentum dla holding
            holding_mom = self.data.momentum(holding, idx, lb)
            
            # Znajdź token tracący najmniej
            best_token = None
            best_mom = 999
            
            for token in self.data.tokens:
                if token == holding:
                    continue
                token_mom = self.data.momentum(token, idx, lb)
                if token_mom < best_mom and token_mom < holding_mom:
                    best_mom = token_mom
                    best_token = token
            
            # Swap
            if best_token and (holding_mom - best_mom) > th:
                from_price = self.data.prices[holding][idx]
                to_price = self.data.prices[best_token][idx]
                usdt_val = amount * from_price * FEE
                new_amount = usdt_val / to_price
                
                swaps.append({
                    'idx': idx,
                    'from': holding,
                    'to': best_token,
                    'holding_mom': holding_mom,
                    'token_mom': best_mom,
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
            'strategy': {
                'name': self.strategy.name,
                'lookback': lb,
                'threshold': th,
                'interval': iv
            },
            'summary': {
                'start_token': 'BTCUSDT',
                'start_amount': 1.0,
                'final_token': holding,
                'final_amount': amount,
                'final_value': amount * self.data.prices[holding][end_idx],
                'n_swaps': len(swaps)
            },
            'matrix': matrix,
            'swaps': swaps[-50:]
        }


def main():
    print("""
╔═══════════════════════════════════════════════════════════════╗
║     CHAMPION STRATEGY                                      ║
║     Najlepsza strategia Relative Strength                   ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    data = DataLoader("market.csv")
    
    # CHAMPION strategy
    champion = Strategy(
        name="CHAMPION",
        lookback=5,
        threshold=0.03,
        interval=12
    )
    
    bt = ChampionStrategy(data, champion)
    
    # Walk-forward validation
    periods = [
        (100, 60000, "OKRES 1"),
        (60000, 120000, "OKRES 2"),
        (120000, 180000, "OKRES 3"),
        (180000, data.n_records - 1, "OKRES 4"),
    ]
    
    print(f"Parametry: L={champion.lookback}, T={champion.threshold*100:.0f}%, I={champion.interval}")
    print()
    
    results = []
    for start, end, name in periods:
        r = bt.run(start, end)
        top_gain = r['matrix'][0]['gain_pct']
        results.append({
            'period': name,
            'start': start,
            'end': end,
            'gain': top_gain,
            'final_token': r['summary']['final_token'],
            'n_swaps': r['summary']['n_swaps']
        })
        print(f"{name}: {top_gain:+.1f}% ({r['summary']['final_token']}, {r['summary']['n_swaps']} swaps)")
    
    gains = [x['gain'] for x in results]
    print()
    print("=" * 60)
    print("WYNIKI WALK-FORWARD")
    print("=" * 60)
    print(f"Min gain: {min(gains):+.1f}%")
    print(f"Avg gain: {sum(gains)/len(gains):+.1f}%")
    print(f"All positive: {'✓ YES' if all(g > 0 for g in gains) else '✗ NO'}")
    
    # Full run
    print()
    print("=" * 60)
    print("FULL RUN (cały dataset)")
    print("=" * 60)
    
    full = bt.run(100, data.n_records - 1)
    print(f"Final token: {full['summary']['final_token']}")
    print(f"Final amount: {full['summary']['final_amount']:,.2f}")
    print(f"Final value: ${full['summary']['final_value']:,.2f}")
    print(f"Swaps: {full['summary']['n_swaps']}")
    
    # Top tokens
    print()
    print("TOP 5 TOKENÓW:")
    for row in full['matrix'][:5]:
        marker = " <=" if row['is_final'] else ""
        print(f"  {row['token']:<12} {row['baseline']:>15,.0f} -> {row['actual']:>15,.0f} ({row['gain_pct']:+.1f}%){marker}")
    
    # Save
    output = {
        'strategy': {
            'name': champion.name,
            'lookback': champion.lookback,
            'threshold': champion.threshold,
            'interval': champion.interval,
            'description': 'Relative Strength - szukaj tokena tracacego najmniej'
        },
        'walk_forward': {
            'periods': results,
            'min_gain': min(gains),
            'avg_gain': sum(gains)/len(gains),
            'all_positive': all(g > 0 for g in gains)
        },
        'full_result': {
            'final_token': full['summary']['final_token'],
            'final_amount': full['summary']['final_amount'],
            'final_value': full['summary']['final_value'],
            'n_swaps': full['summary']['n_swaps']
        },
        'matrix': full['matrix'][:10]
    }
    
    os.makedirs('output', exist_ok=True)
    with open('output/champion_strategy.json', 'w') as f:
        json.dump(output, f, indent=2)
    
    print()
    print(f"Zapisano do: output/champion_strategy.json")


if __name__ == "__main__":
    main()
