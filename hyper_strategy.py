#!/usr/bin/env python3
"""
HYPER STRATEGY - Łączenie strategii w meta-strategie

Strategie składowe:
1. Relative Strength (bazowa) - unikaj przegranych
2. Multi-timeframe - wektor z różnych okresów
3. Consensus voting - głosowanie wielu strategii
4. Regime detection - wykrywanie trendu rynku

Idea: Hiperstrategia = średnia ważona głosów wielu strategii
"""

import csv
import json
import time
from dataclasses import dataclass, field
from typing import List, Dict, Tuple
from collections import defaultdict

FEE = 0.9996 * 0.9996


@dataclass
class Strategy:
    """Pojedyncza strategia."""
    name: str
    lookback: int
    threshold: float
    interval: int
    weight: float = 1.0


@dataclass 
class Vote:
    """Głos strategii na dany token."""
    token: str
    score: float
    strategy_name: str


@dataclass
class HyperParams:
    """Parametry hiperstrategii."""
    # Strategie składowe
    strategies: List[Strategy] = field(default_factory=list)
    
    # Tryb łączenia
    combine_mode: str = "consensus"  # consensus, weighted, regime
    
    # Regime detection
    detect_trend: bool = True
    trend_lookback: int = 50
    
    # Multi-timeframe
    timeframes: List[int] = field(default_factory=lambda: [10, 20, 50])


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
    
    def detect_regime(self, idx, lookback=50):
        """Wykryj regime rynku: bullish, bearish, neutral."""
        btc_now = self.prices['BTCUSDT'][idx]
        btc_then = self.prices['BTCUSDT'][max(0, idx - lookback)]
        change = (btc_now - btc_then) / btc_then
        
        if change > 0.05:  # > 5% wzrost
            return "bullish"
        elif change < -0.05:  # > 5% spadek
            return "bearish"
        else:
            return "neutral"


class HyperStrategy:
    """
    Hiperstrategia - łączy wiele strategii w jedną.
    """
    
    def __init__(self, data: DataLoader, params: HyperParams):
        self.data = data
        self.params = params
        
        # Inicjalizuj strategie
        self.strategies = params.strategies or [
            Strategy("RS_10", lookback=10, threshold=0.015, interval=15),
            Strategy("RS_20", lookback=20, threshold=0.020, interval=15),
            Strategy("RS_50", lookback=50, threshold=0.025, interval=20),
            Strategy("Fast", lookback=5, threshold=0.010, interval=10),
            Strategy("Slow", lookback=100, threshold=0.030, interval=30),
        ]
    
    def get_votes(self, idx: int) -> List[Vote]:
        """
        Pobierz głosy od wszystkich strategii na danym idx.
        """
        votes = []
        regime = self.data.detect_regime(idx, self.params.trend_lookback)
        
        for strat in self.strategies:
            # Regime-aware: zmień threshold w zależności od regime
            if self.params.detect_trend:
                if regime == "bearish":
                    threshold = strat.threshold * 0.8  # Agresywniejszy w bearish
                elif regime == "bullish":
                    threshold = strat.threshold * 1.2  # Konserwatywniejszy w bullish
                else:
                    threshold = strat.threshold
            else:
                threshold = strat.threshold
            
            # Momentum dla wszystkich tokenów
            best_token = None
            best_score = -999
            
            for token in self.data.tokens:
                mom = self.data.momentum(token, idx, strat.lookback)
                # Niższy momentum = traci mniej = wyższy score (odwrotnie!)
                # Dla bearish: dodatkowa premia za stablecoiny
                score = -mom * strat.weight
                
                if token in ['BTCUSDT', 'ETHUSDT'] and regime == "bearish":
                    score *= 0.8  # Premia za bezpieczne
                
                if score > best_score:
                    best_score = score
                    best_token = token
            
            votes.append(Vote(
                token=best_token,
                score=best_score,
                strategy_name=strat.name
            ))
        
        return votes
    
    def decide(self, idx: int, current_holding: str) -> Tuple[str, float]:
        """
        Podejmij decyzję: który token trzymać.
        Zwraca: (token, confidence_score)
        """
        votes = self.get_votes(idx)
        
        # Agreguj głosy
        token_scores = defaultdict(float)
        for vote in votes:
            token_scores[vote.token] += vote.score
        
        # Znajdź najlepszy token
        best_token = max(token_scores.items(), key=lambda x: x[1])
        
        return best_token[0], best_token[1]
    
    def run(self, start_idx=100, end_idx=None) -> dict:
        """Uruchom hiperstrategię."""
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
            if idx - last_swap < 10:  # Hiperstrategia ma stały interval 10
                continue
            
            # Decyduj
            best_token, confidence = self.decide(idx, holding)
            
            # Swap jeśli token się zmienił i wysokie confidence
            if best_token != holding and confidence > 0.02:  # 2% confidence
                from_price = self.data.prices[holding][idx]
                to_price = self.data.prices[best_token][idx]
                usdt_val = amount * from_price * FEE
                new_amount = usdt_val / to_price
                
                swaps.append({
                    'idx': idx,
                    'from': holding,
                    'to': best_token,
                    'confidence': confidence,
                    'regime': self.data.detect_regime(idx, self.params.trend_lookback)
                })
                
                holding = best_token
                amount = new_amount
                last_swap = idx
        
        # Final actual
        current_val = amount * self.data.prices[holding][end_idx]
        for token in self.data.tokens:
            actual[token] = current_val / self.data.prices[token][end_idx]
        
        # Buduj matrix
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
                'final_token': holding,
                'final_amount': amount,
                'final_value': amount * self.data.prices[holding][end_idx],
                'n_swaps': len(swaps),
                'strategies': [s.name for s in self.strategies],
                'combine_mode': self.params.combine_mode
            },
            'matrix': matrix,
            'swaps': swaps[-50:]
        }


