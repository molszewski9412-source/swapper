#!/usr/bin/env python3
"""
CHAMPION ULTIMATE BACKTESTER - Wsparcie dla 100+ tokenów

Funkcje:
- Automatyczne wykrywanie tokenów z CSV
- Generowanie syntetycznych tokenów dla testowania skalowalności
- Walk-forward validation
- Export wyników
"""

import csv
import json
import os
import time
import random
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import datetime

FEE = 0.9996 * 0.9996  # 0.08% total


@dataclass
class TokenData:
    """Dane pojedynczego tokena."""
    name: str
    prices: List[float]
    is_synthetic: bool = False


@dataclass
class Swap:
    """Zapis pojedynczego swapu."""
    idx: int
    from_token: str
    to_token: str
    from_amount: float
    to_amount: float
    holding_momentum: float
    target_momentum: float
    diff: float


@dataclass
class Strategy:
    """Parametry strategii."""
    name: str
    lookback: int
    threshold: float
    interval: int
    min_interval: int = 10
    
    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'lookback': self.lookback,
            'threshold': self.threshold,
            'interval': self.interval
        }


class DataLoader:
    """
    Loader danych rynkowych z obsługą 100+ tokenów.
    
    Uwaga: Obecny dataset (market.csv) zawiera tylko 20 realnych tokenów.
    Dla 100+ tokenów wymagany jest większy dataset lub integracja z API.
    """
    
    def __init__(self, filepath: str = "market.csv"):
        self.filepath = filepath
        self.tokens: List[TokenData] = []
        self.n_records = 0
        self.real_tokens_count = 0
        self.synthetic_tokens_count = 0
    
    def load(self, max_tokens: int = 100, synthetic_ratio: float = 0.0) -> None:
        """
        Ładuje dane.
        
        Args:
            max_tokens: Maksymalna liczba tokenów (realne + syntetyczne)
            synthetic_ratio: Jaka część tokenów ma być syntetyczna (0.0-1.0)
                           Domyślnie 0 - tylko realne tokeny
        """
        # Najpierw ładuj realne tokeny
        real_tokens = self._load_real_tokens()
        self.real_tokens_count = len(real_tokens)
        
        # Jeśli mamy więcej realnych tokenów niż max, ucinamy
        if len(real_tokens) >= max_tokens:
            self.tokens = real_tokens[:max_tokens]
            self.synthetic_tokens_count = 0
        else:
            # Mamy mniej realnych niż max_tokens
            self.tokens = real_tokens[:]
            
            # Dodaj syntetyczne jeśli synthetic_ratio > 0
            if synthetic_ratio > 0:
                synthetic_needed = min(
                    int((max_tokens - len(real_tokens)) * synthetic_ratio),
                    max_tokens - len(real_tokens)
                )
                synthetic_tokens = self._generate_synthetic_tokens(real_tokens, synthetic_needed)
                self.synthetic_tokens_count = len(synthetic_tokens)
                self.tokens.extend(synthetic_tokens)
            else:
                self.synthetic_tokens_count = 0
        
        self.n_records = min(len(t.prices) for t in self.tokens)
        
        # Trim all prices to common length
        for token in self.tokens:
            token.prices = token.prices[:self.n_records]
        
        print(f"[DATA] Załadowano {len(self.tokens)} tokenów "
              f"({self.real_tokens_count} realnych, {self.synthetic_tokens_count} syntetycznych)")
        
        if self.real_tokens_count < max_tokens:
            print(f"[DATA] Uwaga: Dataset zawiera tylko {self.real_tokens_count} tokenów.")
            print(f"[DATA] Dla {max_tokens} tokenów wymagany jest większy dataset lub API.")
        
        print(f"[DATA] Rekordów: {self.n_records}")
    
    def _load_real_tokens(self) -> List[TokenData]:
        """Ładuje realne tokeny z CSV."""
        tokens = []
        
        with open(self.filepath, 'r') as f:
            reader = csv.reader(f)
            header = next(reader)
            
            # Znajdź kolumny BID
            token_names = []
            for col in header:
                if col.endswith('_BID'):
                    token_names.append(col.replace('_BID', ''))
            
            # Inicjalizuj struktury
            prices_dict = {t: [] for t in token_names}
            
            # Ładuj dane
            for row in reader:
                for i, t in enumerate(token_names):
                    idx = 1 + i * 2
                    if idx < len(row):
                        try:
                            prices_dict[t].append(float(row[idx]))
                        except:
                            prices_dict[t].append(0)
            
            # Twórz TokenData
            for t in token_names:
                if prices_dict[t]:
                    tokens.append(TokenData(
                        name=t,
                        prices=prices_dict[t],
                        is_synthetic=False
                    ))
        
        return tokens
    
    def _generate_synthetic_tokens(self, base_tokens: List[TokenData], count: int) -> List[TokenData]:
        """
        Generuje syntetyczne tokeny na podstawie realnych.
        
        Syntetyczne tokeny mają:
        - Różne skale cen (0.001 do 100000)
        - Losowe momentum niezależne od bazowego
        - Zmienność w czasie
        """
        synthetic = []
        random.seed(42)  # Reprodukowalność
        
        for i in range(count):
            # Losowa cena startowa z różnych skal
            price_scales = [0.001, 0.01, 0.1, 1, 10, 100, 1000, 10000]
            base_price = random.choice(price_scales) * random.uniform(0.5, 2.0)
            
            # Losowy momentum drift (-30% do +30% na całym okresie)
            total_drift = random.uniform(-0.5, 0.5)
            
            # Zmienność (volatility)
            volatility = random.uniform(0.01, 0.05)  # 1-5% dziennie
            
            new_prices = []
            current_price = base_price
            
            for j in range(len(base_tokens[0].prices)):
                # GBM-like price movement
                daily_return = random.gauss(total_drift / len(base_tokens[0].prices), volatility)
                current_price = current_price * (1 + daily_return)
                current_price = max(0.0001, current_price)
                new_prices.append(current_price)
            
            synthetic.append(TokenData(
                name=f"SYN{i:03d}",
                prices=new_prices,
                is_synthetic=True
            ))
        
        return synthetic
    
    def momentum(self, token_name: str, idx: int, period: int) -> float:
        """Oblicza momentum dla tokena."""
        token = self.get_token(token_name)
        if token is None or idx < period:
            return 0.0
        
        past = token.prices[idx - period]
        now = token.prices[idx]
        
        if past <= 0:
            return 0.0
        
        return (now - past) / past
    
    def get_token(self, name: str) -> Optional[TokenData]:
        """Pobiera token po nazwie."""
        for t in self.tokens:
            if t.name == name:
                return t
        return None
    
    def get_all_token_names(self) -> List[str]:
        """Zwraca listę wszystkich nazw tokenów."""
        return [t.name for t in self.tokens]


