#!/usr/bin/env python3
"""
Swapper Web Dashboard v2 - Pełna wizualizacja strategii

Funkcje:
1. Macierz baseline z initial amounts
2. Wyświetlanie wyników strategii na żywo
3. Wybór różnych strategii
4. Wykres equity curve
5. Tabela swapów
"""

from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import csv
import json
import random
import threading
import time
from dataclasses import dataclass, asdict
from typing import List, Optional
from datetime import datetime
import os

app = Flask(__name__)
CORS(app)

# Stałe
SWAP_FEE = 0.0004
DATA_PATH = "market.csv"


@dataclass
class StrategyParams:
    """Parametry strategii."""
    strategy_type: str = "momentum"
    lookback: int = 200
    threshold: float = 0.03
    min_interval: int = 20
    vs_btc_threshold: float = 0.01
    rsi_buy: int = 30
    rsi_sell: int = 70


class DataLoader:
    """Ładowanie danych rynkowych."""
    
    def __init__(self, filepath: str = DATA_PATH):
        self.filepath = filepath
        self.tokens = []
        self.prices = {}
        self.n_records = 0
        self.mids = {}
        
    def load(self):
        """Ładuje dane z CSV."""
        print(f"Ładowanie danych z {self.filepath}...")
        
        with open(self.filepath, 'r') as f:
            reader = csv.reader(f)
            header = next(reader)
            
            for i, col in enumerate(header):
                if col.endswith('_BID'):
                    t = col.replace('_BID', '')
                    self.tokens.append(t)
                    self.prices[t] = []
                    self.mids[t] = []
            
            for row in reader:
                for i, t in enumerate(self.tokens):
                    bid_idx = 1 + i * 2
                    ask_idx = bid_idx + 1
                    if bid_idx < len(row) and ask_idx < len(row):
                        try:
                            bid = float(row[bid_idx])
                            ask = float(row[ask_idx])
                            mid = (bid + ask) / 2
                            self.prices[t].append(bid)
                            self.mids[t].append(mid)
                        except:
                            pass
        
        # Minimalna długość
        min_len = min(len(self.prices[t]) for t in self.tokens)
        for t in self.tokens:
            self.prices[t] = self.prices[t][:min_len]
            self.mids[t] = self.mids[t][:min_len]
        
        self.n_records = min_len
        print(f"Załadowano {self.n_records} rekordów, {len(self.tokens)} tokenów")
        
        # Oblicz returns
        self.returns = {}
        for t in self.tokens:
            self.returns[t] = []
            for i in range(1, len(self.mids[t])):
                r = (self.mids[t][i] - self.mids[t][i-1]) / self.mids[t][i-1]
                self.returns[t].append(r)
    
    def get_mid(self, token: str, idx: int) -> float:
        return self.mids[token][idx]
    
    def momentum(self, token: str, idx: int, period: int) -> float:
        if idx < period:
            return 0.0
        p1 = self.mids[token][idx - period]
        p2 = self.mids[token][idx]
        return (p2 - p1) / p1
    
    def rsi(self, token: str, idx: int, period: int = 14) -> float:
        if idx < period + 1:
            return 50.0
        gains = []
        losses = []
        for i in range(idx - period, idx):
            r = self.returns[token][i]
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


class Backtester:
    """Backtester strategii."""
    
    def __init__(self, data: DataLoader):
        self.data = data
        self.SWAP_FEE = SWAP_FEE
    
    def run_momentum(self, params: StrategyParams) -> dict:
        """Momentum strategy."""
        holding = "BTCUSDT"
        amount = 1.0
        last_swap = 0
        swaps = []
        equity = []
        btc_equity = []
        
        for idx in range(params.lookback, self.data.n_records - 1):
            # Equity curve
            val = amount * self.data.get_mid(holding, idx)
            equity.append(val)
            btc_equity.append(self.data.get_mid("BTCUSDT", idx))
            
            # Min interval
            if idx - last_swap < params.min_interval:
                continue
            
            # Current momentum
            holding_mom = self.data.momentum(holding, idx, params.lookback)
            
            # Find best
            best_token = None
            best_rel_mom = -999
            
            for token in self.data.tokens:
                if token == holding:
                    continue
                
                token_mom = self.data.momentum(token, idx, params.lookback)
                btc_mom = self.data.momentum("BTCUSDT", idx, params.lookback)
                rel_mom = token_mom - holding_mom
                vs_btc = token_mom - btc_mom
                
                if rel_mom > best_rel_mom and vs_btc > params.vs_btc_threshold:
                    best_rel_mom = rel_mom
                    best_token = token
            
            if best_token and best_rel_mom > params.threshold:
                # Swap
                from_price = self.data.get_mid(holding, idx)
                to_price = self.data.get_mid(best_token, idx)
                usdt = amount * from_price * (1 - self.SWAP_FEE)
                amount = usdt / to_price
                
                swaps.append({
                    'idx': idx,
                    'from': holding,
                    'to': best_token,
                    'amount': amount,
                    'momentum': best_rel_mom
                })
                holding = best_token
                last_swap = idx
        
        # Final
        final_idx = self.data.n_records - 1
        final_value = amount * self.data.get_mid(holding, final_idx)
        btc_final = self.data.get_mid("BTCUSDT", final_idx)
        btc_value = btc_final
        
        return {
            'holding': holding,
            'amount': amount,
            'final_value': final_value,
            'gain_vs_btc': ((final_value / btc_value) - 1) * 100,
            'n_swaps': len(swaps),
            'swaps': swaps,
            'equity': equity[-500:],  # Last 500 points
            'btc_equity': btc_equity[-500:],
            'start_price': self.data.get_mid("BTCUSDT", params.lookback),
            'end_price': self.data.get_mid("BTCUSDT", final_idx)
        }


