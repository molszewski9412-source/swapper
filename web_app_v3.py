#!/usr/bin/env python3
"""
Swapper Web Dashboard v3 - POPRAWNA wersja

Liczy ILOŚĆ tokenów, nie USDT!

Start: 1 BTC
Strategia: zamienia tokeny, śledzi ILOŚĆ tokenów
Final: "Masz X.XXX tokenów"
"""

from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import csv
from dataclasses import dataclass

app = Flask(__name__)
CORS(app)

SWAP_FEE = 0.0004


class DataLoader:
    """Ładowanie danych."""
    
    def __init__(self, filepath: str = "market.csv"):
        self.filepath = filepath
        self.tokens = []
        self.bids = {}
        self.asks = {}
        self.n_records = 0
        
    def load(self):
        """Ładuje dane z CSV."""
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
    
    def get_bid(self, token: str, idx: int) -> float:
        return self.bids[token][idx]
    
    def get_ask(self, token: str, idx: int) -> float:
        return self.asks[token][idx]
    
    def momentum(self, token: str, idx: int, period: int) -> float:
        if idx < period:
            return 0.0
        p1 = self.bids[token][idx - period]
        p2 = self.bids[token][idx]
        return (p2 - p1) / p1


def calculate_baseline(data: DataLoader) -> dict:
    """Oblicza ile każdego tokenu mogliśmy mieć na start za 1 BTC."""
    btc_price = data.get_bid('BTCUSDT', 0)
    baseline = {}
    
    for token in data.tokens:
        # 1 BTC -> USDT -> Token
        usdt = 1.0 * btc_price * (1 - SWAP_FEE)
        token_price = data.get_ask(token, 0)  # Kupujemy po ask
        amount = usdt / token_price
        baseline[token] = {
            'initial_amount': amount,
            'initial_price': token_price,
            'final_price': data.get_bid(token, -1)
        }
    
    return baseline


def run_strategy(data: DataLoader, lookback: int, threshold: float, 
                 min_interval: int, vs_btc_threshold: float) -> dict:
    """
    Uruchamia strategię momentum.
    
    Zwraca ILOŚĆ tokenów!
    """
    # Initialize
    holding = "BTCUSDT"
    amount = 1.0  # 1 BTC na start
    last_swap = 0
    swaps = []
    equity_curve = []  # Track amount over time
    
    for idx in range(lookback, data.n_records - 1):
        # Track amount
        equity_curve.append(amount)
        
        # Min interval
        if idx - last_swap < min_interval:
            continue
        
        # Momentum calculation
        holding_mom = data.momentum(holding, idx, lookback)
        
        best_token = None
        best_score = -999
        
        for token in data.tokens:
            if token == holding:
                continue
            
            token_mom = data.momentum(token, idx, lookback)
            btc_mom = data.momentum('BTCUSDT', idx, lookback)
            
            rel_mom = token_mom - holding_mom
            vs_btc = token_mom - btc_mom
            
            if rel_mom > best_score and vs_btc > vs_btc_threshold:
                best_score = rel_mom
                best_token = token
        
        # Execute swap if threshold met
        if best_token and best_score > threshold:
            from_price = data.get_bid(holding, idx)  # Selling price
            to_price = data.get_ask(best_token, idx)  # Buying price
            
            # Swap calculation
            usdt = amount * from_price * (1 - SWAP_FEE)
            new_amount = usdt / to_price
            
            swaps.append({
                'idx': idx,
                'from': holding,
                'to': best_token,
                'amount_in': amount,
                'amount_out': new_amount
            })
            
            holding = best_token
            amount = new_amount
            last_swap = idx
    
    # Final results
    final_token = holding
    final_amount = amount
    
    # Baseline comparison
    baseline = calculate_baseline(data)
    baseline_amount = baseline[final_token]['initial_amount']
    
    # USDT comparison
    final_usdt = final_amount * data.get_bid(final_token, -1)
    btc_usdt = 1.0 * data.get_bid('BTCUSDT', -1)
    
    return {
        'strategy': 'momentum',
        'params': {
            'lookback': lookback,
            'threshold': threshold,
            'min_interval': min_interval,
            'vs_btc_threshold': vs_btc_threshold
        },
        'initial': {
            'token': 'BTCUSDT',
            'amount': 1.0
        },
        'final': {
            'token': final_token,
            'amount': final_amount,
            'formatted': format_amount(final_amount)
        },
        'baseline': {
            'token': final_token,
            'amount': baseline_amount,
            'formatted': format_amount(baseline_amount)
        },
        'comparison': {
            'strategy_better_than_baseline': final_amount > baseline_amount,
            'ratio': final_amount / baseline_amount if baseline_amount > 0 else 0
        },
        'usdt_values': {
            'strategy_final': final_usdt,
            'btc_final': btc_usdt,
            'gain_vs_btc': ((final_usdt / btc_usdt) - 1) * 100
        },
        'n_swaps': len(swaps),
        'swaps': swaps[-20:],  # Last 20 swaps
        'equity_curve': equity_curve[-500:],  # Last 500 points
        'tokens': data.tokens
    }


def format_amount(amount: float) -> str:
    """Formatuje ilość tokenów."""
    if amount >= 1000:
        return f"{amount:,.2f}"
    elif amount >= 1:
        return f"{amount:,.4f}"
    elif amount >= 0.01:
        return f"{amount:,.6f}"
    else:
        return f"{amount:,.8f}"


# Global data
global_data = None


@app.route('/')
def index():
    return render_template('dashboard_v3.html')


@app.route('/api/init', methods=['POST'])
def init_data():
    """Inicjalizuje dane."""
    global global_data
    global_data = DataLoader("market.csv")
    global_data.load()
    
    baseline = calculate_baseline(global_data)
    
    return jsonify({
        'tokens': global_data.tokens,
        'n_records': global_data.n_records,
        'baseline': baseline
    })


@app.route('/api/run', methods=['POST'])
def run():
    """Uruchamia strategię."""
    global global_data
    
    if global_data is None:
        init_data()
    
    data = request.json or {}
    
    result = run_strategy(
        global_data,
        lookback=int(data.get('lookback', 200)),
        threshold=float(data.get('threshold', 0.03)),
        min_interval=int(data.get('min_interval', 20)),
        vs_btc_threshold=float(data.get('vs_btc_threshold', 0.01))
    )
    
    return jsonify(result)


@app.route('/api/optimize', methods=['POST'])
def optimize():
    """Optymalizuje strategię."""
    global global_data
    
    if global_data is None:
        init_data()
    
    results = []
    
    for lookback in [100, 200, 300, 500]:
        for threshold in [0.01, 0.02, 0.03, 0.05]:
            for interval in [10, 20, 50]:
                r = run_strategy(global_data, lookback, threshold, interval, 0.01)
                results.append(r)
    
    # Sort by final amount (token count)
    results.sort(key=lambda x: x['final']['amount'], reverse=True)
    
    return jsonify({
        'results': results[:50],
        'best': results[0] if results else None
    })


if __name__ == '__main__':
    print("""
╔═══════════════════════════════════════════════════════════════╗
║     SWAPPER Web Dashboard v3 - POPRAWNA WERSJA           ║
║     http://localhost:5000                                ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    app.run(debug=True, host='0.0.0.0', port=5000)