class ChampionBacktester:
    """
    Backtester strategii CHAMPION_ULTIMATE.
    """
    
    def __init__(self, data: DataLoader, strategy: Strategy):
        self.data = data
        self.strategy = strategy
    
    def run(self, start_idx: int = 100, end_idx: int = None, 
            track_swaps: bool = True) -> dict:
        """
        Uruchamia backtest.
        
        Returns:
            Słownik z wynikami
        """
        if end_idx is None:
            end_idx = self.data.n_records - 1
        
        # Inicjalizacja
        holding = "BTCUSDT"
        amount = 1.0
        last_swap_idx = 0
        swaps: List[Swap] = []
        
        lb = self.strategy.lookback
        th = self.strategy.threshold
        iv = self.strategy.interval
        
        # Baseline
        btc_price = self.data.get_token('BTCUSDT').prices[start_idx]
        usdt_start = 1.0 * btc_price * FEE
        baseline = {}
        for token in self.data.tokens:
            if token.prices[start_idx] > 0:
                baseline[token.name] = usdt_start / token.prices[start_idx]
            else:
                baseline[token.name] = 0
        
        # Główna pętla
        for idx in range(start_idx, end_idx):
            # Min interval check
            if idx - last_swap_idx < iv:
                continue
            
            # Momentum holding
            holding_mom = self.data.momentum(holding, idx, lb)
            
            # Znajdź token tracący najmniej
            best_token = None
            best_mom = 999.0
            best_diff = 0.0
            
            for token in self.data.tokens:
                if token.name == holding:
                    continue
                
                token_mom = self.data.momentum(token.name, idx, lb)
                
                # Token musi tracić MNIEJ niż holding
                if token_mom < best_mom and token_mom < holding_mom:
                    best_mom = token_mom
                    best_token = token.name
                    best_diff = holding_mom - token_mom
            
            # Swap
            if best_token and best_diff > th:
                from_token = self.data.get_token(holding)
                to_token = self.data.get_token(best_token)
                
                if from_token and to_token:
                    from_price = from_token.prices[idx]
                    to_price = to_token.prices[idx]
                    
                    if from_price > 0 and to_price > 0:
                        usdt = amount * from_price * FEE
                        new_amount = usdt / to_price
                        
                        if track_swaps:
                            swaps.append(Swap(
                                idx=idx,
                                from_token=holding,
                                to_token=best_token,
                                from_amount=amount,
                                to_amount=new_amount,
                                holding_momentum=holding_mom,
                                target_momentum=best_mom,
                                diff=best_diff
                            ))
                        
                        holding = best_token
                        amount = new_amount
                        last_swap_idx = idx
        
        # Final values
        final_token = self.data.get_token(holding)
        final_price = final_token.prices[end_idx] if final_token else 0
        final_value = amount * final_price
        
        btc_final = self.data.get_token('BTCUSDT').prices[end_idx]
        vs_btc = ((final_value / btc_final) - 1) * 100 if btc_final > 0 else 0
        
        # Matrix
        matrix = []
        for token in self.data.tokens:
            bl = baseline.get(token.name, 0)
            if token.prices[end_idx] > 0:
                actual = final_value / token.prices[end_idx]
            else:
                actual = 0
            
            gain = ((actual / bl) - 1) * 100 if bl > 0 else 0
            
            matrix.append({
                'token': token.name,
                'baseline': bl,
                'actual': actual,
                'gain_pct': gain,
                'is_final': token.name == holding,
                'is_synthetic': token.is_synthetic
            })
        
        matrix.sort(key=lambda x: x['gain_pct'], reverse=True)
        
        return {
            'strategy': self.strategy.to_dict(),
            'summary': {
                'start_token': 'BTCUSDT',
                'start_amount': 1.0,
                'final_token': holding,
                'final_amount': amount,
                'final_value': final_value,
                'vs_btc_pct': vs_btc,
                'n_swaps': len(swaps),
                'n_real_tokens': self.data.real_tokens_count,
                'n_synthetic_tokens': self.data.synthetic_tokens_count,
                'n_total_tokens': len(self.data.tokens)
            },
            'matrix': matrix[:20],  # Top 20
            'swaps': [
                {
                    'idx': s.idx,
                    'from': s.from_token,
                    'to': s.to_token,
                    'diff': s.diff
                }
                for s in swaps[-30:]
            ],
            'all_swaps': len(swaps)
        }