# Global state
state = {
    "running": False,
    "data_loaded": False,
    "best_result": None,
    "current_result": None,
    "baseline": None,
    "params": None,
    "strategy_types": ["momentum", "rsi_contrarian", "relative_strength"]
}

# Global data
global_data = None


def load_data():
    """Ładuje dane globalnie."""
    global global_data, state
    if global_data is None:
        global_data = DataLoader(DATA_PATH)
        global_data.load()
        
        # Oblicz baseline
        btc_mid = global_data.get_mid("BTCUSDT", 100)
        btc_start = global_data.get_mid("BTCUSDT", 0)
        usdt_value = btc_start
        
        baseline = []
        for token in global_data.tokens:
            token_price = global_data.get_mid(token, 0)
            initial_amount = usdt_value / token_price
            final_price = global_data.get_mid(token, -1)
            current_value = initial_amount * final_price
            
            baseline.append({
                'token': token,
                'initial_amount': initial_amount,
                'initial_price': token_price,
                'final_price': final_price,
                'current_value': current_value,
                'gain_pct': ((final_price / token_price) - 1) * 100,
                'is_btc': token == "BTCUSDT"
            })
        
        state["baseline"] = baseline
        state["data_loaded"] = True
        
        print(f"Dane załadowane. Baseline obliczony dla {len(baseline)} tokenów.")


@app.route('/')
def index():
    """Strona główna."""
    return render_template('dashboard_v2.html')


@app.route('/api/baseline')
def get_baseline():
    """Zwraca macierz baseline."""
    load_data()
    return jsonify({
        'start_token': 'BTCUSDT',
        'start_price': global_data.get_mid("BTCUSDT", 0),
        'baseline': state["baseline"]
    })


@app.route('/api/run', methods=['POST'])
def run_strategy():
    """Uruchamia strategię."""
    global state, global_data
    
    load_data()
    
    data = request.json or {}
    
    # Parse params
    params = StrategyParams(
        strategy_type=data.get('strategy_type', 'momentum'),
        lookback=int(data.get('lookback', 200)),
        threshold=float(data.get('threshold', 0.03)),
        min_interval=int(data.get('min_interval', 20)),
        vs_btc_threshold=float(data.get('vs_btc_threshold', 0.01))
    )
    
    state["params"] = asdict(params)
    state["running"] = True
    
    # Run backtest
    bt = Backtester(global_data)
    result = bt.run_momentum(params)
    
    state["current_result"] = result
    state["running"] = False
    
    # Update best if better
    if state["best_result"] is None or result['gain_vs_btc'] > state["best_result"]['gain_vs_btc']:
        state["best_result"] = result
    
    return jsonify({
        'result': result,
        'params': state["params"]
    })


@app.route('/api/optimize', methods=['POST'])
def optimize():
    """Optymalizuje strategię - testuje wiele kombinacji."""
    global state, global_data
    
    load_data()
    
    data = request.json or {}
    n_iterations = int(data.get('n_iterations', 20))
    
    state["running"] = True
    results = []
    
    # Grid search
    for lookback in [100, 200, 300, 500]:
        for threshold in [0.01, 0.02, 0.03, 0.05]:
            for interval in [10, 20, 50]:
                params = StrategyParams(
                    lookback=lookback,
                    threshold=threshold,
                    min_interval=interval
                )
                
                bt = Backtester(global_data)
                result = bt.run_momentum(params)
                result['params'] = asdict(params)
                results.append(result)
                
                # Update best
                if state["best_result"] is None or result['gain_vs_btc'] > state["best_result"]['gain_vs_btc']:
                    state["best_result"] = result
                    state["params"] = asdict(params)
    
    # Sort by gain
    results.sort(key=lambda x: x['gain_vs_btc'], reverse=True)
    
    state["running"] = False
    
    return jsonify({
        'results': results[:50],  # Top 50
        'best': state["best_result"],
        'best_params': state["params"]
    })


@app.route('/api/state')
def get_state():
    """Zwraca obecny stan."""
    return jsonify({
        'running': state["running"],
        'data_loaded': state["data_loaded"],
        'best_result': state["best_result"],
        'current_result': state["current_result"],
        'params': state["params"]
    })


if __name__ == '__main__':
    print("""
╔═══════════════════════════════════════════════════════════════╗
║          SWAPPER Web Dashboard v2                           ║
║          http://localhost:5000                              ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    # Pre-load data
    load_data()
    
    app.run(debug=True, host='0.0.0.0', port=5000)
