#!/usr/bin/env python3
"""
Matrix App v3 - RELATIVE STRENGTH Strategy

Strategia: Byc w tokenie ktory traci MNIEJ niz obecny
"""

from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import csv
import time

app = Flask(__name__)
CORS(app)

# Fee: 0.04% x 2 = 0.08% za swap
FEE = 0.9996 * 0.9996


class DataLoader:
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
    
    def momentum(self, token, idx, period):
        if idx < period:
            return 0.0
        return (self.prices[token][idx] - self.prices[token][idx - period]) / self.prices[token][idx - period]


class Backtester:
    """
    RELATIVE STRENGTH Strategy:
    - Zamiast gonic zwyciezcow, unikaj przegranych
    - Szukaj tokena ktory traci MNIEJ niz aktualny
    """
    
    def __init__(self, data):
        self.data = data
        self.btc_final = 1.0 * data.prices['BTCUSDT'][-1]
        
    def run(self, lookback, threshold, min_interval):
        holding = "BTCUSDT"
        amount = 1.0
        last_swap = 0
        swaps = []
        
        # Baseline
        btc_price = self.data.prices['BTCUSDT'][0]
        usdt_start = 1.0 * btc_price * FEE
        baseline = {t: usdt_start / self.data.prices[t][0] for t in self.data.tokens}
        
        actual = {t: 0.0 for t in self.data.tokens}
        top = {t: baseline[t] for t in self.data.tokens}
        
        for idx in range(lookback, self.data.n_records - 1):
            # Actual amounts
            current_val = amount * self.data.prices[holding][idx] * FEE
            for token in self.data.tokens:
                actual[token] = current_val / self.data.prices[token][idx]
                # Update top
                token_val = actual[token] * self.data.prices[token][idx]
                if token_val > top[token] * self.data.prices[token][idx]:
                    top[token] = actual[token]
            
            # Min interval
            if idx - last_swap < min_interval:
                continue
            
            # RELATIVE STRENGTH: szukaj tokena tracacego MNIEJ
            holding_mom = self.data.momentum(holding, idx, lookback)
            best_token = None
            best_mom = 999  # Nizszy = traci mniej
            
            for token in self.data.tokens:
                if token == holding:
                    continue
                token_mom = self.data.momentum(token, idx, lookback)
                # Token musi tracic MNIEJ niz holding
                if token_mom < best_mom and token_mom < holding_mom:
                    best_mom = token_mom
                    best_token = token
            
            # Swap jesli roznica > threshold
            if best_token and (holding_mom - best_mom) > threshold:
                from_price = self.data.prices[holding][idx]
                to_price = self.data.prices[best_token][idx]
                usdt = amount * from_price * FEE
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
        
        # Results
        final_value = amount * self.data.prices[holding][-1]
        gain_vs_btc = ((final_value / self.btc_final) - 1) * 100
        
        matrix = []
        for token in self.data.tokens:
            gain_pct = ((actual[token] / baseline[token]) - 1) * 100 if baseline[token] > 0 else 0
            matrix.append({
                'token': token,
                'baseline': baseline[token],
                'actual': actual[token],
                'top': top[token],
                'gain_pct': gain_pct
            })
        
        matrix.sort(key=lambda x: x['gain_pct'], reverse=True)
        
        return {
            'params': {'lookback': lookback, 'threshold': threshold, 'min_interval': min_interval},
            'final_token': holding,
            'final_amount': amount,
            'final_value': final_value,
            'gain_vs_btc': gain_vs_btc,
            'n_swaps': len(swaps),
            'swaps': swaps[-20:],
            'matrix': matrix
        }


global_data = None


@app.route('/')
def index():
    return render_template('matrix.html')


@app.route('/api/init', methods=['POST'])
def init():
    global global_data
    global_data = DataLoader("market.csv")
    global_data.load()
    return jsonify({
        'tokens': global_data.tokens,
        'n_records': global_data.n_records
    })


@app.route('/api/run', methods=['POST'])
def run_single():
    global global_data
    if global_data is None:
        global_data = DataLoader("market.csv")
        global_data.load()
    
    data = request.json or {}
    bt = Backtester(global_data)
    
    result = bt.run(
        lookback=int(data.get('lookback', 50)),
        threshold=float(data.get('threshold', 0.05)),
        min_interval=int(data.get('min_interval', 20))
    )
    
    return jsonify(result)


@app.route('/api/optimize', methods=['POST'])
def optimize():
    global global_data
    if global_data is None:
        global_data = DataLoader("market.csv")
        global_data.load()
    
    bt = Backtester(global_data)
    start = time.time()
    
    results = []
    # TESTUJ WIĘCEJ KOMBINACJI!
    for lookback in [10, 20, 30, 50, 75, 100]:
        for threshold in [0.005, 0.010, 0.015, 0.020, 0.025, 0.030, 0.040, 0.050, 0.075, 0.100]:
            for interval in [5, 10, 15, 20, 30]:
                r = bt.run(lookback, threshold, interval)
                results.append({
                    'params': r['params'],
                    'final_token': r['final_token'],
                    'final_amount': r['final_amount'],
                    'final_value': r['final_value'],
                    'gain_vs_btc': r['gain_vs_btc'],
                    'n_swaps': r['n_swaps'],
                    'matrix': r['matrix'][:3]
                })
    
    results.sort(key=lambda x: x['gain_vs_btc'], reverse=True)
    elapsed = time.time() - start
    
    return jsonify({
        'best': results[0],
        'top_20': results[:20],
        'total': len(results),
        'time': f'{elapsed:.1f}s'
    })


if __name__ == '__main__':
    print("""
╔═══════════════════════════════════════════════════════════════╗
║     MATRIX APP v3 - RELATIVE STRENGTH                     ║
║     http://localhost:5000                                ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    app.run(debug=True, host='0.0.0.0', port=5000)
