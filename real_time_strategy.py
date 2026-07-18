#!/usr/bin/env python3
"""
REAL-TIME STRATEGY SYSTEM

Symulacja dokładnie odwzorowująca realny trading:
- Timestamp po timestampie (dane "płyną" jak z API)
- Decyzje na podstawie TYLKO przeszłych danych
- Brak lookahead bias
- Zapis zwycięskich strategii
"""

import csv
import json
import os
import time
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable
from datetime import datetime

FEE = 0.9996 * 0.9996  # 0.08% za swap


@dataclass
class Strategy:
    """Strategia handlowa."""
    name: str
    lookback: int
    threshold: float
    interval: int
    
    # Opcjonalne parametry
    min_swaps: int = 0
    max_swaps: int = 9999
    use_trailing: bool = False
    
    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'lookback': self.lookback,
            'threshold': self.threshold,
            'interval': self.interval,
            'min_swaps': self.min_swaps,
            'max_swaps': self.max_swaps
        }


@dataclass
class Swap:
    """Pojedynczy swap."""
    timestamp_idx: int
    from_token: str
    to_token: str
    from_amount: float
    to_amount: float
    holding_momentum: float
    target_momentum: float
    confidence: float


@dataclass 
class TradingState:
    """Stan tradingu w danym momencie."""
    timestamp_idx: int
    holding: str
    amount: float
    usdt_value: float


class RealTimeDataStream:
    """
    Symuluje stream danych - tak jakbymy dostawali z API.
    DANE SĄ TYLKO DO ODCZYTU - nie zaglądamy w przyszłość!
    """
    
    def __init__(self, filepath: str = "market.csv"):
        self.tokens = []
        self.prices = {}  # Lista cen dla każdego tokena
        self.n_records = 0
        
        self._load_data(filepath)
        
    def _load_data(self, filepath: str):
        """Ładowanie danych."""
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
                            self.prices[t].append(0)
        
        self.n_records = min(len(self.prices[t]) for t in self.tokens)
    
    def get_price(self, token: str, at_idx: int) -> float:
        """Pobiera cenę w danym momencie (tylko przeszłość!)."""
        if at_idx >= self.n_records:
            raise IndexError(f"Index {at_idx} out of range")
        return self.prices[token][at_idx]
    
    def get_momentum(self, token: str, at_idx: int, period: int) -> float:
        """
        Oblicza momentum - patrzy TYLKO wstecz!
        """
        if at_idx < period:
            return 0.0
        
        current = self.prices[token][at_idx]
        past = self.prices[token][at_idx - period]
        
        if past == 0:
            return 0.0
            
        return (current - past) / past
    
    def get_historical_prices(self, token: str, at_idx: int, lookback: int) -> List[float]:
        """Zwraca ceny z ostatnich `lookback` okresów (bez current)."""
        start = max(0, at_idx - lookback)
        return self.prices[token][start:at_idx]
    
    def iterate(self, start: int = 100):
        """
        Generator - zwraca kolejne timestamy jak z API.
        Używaj TYLKO tego do iteracji!
        """
        for idx in range(start, self.n_records):
            yield idx


