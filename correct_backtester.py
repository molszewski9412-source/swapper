#!/usr/bin/env python3
"""
Correct Backtester - liczy ILOŚĆ TOKENÓW, nie USDT

Logika:
1. Start: 1 BTC
2. Swap BTC -> Token = otrzymujemy ILOŚĆ tokenów
3. Śledzimy ile tokenów mamy
4. Final: "Masz X.XXX tokenów" - nie ich wartość USDT
"""

import csv
import json
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Swap:
    """Zapis swapu."""
    idx: int
    from_token: str
    to_token: str
    amount_in: float  # Ile oddaliśmy
    amount_out: float  # Ile dostaliśmy
    from_price: float
    to_price: float


class CorrectBacktester:
    """
    Backtester który liczy ILOŚĆ tokenów, nie USDT.
    
    Kluczowa różnica:
    - Zwykły: "Mam wartość $X USDT"
    - Ten: "Mam X.XXX tokenów"
    
    Dla porównania:
    - BTC buy&hold: 1 BTC (niezmienna ilość)
    - Strategia: zmienna ilość różnych tokenów
    """
    
    def __init__(self, filepath: str = "market.csv"):
        self.filepath = filepath
        self.tokens = []
        self.bids = {}  # Token -> list of bid prices
        self.asks = {}  # Token -> list of ask prices
        self.n_records = 0
        self.SWAP_FEE = 0.0004  # 0.04%
        
    def load(self):
        """Ładuje dane."""
        print(f"Ładowanie z {self.filepath}...")
        
        with open(self.filepath, 'r') as f:
            reader = csv.reader(f)
            header = next(reader)
            
            # Parse header
            for i, col in enumerate(header):
                if col.endswith('_BID'):
                    t = col.replace('_BID', '')
                    self.tokens.append(t)
                    self.bids[t] = []
                    self.asks[t] = []
            
            # Load data
            for row in reader:
                for i, t in enumerate(self.tokens):
                    bid_idx = 1 + i * 2
                    ask_idx = bid_idx + 1
                    if bid_idx < len(row) and ask_idx < len(row):
                        try:
                            self.bids[t].append(float(row[bid_idx]))
                            self.asks[t].append(float(row[ask_idx]))
                        except:
                            pass
        
        # Normalize lengths
        min_len = min(len(self.bids[t]) for t in self.tokens)
        for t in self.tokens:
            self.bids[t] = self.bids[t][:min_len]
            self.asks[t] = self.asks[t][:min_len]
        
        self.n_records = min_len
        print(f"Załadowano {self.n_records} rekordów, {len(self.tokens)} tokenów")
    
    def calculate_baseline(self) -> dict:
        """
        Oblicza baseline - ile każdego tokenu mogliśmy mieć na start.
        
        Start: 1 BTC
        Oblicz: ile SOL, ETH, itp. mogliśmy kupić za 1 BTC
        """
        # BTC na start
        btc_price = self.bids['BTCUSDT'][0]  # Bid price (selling BTC)
        
        baseline = {}
        
        for token in self.tokens:
            # Kupujemy token za BTC (sell BTC at bid, buy token at ask)
            # 1 BTC -> USDT (sell at bid) -> Token (buy at ask)
            usdt_after_sell = 1.0 * btc_price * (1 - self.SWAP_FEE)  # Po sprzedaży BTC
            token_price = self.asks[token][0]  # Ask (buy price)
            amount = usdt_after_sell / token_price  # Ile tokenów dostajemy
            
            baseline[token] = {
                'initial_amount': amount,
                'initial_price': token_price,
                'final_price': self.bids[token][-1],  # Bid at end
                'final_value_usdt': amount * self.bids[token][-1]
            }
        
        return baseline
    
    def run_strategy(self, 
                     lookback: int = 200,
                     threshold: float = 0.03,
                     min_interval: int = 20,
                     vs_btc_threshold: float = 0.01) -> dict:
        """
        Uruchamia strategię momentum.
        
        Zwraca:
        - final_amount: ile tokenów końcowych mamy
        - final_token: jaki to token
        - swap_history: historia wszystkich swapów
        - token_amounts: ile każdego tokenu mogliśmy mieć na każdym kroku
        """
        # Initialize
        holding = "BTCUSDT"
        amount = 1.0  # 1 BTC na start
        last_swap = 0
        swaps = []
        
        # Track ile każdego tokenu "teoretycznie" moglibyśmy mieć
        # (gdybyśmy od razu przeszli na ten token)
        token_amounts = {t: [] for t in self.tokens}
        
        for idx in range(lookback, self.n_records - 1):
            # Oblicz ile każdego tokenu moglibyśmy mieć teraz
            # (wartość w BTC / cena tokenu)
            current_btc_value = amount * self.bids[holding][idx]
            usdt_value = current_btc_value * (1 - self.SWAP_FEE)
            
            for token in self.tokens:
                token_price = self.asks[token][idx]
                theoretical_amount = usdt_value / token_price
                token_amounts[token].append(theoretical_amount)
            
            # Min interval check
            if idx - last_swap < min_interval:
                continue
            
            # Oblicz momentum dla wszystkich tokenów
            holding_mom = self._momentum(holding, idx, lookback)
            
            best_token = None
            best_score = float('-inf')
            
            for token in self.tokens:
                if token == holding:
                    continue
                
                token_mom = self._momentum(token, idx, lookback)
                btc_mom = self._momentum('BTCUSDT', idx, lookback)
                
                # Relative momentum vs holding
                rel_mom = token_mom - holding_mom
                # Vs BTC
                vs_btc = token_mom - btc_mom
                
                # Score = relative momentum * vs_btc
                score = rel_mom
                
                if score > best_score and vs_btc > vs_btc_threshold:
                    best_score = score
                    best_token = token
            
            # Wykonaj swap jeśli momentum > threshold
            if best_token and best_score > threshold:
                # Swap!
                # Selling holding -> USDT -> Buying best_token
                from_price = self.bids[holding][idx]  # Sell at bid
                to_price = self.asks[best_token][idx]  # Buy at ask
                
                # Calculate amounts
                usdt = amount * from_price * (1 - self.SWAP_FEE)
                new_amount = usdt / to_price
                
                swaps.append(Swap(
                    idx=idx,
                    from_token=holding,
                    to_token=best_token,
                    amount_in=amount,
                    amount_out=new_amount,
                    from_price=from_price,
                    to_price=to_price
                ))
                
                holding = best_token
                amount = new_amount
                last_swap = idx
        
        # Final state
        final_token = holding
        final_amount = amount
        final_btc_value = amount * self.bids[final_token][-1]
        
        # BTC buy&hold: 1 BTC -> ile BTC na końcu? Zawsze 1 BTC
        btc_final = 1.0
        
        # Porównanie
        gain_vs_btc = ((final_btc_value / btc_final) - 1) * 100
        
        return {
            'strategy': 'momentum',
            'params': {
                'lookback': lookback,
                'threshold': threshold,
                'min_interval': min_interval,
                'vs_btc_threshold': vs_btc_threshold
            },
            'initial_token': 'BTCUSDT',
            'initial_amount': 1.0,
            'final_token': final_token,
            'final_amount': final_amount,
            'final_amount_rounded': self._round_amount(final_amount),
            # Ile final tokenów mielibyśmy gdybyśmy od razu kupili i trzymali
            'baseline_final_amount': token_amounts[final_token][-1] if token_amounts[final_token] else 0,
            'total_swaps': len(swaps),
            'gain_vs_btc_pct': gain_vs_btc,
            'swaps': [
                {
                    'idx': s.idx,
                    'from': s.from_token,
                    'to': s.to_token,
                    'amount_in': s.amount_in,
                    'amount_out': self._round_amount(s.amount_out)
                }
                for s in swaps
            ]
        }
    
    def _momentum(self, token: str, idx: int, period: int) -> float:
        """Oblicza momentum (% change over period)."""
        if idx < period:
            return 0.0
        p1 = self.bids[token][idx - period]
        p2 = self.bids[token][idx]
        return (p2 - p1) / p1
    
    def _round_amount(self, amount: float) -> float:
        """Zaokrągla ilość tokenów."""
        if amount >= 1000:
            return round(amount, 2)
        elif amount >= 1:
            return round(amount, 4)
        elif amount >= 0.01:
            return round(amount, 6)
        else:
            return round(amount, 8)


