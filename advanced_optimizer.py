#!/usr/bin/env python3
"""
Advanced Strategy Optimizer - lepsza wersja z wieloma strategiami

Strategie:
1. Momentum - podstawowa (swap do tokenu z wyższym momentum)
2. RSI Contrarian - kupuj gdy RSI niski, sprzedawaj gdy wysoki
3. Relative Strength - porównuj do BTC
4. Breakout - kupuj gdy przebija średnią

Oblicza gain WZGLĘDEM BTC buy&hold.
"""

import csv
import random
import json
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class StrategyParams:
    """Parametry strategii."""
    strategy_type: str = "momentum"  # momentum, rsi_contrarian, relative, breakout
    
    # Momentum params
    lookback: int = 100
    momentum_threshold: float = 0.02
    
    # RSI params
    rsi_period: int = 14
    rsi_buy: int = 30
    rsi_sell: int = 70
    
    # Filter params
    min_interval: int = 10
    min_momentum: float = 0.01
    
    # Relative strength
    vs_btc_threshold: float = 0.02


class DataLoader:
    """Ładowanie danych."""
    
    def __init__(self, filepath: str = "market.csv"):
        self.filepath = filepath
        self.tokens = []
        self.prices = {}  # bid prices
        self.n_records = 0
        
    def load(self):
        """Ładuje dane."""
        print("Ładowanie danych...")
        
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
        
        self.n_records = min(len(self.prices[t]) for t in self.tokens)
        print(f"Załadowano {self.n_records} rekordów, {len(self.tokens)} tokenów")
        
        # Oblicz zmiany procentowe
        self.returns = {}
        for t in self.tokens:
            self.returns[t] = []
            for i in range(1, len(self.prices[t])):
                ret = (self.prices[t][i] - self.prices[t][i-1]) / self.prices[t][i-1]
                self.returns[t].append(ret)
    
    def get_price(self, token: str, idx: int) -> float:
        return self.prices[token][idx]
    
    def get_return(self, token: str, idx: int) -> float:
        """Zwrot w danym momencie (indeks 0 = początek returns)."""
        if idx <= 0 or idx > len(self.returns[token]):
            return 0.0
        return self.returns[token][idx - 1]
    
    def momentum(self, token: str, idx: int, period: int) -> float:
        """Momentum = % change over period."""
        if idx < period:
            return 0.0
        p1 = self.prices[token][idx - period]
        p2 = self.prices[token][idx]
        return (p2 - p1) / p1
    
    def rsi(self, token: str, idx: int, period: int = 14) -> float:
        """RSI."""
        if idx < period + 1:
            return 50.0
        
        gains = []
        losses = []
        for i in range(idx - period, idx):
            r = self.get_return(token, i + 1)
            if r > 0:
                gains.append(r)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(r))
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
    
    def relative_strength(self, token: str, idx: int, period: int) -> float:
        """Relative strength vs BTC."""
        if idx < period:
            return 0.0
        
        token_mom = self.momentum(token, idx, period)
        btc_mom = self.momentum('BTCUSDT', idx, period)
        
        return token_mom - btc_mom
    
    def sma(self, token: str, idx: int, period: int) -> float:
        """Simple Moving Average."""
        if idx < period:
            return self.prices[token][idx]
        
        return sum(self.prices[token][idx - period + 1:idx + 1]) / period