class RealTimeStrategy:
    """
    Strategia działająca w czasie rzeczywistym.
    
    W KAŻDYM KROCKU:
    1. Dostajesz nowy timestamp
    2. Możesz czytać TYLKO dane do tego timestampu
    3. Podejmujesz decyzję
    """
    
    def __init__(self, strategy: Strategy, data: RealTimeDataStream):
        self.strategy = strategy
        self.data = data
        
        self.swaps: List[Swap] = []
        self.last_swap_idx = 0
        
    def should_swap(self, at_idx: int, current_holding: str) -> Optional[tuple]:
        """
        Sprawdza czy powinniśmy wykonać swap.
        Zwraca (target_token, confidence) lub None.
        
        TA METODA PATRZY TYLKO W PRZESZŁOŚĆ!
        """
        # Min interval
        if at_idx - self.last_swap_idx < self.strategy.interval:
            return None
        
        lb = self.strategy.lookback
        th = self.strategy.threshold
        
        # Oblicz momentum dla current holding
        holding_mom = self.data.get_momentum(current_holding, at_idx, lb)
        
        # Znajdź token tracący najmniej
        best_token = None
        best_mom = 999
        best_confidence = 0
        
        for token in self.data.tokens:
            if token == current_holding:
                continue
            
            token_mom = self.data.get_momentum(token, at_idx, lb)
            
            # Token musi tracić MNIEJ niż holding
            if token_mom < best_mom and token_mom < holding_mom:
                best_mom = token_mom
                best_token = token
                best_confidence = holding_mom - token_mom
        
        # Sprawdź threshold
        if best_token and best_confidence > th:
            return (best_token, best_confidence)
        
        return None
    
    def execute_swap(self, at_idx: int, from_token: str, to_token: str, 
                    current_amount: float) -> float:
        """
        Wykonuje swap i zwraca nową ilość tokenów.
        """
        from_price = self.data.get_price(from_token, at_idx)
        to_price = self.data.get_price(to_token, at_idx)
        
        # Jeśli cena jest 0, nie wykonuj swap
        if from_price <= 0 or to_price <= 0:
            return current_amount
        
        holding_mom = self.data.get_momentum(from_token, at_idx, self.strategy.lookback)
        to_mom = self.data.get_momentum(to_token, at_idx, self.strategy.lookback)
        
        usdt = current_amount * from_price * FEE
        new_amount = usdt / to_price if to_price > 0 else current_amount
        
        swap = Swap(
            timestamp_idx=at_idx,
            from_token=from_token,
            to_token=to_token,
            from_amount=current_amount,
            to_amount=new_amount,
            holding_momentum=holding_mom,
            target_momentum=to_mom,
            confidence=holding_mom - to_mom
        )
        
        self.swaps.append(swap)
        self.last_swap_idx = at_idx
        
        return new_amount


class Backtester:
    """
    Backtester działający dokładnie jak realny trading.
    """
    
    def __init__(self, data: RealTimeDataStream):
        self.data = data
        
    def run(self, strategy: Strategy, start_idx: int = 100, end_idx: int = None) -> dict:
        """
        Uruchamia backtest - timestamp po timestampie.
        """
        if end_idx is None:
            end_idx = self.data.n_records - 1
        
        # Inicjalizacja
        rt_strategy = RealTimeStrategy(strategy, self.data)
        
        holding = "BTCUSDT"
        amount = 1.0
        
        # Baseline - ile każdego tokena gdybyśmy kupili na start
        btc_price = self.data.get_price('BTCUSDT', start_idx)
        usdt_start = 1.0 * btc_price * FEE
        baseline = {}
        for token in self.data.tokens:
            token_price = self.data.get_price(token, start_idx)
            baseline[token] = usdt_start / token_price
        
        # Tracking
        actual_equiv = {t: 0.0 for t in self.data.tokens}
        
        # ITERACJA PO TYM CZASIE - DOKŁADNIE JAK W REALNYM TRADINGU!
        for idx in self.data.iterate(start_idx):
            if idx >= end_idx:
                break
            
            # Oblicz aktualne ekwiwalenty
            current_value = amount * self.data.get_price(holding, idx)
            for token in self.data.tokens:
                token_price = self.data.get_price(token, idx)
                if token_price > 0:
                    actual_equiv[token] = current_value / token_price
            
            # Sprawdź czy swap
            swap_decision = rt_strategy.should_swap(idx, holding)
            
            if swap_decision:
                target_token, confidence = swap_decision
                amount = rt_strategy.execute_swap(idx, holding, target_token, amount)
                holding = target_token
        
        # Final actual equivalents
        current_value = amount * self.data.get_price(holding, end_idx)
        for token in self.data.tokens:
            token_price = self.data.get_price(token, end_idx)
            if token_price > 0:
                actual_equiv[token] = current_value / token_price
        
        # Buduj macierz
        matrix = []
        for token in self.data.tokens:
            bl = baseline[token]
            ac = actual_equiv[token]
            gain = ((ac / bl) - 1) * 100 if bl > 0 else 0
            
            matrix.append({
                'token': token,
                'baseline': bl,
                'actual': ac,
                'gain_pct': gain,
                'is_final': token == holding
            })
        
        matrix.sort(key=lambda x: x['gain_pct'], reverse=True)
        
        # Final value
        final_value = amount * self.data.get_price(holding, end_idx)
        btc_final = self.data.get_price('BTCUSDT', end_idx)
        
        return {
            'strategy': strategy.to_dict(),
            'summary': {
                'start_token': 'BTCUSDT',
                'start_amount': 1.0,
                'final_token': holding,
                'final_amount': amount,
                'final_value': final_value,
                'vs_btc': ((final_value / btc_final) - 1) * 100,
                'n_swaps': len(rt_strategy.swaps)
            },
            'matrix': matrix,
            'swaps': [
                {
                    'idx': s.timestamp_idx,
                    'from': s.from_token,
                    'to': s.to_token,
                    'confidence': s.confidence
                }
                for s in rt_strategy.swaps[-30:]
            ]
        }


