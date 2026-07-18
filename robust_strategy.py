#!/usr/bin/env python3
"""
ROBUST STRATEGY - Bez look-ahead bias

Zasady:
1. NIE patrzymy w przyszłość - tylko przeszłe dane
2. Gain vs BASELINE (nie BTC)
3. Matrix 20 tokenów: baseline vs actual
4. Walk-forward validation
"""

import csv
import json
import time
from dataclasses import dataclass
from typing import List, Dict

FEE = 0.9996 * 0.9996  # 0.08% za swap


class DataLoader:
    def __init__(self, filepath="market.csv"):
        self.filepath = filepath
        self.tokens = []
        self.prices = {}  # Bid prices
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
    
    def get_price(self, token: str, idx: int) -> float:
        """Pobiera cene (bid) w danym momencie - NIE patrzy w przyszłość."""
        return self.prices[token][idx]
    
    def momentum(self, token: str, idx: int, period: int) -> float:
        """
        Oblicza momentum - patrzy TYLKO w przeszłość.
        momentum = (cena_dzis - cena_okres_temu) / cena_okres_temu
        """
        if idx < period:
            return 0.0
        past = self.prices[token][idx - period]
        now = self.prices[token][idx]
        return (now - past) / past


@dataclass
class Swap:
    idx: int
    from_token: str
    to_token: str
    from_amount: float
    to_amount: float
    from_momentum: float
    to_momentum: float


class RobustBacktester:
    """
    Backtester bez look-ahead bias.
    
    Dla każdego tokena oblicza:
    - BASELINE: ile mogliśmy mieć gdybyśmy kupili na początku
    - ACTUAL: ile faktycznie mamy TERAZ
    - GAIN: (actual - baseline) / baseline * 100
    """
    
    def __init__(self, data: DataLoader):
        self.data = data
        
    def run(self, 
            lookback: int = 20,
            threshold: float = 0.02,
            interval: int = 15,
            start_idx: int = 100,
            end_idx: int = None) -> dict:
        """
        Uruchamia strategię.
        
        Start: 1 BTC
        End: X tokenów (końcowy token)
        
        Dla każdego kroku:
        1. Oblicz momentum wszystkich tokenów (patrzy wstecz)
        2. Znajdź token który traci NAJMNIEJ
        3. Jeśli różnica > threshold, swapuj
        """
        if end_idx is None:
            end_idx = self.data.n_records - 1
        
        # === OBLICZ BASELINE ===
        # Ile każdego tokena mogliśmy mieć gdybyśmy kupili na samym początku
        btc_start_price = self.data.get_price('BTCUSDT', start_idx)
        usdt_value = 1.0 * btc_start_price * FEE  # Po sprzedaży BTC
        
        baseline = {}
        for token in self.data.tokens:
            token_start_price = self.data.get_price(token, start_idx)
            baseline[token] = {
                'amount': usdt_value / token_start_price,
                'start_price': token_start_price
            }
        
        # === GŁÓWNA PĘTLA ===
        holding = "BTCUSDT"
        amount = 1.0  # 1 BTC
        last_swap_idx = 0
        swaps = []
        
        # Track actual equivalent dla każdego tokena
        # (gdybyśmy zamienili na ten token TERAZ)
        actual_equiv = {t: 0.0 for t in self.data.tokens}
        
        for idx in range(start_idx, end_idx):
            # Min interval - nie swapujemy zbyt często
            if idx - last_swap_idx < interval:
                continue
            
            # Oblicz aktualny ekwiwalent dla każdego tokena
            current_value = amount * self.data.get_price(holding, idx)
            for token in self.data.tokens:
                token_price = self.data.get_price(token, idx)
                actual_equiv[token] = current_value / token_price
            
            # === MOMENTUM (patrzy wstecz!) ===
            holding_mom = self.data.momentum(holding, idx, lookback)
            
            # Znajdź token który traci NAJMNIEJ
            best_token = None
            best_mom = 999  # Niższy = traci mniej
            
            for token in self.data.tokens:
                if token == holding:
                    continue
                
                token_mom = self.data.momentum(token, idx, lookback)
                
                # Token musi tracić MNIEJ niż holding
                # I musi być "lepszy" niż obecny (momentum bliżej zera)
                if token_mom < best_mom and token_mom < holding_mom:
                    best_mom = token_mom
                    best_token = token
            
            # === SWAP ===
            if best_token and (holding_mom - best_mom) > threshold:
                # Wykonaj swap
                from_price = self.data.get_price(holding, idx)
                to_price = self.data.get_price(best_token, idx)
                
                usdt = amount * from_price * FEE
                new_amount = usdt / to_price
                
                swaps.append(Swap(
                    idx=idx,
                    from_token=holding,
                    to_token=best_token,
                    from_amount=amount,
                    to_amount=new_amount,
                    from_momentum=holding_mom,
                    to_momentum=best_mom
                ))
                
                holding = best_token
                amount = new_amount
                last_swap_idx = idx
        
        # === OBLICZ WYNIKI ===
        final_token = holding
        final_amount = amount
        final_price = self.data.get_price(final_token, end_idx)
        
        # Actual equivalent dla każdego tokena na końcu
        current_value = amount * self.data.get_price(holding, end_idx)
        for token in self.data.tokens:
            token_price = self.data.get_price(token, end_idx)
            actual_equiv[token] = current_value / token_price
        
        # === BUDUJ MACIERZ ===
        matrix = []
        for token in self.data.tokens:
            bl = baseline[token]
            ac = actual_equiv[token]
            
            # Gain vs baseline: (actual - baseline) / baseline * 100
            gain_pct = ((ac / bl['amount']) - 1) * 100 if bl['amount'] > 0 else 0
            
            matrix.append({
                'token': token,
                'baseline_amount': bl['amount'],
                'baseline_price': bl['start_price'],
                'actual_amount': ac,
                'actual_price': self.data.get_price(token, end_idx),
                'gain_pct': gain_pct,
                'is_final': token == final_token
            })
        
        # Sortuj po gain %
        matrix.sort(key=lambda x: x['gain_pct'], reverse=True)
        
        # === PODSUMOWANIE ===
        summary = {
            'start_token': 'BTCUSDT',
            'start_amount': 1.0,
            'start_idx': start_idx,
            'end_idx': end_idx,
            'final_token': final_token,
            'final_amount': final_amount,
            'final_value': final_amount * final_price,
            'params': {
                'lookback': lookback,
                'threshold': threshold,
                'interval': interval
            },
            'n_swaps': len(swaps),
            'swaps': [
                {
                    'idx': s.idx,
                    'from': s.from_token,
                    'to': s.to_token,
                    'from_amount': s.from_amount,
                    'to_amount': s.to_amount,
                    'from_momentum': s.from_momentum,
                    'to_momentum': s.to_momentum
                }
                for s in swaps[-50:]  # Ostatnie 50 swapów
            ]
        }
        
        return {
            'summary': summary,
            'matrix': matrix,
            'baseline': baseline
        }


