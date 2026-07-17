#!/usr/bin/env python3
"""
Strategy Optimizer - znajduje najlepsze strategie swapowania

1. Ładuje dane z market.csv
2. Testuje różne kombinacje parametrów
3. Oblicza gain WZGLĘDEM BTC buy&hold
4. Zapisuje najlepsze strategie
"""

import csv
import random
import json
from dataclasses import dataclass, field
from typing import Optional
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing as mp


# Stałe
SWAP_FEE = 0.0004  # 0.04% za leg
MID_PRICE = True    # Używaj mid prices


@dataclass
class StrategyParams:
    """Parametry strategii."""
    # Parametry momentum
    lookback_period: int = 100      # Okres obliczania momentum
    momentum_threshold: float = 0.02  # Min. różnica momentum do swapa
    min_momentum: float = 0.01       # Min. momentum żeby rozważyć swap
    
    # Filtry
    min_swap_interval: int = 10       # Min. records między swapami
    rsi_oversold: int = 30           # RSI poniżej którego kupujemy
    rsi_overbought: int = 70          # RSI powyżej którego sprzedajemy
    
    # Volatility filter
    volatility_threshold: float = 0.01  # Min. zmienność żeby rozważyć swap


@dataclass
class StrategyResult:
    """Wynik strategii."""
    params: StrategyParams
    total_swaps: int = 0
    final_token: str = ""
    final_amount: float = 0.0
    final_value: float = 0.0
    
    # Gains
    gain_vs_btc: float = 0.0      # Ile % lepiej niż BTC
    gain_vs_baseline: float = 0.0 # Ile % vs początkowa wartość
    alpha: float = 0.0            # Alpha ponad rynek
    
    # Metryki
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    
    # Historia
    swap_history: list = field(default_factory=list)


class DataLoader:
    """Ładowanie i przetwarzanie danych rynkowych."""
    
    def __init__(self, filepath: str = "market.csv"):
        self.filepath = filepath
        self.tokens = []
        self.prices = {}  # token -> list of (bid, ask)
        self.mids = {}    # token -> list of mid prices
        self.n_records = 0
        
    def load(self):
        """Ładuje dane z CSV."""
        print("Ładowanie danych...")
        
        token_cols = {}
        
        with open(self.filepath, 'r') as f:
            reader = csv.reader(f)
            header = next(reader)
            
            for i, col in enumerate(header):
                if col.endswith("_BID"):
                    token = col.replace("_BID", "")
                    self.tokens.append(token)
                    token_cols[token] = i
                    self.prices[token] = []
                    self.mids[token] = []
            
            for row in reader:
                try:
                    for token, idx in token_cols.items():
                        bid_str = row[idx].strip()
                        ask_str = row[idx + 1].strip()
                        
                        if not bid_str or not ask_str:
                            continue
                        
                        bid = float(bid_str)
                        ask = float(ask_str)
                        mid = (bid + ask) / 2
                        
                        self.prices[token].append((bid, ask))
                        self.mids[token].append(mid)
                except (ValueError, IndexError):
                    continue
        
        self.n_records = len(self.mids[self.tokens[0]])
        print(f"Załadowano {self.n_records} rekordów, {len(self.tokens)} tokenów")
        
    def get_mid(self, token: str, idx: int) -> float:
        """Pobiera mid price."""
        return self.mids[token][idx]
    
    def calculate_momentum(self, token: str, idx: int, period: int) -> float:
        """Oblicza momentum (zmiana % vs period ago)."""
        if idx < period:
            return 0.0
        current = self.mids[token][idx]
        past = self.mids[token][idx - period]
        return (current - past) / past
    
    def calculate_rsi(self, token: str, idx: int, period: int = 14) -> float:
        """Oblicza RSI."""
        if idx < period + 1:
            return 50.0  # Neutral
        
        gains = []
        losses = []
        
        for i in range(idx - period, idx):
            change = self.mids[token][i + 1] - self.mids[token][i]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def calculate_volatility(self, token: str, idx: int, period: int = 20) -> float:
        """Oblicza zmienność (stddev % change)."""
        if idx < period:
            return 0.0
        
        returns = []
        for i in range(idx - period, idx):
            ret = (self.mids[token][i + 1] - self.mids[token][i]) / self.mids[token][i]
            returns.append(ret)
        
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / len(returns)
        return variance ** 0.5