class Backtester:
    """Backtester strategii."""
    
    def __init__(self, data: DataLoader):
        self.data = data
        self.SWAP_FEE = 0.0004  # 0.04% per leg
        
        # State
        self.holding = None
        self.amount = 0.0
        self.last_swap_idx = 0
        self.swaps = []
        self.equity = []
        
    def reset(self, start_token: str = "BTCUSDT", start_amount: float = 1.0):
        self.holding = start_token
        self.amount = start_amount
        self.last_swap_idx = 0
        self.swaps = []
        self.equity = []
    
    def execute_swap(self, to_token: str, idx: int) -> bool:
        """Wykonuje swap."""
        if to_token == self.holding:
            return False
        
        from_price = self.data.get_price(self.holding, idx)
        to_price = self.data.get_price(to_token, idx)
        
        usdt = self.amount * from_price * (1 - self.SWAP_FEE)
        self.amount = usdt / to_price
        
        self.swaps.append({
            'idx': idx,
            'from': self.holding,
            'to': to_token,
            'amount': self.amount
        })
        
        self.holding = to_token
        self.last_swap_idx = idx
        
        return True
    
    def get_value(self, idx: int) -> float:
        price = self.data.get_price(self.holding, idx)
        return self.amount * price
    
    def run_momentum(self, params: StrategyParams) -> dict:
        """Momentum strategy - swap to token with higher momentum."""
        self.reset()
        
        for idx in range(params.lookback, self.data.n_records - 1):
            # Min interval check
            if idx - self.last_swap_idx < params.min_interval:
                self.equity.append(self.get_value(idx))
                continue
            
            # Current momentum
            holding_mom = self.data.momentum(self.holding, idx, params.lookback)
            
            # Find best token
            best_token = None
            best_rel_mom = -999
            
            for token in self.data.tokens:
                if token == self.holding:
                    continue
                
                token_mom = self.data.momentum(token, idx, params.lookback)
                rel_mom = token_mom - holding_mom
                
                # Check vs BTC
                btc_mom = self.data.momentum('BTCUSDT', idx, params.lookback)
                vs_btc = token_mom - btc_mom
                
                if rel_mom > best_rel_mom and vs_btc > params.vs_btc_threshold:
                    best_rel_mom = rel_mom
                    best_token = token
            
            # Execute swap
            if best_token and best_rel_mom > params.momentum_threshold:
                self.execute_swap(best_token, idx)
            
            self.equity.append(self.get_value(idx))
        
        return self._get_results()
    
    def run_rsi_contrarian(self, params: StrategyParams) -> dict:
        """RSI Contrarian - buy oversold, sell overbought."""
        self.reset()
        
        for idx in range(params.rsi_period + 1, self.data.n_records - 1):
            if idx - self.last_swap_idx < params.min_interval:
                self.equity.append(self.get_value(idx))
                continue
            
            current_rsi = self.data.rsi(self.holding, idx, params.rsi_period)
            
            # Sell if overbought
            if current_rsi > params.rsi_sell:
                # Find most oversold token (that beats BTC)
                best_token = None
                best_rsi = 100
                
                for token in self.data.tokens:
                    if token == self.holding:
                        continue
                    
                    token_rsi = self.data.rsi(token, idx, params.rsi_period)
                    vs_btc = self.data.relative_strength(token, idx, params.lookback)
                    
                    if token_rsi < best_rsi and vs_btc > params.vs_btc_threshold:
                        best_rsi = token_rsi
                        best_token = token
                
                if best_token:
                    self.execute_swap(best_token, idx)
            
            # Buy if oversold
            elif current_rsi < params.rsi_buy:
                # Find strongest recovery candidate
                best_token = None
                best_score = -999
                
                for token in self.data.tokens:
                    if token == self.holding:
                        continue
                    
                    token_rsi = self.data.rsi(token, idx, params.rsi_period)
                    vs_btc = self.data.relative_strength(token, idx, params.lookback)
                    score = vs_btc - (50 - token_rsi) / 100  # Prefer oversold but with strength
                    
                    if score > best_score and vs_btc > params.vs_btc_threshold:
                        best_score = score
                        best_token = token
                
                if best_token:
                    self.execute_swap(best_token, idx)
            
            self.equity.append(self.get_value(idx))
        
        return self._get_results()
    
    def run_relative_strength(self, params: StrategyParams) -> dict:
        """Relative Strength vs BTC."""
        self.reset()
        
        for idx in range(params.lookback, self.data.n_records - 1):
            if idx - self.last_swap_idx < params.min_interval:
                self.equity.append(self.get_value(idx))
                continue
            
            # Find token outperforming BTC most
            best_token = None
            best_vs_btc = -999
            
            for token in self.data.tokens:
                if token == self.holding:
                    continue
                
                vs_btc = self.data.relative_strength(token, idx, params.lookback)
                
                if vs_btc > best_vs_btc and vs_btc > params.vs_btc_threshold:
                    best_vs_btc = vs_btc
                    best_token = token
            
            if best_token:
                self.execute_swap(best_token, idx)
            
            self.equity.append(self.get_value(idx))
        
        return self._get_results()
    
    def _get_results(self) -> dict:
        """Oblicza wyniki."""
        final_idx = self.data.n_records - 1
        final_value = self.get_value(final_idx)
        
        # BTC buy & hold
        btc_start = self.data.get_price('BTCUSDT', 100)
        btc_end = self.data.get_price('BTCUSDT', final_idx)
        btc_value = btc_end  # 1 BTC
        
        # Zyski
        gain_vs_btc = ((final_value / btc_value) - 1) * 100
        
        return {
            'holding': self.holding,
            'amount': self.amount,
            'final_value': final_value,
            'gain_vs_btc': gain_vs_btc,
            'n_swaps': len(self.swaps),
            'swaps': self.swaps[-20:],  # Last 20 swaps
            'equity': self.equity[-1000:]  # Last 1000 equity points
        }


