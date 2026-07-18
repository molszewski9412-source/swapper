#!/usr/bin/env python3
"""
Swapper Web App v4 - Robust Strategy

- Bez look-ahead bias
- Gain vs baseline (nie BTC)
- Matrix 20 tokenów
- Walk-forward validation
"""

from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import csv
import time

app = Flask(__name__)
CORS(app)

FEE = 0.9996 * 0.9996  # 0.08% za swap


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


class RobustBacktester:
    """
    Backtester bez look-ahead bias.
    """
    
    def __init__(self, data):
        self.data = data
        
    def run(self, lookback, threshold, interval, start_idx=None, end_idx=None):
        if start_idx is None:
            start_idx = 100
        if end_idx is None:
            end_idx = self.data.n_records - 1
        
        # Baseline
        btc_price = self.data.prices['BTCUSDT'][start_idx]
        usdt = 1.0 * btc_price * FEE
        
        baseline = {}
        for token in self.data.tokens:
            baseline[token] = usdt / self.data.prices[token][start_idx]
        
        # Main loop
        holding = "BTCUSDT"
        amount = 1.0
        last_swap = 0
        swaps = []
        
        actual = {t: 0.0 for t in self.data.tokens}
        
        for idx in range(start_idx, end_idx):
            if idx - last_swap < interval:
                continue
            
            # Calculate actual equivalents
            current_val = amount * self.data.prices[holding][idx]
            for token in self.data.tokens:
                actual[token] = current_val / self.data.prices[token][idx]
            
            # Find best token (losing LESS)
            holding_mom = self.data.momentum(holding, idx, lookback)
            best_token = None
            best_mom = 999
            
            for token in self.data.tokens:
                if token == holding:
                    continue
                token_mom = self.data.momentum(token, idx, lookback)
                if token_mom < best_mom and token_mom < holding_mom:
                    best_mom = token_mom
                    best_token = token
            
            # Swap
            if best_token and (holding_mom - best_mom) > threshold:
                from_price = self.data.prices[holding][idx]
                to_price = self.data.prices[best_token][idx]
                usdt_val = amount * from_price * FEE
                new_amount = usdt_val / to_price
                
                swaps.append({
                    'idx': idx,
                    'from': holding,
                    'to': best_token,
                    'from_amount': amount,
                    'to_amount': new_amount,
                    'diff': holding_mom - best_mom
                })
                
                holding = best_token
                amount = new_amount
                last_swap = idx
        
        # Final actual equivalents
        current_val = amount * self.data.prices[holding][end_idx]
        for token in self.data.tokens:
            actual[token] = current_val / self.data.prices[token][end_idx]
        
        # Build matrix
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
                'start_token': 'BTCUSDT',
                'start_amount': 1.0,
                'final_token': holding,
                'final_amount': amount,
                'final_value': amount * self.data.prices[holding][end_idx],
                'params': {'lookback': lookback, 'threshold': threshold, 'interval': interval},
                'n_swaps': len(swaps),
                'swaps': swaps[-50:]
            },
            'matrix': matrix,
            'baseline': baseline
        }


global_data = None


@app.route('/')
def index():
    return render_template('robust_dashboard.html')


@app.route('/api/robust', methods=['POST'])
def robust():
    """Walk-forward validation - testuj na 4 okresach."""
    global global_data
    if global_data is None:
        global_data = DataLoader("market.csv")
        global_data.load()
    
    bt = RobustBacktester(global_data)
    
    # Testuj kombinacje
    results = []
    periods = [
        (100, 60000),
        (60000, 120000),
        (120000, 180000),
        (180000, global_data.n_records - 1)
    ]
    
    for lookback in [10, 15, 20, 30, 50]:
        for threshold in [0.010, 0.015, 0.020, 0.025, 0.030, 0.050]:
            for interval in [10, 15, 20, 30]:
                gains = []
                
                for start_idx, end_idx in periods:
                    r = bt.run(lookback, threshold, interval, start_idx, end_idx)
                    gains.append(r['matrix'][0]['gain_pct'])
                
                results.append({
                    'params': {'lookback': lookback, 'threshold': threshold, 'interval': interval},
                    'gains': gains,
                    'min_gain': min(gains),
                    'avg_gain': sum(gains) / len(gains)
                })
    
    results.sort(key=lambda x: x['min_gain'], reverse=True)
    
    return jsonify({'results': results})


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
def run():
    global global_data
    if global_data is None:
        global_data = DataLoader("market.csv")
        global_data.load()
    
    data = request.json or {}
    bt = RobustBacktester(global_data)
    
    result = bt.run(
        lookback=int(data.get('lookback', 10)),
        threshold=float(data.get('threshold', 0.015)),
        interval=int(data.get('interval', 15))
    )
    
    return jsonify(result)


@app.route('/api/optimize', methods=['POST'])
def optimize():
    global global_data
    if global_data is None:
        global_data = DataLoader("market.csv")
        global_data.load()
    
    bt = RobustBacktester(global_data)
    start = time.time()
    
    results = []
    
    # Walk-forward validation
    periods = [
        (100, 60000),
        (60000, 120000),
        (120000, 180000),
        (180000, global_data.n_records - 1)
    ]
    
    # Testuj kombinacje
    for lookback in [10, 15, 20, 30, 50]:
        for threshold in [0.010, 0.015, 0.020, 0.025, 0.030, 0.050]:
            for interval in [10, 15, 20, 30]:
                gains = []
                
                for start_idx, end_idx in periods:
                    r = bt.run(lookback, threshold, interval, start_idx, end_idx)
                    top_gain = r['matrix'][0]['gain_pct']
                    gains.append(top_gain)
                
                results.append({
                    'params': {'lookback': lookback, 'threshold': threshold, 'interval': interval},
                    'gains': gains,
                    'min_gain': min(gains),
                    'avg_gain': sum(gains) / len(gains),
                    'all_positive': all(g > 0 for g in gains)
                })
    
    # Sortuj po min_gain
    results.sort(key=lambda x: x['min_gain'], reverse=True)
    
    # Filtruj pozytywne
    positive = [r for r in results if r['all_positive']]
    
    elapsed = time.time() - start
    
    return jsonify({
        'robust': positive[:20] if positive else results[:20],
        'all_tested': len(results),
        'positive_count': len(positive),
        'time': f'{elapsed:.1f}s'
    })


if __name__ == '__main__':
    print("""
╔═══════════════════════════════════════════════════════════════╗
║     SWAPPER v4 - ROBUST STRATEGY                        ║
║     http://localhost:5000                                ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    app.run(debug=True, host='0.0.0.0', port=5000)