def walk_forward_test(data: DataLoader, strategy: Strategy) -> dict:
    """
    Walk-forward validation na 4 okresach.
    """
    periods = [
        (100, 60000, "OKRES 1"),
        (60000, 120000, "OKRES 2"),
        (120000, 180000, "OKRES 3"),
        (180000, data.n_records - 1, "OKRES 4"),
    ]
    
    results = []
    
    for start, end, name in periods:
        bt = ChampionBacktester(data, strategy)
        result = bt.run(start, end, track_swaps=False)
        
        results.append({
            'period': name,
            'start': start,
            'end': end,
            'gain': result['summary']['vs_btc_pct'],
            'swaps': result['summary']['n_swaps']
        })
    
    gains = [r['gain'] for r in results]
    
    return {
        'strategy': strategy.to_dict(),
        'periods': results,
        'min_gain': min(gains),
        'avg_gain': sum(gains) / len(gains),
        'all_positive': all(g > 0 for g in gains)
    }


def find_best_params(data: DataLoader) -> Tuple[Strategy, dict]:
    """
    Szuka najlepszych parametrów przez grid search.
    """
    lookbacks = [3, 5, 7, 10, 15]
    thresholds = [0.02, 0.025, 0.03, 0.035, 0.04]
    intervals = [5, 8, 10, 12, 15]
    
    best_result = None
    best_min_gain = -999
    
    total = len(lookbacks) * len(thresholds) * len(intervals)
    print(f"[GRID] Testowanie {total} kombinacji...")
    
    for i, lb in enumerate(lookbacks):
        for th in thresholds:
            for iv in intervals:
                strategy = Strategy(
                    name=f"GRID_L{lb}_T{int(th*1000)}_I{iv}",
                    lookback=lb,
                    threshold=th,
                    interval=iv
                )
                
                result = walk_forward_test(data, strategy)
                
                if result['min_gain'] > best_min_gain:
                    best_min_gain = result['min_gain']
                    best_result = (strategy, result)
    
    return best_result