class StrategyOptimizer:
    """
    Optymalizator strategii z zapisem zwycięskich.
    """
    
    def __init__(self, data: RealTimeDataStream):
        self.data = data
        self.backtester = Backtester(data)
        self.winners: List[dict] = []
        
        os.makedirs('output/strategies', exist_ok=True)
        
    def test_single(self, strategy: Strategy) -> dict:
        """Testuje pojedynczą strategię."""
        return self.backtester.run(strategy)
    
    def test_grid(self) -> List[dict]:
        """Testuje grid wszystkich kombinacji."""
        results = []
        
        lookbacks = [3, 5, 7, 10, 15, 20]
        thresholds = [0.02, 0.025, 0.03, 0.035, 0.04, 0.05]
        intervals = [5, 8, 10, 12, 15, 20]
        
        total = len(lookbacks) * len(thresholds) * len(intervals)
        print(f"Testing {total} combinations...")
        
        for i, lb in enumerate(lookbacks):
            for th in thresholds:
                for iv in intervals:
                    strategy = Strategy(
                        name=f"RS_L{lb}_T{int(th*1000)}_I{iv}",
                        lookback=lb,
                        threshold=th,
                        interval=iv
                    )
                    
                    result = self.backtester.run(strategy)
                    results.append(result)
        
        # Sortuj po vs_btc
        results.sort(key=lambda x: x['summary']['vs_btc'], reverse=True)
        
        return results
    
    def walk_forward_test(self) -> dict:
        """
        Walk-forward test - testuj na 4 niezależnych okresach.
        """
        periods = [
            (100, 60000, "OK1"),
            (60000, 120000, "OK2"),
            (120000, 180000, "OK3"),
            (180000, self.data.n_records - 1, "OK4"),
        ]
        
        lookbacks = [5, 7, 10]
        thresholds = [0.025, 0.03, 0.035]
        intervals = [10, 12, 15]
        
        best_result = None
        best_min_gain = -999
        
        for lb in lookbacks:
            for th in thresholds:
                for iv in intervals:
                    gains = []
                    
                    for start, end, name in periods:
                        strategy = Strategy(
                            name=f"WF_L{lb}_T{int(th*1000)}_I{iv}",
                            lookback=lb,
                            threshold=th,
                            interval=iv
                        )
                        
                        result = self.backtester.run(strategy, start, end)
                        gains.append(result['summary']['vs_btc'])
                    
                    min_gain = min(gains)
                    
                    if min_gain > best_min_gain:
                        best_min_gain = min_gain
                        best_result = {
                            'params': (lb, th, iv),
                            'gains': gains,
                            'min_gain': min_gain,
                            'avg_gain': sum(gains) / len(gains)
                        }
        
        return best_result
    
    def save_winner(self, strategy: Strategy, result: dict):
        """Zapisuje zwycięską strategię."""
        winner = {
            'strategy': strategy.to_dict(),
            'result': {
                'vs_btc': result['summary']['vs_btc'],
                'final_token': result['summary']['final_token'],
                'final_value': result['summary']['final_value'],
                'n_swaps': result['summary']['n_swaps'],
                'timestamp': datetime.now().isoformat()
            }
        }
        
        self.winners.append(winner)
        
        # Zapisz do pliku
        filename = f"output/strategies/{strategy.name}_{int(time.time())}.json"
        with open(filename, 'w') as f:
            json.dump(winner, f, indent=2)
        
        # Aktualizuj główny plik
        with open('output/strategies/WINNERS.json', 'w') as f:
            json.dump({'winners': self.winners}, f, indent=2)
        
        print(f"Saved winner: {strategy.name}")
        return filename