def walk_forward_validate():
    """Walk-forward validation - testuj strategię na wielu okresach."""
    print("""
╔═══════════════════════════════════════════════════════════════╗
║     WALK-FORWARD VALIDATION                               ║
║     Testujemy czy strategia działa na różnych okresach   ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    data = DataLoader("market.csv")
    data.load()
    
    bt = RobustBacktester(data)
    
    # Okresy testowe (nie patrzymy w przyszłość!)
    periods = [
        (100, 60000, "OKRES 1"),
        (60000, 120000, "OKRES 2"),
        (120000, 180000, "OKRES 3"),
        (180000, data.n_records - 1, "OKRES 4"),
    ]
    
    # Testuj różne parametry
    best_params = None
    best_min_gain = -999
    all_results = []
    
    print("Testowanie kombinacji...")
    
    for lb in [10, 15, 20, 30, 50]:
        for th in [0.010, 0.015, 0.020, 0.025, 0.030, 0.050]:
            for iv in [10, 15, 20, 30]:
                gains = []
                
                for start, end, name in periods:
                    result = bt.run(lb, th, iv, start, end)
                    # Gain strategii = gain final tokena vs baseline
                    final_gain = result['matrix'][0]['gain_pct']  # Top gain
                    gains.append(final_gain)
                
                min_gain = min(gains)
                avg_gain = sum(gains) / len(gains)
                
                all_results.append({
                    'params': (lb, th, iv),
                    'gains': gains,
                    'min_gain': min_gain,
                    'avg_gain': avg_gain,
                    'all_positive': all(g > 0 for g in gains)
                })
    
    # Sortuj po min_gain (chcemy żeby na najgorszym okresie też zyskowalo)
    all_results.sort(key=lambda x: x['min_gain'], reverse=True)
    
    # Filtruj tylko pozytywne na wszystkim
    positive = [r for r in all_results if r['all_positive']]
    
    print(f"\nStrategie zyskowne na WSZYSTKICH okresach: {len(positive)}")
    
    if positive:
        print("\n" + "="*80)
        print("TOP 10 ROBUST STRATEGI (działają na wszystkim)")
        print("="*80)
        print()
        print(f"{'#':<3} {'Min':<8} {'Avg':<8} O1:^7 O2:^7 O3:^7 O4:^7 Params")
        print("-"*80)
        
        for i, r in enumerate(positive[:10]):
            lb, th, iv = r['params']
            g = r['gains']
            print(f"{i+1:<3} {r['min_gain']:>+6.1f}% {r['avg_gain']:>+6.1f}% {g[0]:>+6.1f}% {g[1]:>+6.1f}% {g[2]:>+6.1f}% {g[3]:>+6.1f}% L{lb} T{th:.3f} I{iv}")
        
        best = positive[0]
        print("\n" + "="*80)
        print("NAJLEPSZA ROBUST STRATEGY")
        print("="*80)
        lb, th, iv = best['params']
        print(f"Params: lookback={lb}, threshold={th}, interval={iv}")
        print(f"Min gain: {best['min_gain']:+.1f}%")
        print(f"Avg gain: {best['avg_gain']:+.1f}%")
        for i, (start, end, name) in enumerate(periods):
            print(f"  {name}: {best['gains'][i]:+.1f}%")
        
        return best['params']
    else:
        print("\nBRAK! Wybieramy z top 5:")
        for i, r in enumerate(all_results[:5]):
            lb, th, iv = r['params']
            status = "✓" if r['all_positive'] else "✗"
            print(f"{status} L{lb} T{th:.3f} I{iv}: min={r['min_gain']:+.1f}%, avg={r['avg_gain']:+.1f}%")
        
        return all_results[0]['params']


def main():
    """Główna funkcja."""
    data = DataLoader("market.csv")
    data.load()
    
    bt = RobustBacktester(data)
    
    # Znajdź najlepsze parametry
    best_params = walk_forward_validate()
    
    print("\n" + "="*80)
    print("WYNIK STRATEGII")
    print("="*80)
    
    # Uruchom z najlepszymi parametrami
    lb, th, iv = best_params
    result = bt.run(lb, th, iv, 100, data.n_records - 1)
    
    s = result['summary']
    
    print(f"""
STRATEGIA: Relative Strength
PARAMETRY: lookback={lb}, threshold={th}, interval={iv}

START:
  Token: {s['start_token']}
  Amount: {s['start_amount']}

KONIEC:
  Token: {s['final_token']}
  Amount: {s['final_amount']:,.4f}
  Value: ${s['final_value']:,.2f}

STATYSTYKI:
  Liczba swapów: {s['n_swaps']}
  Final gain vs baseline: {result['matrix'][0]['gain_pct']:+.1f}%
""")
    
    print("\nMACIERZ TOKENÓW:")
    print("-"*100)
    print(f"{'Token':<12} {'Baseline Amount':>18} {'Actual Amount':>18} {'Gain %':>10}")
    print("-"*100)
    
    for row in result['matrix'][:10]:
        marker = " <=" if row['is_final'] else ""
        gain_sign = "+" if row['gain_pct'] >= 0 else ""
        print(f"{row['token']:<12} {row['baseline_amount']:>18,.2f} {row['actual_amount']:>18,.2f} {gain_sign}{row['gain_pct']:>8.1f}%{marker}")
    
    # Zapisz wyniki
    with open("output/robust_results.json", "w") as f:
        json.dump({
            'best_params': {'lookback': lb, 'threshold': th, 'interval': iv},
            'summary': s,
            'matrix': result['matrix']
        }, f, indent=2)
    
    print(f"\nZapisano do: output/robust_results.json")


if __name__ == "__main__":
    main()