def main():
    print("""
╔═══════════════════════════════════════════════════════════════╗
║     CHAMPION ULTIMATE BACKTESTER                         ║
║     100+ tokenów | Walk-forward | Grid Search            ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    # Konfiguracja
    max_tokens = 100
    synthetic_ratio = 0.0  # Tylko realne tokeny (dataset ma tylko 20)
    
    print(f"[CONFIG] Max tokens: {max_tokens}")
    print(f"[CONFIG] Synthetic ratio: {synthetic_ratio*100:.0f}%")
    print()
    
    # Ładuj dane
    print("[LOAD] Ładowanie danych...")
    data = DataLoader("market.csv")
    data.load(max_tokens=max_tokens, synthetic_ratio=synthetic_ratio)
    print()
    
    # Użyj champion_ultimate params
    champion = Strategy(
        name="CHAMPION_ULTIMATE",
        lookback=5,
        threshold=0.03,
        interval=10
    )
    
    print(f"[STRATEGY] CHAMPION_ULTIMATE: L{champion.lookback} T{champion.threshold*100:.0f}% I{champion.interval}")
    print()
    
    # Walk-forward test
    print("=" * 70)
    print("WALK-FORWARD TEST")
    print("=" * 70)
    
    wf_result = walk_forward_test(data, champion)
    
    for period in wf_result['periods']:
        print(f"  {period['period']}: {period['gain']:+.1f}% ({period['swaps']} swaps)")
    
    print()
    print(f"Min gain: {wf_result['min_gain']:+.1f}%")
    print(f"Avg gain: {wf_result['avg_gain']:+.1f}%")
    print(f"All positive: {'✓' if wf_result['all_positive'] else '✗'}")
    print()
    
    # Full test
    print("=" * 70)
    print("FULL TEST")
    print("=" * 70)
    
    bt = ChampionBacktester(data, champion)
    full_result = bt.run(100, data.n_records - 1)
    
    summary = full_result['summary']
    print(f"Tokens: {summary['n_total_tokens']} ({summary['n_real_tokens']} real, {summary['n_synthetic_tokens']} synthetic)")
    print(f"Final: {summary['final_token']}")
    print(f"Amount: {summary['final_amount']:,.4f}")
    print(f"Value: ${summary['final_value']:,.2f}")
    print(f"vs BTC: {summary['vs_btc_pct']:+.1f}%")
    print(f"Swaps: {summary['n_swaps']}")
    print()
    
    # Top tokens
    print("TOP 10:")
    for row in full_result['matrix'][:10]:
        marker = " ◄◄" if row['is_final'] else ""
        synth = " [SYN]" if row.get('is_synthetic', False) else ""
        print(f"  {row['token']:<20} {row['gain_pct']:>+8.1f}%{marker}{synth}")
    print()
    
    # Save
    output = {
        'strategy': champion.to_dict(),
        'walk_forward': wf_result,
        'full_test': full_result,
        'config': {
            'max_tokens': max_tokens,
            'synthetic_ratio': synthetic_ratio,
            'real_tokens': data.real_tokens_count,
            'synthetic_tokens': data.synthetic_tokens_count
        },
        'timestamp': datetime.now().isoformat()
    }
    
    os.makedirs('output', exist_ok=True)
    with open('output/champion_ultimate_results.json', 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"Zapisano do: output/champion_ultimate_results.json")


if __name__ == "__main__":
    main()