def main():
    """Główna funkcja."""
    print("""
╔═══════════════════════════════════════════════════════════════╗
║     CORRECT BACKTESTER - liczy ILOŚĆ TOKENÓW              ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    # Load data
    bt = CorrectBacktester("market.csv")
    bt.load()
    
    # Calculate baseline
    print("\n" + "="*60)
    print("BASELINE (ile każdego tokenu mogliśmy mieć na start)")
    print("="*60)
    print(f"{'Token':<12} {'Initial Amount':>15} {'Start Price':>15} {'Final Price':>15}")
    print("-" * 60)
    
    baseline = bt.calculate_baseline()
    for token in sorted(baseline.keys(), key=lambda x: baseline[x]['initial_amount'], reverse=True):
        b = baseline[token]
        print(f"{token:<12} {b['initial_amount']:>15.6f} ${b['initial_price']:>14.2f} ${b['final_price']:>14.2f}")
    
    # Run strategy
    print("\n" + "="*60)
    print("TESTOWANIE STRATEGI")
    print("="*60)
    
    best_result = None
    
    for lookback in [100, 200, 300, 500]:
        for threshold in [0.01, 0.02, 0.03, 0.05]:
            for interval in [10, 20, 50]:
                result = bt.run_strategy(
                    lookback=lookback,
                    threshold=threshold,
                    min_interval=interval
                )
                
                if best_result is None or result['final_amount'] > best_result['final_amount']:
                    best_result = result
                    print(f"\n  NEW BEST!")
                    print(f"  Params: lookback={lookback}, threshold={threshold}, interval={interval}")
                    print(f"  Final: {result['final_amount_rounded']} {result['final_token']}")
                    print(f"  Swaps: {result['total_swaps']}")
    
    # Results
    print("\n" + "="*60)
    print("NAJLEPSZY WYNIK")
    print("="*60)
    print(f"\nInitial: 1.0000 BTCUSDT")
    print(f"Final:   {best_result['final_amount_rounded']} {best_result['final_token']}")
    print(f"Swaps:   {best_result['total_swaps']}")
    print(f"\nIlość tokenów końcowych: {best_result['final_amount_rounded']}")
    print(f"Ilość BTC buy&hold: 1.0000 BTC (zawsze 1 BTC)")
    print(f"\nGdybyśmy kupili i trzymali {best_result['final_token']} od początku:")
    print(f"  Mielibyśmy: {best_result['baseline_final_amount']:.6f} {best_result['final_token']}")
    
    # Save
    with open("output/correct_results.json", "w") as f:
        json.dump(best_result, f, indent=2)
    
    print(f"\nZapisano do: output/correct_results.json")


if __name__ == "__main__":
    main()