def save_strategies(strategies: List[Strategy], filepath: str = "output/winning_strategies.json"):
    """Zapisz strategie do pliku."""
    import os
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    data = {
        'strategies': [
            {
                'name': s.name,
                'lookback': s.lookback,
                'threshold': s.threshold,
                'interval': s.interval,
                'weight': s.weight
            }
            for s in strategies
        ],
        'saved_at': time.strftime('%Y-%m-%d %H:%M:%S')
    }
    
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"Zapisano {len(strategies)} strategii do {filepath}")


def load_strategies(filepath: str = "output/winning_strategies.json") -> List[Strategy]:
    """Wczytaj strategie z pliku."""
    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        return [
            Strategy(
                name=s['name'],
                lookback=s['lookback'],
                threshold=s['threshold'],
                interval=s['interval'],
                weight=s.get('weight', 1.0)
            )
            for s in data['strategies']
        ]
    except:
        return []


def compare_strategies():
    """Porównaj pojedyncze vs hiperstrategie."""
    print("""
╔═══════════════════════════════════════════════════════════════╗
║     HYPER STRATEGY - Porównanie                         ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    data = DataLoader("market.csv")
    data.load()
    
    # Okresy testowe
    periods = [
        (100, 60000, "OKRES 1"),
        (60000, 120000, "OKRES 2"),
        (120000, 180000, "OKRES 3"),
        (180000, data.n_records - 1, "OKRES 4"),
    ]
    
    # === TESTUJ POJEDYNCZE STRATEGIE ===
    print("Testowanie pojedynczych strategii...")
    
    single_results = []
    
    for lb in [10, 15, 20, 30, 50]:
        for th in [0.010, 0.015, 0.020, 0.025, 0.030]:
            for iv in [10, 15, 20]:
                gains = []
                
                for start, end, _ in periods:
                    # Prosty backtest
                    holding = "BTCUSDT"
                    amount = 1.0
                    last_swap = 0
                    
                    for idx in range(start, end):
                        if idx - last_swap < iv:
                            continue
                        
                        holding_mom = data.momentum(holding, idx, lb)
                        best_token = None
                        best_mom = 999
                        
                        for token in data.tokens:
                            if token == holding:
                                continue
                            token_mom = data.momentum(token, idx, lb)
                            if token_mom < best_mom and token_mom < holding_mom:
                                best_mom = token_mom
                                best_token = token
                        
                        if best_token and (holding_mom - best_mom) > th:
                            from_price = data.prices[holding][idx]
                            to_price = data.prices[best_token][idx]
                            usdt_val = amount * from_price * FEE
                            amount = usdt_val / to_price
                            holding = best_token
                            last_swap = idx
                    
                    value = amount * data.prices[holding][end]
                    gain = ((value / data.prices['BTCUSDT'][end]) - 1) * 100
                    gains.append(gain)
                
                min_gain = min(gains)
                avg_gain = sum(gains) / len(gains)
                
                single_results.append({
                    'params': (lb, th, iv),
                    'gains': gains,
                    'min_gain': min_gain,
                    'avg_gain': avg_gain,
                    'all_positive': all(g > 0 for g in gains)
                })
    
    single_results.sort(key=lambda x: x['min_gain'], reverse=True)
    positive_single = [r for r in single_results if r['all_positive']]
    
    # === TESTUJ HIPERSTRATEGIE ===
    print("Testowanie hiperstrategii...")
    
    # Hiperstrategia z top pojedynczych
    top_strategies = [
        Strategy("RS_10", lookback=10, threshold=0.015, interval=15, weight=1.5),
        Strategy("RS_20", lookback=20, threshold=0.020, interval=15, weight=1.2),
        Strategy("RS_50", lookback=50, threshold=0.025, interval=20, weight=1.0),
    ]
    
    params = HyperParams(
        strategies=top_strategies,
        combine_mode="consensus",
        detect_trend=True,
        trend_lookback=50
    )
    
    hyper = HyperStrategy(data, params)
    
    hyper_results = []
    for start, end, name in periods:
        result = hyper.run(start, end)
        top_gain = result['matrix'][0]['gain_pct']
        hyper_results.append(top_gain)
    
    hyper_min = min(hyper_results)
    hyper_avg = sum(hyper_results) / len(hyper_results)
    
    # === PORÓWNANIE ===
    print()
    print("=" * 80)
    print("PORÓWNANIE: POJEDYNCZE vs HIPERSTRATEGIA")
    print("=" * 80)
    print()
    
    print(f"{'Typ':<20} {'Min Gain':<12} {'Avg Gain':<12} {'OK1':<8} {'OK2':<8} {'OK3':<8} {'OK4':<8}")
    print("-" * 80)
    
    # Best single
    if positive_single:
        best_single = positive_single[0]
        lb, th, iv = best_single['params']
        print(f"{'Best Single':<20} {best_single['min_gain']:>+10.1f}% {best_single['avg_gain']:>+10.1f}% {best_single['gains'][0]:>+6.1f}% {best_single['gains'][1]:>+6.1f}% {best_single['gains'][2]:>+6.1f}% {best_single['gains'][3]:>+6.1f}%")
        print(f"{'  (L' + str(lb) + ' T' + str(th) + ' I' + str(iv) + ')':<20}")
    
    print(f"{'HYPER STRATEGY':<20} {hyper_min:>+10.1f}% {hyper_avg:>+10.1f}% {hyper_results[0]:>+6.1f}% {hyper_results[1]:>+6.1f}% {hyper_results[2]:>+6.1f}% {hyper_results[3]:>+6.1f}%")
    print(f"{'  (consensus + regime)':<20}")
    
    # Zapisz strategie
    save_strategies(top_strategies)
    
    return {
        'best_single': positive_single[0] if positive_single else None,
        'hyper_results': hyper_results,
        'strategies': top_strategies
    }


def main():
    """Główna funkcja."""
    result = compare_strategies()
    
    print()
    print("=" * 80)
    print("PODSUMOWANIE")
    print("=" * 80)
    
    if result['best_single']:
        print(f"Najlepsza pojedyncza: min={result['best_single']['min_gain']:+.1f}%, avg={result['best_single']['avg_gain']:+.1f}%")
    
    print(f"Hiperstrategia: min={min(result['hyper_results']):+.1f}%, avg={sum(result['hyper_results'])/len(result['hyper_results']):+.1f}%")
    
    # Zapisz wyniki
    with open("output/hyper_results.json", "w") as f:
        json.dump({
            'best_single': result['best_single'],
            'hyper_results': result['hyper_results'],
            'strategies': [s.name for s in result['strategies']]
        }, f, indent=2)
    
    print("\nZapisano do: output/hyper_results.json")


if __name__ == "__main__":
    main()