class Backtester:
    """Backtester strategii."""
    
    def __init__(self, data: DataLoader, start_token: str = "BTCUSDT", 
                 start_amount: float = 1.0, start_idx: int = 100):
        self.data = data
        self.start_token = start_token
        self.start_amount = start_amount
        self.start_idx = start_idx  # Zaczynamy po warmup period
        
        # Stan portfolio
        self.holding_token = start_token
        self.holding_amount = start_amount
        self.last_swap_idx = 0
        self.swap_history = []
        
        # Metryki
        self.equity_curve = []
        
    def reset(self):
        """Resetuje stan."""
        self.holding_token = self.start_token
        self.holding_amount = self.start_amount
        self.last_swap_idx = 0
        self.swap_history = []
        self.equity_curve = []
    
    def get_value(self, idx: int) -> float:
        """Pobiera bieżącą wartość w USDT."""
        mid = self.data.get_mid(self.holding_token, idx)
        return self.holding_amount * mid
    
    def execute_swap(self, to_token: str, idx: int) -> bool:
        """Wykonuje swap."""
        if to_token == self.holding_token:
            return False
        
        # Pobierz ceny mid
        from_mid = self.data.get_mid(self.holding_token, idx)
        to_mid = self.data.get_mid(to_token, idx)
        
        # Oblicz swap z fee
        usdt_value = self.holding_amount * from_mid
        after_fee = usdt_value * (1 - SWAP_FEE)
        new_amount = after_fee / to_mid
        
        # Zapisz swap
        self.swap_history.append({
            'idx': idx,
            'from': self.holding_token,
            'to': to_token,
            'amount_in': self.holding_amount,
            'amount_out': new_amount
        })
        
        # Aktualizuj stan
        self.holding_token = to_token
        self.holding_amount = new_amount
        self.last_swap_idx = idx
        
        return True
    
    def run(self, params: StrategyParams) -> StrategyResult:
        """Uruchamia backtest z danymi parametrami."""
        self.reset()
        
        # Pobierz początkową wartość BTC (dla porównania)
        btc_start_value = self.data.get_mid("BTCUSDT", self.start_idx) * self.start_amount
        btc_current = btc_start_value
        
        # Equity curve dla Sharpe ratio
        equity_values = []
        
        # Główna pętla
        for idx in range(self.start_idx, self.data.n_records - 1):
            # Aktualizuj equity
            current_value = self.get_value(idx)
            equity_values.append(current_value)
            
            # Sprawdź czy można swapować (min interval)
            if idx - self.last_swap_idx < params.min_swap_interval:
                continue
            
            # Oblicz momentum dla wszystkich tokenów
            best_token = None
            best_score = float('-inf')
            
            for token in self.data.tokens:
                if token == self.holding_token:
                    continue
                
                # Momentum
                holding_mom = self.data.calculate_momentum(
                    self.holding_token, idx, params.lookback_period)
                token_mom = self.data.calculate_momentum(
                    token, idx, params.lookback_period)
                
                rel_momentum = token_mom - holding_mom
                
                # RSI filter
                rsi = self.data.calculate_rsi(token, idx)
                if rsi < params.rsi_oversold or rsi > params.rsi_overbought:
                    continue
                
                # Volatility filter
                volatility = self.data.calculate_volatility(token, idx)
                if volatility < params.volatility_threshold:
                    continue
                
                # Momentum threshold
                if rel_momentum < params.min_momentum:
                    continue
                
                # Score = relative momentum * volatility (diversyfikacja)
                score = rel_momentum * (1 + volatility)
                
                if score > best_score:
                    best_score = score
                    best_token = token
            
            # Wykonaj swap jeśli znaleziono
            if best_token and best_score > params.momentum_threshold:
                self.execute_swap(best_token, idx)
        
        # Oblicz wyniki
        final_idx = self.data.n_records - 1
        final_mid = self.data.get_mid(self.holding_token, final_idx)
        final_value = self.holding_amount * final_mid
        
        # BTC buy & hold
        btc_final = self.data.get_mid("BTCUSDT", final_idx)
        btc_final_value = self.start_amount * btc_final
        
        # Zyski
        gain_vs_btc = ((final_value / btc_final_value) - 1) * 100
        gain_vs_baseline = ((final_value / btc_start_value) - 1) * 100
        
        # Sharpe ratio (uproszczony)
        if len(equity_values) > 1:
            returns = [(equity_values[i] - equity_values[i-1]) / equity_values[i-1] 
                      for i in range(1, len(equity_values))]
            mean_ret = sum(returns) / len(returns)
            std_ret = (sum((r - mean_ret) ** 2 for r in returns) / len(returns)) ** 0.5
            sharpe = (mean_ret / std_ret * (252 * 24)) ** 0.5 if std_ret > 0 else 0
        else:
            sharpe = 0
        
        return StrategyResult(
            params=params,
            total_swaps=len(self.swap_history),
            final_token=self.holding_token,
            final_amount=self.holding_amount,
            final_value=final_value,
            gain_vs_btc=gain_vs_btc,
            gain_vs_baseline=gain_vs_baseline,
            alpha=gain_vs_btc,
            sharpe_ratio=sharpe,
            swap_history=self.swap_history
        )


def test_strategy(args):
    """Testuje pojedynczą strategię (dla parallel execution)."""
    params, data_path = args
    data = DataLoader(data_path)
    data.load()
    
    backtester = Backtester(data)
    result = backtester.run(params)
    
    return result