def main():
    """Main."""
    import time
    
    print("""
╔═══════════════════════════════════════════════════════════════╗
║     ADVANCED STRATEGY OPTIMIZER v2                           ║
║     Szuka najlepszej strategii vs BTC buy&hold              ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    # Load data
    data = DataLoader("market.csv")
    data.load()
    
    # BTC performance check
    btc_start = data.get_price('BTCUSDT', 100)
    btc_end = data.get_price('BTCUSDT', data.n_records - 1)
    btc_loss = ((btc_end - btc_start) / btc_start) * 100
    print(f"\nBTC buy&hold: ${btc_start:.2f} → ${btc_end:.2f} ({btc_loss:+.2f}%)")
    print(f"Strategia musi być LEPSZA niż {btc_loss:+.2f}%")
    
    # Initialize backtester
    bt = Backtester(data)
    
    results = []
    
    print("\n" + "="*60)
    print("TESTOWANIE STRATEGI")
    print("="*60)
    
    # 1. Test Momentum
    print("\n[1/3] Momentum Strategy...")
    for lookback in [50, 100, 200, 500]:
        for threshold in [0.01, 0.02, 0.03, 0.05]:
            for interval in [10, 20, 50]:
                params = StrategyParams(
                    strategy_type="momentum",
                    lookback=lookback,
                    momentum_threshold=threshold,
                    min_interval=interval,
                    vs_btc_threshold=0.01
                )
                r = bt.run_momentum(params)
                r['params'] = params
                results.append(r)
                print(f"  Momentum L{lookback} T{threshold} I{interval}: {r['gain_vs_btc']:+.2f}% ({r['n_swaps']} swaps)")
    
    # 2. Test RSI Contrarian
    print("\n[2/3] RSI Contrarian Strategy...")
    for rsi_buy in [20, 25, 30]:
        for rsi_sell in [70, 75, 80]:
            for lookback in [50, 100]:
                params = StrategyParams(
                    strategy_type="rsi_contrarian",
                    lookback=lookback,
                    rsi_buy=rsi_buy,
                    rsi_sell=rsi_sell,
                    min_interval=10,
                    vs_btc_threshold=0.01
                )
                r = bt.run_rsi_contrarian(params)
                r['params'] = params
                results.append(r)
                print(f"  RSI ({rsi_buy}/{rsi_sell}) L{lookback}: {r['gain_vs_btc']:+.2f}% ({r['n_swaps']} swaps)")
    
    # 3. Test Relative Strength
    print("\n[3/3] Relative Strength Strategy...")
    for lookback in [50, 100, 200]:
        for threshold in [0.01, 0.02, 0.03]:
            params = StrategyParams(
                strategy_type="relative",
                lookback=lookback,
                vs_btc_threshold=threshold,
                min_interval=10
            )
            r = bt.run_relative_strength(params)
            r['params'] = params
            results.append(r)
            print(f"  Relative L{lookback} T{threshold}: {r['gain_vs_btc']:+.2f}% ({r['n_swaps']} swaps)")
    
    # Sort by gain
    results.sort(key=lambda x: x['gain_vs_btc'], reverse=True)
    
    # Best result
    best = results[0]
    
    print("\n" + "="*60)
    print("NAJLEPSZA STRATEGIA")
    print("="*60)
    print(f"Type: {best['params'].strategy_type}")
    print(f"Gain vs BTC: {best['gain_vs_btc']:+.2f}%")
    print(f"Final: {best['amount']:.4f} {best['holding']} = ${best['final_value']:,.2f}")
    print(f"Swaps: {best['n_swaps']}")
    print(f"\nParametry:")
    print(f"  lookback: {best['params'].lookback}")
    print(f"  threshold: {best['params'].momentum_threshold}")
    print(f"  min_interval: {best['params'].min_interval}")
    
    # Save results
    output = {
        'best': {
            'strategy_type': best['params'].strategy_type,
            'gain_vs_btc': best['gain_vs_btc'],
            'final_value': best['final_value'],
            'n_swaps': best['n_swaps'],
            'params': best['params'].__dict__
        },
        'top_10': [
            {
                'gain_vs_btc': r['gain_vs_btc'],
                'type': r['params'].strategy_type,
                'n_swaps': r['n_swaps'],
                'params': r['params'].__dict__
            }
            for r in results[:10]
        ],
        'btc_performance': {
            'start': btc_start,
            'end': btc_end,
            'change': btc_loss
        }
    }
    
    import os
    os.makedirs('output', exist_ok=True)
    with open('output/advanced_results.json', 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"\nZapisano do: output/advanced_results.json")
    
    # Show top 5
    print("\n" + "="*60)
    print("TOP 5 STRATEGIÍW")
    print("="*60)
    for i, r in enumerate(results[:5]):
        p = r['params']
        print(f"\n#{i+1} {r['gain_vs_btc']:+.2f}% ({r['params'].strategy_type})")
        print(f"   {p}")


if __name__ == "__main__":
    main()
