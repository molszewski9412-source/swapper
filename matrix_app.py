#!/usr/bin/env python3
"""
Matrix App - Prosta aplikacja pokazująca macierz tokenów

Pokazuje dla każdego tokenu:
- Baseline: ile mogliśmy mieć na start (za 1 BTC)
- Actual: ile faktycznie mamy (dynamicznie)
- Top: najwyższy osiągnięty wynik (zablokowany przy swapach)
- % Gain: procentowa zmiana vs baseline
"""

from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import csv
from dataclasses import dataclass
from typing import List, Optional

app = Flask(__name__)
CORS(app)

SWAP_FEE = 0.0004


@dataclass
class TokenMatrix:
    """Dane dla jednego tokena."""
    token: str
    baseline_amount: float      # Ile na start
    actual_amount: float         # Ile teraz
    top_amount: float           # Top osiągnięty
    baseline_value_usdt: float  # Wartość USDT na start
    actual_value_usdt: float    # Wartość USDT teraz
    top_value_usdt: float       # Top w USDT
    gain_pct: float             # % gain vs baseline


class DataLoader:
    """Ładowanie danych."""
    
    def __init__(self, filepath: str = "market.csv"):
        self.filepath = filepath
        self.tokens = []
        self.bids = {}
        self.asks = {}
        self.n_records = 0
        
    def load(self):
        with open(self.filepath, 'r') as f:
            reader = csv.reader(f)
            header = next(reader)
            
            for i, col in enumerate(header):
                if col.endswith('_BID'):
                    t = col.replace('_BID', '')
                    self.tokens.append(t)
                    self.bids[t] = []
                    self.asks[t] = []
            
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
        
        min_len = min(len(self.bids[t]) for t in self.tokens)
        for t in self.tokens:
            self.bids[t] = self.bids[t][:min_len]
            self.asks[t] = self.asks[t][:min_len]
        
        self.n_records = min_len


class Backtester:
    """Backtester z pełną macierzą."""
    
    def __init__(self, data: DataLoader):
        self.data = data
        
    def run(self, 
            lookback: int = 200,
            threshold: float = 0.03,
            min_interval: int = 20) -> dict:
        """
        Uruchamia backtest i zwraca pełną macierz.
        
        Dla każdego tokenu oblicza:
        - Baseline: ile byśmy mieli gdybyśmy kupili na start
        - Actual: ile faktycznie mamy (bieżąco)
        - Top: najwyższy osiągnięty wynik (zablokowany)
        """
        
        # Initialize
        holding = "BTCUSDT"
        amount = 1.0
        last_swap = 0
        swaps = []
        
        # Macierz dla każdego tokenu
        matrix = {}
        for token in self.data.tokens:
            matrix[token] = {
                'baseline_amount': 0.0,
                'baseline_value': 0.0,
                'actual_amount': 0.0,
                'actual_value': 0.0,
                'top_amount': 0.0,
                'top_value': 0.0,
            }
        
        # Oblicz baseline (ile każdego tokena za 1 BTC na start)
        btc_price_start = self.data.bids['BTCUSDT'][0]
        usdt_start = 1.0 * btc_price_start * (1 - SWAP_FEE)
        
        for token in self.data.tokens:
            token_price_start = self.data.asks[token][0]
            amount_start = usdt_start / token_price_start
            value_start = amount_start * self.data.bids[token][0]
            
            matrix[token]['baseline_amount'] = amount_start
            matrix[token]['baseline_value'] = value_start
            matrix[token]['top_amount'] = amount_start
            matrix[token]['top_value'] = value_start
        
        # Główna pętla
        for idx in range(lookback, self.data.n_records - 1):
            
            # Oblicz ACTUAL dla każdego tokenu
            # (gdybyśmy w danym momencie zamienili na ten token)
            current_btc_value = amount * self.data.bids[holding][idx]
            usdt_current = current_btc_value * (1 - SWAP_FEE)
            
            for token in self.data.tokens:
                token_price = self.data.asks[token][idx]
                actual_amount = usdt_current / token_price
                actual_value = actual_amount * self.data.bids[token][idx]
                
                matrix[token]['actual_amount'] = actual_amount
                matrix[token]['actual_value'] = actual_value
                
                # Aktualizuj TOP jeśli wyższy
                if actual_value > matrix[token]['top_value']:
                    matrix[token]['top_amount'] = actual_amount
                    matrix[token]['top_value'] = actual_value
            
            # Sprawdź czy można swapować
            if idx - last_swap < min_interval:
                continue
            
            # Momentum
            holding_mom = self._momentum(holding, idx, lookback)
            
            best_token = None
            best_score = -999
            
            for token in self.data.tokens:
                if token == holding:
                    continue
                
                token_mom = self._momentum(token, idx, lookback)
                btc_mom = self._momentum('BTCUSDT', idx, lookback)
                rel_mom = token_mom - holding_mom
                vs_btc = token_mom - btc_mom
                
                if rel_mom > best_score and vs_btc > 0.01:
                    best_score = rel_mom
                    best_token = token
            
            # Swap
            if best_token and best_score > threshold:
                from_price = self.data.bids[holding][idx]
                to_price = self.data.asks[best_token][idx]
                
                usdt = amount * from_price * (1 - SWAP_FEE)
                new_amount = usdt / to_price
                
                swaps.append({
                    'idx': idx,
                    'from': holding,
                    'to': best_token,
                    'amount': new_amount
                })
                
                holding = best_token
                amount = new_amount
                last_swap = idx
        
        # Konwertuj na wyniki
        results = []
        for token in self.data.tokens:
            m = matrix[token]
            gain_pct = ((m['actual_value'] / m['baseline_value']) - 1) * 100 if m['baseline_value'] > 0 else 0
            
            results.append({
                'token': token,
                'baseline': {
                    'amount': m['baseline_amount'],
                    'value_usdt': m['baseline_value']
                },
                'actual': {
                    'amount': m['actual_amount'],
                    'value_usdt': m['actual_value']
                },
                'top': {
                    'amount': m['top_amount'],
                    'value_usdt': m['top_value']
                },
                'gain_pct': gain_pct
            })
        
        # Sortuj po gain %
        results.sort(key=lambda x: x['gain_pct'], reverse=True)
        
        return {
            'params': {
                'lookback': lookback,
                'threshold': threshold,
                'min_interval': min_interval
            },
            'final_state': {
                'token': holding,
                'amount': amount,
                'value_usdt': amount * self.data.bids[holding][-1]
            },
            'n_swaps': len(swaps),
            'swaps': swaps,
            'matrix': results
        }
    
    def _momentum(self, token: str, idx: int, period: int) -> float:
        if idx < period:
            return 0.0
        p1 = self.data.bids[token][idx - period]
        p2 = self.data.bids[token][idx]
        return (p2 - p1) / p1