def generate_random_params() -> StrategyParams:
    """Generuje losowe parametry."""
    return StrategyParams(
        lookback_period=random.choice([50, 100, 150, 200, 300]),
        momentum_threshold=random.uniform(0.005, 0.05),
        min_momentum=random.uniform(0.001, 0.02),
        min_swap_interval=random.choice([5, 10, 20, 30, 50]),
        rsi_oversold=random.choice([20, 25, 30, 35]),
        rsi_overbought=random.choice([65, 70, 75, 80]),
        volatility_threshold=random.uniform(0.005, 0.03)
    )


def main():
    """Główna funkcja."""
    import time
    
    print("""
╔═══════════════════════════════════════════════════════════════╗
║        STRATEGY OPTIMIZER                                     ║
║        Szuka najlepszych strategii swapowania                ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    data_path = "market.csv"
    
    # Ładuj dane raz
    print("Krok 1: Ładowanie danych...")
    data = DataLoader(data_path)
    data.load()
    
    # Parametry
    n_strategies = 100
    n_parallel = mp.cpu_count()
    
    print(f"\nKrok 2: Testowanie {n_strategies} strategii...")
    print(f"Pusta pamięć: {n_parallel} CPU")
    
    results = []
    best = None
    
    start_time = time.time()
    
    for i in range(n_strategies):
        # Generuj losowe parametry
        params = generate_random_params()
        
        # Testuj
        backtester = Backtester(data)
        result = backtester.run(params)
        results.append(result)
        
        # Aktualizuj best
        if best is None or result.gain_vs_btc > best.gain_vs_btc:
            best = result
            print(f"  [{i+1}/{n_strategies}] NEW BEST! Gain vs BTC: {result.gain_vs_btc:+.2f}% "
                  f"({result.total_swaps} swaps)")
        
        if (i + 1) % 20 == 0:
            elapsed = time.time() - start_time
            print(f"  Postęp: {i+1}/{n_strategies} ({elapsed:.1f}s)")
    
    elapsed = time.time() - start_time
    
    # Sortuj wyniki
    results.sort(key=lambda x: x.gain_vs_btc, reverse=True)
    
    # Top 10
    print(f"\n{'='*60}")
    print("TOP 10 STRATEGIÍW")
    print(f"{'='*60}")
    
    for i, r in enumerate(results[:10]):
        p = r.params
        print(f"\n#{i+1} - Gain vs BTC: {r.gain_vs_btc:+.2f}%")
        print(f"   Final: {r.final_amount:.4f} {r.final_token} = ${r.final_value:,.2f}")
        print(f"   Swaps: {r.total_swaps}")
        print(f"   Params: lookback={p.lookback_period}, mom_thresh={p.momentum_threshold:.4f}, "
              f"min_swap={p.min_swap_interval}, rsi=({p.rsi_oversold}/{p.rsi_overbought})")
    
    # Zapisz najlepsze
    best_result = results[0]
    
    output = {
        "best_strategy": {
            "gain_vs_btc": best_result.gain_vs_btc,
            "gain_vs_baseline": best_result.gain_vs_baseline,
            "final_token": best_result.final_token,
            "final_value": best_result.final_value,
            "total_swaps": best_result.total_swaps,
            "params": {
                "lookback_period": best_result.params.lookback_period,
                "momentum_threshold": best_result.params.momentum_threshold,
                "min_momentum": best_result.params.min_momentum,
                "min_swap_interval": best_result.params.min_swap_interval,
                "rsi_oversold": best_result.params.rsi_oversold,
                "rsi_overbought": best_result.params.rsi_overbought,
                "volatility_threshold": best_result.params.volatility_threshold
            },
            "swap_history": best_result.swap_history
        },
        "all_results": [
            {
                "gain_vs_btc": r.gain_vs_btc,
                "gain_vs_baseline": r.gain_vs_baseline,
                "total_swaps": r.total_swaps,
                "params": r.params.__dict__
            }
            for r in results[:50]
        ],
        "stats": {
            "n_strategies_tested": n_strategies,
            "elapsed_seconds": elapsed,
            "strategies_per_second": n_strategies / elapsed
        }
    }
    
    with open("output/optimization_results.json", "w") as f:
        json.dump(output, f, indent=2)
    
    print(f"\n{'='*60}")
    print(f"NAJLEPSZA STRATEGIA")
    print(f"{'='*60}")
    print(f"Gain vs BTC: {best_result.gain_vs_btc:+.2f}%")
    print(f"Gain vs Start: {best_result.gain_vs_baseline:+.2f}%")
    print(f"Final: {best_result.final_amount:.4f} {best_result.final_token}")
    print(f"Swaps: {best_result.total_swaps}")
    
    print(f"\nZapisano do: output/optimization_results.json")
    print(f"Czas: {elapsed:.1f} sekund ({n_strategies/elapsed:.1f} strategii/sek)")


if __name__ == "__main__":
    main()
