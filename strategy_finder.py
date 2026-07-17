#!/usr/bin/env python3
"""
Strategy Finder v2 - ZOPTYMALIZOWANA WERSJA

Nowa strategia: RELATIVE STRENGTH (nie momentum!)
- Zasada: Byc w tokenie ktory traci MNIEJ niz obecny
- Zamiast gonic zwyciescow, unikaj przegranych
- Idealna na spadajacy rynek

Parametry:
- lookback: jak daleko wstecz liczyc zmiane
- threshold: min. roznica momentum do swapa  
- interval: min. records miedzy swapami
"""

import csv
import json
import time
from dataclasses import dataclass
from typing import List, Tuple, Optional

# Fee: 0.04% za kazda strone = 0.08% za caly swap
FEE_TOTAL = 0.9996 * 0.9996  # = 0.9992


@dataclass
class StrategyParams:
    """Parametry strategii."""
    lookback: int = 20
    threshold: float = 0.03  # Min 3% difference
    min_interval: int = 10


@dataclass
class StrategyResult:
    """Wynik strategii."""
    params: StrategyParams
    final_token: str
    final_amount: float
    final_value_usdt: float
    gain_vs_btc: float
    n_swaps: int
    swaps: List[dict]


class DataLoader:
    """Ładowanie danych."""
    
    def __init__(self, filepath: str = "market.csv"):
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
    
    def momentum(self, token: str, idx: int, period: int) -> float:
        """Zwraca % zmiane ceny za okres."""
        if idx < period:
            return 0.0
        return (self.prices[token][idx] - self.prices[token][idx - period]) / self.prices[token][idx - period]


class StrategyFinder:
    """
    Finder strategii - RELATIVE STRENGTH approach.
    
    Zasada dzialania:
    1. Sprawdz momentum (zmiana %) wszystkich tokenow
    2. Znajdz token ktory traci NAJMNIEJ (momentum bliskie 0 lub dodatnie)
    3. Jesli aktualny holding traci WICEJ niz inny token, swapuj
    4.梓 Aby swap byl opłacalny, różnica musi byc > threshold
    """
    
    def __init__(self, data: DataLoader):
        self.data = data
        self.btc_final_value = 1.0 * data.prices['BTCUSDT'][-1]
        
    def calculate_baseline(self) -> dict:
        """Oblicza baseline dla kazdego tokena."""
        btc_price = self.data.prices['BTCUSDT'][0]
        usdt = 1.0 * btc_price * FEE_TOTAL
        
        baseline = {}
        for token in self.data.tokens:
            amount = usdt / self.data.prices[token][0]
            baseline[token] = {
                'initial_amount': amount,
                'initial_price': self.data.prices[token][0],
                'final_price': self.data.prices[token][-1]
            }
        
        return baseline
    
    def run(self, params: StrategyParams) -> StrategyResult:
        """
        Uruchamia strategie RELATIVE STRENGTH.
        
        Kluczowa roznica vs momentum:
        - Momentum: szukaj tokenow ktore ZYSKUJA najwiecej
        - Relative Strength: szukaj tokenow ktore TRACA najmniej
        """
        holding = "BTCUSDT"
        amount = 1.0
        last_swap = 0
        swaps = []
        
        for idx in range(params.lookback, self.data.n_records - 1):
            # Min interval check
            if idx - last_swap < params.min_interval:
                continue
            
            # Momentum obecnego tokena
            holding_mom = self.data.momentum(holding, idx, params.lookback)
            
            # Znajdz token tracacy NAJMNIEJ
            best_token = None
            best_mom = 999  # Nizszy momentum = traci mniej
            
            for token in self.data.tokens:
                if token == holding:
                    continue
                
                token_mom = self.data.momentum(token, idx, params.lookback)
                
                # Token traci mniej niz aktualny?
                if token_mom < best_mom and token_mom < holding_mom:
                    best_mom = token_mom
                    best_token = token
            
            # Swap jesli roznica > threshold
            if best_token and (holding_mom - best_mom) > params.threshold:
                from_price = self.data.prices[holding][idx]
                to_price = self.data.prices[best_token][idx]
                
                # Swap z fee
                usdt = amount * from_price * FEE_TOTAL
                new_amount = usdt / to_price
                
                swaps.append({
                    'idx': idx,
                    'from': holding,
                    'to': best_token,
                    'from_mom': holding_mom,
                    'to_mom': best_mom,
                    'amount_out': new_amount
                })
                
                holding = best_token
                amount = new_amount
                last_swap = idx
        
        # Oblicz wyniki
        final_value = amount * self.data.prices[holding][-1]
        gain_vs_btc = ((final_value / self.btc_final_value) - 1) * 100
        
        return StrategyResult(
            params=params,
            final_token=holding,
            final_amount=amount,
            final_value_usdt=final_value,
            gain_vs_btc=gain_vs_btc,
            n_swaps=len(swaps),
            swaps=swaps[-20:]  # Ostatnie 20 swapow
        )
    
    def optimize(self) -> List[StrategyResult]:
        """Optymalizuje parametry."""
        results = []
        
        lookbacks = [10, 20, 50, 100, 200]
        thresholds = [0.01, 0.02, 0.03, 0.05, 0.10]
        intervals = [5, 10, 20, 50, 100]
        
        for lb in lookbacks:
            for th in thresholds:
                for iv in intervals:
                    params = StrategyParams(
                        lookback=lb,
                        threshold=th,
                        min_interval=iv
                    )
                    result = self.run(params)
                    results.append(result)
        
        # Sortuj po gain vs BTC
        results.sort(key=lambda x: x.gain_vs_btc, reverse=True)
        
        return results