def main():
    print("""
╔═══════════════════════════════════════════════════════════════╗
║     REAL-TIME STRATEGY SYSTEM                             ║
║     Timestamp by timestamp - dokładnie jak w realnym      ║
║     tradingu. Bez lookahead bias!                          ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    # Load data
    print("Loading data...")
    data = RealTimeDataStream("market.csv")
    print(f"Loaded {data.n_records} records, {len(data.tokens)} tokens")
    
    optimizer = StrategyOptimizer(data)
    
    # === WALK-FORWARD TEST ===
    print()
    print("=" * 70)
    print("WALK-FORWARD TEST")
    print("=" * 70)
    
    wf = optimizer.walk_forward_test()
    print(f"Best: L{wf['params'][0]} T{wf['params'][1]} I{wf['params'][2]}")
    print(f"Gains: {[f'{g:+.1f}%' for g in wf['gains']]}")
    print(f"Min: {wf['min_gain']:+.1f}%, Avg: {wf['avg_gain']:+.1f}%")
    
    # === FULL TEST WITH BEST ===
    print()
    print("=" * 70)
    print("FULL TEST (cały okres)")
    print("=" * 70)
    
    best_strategy = Strategy(
        name="CHAMPION_WF",
        lookback=wf['params'][0],
        threshold=wf['params'][1],
        interval=wf['params'][2]
    )
    
    result = optimizer.test_single(best_strategy)
    
    print(f"Strategy: L{best_strategy.lookback} T{best_strategy.threshold*100:.1f}% I{best_strategy.interval}")
    print(f"Final token: {result['summary']['final_token']}")
    print(f"Final value: ${result['summary']['final_value']:,.2f}")
    print(f"vs BTC: {result['summary']['vs_btc']:+.1f}%")
    print(f"Swaps: {result['summary']['n_swaps']}")
    
    # Save as winner
    optimizer.save_winner(best_strategy, result)
    
    # === MATRIX ===
    print()
    print("=" * 70)
    print("MACIERZ WYNIKÓW")
    print("=" * 70)
    print()
    print(f"{'TOKEN':<12} {'BASELINE':>18} {'ACTUAL':>18} {'GAIN %':>10}")
    print("-" * 60)
    
    for row in result['matrix'][:10]:
        marker = " ◄◄" if row['is_final'] else ""
        print(f"{row['token']:<12} {row['baseline']:>18,.2f} {row['actual']:>18,.2f} {row['gain_pct']:>+9.1f}%{marker}")
    
    # === SAVE FULL RESULT ===
    with open('output/real_time_results.json', 'w') as f:
        json.dump(result, f, indent=2)
    
    print()
    print(f"Saved to: output/real_time_results.json")
    print(f"Winners saved to: output/strategies/WINNERS.json")


if __name__ == "__main__":
    main()
