#!/usr/bin/env python3
"""
REAL-TIME TRADER SERVER - Port 12000

- API: GET /api/status - zwraca stan portfela
- Persistence: stan zapisywany do portfolio_state.json
- Przy starcie: wczytuje poprzedni stan jeśli istnieje
"""

import json
import os
import csv
import threading
import time
from flask import Flask, jsonify, request
from datetime import datetime

app = Flask(__name__)

STATE_FILE = 'portfolio_state.json'
DATA_FILE = 'market.csv'
UPDATE_INTERVAL = 1  # sekundy

# Stan portfela
portfolio = {
    'holding_token': 'BTCUSDT',
    'holding_amount': 1.0,
    'total_swaps': 0,
    'swap_history': [],
    'start_time': datetime.now().isoformat(),
    'current_idx': 100,
    'last_update': None,
    'lookback': 5,
    'threshold': 0.03,
    'interval': 12
}

# Dane rynkowe
data_lock = threading.Lock()
tokens = []
prices = {}
n_records = 0


def load_market_data():
    """Ładuje dane rynkowe."""
    global tokens, prices, n_records
    
    with open(DATA_FILE, 'r') as f:
        reader = csv.reader(f)
        header = next(reader)
        
        for i, col in enumerate(header):
            if col.endswith('_BID'):
                t = col.replace('_BID', '')
                tokens.append(t)
                prices[t] = []
        
        for row in reader:
            for i, t in enumerate(tokens):
                idx = 1 + i * 2
                if idx < len(row):
                    try:
                        prices[t].append(float(row[idx]))
                    except:
                        prices[t].append(0)
        
        min_len = min(len(prices[t]) for t in tokens)
        for t in tokens:
            prices[t] = prices[t][:min_len]
        
        n_records = min_len


def save_state():
    """Zapisuje stan portfela do pliku."""
    with open(STATE_FILE, 'w') as f:
        json.dump(portfolio, f, indent=2)


def load_state():
    """Wczytuje stan portfela z pliku."""
    global portfolio
    
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            loaded = json.load(f)
            
        # Sprawdź czy to wczorajszy stan (nowszy niż 1 dzień)
        last_update = loaded.get('last_update')
        if last_update:
            try:
                last_dt = datetime.fromisoformat(last_update)
                age = (datetime.now() - last_dt).total_seconds()
                if age < 86400:  # mniej niż 24h
                    portfolio.update(loaded)
                    print(f"[STATE] Wczytano poprzedni stan z {last_update}")
                    print(f"[STATE] Holding: {portfolio['holding_token']}, "
                          f"Amount: {portfolio['holding_amount']:.4f}, "
                          f"Swaps: {portfolio['total_swaps']}")
                    return True
            except:
                pass
    
    print("[STATE] Brak poprzedniego stanu - start od nowa")
    return False


def momentum(token, idx, period):
    """Oblicza momentum."""
    if idx < period:
        return 0.0
    past = prices[token][idx - period]
    now = prices[token][idx]
    if past <= 0:
        return 0.0
    return (now - past) / past


def calculate_portfolio_value():
    """Oblicza wartość portfela w USDT."""
    holding = portfolio['holding_token']
    amount = portfolio['holding_amount']
    
    if holding == 'BTCUSDT':
        return amount * prices['BTCUSDT'][portfolio['current_idx']]
    else:
        # Konwersja przez BTC
        btc_value = amount * prices[holding][portfolio['current_idx']]
        return btc_value * prices['BTCUSDT'][portfolio['current_idx']]


def calculate_token_accumulation_roi():
    """Oblicza ROI akumulacji tokenów vs baseline."""
    holding = portfolio['holding_token']
    current_idx = portfolio['current_idx']
    start_idx = 100
    
    # Baseline: ile BTC kupiliśmy na start
    btc_price_start = prices['BTCUSDT'][start_idx]
    initial_btc = 1.0
    
    # Ile tokenów mogliśmy mieć gdybyśmy kupili na start i trzymali
    if holding == 'BTCUSDT':
        baseline_tokens = initial_btc
    else:
        # Kup BTC -> USDT -> Token
        usdt = initial_btc * btc_price_start * 0.9996
        baseline_tokens = usdt / prices[holding][start_idx]
    
    # Ile mamy teraz
    current_tokens = portfolio['holding_amount'] if holding != 'BTCUSDT' else 1.0
    
    if baseline_tokens > 0:
        return ((current_tokens / baseline_tokens) - 1) * 100
    return 0.0