def main():
    """Główna funkcja."""
    print("""
╔═══════════════════════════════════════════════════════════════╗
║     STRATEGY FINDER v2 - RELATIVE STRENGTH               ║
║                                                       ║
║     Zasada: Byc w tokenie ktory traci MNIEJ           ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    # Load data
    print("Ładowanie danych...")
    data = DataLoader("market.csv")
    data.load()
    
    finder = StrategyFinder(data)
    
    # Calculate baseline
    print("\nObliczanie baseline...")
    baseline = finder.calculate_baseline()
    
    # BTC performance
    btc_gain = ((data.prices['BTCUSDT'][-1] / data.prices['BTCUSDT'][100]) - 1) * 100
    print(f"\nBTC buy&hold: {btc_gain:+.1f}%")
    print(f"Cel strategii: byc LEPSZYM niz BTC")
    
    # Optimize
    print("\n" + "="*60)
    print("OPTYMALIZACJA (szukanie najlepszej strategii)...")
    print("="*60 + "\n")
    
    start = time.time()
    results = finder.optimize()
    elapsed = time.time() - start
    
    print(f"Przetestowano {len(results)} kombinacji w {elapsed:.1f}s\n")
    
    # Best result
    best = results[0]
    
    print("="*60)
    print("NAJLEPSZA STRATEGIA znaleziona!")
    print("="*60)
    print(f"\nGain vs BTC: +{best.gain_vs_btc:.1f}%")
    print(f"Final token: {best.final_token}")
    print(f"Final amount: {best.final_amount:,.2f}")
    print(f"Final value: ${best.final_value_usdt:,.2f}")
    print(f"Liczba swapow: {best.n_swaps}")
    print(f"\nParametry:")
    print(f"  lookback: {best.params.lookback}")
    print(f"  threshold: {best.params.threshold} ({best.params.threshold*100:.0f}%)")
    print(f"  min_interval: {best.params.min_interval}")
    
    # Top 5
    print("\n" + "="*60)
    print("TOP 5 STRATEGI")
    print("="*60)
    for i, r in enumerate(results[:5]):
        print(f"\n#{i+1} +{r.gain_vs_btc:.1f}% ({r.final_amount:,.0f} {r.final_token})")
        print(f"   Params: L{r.params.lookback} T{r.params.threshold*100:.0f}% I{r.params.min_interval}")
    
    # Save results
    output = {
        'best_strategy': {
            'gain_vs_btc': best.gain_vs_btc,
            'final_token': best.final_token,
            'final_amount': best.final_amount,
            'final_value_usdt': best.final_value_usdt,
            'n_swaps': best.n_swaps,
            'params': {
                'lookback': best.params.lookback,
                'threshold': best.params.threshold,
                'min_interval': best.params.min_interval
            }
        },
        'top_10': [
            {
                'gain_vs_btc': r.gain_vs_btc,
                'final_token': r.final_token,
                'final_amount': r.final_amount,
                'params': r.params.__dict__
            }
            for r in results[:10]
        ],
        'stats': {
            'n_tested': len(results),
            'time_seconds': elapsed,
            'btc_gain': btc_gain
        }
    }
    
    import os
    os.makedirs('output', exist_ok=True)
    with open('output/best_strategy.json', 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"\n\nZapisano do: output/best_strategy.json")


if __name__ == "__main__":
    main()
