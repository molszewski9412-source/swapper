#!/usr/bin/env python3
"""
Matrix App v2 - Usprawniona wersja z lepszym UI
"""

from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import csv
import time

app = Flask(__name__)
CORS(app)

SWAP_FEE = 0.0004


class DataLoader:
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
    
    def momentum(self, token, idx, period):
        if idx < period:
            return 0.0
        return (self.bids[token][idx] - self.bids[token][idx - period]) / self.bids[token][idx - period]


class Backtester:
    def __init__(self, data):
        self.data = data
        
    def run(self, lookback, threshold, min_interval):
        holding = "BTCUSDT"
        amount = 1.0
        last_swap = 0
        swaps = []
        
        # Baseline
        btc_price = self.data.bids['BTCUSDT'][0]
        usdt_start = 1.0 * btc_price * (1 - SWAP_FEE)
        
        baseline = {}
        for token in self.data.tokens:
            baseline[token] = usdt_start / self.data.asks[token][0]
        
        actual = {t: 0.0 for t in self.data.tokens}
        top = {t: baseline[t] for t in self.data.tokens}
        
        for idx in range(lookback, self.data.n_records - 1):
            # Calculate actual
            current_btc = amount * self.data.bids[holding][idx]
            usdt = current_btc * (1 - SWAP_FEE)
            
            for token in self.data.tokens:
                actual[token] = usdt / self.data.asks[token][idx]
                # Update top
                token_val = actual[token] * self.data.bids[token][idx]
                if token_val > top[token] * self.data.bids[token][idx]:
                    top[token] = actual[token]
            
            # Check swap
            if idx - last_swap < min_interval:
                continue
            
            holding_mom = self.data.momentum(holding, idx, lookback)
            best_token = None
            best_score = -999
            
            for token in self.data.tokens:
                if token == holding:
                    continue
                token_mom = self.data.momentum(token, idx, lookback)
                btc_mom = self.data.momentum('BTCUSDT', idx, lookback)
                rel_mom = token_mom - holding_mom
                vs_btc = token_mom - btc_mom
                
                if rel_mom > best_score and vs_btc > 0.01:
                    best_score = rel_mom
                    best_token = token
            
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
        
        # Build matrix
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
        lookback=int(data.get('lookback', 200)),
        threshold=float(data.get('threshold', 0.03)),
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
    for lookback in [50, 100, 200, 300, 500]:
        for threshold in [0.01, 0.02, 0.03, 0.05, 0.10]:
            for interval in [5, 10, 20, 50, 100]:
                r = bt.run(lookback, threshold, interval)
                results.append({
                    'params': r['params'],
                    'final_token': r['final_token'],
                    'final_amount': r['final_amount'],
                    'n_swaps': r['n_swaps'],
                    'matrix': r['matrix'][:3]
                })
    
    results.sort(key=lambda x: x['final_amount'], reverse=True)
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
║     MATRIX APP v2                                        ║
║     http://localhost:5000                                ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    app.run(debug=True, host='0.0.0.0', port=5000)