def execute_tick():
    """Wykonuje jeden krok tradingu."""
    global portfolio
    
    idx = portfolio['current_idx']
    lb = portfolio['lookback']
    th = portfolio['threshold']
    iv = portfolio['interval']
    
    if idx >= n_records - 1:
        return
    
    # Min interval check
    if portfolio['swap_history']:
        last_swap_idx = portfolio['swap_history'][-1]['idx']
        if idx - last_swap_idx < iv:
            portfolio['current_idx'] += 1
            portfolio['last_update'] = datetime.now().isoformat()
            return
    
    holding = portfolio['holding_token']
    
    # Oblicz momentum
    holding_mom = momentum(holding, idx, lb)
    
    # Znajdź najlepszy token (tracący najmniej)
    best_token = None
    best_mom = 999
    
    for token in tokens:
        if token == holding:
            continue
        
        token_mom = momentum(token, idx, lb)
        
        if token_mom < best_mom and token_mom < holding_mom:
            best_mom = token_mom
            best_token = token
    
    # Swap jeśli threshold przekroczony
    if best_token and (holding_mom - best_mom) > th:
        from_price = prices[holding][idx]
        to_price = prices[best_token][idx]
        
        if from_price > 0 and to_price > 0:
            usdt = portfolio['holding_amount'] * from_price * 0.9996 * 0.9996
            new_amount = usdt / to_price
            
            portfolio['swap_history'].append({
                'idx': idx,
                'from': holding,
                'to': best_token,
                'amount_in': portfolio['holding_amount'],
                'amount_out': new_amount
            })
            
            portfolio['holding_token'] = best_token
            portfolio['holding_amount'] = new_amount
            portfolio['total_swaps'] += 1
            
            # Zapisz natychmiast po swapie
            save_state()
    
    portfolio['current_idx'] += 1
    portfolio['last_update'] = datetime.now().isoformat()


# Background thread
running = True

def trading_loop():
    """Główna pętla tradingu."""
    global running
    
    print(f"[TRADING] Start pętli (idx={portfolio['current_idx']}/{n_records})")
    
    while running and portfolio['current_idx'] < n_records - 1:
        execute_tick()
        
        # Zapisz co 100 kroków
        if portfolio['current_idx'] % 100 == 0:
            save_state()
        
        time.sleep(UPDATE_INTERVAL)
    
    # Final save
    save_state()
    print(f"[TRADING] Koniec - zapisano stan")


@app.route('/api/status', methods=['GET'])
def get_status():
    """Zwraca status portfela."""
    current_idx = portfolio['current_idx']
    
    holding_value_usdt = calculate_portfolio_value()
    token_accumulation_roi = calculate_token_accumulation_roi()
    
    # Oblicz ile każdego tokena moglibyśmy mieć
    token_equiv = {}
    for token in tokens:
        if prices[token][current_idx] > 0:
            token_equiv[token] = holding_value_usdt / prices[token][current_idx]
    
    return jsonify({
        'portfolio': {
            'holding_token': portfolio['holding_token'],
            'holding_amount': portfolio['holding_amount'],
            'holding_value_usdt': holding_value_usdt,
            'token_accumulation_roi': token_accumulation_roi,
            'total_swaps': portfolio['total_swaps'],
            'current_idx': current_idx,
            'n_records': n_records,
            'progress_pct': round((current_idx / n_records) * 100, 2),
            'start_time': portfolio['start_time'],
            'last_update': portfolio['last_update'],
            'lookback': portfolio['lookback'],
            'threshold': portfolio['threshold'],
            'interval': portfolio['interval']
        },
        'swaps': portfolio['swap_history'][-10:],
        'top_tokens': sorted(
            [{'token': t, 'equiv': token_equiv.get(t, 0)} for t in tokens],
            key=lambda x: x['equiv'],
            reverse=True
        )[:5]
    })


@app.route('/api/config', methods=['POST'])
def update_config():
    """Aktualizuje konfigurację strategii."""
    data = request.json or {}
    
    if 'lookback' in data:
        portfolio['lookback'] = int(data['lookback'])
    if 'threshold' in data:
        portfolio['threshold'] = float(data['threshold'])
    if 'interval' in data:
        portfolio['interval'] = int(data['interval'])
    
    save_state()
    
    return jsonify({'status': 'ok', 'config': {
        'lookback': portfolio['lookback'],
        'threshold': portfolio['threshold'],
        'interval': portfolio['interval']
    }})


@app.route('/api/reset', methods=['POST'])
def reset_portfolio():
    """Resetuje portfel do początkowego stanu."""
    portfolio['holding_token'] = 'BTCUSDT'
    portfolio['holding_amount'] = 1.0
    portfolio['total_swaps'] = 0
    portfolio['swap_history'] = []
    portfolio['current_idx'] = 100
    portfolio['start_time'] = datetime.now().isoformat()
    
    save_state()
    
    return jsonify({'status': 'reset'})


@app.route('/api/swaps', methods=['GET'])
def get_swaps():
    """Zwraca historię swapów."""
    limit = int(request.args.get('limit', 50))
    return jsonify({
        'swaps': portfolio['swap_history'][-limit:],
        'total': portfolio['total_swaps']
    })


if __name__ == '__main__':
    print("""
╔═══════════════════════════════════════════════════════════════╗
║     REAL-TIME TRADER SERVER                           ║
║     Port: 12000                                        ║
║     API: /api/status                                   ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    # Ładuj dane
    print("Ładowanie danych rynkowych...")
    load_market_data()
    print(f"Załadowano {n_records} rekordów, {len(tokens)} tokenów")
    
    # Wczytaj lub zainicjuj stan
    has_prev = load_state()
    
    # Uruchom w tle
    trader_thread = threading.Thread(target=trading_loop, daemon=True)
    trader_thread.start()
    
    # Start serwera
    print(f"\nSerwer startuje na http://0.0.0.0:12000")
    print(f"API: curl http://localhost:12000/api/status\n")
    
    app.run(host='0.0.0.0', port=12000, debug=False, use_reloader=False)