# Global
global_data = None


@app.route('/')
def index():
    return render_template('matrix.html')


@app.route('/api/init', methods=['POST'])
def init_data():
    global global_data
    global_data = DataLoader("market.csv")
    global_data.load()
    return jsonify({
        'tokens': global_data.tokens,
        'n_records': global_data.n_records
    })


@app.route('/api/matrix', methods=['POST'])
def get_matrix():
    """Zwraca macierz dla danej strategii."""
    global global_data
    
    if global_data is None:
        global_data = DataLoader("market.csv")
        global_data.load()
    
    data = request.json or {}
    
    bt = Backtester(global_data)
    result = bt.run(
        lookback=int(data.get('lookback', 200)),
        threshold=float(data.get('threshold', 0.03)),
        min_interval=int(data.get('min_interval', 20))
    )
    
    return jsonify(result)


@app.route('/api/optimize', methods=['POST'])
def optimize():
    """Testuje wiele strategii i zwraca najlepsze."""
    global global_data
    
    if global_data is None:
        global_data = DataLoader("market.csv")
        global_data.load()
    
    bt = Backtester(global_data)
    all_results = []
    
    # Grid search
    for lookback in [100, 200, 300, 500]:
        for threshold in [0.01, 0.02, 0.03, 0.05]:
            for interval in [10, 20, 50]:
                result = bt.run(lookback, threshold, interval)
                
                # Oblicz overall score (średni gain % lub końcowa wartość)
                avg_gain = sum(r['gain_pct'] for r in result['matrix']) / len(result['matrix'])
                final_value = result['final_state']['value_usdt']
                
                all_results.append({
                    'params': result['params'],
                    'final_value': final_value,
                    'final_token': result['final_state']['token'],
                    'n_swaps': result['n_swaps'],
                    'avg_gain_pct': avg_gain,
                    'matrix': result['matrix'][:5]  # Top 5 tokenów
                })
    
    # Sortuj po final value
    all_results.sort(key=lambda x: x['final_value'], reverse=True)
    
    return jsonify({
        'best': all_results[0] if all_results else None,
        'top_10': all_results[:10],
        'all_count': len(all_results)
    })


if __name__ == '__main__':
    print("""
╔═══════════════════════════════════════════════════════════════╗
║     MATRIX APP - Macierz Tokenów                          ║
║     http://localhost:5000                                ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    app.run(debug=True, host='0.0.0.0', port=5000)
