#!/usr/bin/env python3
"""
CHAMPION ULTIMATE - DASHBOARD
Ładny interfejs z portfolio, macierzą i kontrolą
"""

import json
import os
import time
import requests
import threading
import subprocess
import sys
import signal
from datetime import datetime
from flask import Flask, jsonify, request, render_template_string, send_file
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# === KONFIGURACJA ===
STRATEGY = {
    'name': 'CHAMPION_ULTIMATE',
    'lookback': 5,
    'threshold': 0.02,
    'interval': 10
}

TRACKED_SYMBOLS = [
    'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'ADAUSDT',
    'DOGEUSDT', 'DOTUSDT', 'AVAXUSDT', 'LINKUSDT', 'LTCUSDT',
    'UNIUSDT', 'ATOMUSDT', 'NEARUSDT', 'FILUSDT', 'AAVEUSDT',
    'SNXUSDT', 'CRVUSDT', 'LDOUSDT', 'ARBUSDT', 'OPUSDT',
    'INJUSDT', 'SUIUSDT', 'SEIUSDT', 'TIAUSDT', 'PEPEUSDT',
    'SHIBUSDT', 'BONKUSDT', 'APTUSDT', 'SANDUSDT', 'MANAUSDT',
    'AXSUSDT', 'ALGOUSDT', 'VETUSDT', 'HBARUSDT', 'XTZUSDT',
    'CAKEUSDT', 'RUNEUSDT', 'KAVAUSDT', 'ENSUSDT', 'COMPUSDT',
    'YFIUSDT', 'RPLUSDT', 'GMXUSDT', 'DYDXUSDT', 'APEUSDT',
    'MAGICUSDT', 'GALAUSDT', 'IMXUSDT', 'CROUSDT', 'QNTUSDT',
    'GRTUSDT', 'ALUUSDT', 'WLDUSDT', 'FETUSDT', 'JASMYUSDT',
    'SFPUSDT', 'ZILUSDT', 'CHZUSDT', 'ENJUSDT', 'BATUSDT',
    'SLPUSDT', 'GODSUSDT', 'HIGHUSDT', 'SPELLUSDT', 'RAYUSDT',
    'MAPUSDT', 'SCRTUSDT', 'ATSUSDT', 'REQUSDT', 'UNCUSDT',
    'OOBUSDT', 'HNSUSDT', 'MRVLONUSDT', 'AGLDUSDT', 'BIT1USDT',
    'ZECUSDT', 'ZKUUSDT', 'RLSUSDT', 'ZEUSUSDT', 'NILUSDT',
    'AUCUSDT', 'PERMUSDT', 'EFCUSDT', 'OUSDT', 'VISTAUSDT',
    'RICEUSDT', 'WENUSDT', 'STOPUSDT', 'PUNDIAIUSDT', 'BBUSDT',
    'SIXUSDT', 'QBXUSDT', 'CRMONUSDT', 'XEPUSDT'
]

STATE_FILE = 'portfolio_state.json'
API_BASE = 'https://api.mexc.com'
UPDATE_INTERVAL = 1  # 1 second for faster updates
TRADER_PORT = 12001

app = Flask(__name__)

trader_process = None

@dataclass
class Price:
    symbol: str
    bid: float
    ask: float
    timestamp: str
    
    @property
    def spread(self) -> float:
        return (self.ask - self.bid) / self.ask if self.ask > 0 else 0

@dataclass
class Swap:
    timestamp: str
    from_token: str
    to_token: str
    from_amount: float
    to_amount: float
    from_price: float
    to_price: float
    fee: float
    holding_momentum: float
    target_momentum: float

@dataclass
class PaperPortfolio:
    holding_token: str
    holding_amount: float
    total_swaps: int
    swap_history: List[Swap] = field(default_factory=list)
    start_time: str = ""
    start_value_usdt: float = 0.0
    price_history: Dict[str, List[float]] = field(default_factory=dict)
    baseline: Dict[str, float] = field(default_factory=dict)

portfolio = PaperPortfolio(
    holding_token='BTCUSDT',
    holding_amount=1.0,
    total_swaps=0,
    swap_history=[],
    start_time=datetime.now().isoformat(),
    start_value_usdt=0.0
)

prices_lock = threading.Lock()
current_prices: Dict[str, Price] = {}
running = True
trader_running = False


def fetch_bid_ask(symbol: str) -> Optional[Price]:
    try:
        resp = requests.get(
            f'{API_BASE}/api/v3/ticker/bookTicker',
            params={'symbol': symbol},
            timeout=5
        )
        if resp.status_code == 200:
            data = resp.json()
            return Price(
                symbol=symbol,
                bid=float(data.get('bidPrice', 0)),
                ask=float(data.get('askPrice', 0)),
                timestamp=datetime.now().isoformat()
            )
    except:
        pass
    return None


def fetch_all_prices() -> Dict[str, Price]:
    prices = {}
    for symbol in TRACKED_SYMBOLS:
        price = fetch_bid_ask(symbol)
        if price:
            prices[symbol] = price
    return prices


def get_momentum(symbol: str, period: int = 5) -> float:
    history = portfolio.price_history.get(symbol, [])
    if len(history) < period + 1:
        return 0.0
    current = history[-1]
    past = history[-(period + 1)]
    if past <= 0:
        return 0.0
    return (current - past) / past


def should_swap() -> Optional[tuple]:
    lb = STRATEGY['lookback']
    th = STRATEGY['threshold']
    holding = portfolio.holding_token
    holding_mom = get_momentum(holding, lb)
    
    best_token = None
    best_mom = 999.0
    best_diff = 0.0
    
    for symbol in TRACKED_SYMBOLS:
        if symbol == holding:
            continue
        if len(portfolio.price_history.get(symbol, [])) < lb + 1:
            continue
        
        token_mom = get_momentum(symbol, lb)
        if token_mom < best_mom and token_mom < holding_mom:
            best_mom = token_mom
            best_token = symbol
            best_diff = holding_mom - token_mom
    
    if best_token and best_diff > th:
        return (best_token, best_diff, holding_mom, best_mom)
    return None


def execute_swap(target_token: str, confidence: float, holding_mom: float, target_mom: float):
    global current_prices
    
    with prices_lock:
        holding_price = current_prices.get(portfolio.holding_token)
        target_price = current_prices.get(target_token)
    
    if not holding_price or not target_price:
        return False
    
    bid_price = holding_price.bid
    ask_price = target_price.ask
    
    if bid_price <= 0 or ask_price <= 0:
        return False
    
    fee_factor = 0.9992
    amount = portfolio.holding_amount
    usdt = amount * bid_price * fee_factor
    new_amount = usdt / ask_price * fee_factor
    
    swap = Swap(
        timestamp=datetime.now().isoformat(),
        from_token=portfolio.holding_token,
        to_token=target_token,
        from_amount=amount,
        to_amount=new_amount,
        from_price=bid_price,
        to_price=ask_price,
        fee=0.0008,
        holding_momentum=holding_mom,
        target_momentum=target_mom
    )
    
    portfolio.swap_history.append(swap)
    portfolio.holding_token = target_token
    portfolio.holding_amount = new_amount
    portfolio.total_swaps += 1
    
    return True


def get_gain_pct(token: str) -> float:
    baseline = portfolio.baseline.get(token, 0)
    actual = portfolio.holding_amount if token == portfolio.holding_token else 0
    if baseline <= 0:
        return 0.0
    return ((actual - baseline) / baseline) * 100


def init_baseline():
    global current_prices
    btc_price = current_prices.get('BTCUSDT')
    if not btc_price or btc_price.bid <= 0:
        return
    
    btc_value = 1.0 * btc_price.bid
    
    for symbol in TRACKED_SYMBOLS:
        price = current_prices.get(symbol)
        if price and price.ask > 0:
            portfolio.baseline[symbol] = btc_value / price.ask


def update_loop():
    global current_prices, running
    last_swap_time = 0
    
    while running:
        try:
            # Fetch prices with timeout
            new_prices = {}
            for symbol in TRACKED_SYMBOLS:
                try:
                    price = fetch_bid_ask(symbol)
                    if price:
                        new_prices[symbol] = price
                except:
                    continue
            
            with prices_lock:
                current_prices = new_prices
            
            for symbol, price in current_prices.items():
                if symbol not in portfolio.price_history:
                    portfolio.price_history[symbol] = []
                portfolio.price_history[symbol].append(price.bid)
                if len(portfolio.price_history[symbol]) > 100:
                    portfolio.price_history[symbol] = portfolio.price_history[symbol][-100:]
            
            current_time = time.time()
            if current_time - last_swap_time >= STRATEGY['interval']:
                result = should_swap()
                if result:
                    target_token, confidence, holding_mom, target_mom = result
                    if execute_swap(target_token, confidence, holding_mom, target_mom):
                        last_swap_time = current_time
                        save_state()
            
        except Exception as e:
            print(f"[ERROR] {e}")
        
        time.sleep(UPDATE_INTERVAL)


def save_state():
    data = {
        'holding_token': portfolio.holding_token,
        'holding_amount': portfolio.holding_amount,
        'total_swaps': portfolio.total_swaps,
        'swap_history': [
            {
                'timestamp': s.timestamp,
                'from_token': s.from_token,
                'to_token': s.to_token,
                'from_amount': s.from_amount,
                'to_amount': s.to_amount,
                'from_price': s.from_price,
                'to_price': s.to_price,
                'fee': s.fee,
                'holding_momentum': s.holding_momentum,
                'target_momentum': s.target_momentum
            }
            for s in portfolio.swap_history
        ],
        'start_time': portfolio.start_time,
        'start_value_usdt': portfolio.start_value_usdt,
        'strategy': STRATEGY,
        'baseline': portfolio.baseline
    }
    with open(STATE_FILE, 'w') as f:
        json.dump(data, f, indent=2)


def load_state():
    global portfolio
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                data = json.load(f)
            last_update = data.get('start_time', '')
            if last_update:
                last_dt = datetime.fromisoformat(last_update)
                age = (datetime.now() - last_dt).total_seconds()
                if age < 86400:
                    portfolio.holding_token = data.get('holding_token', 'BTCUSDT')
                    portfolio.holding_amount = data.get('holding_amount', 1.0)
                    portfolio.total_swaps = data.get('total_swaps', 0)
                    portfolio.start_time = data.get('start_time', datetime.now().isoformat())
                    portfolio.start_value_usdt = data.get('start_value_usdt', 0.0)
                    portfolio.swap_history = [Swap(**s) for s in data.get('swap_history', [])]
                    portfolio.baseline = data.get('baseline', {})
                    if 'strategy' in data:
                        STRATEGY.update(data['strategy'])
                    return True
        except Exception as e:
            print(f"[STATE] Error: {e}")
    return False


# === TRADER CONTROL ===
def start_trader():
    global trader_process, trader_running
    if trader_process is None or trader_process.poll() is not None:
        trader_process = subprocess.Popen(
            [sys.executable, __file__, '--trader'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        trader_running = True
        return True
    return False


def stop_trader():
    global trader_process, trader_running
    if trader_process:
        trader_process.terminate()
        trader_process = None
    trader_running = False
    return True


def restart_trader():
    stop_trader()
    time.sleep(1)
    return start_trader()


# === API ===
@app.route('/')
def index():
    return render_template_string(DASHBOARD_HTML)


@app.route('/api/status')
def get_status():
    with prices_lock:
        prices = {s: {'bid': p.bid, 'ask': p.ask, 'spread': p.spread}
                  for s, p in current_prices.items()}
    
    holding_price = current_prices.get(portfolio.holding_token)
    value_usdt = portfolio.holding_amount * holding_price.bid if holding_price else 0
    btc_price = current_prices.get('BTCUSDT')
    btc_value = 1.0 * btc_price.bid if btc_price else 0
    
    momentum_data = {}
    for symbol in TRACKED_SYMBOLS:
        if symbol in portfolio.price_history:
            momentum_data[symbol] = get_momentum(symbol, STRATEGY['lookback'])
    
    baseline_amount = portfolio.baseline.get(portfolio.holding_token, 0)
    gain_pct = get_gain_pct(portfolio.holding_token)
    
    # Debug: include price history length
    btc_hist_len = len(portfolio.price_history.get('BTCUSDT', []))
    
    return jsonify({
        'portfolio': {
            'holding_token': portfolio.holding_token,
            'holding_amount': portfolio.holding_amount,
            'holding_value_usdt': value_usdt,
            'baseline_amount': baseline_amount,
            'gain_pct': gain_pct,
            'total_swaps': portfolio.total_swaps,
            'start_time': portfolio.start_time,
            'strategy': STRATEGY,
            'btc_price': btc_value,
            'tokens_tracked': len(current_prices),
            'btc_history_len': btc_hist_len
        },
        'prices': prices,
        'momentum': momentum_data,
        'swaps': [
            {
                'timestamp': s.timestamp,
                'from_token': s.from_token,
                'to_token': s.to_token,
                'from_amount': s.from_amount,
                'to_amount': s.to_amount,
                'from_price': s.from_price,
                'to_price': s.to_price,
                'fee_pct': s.fee * 100
            }
            for s in portfolio.swap_history[-20:]
        ],
        'trader_running': trader_running_flag
    })


@app.route('/api/control', methods=['POST'])
def control():
    global portfolio
    data = request.json or {}
    action = data.get('action', '')
    
    if action == 'start':
        start_trader()
    elif action == 'stop':
        stop_trader()
    elif action == 'restart':
        restart_trader()
    elif action == 'reset':
        portfolio = PaperPortfolio(
            holding_token='BTCUSDT',
            holding_amount=1.0,
            total_swaps=0,
            swap_history=[],
            start_time=datetime.now().isoformat(),
            start_value_usdt=0.0,
            price_history={}
        )
        save_state()
    
    return jsonify({'status': 'ok', 'action': action, 'trader_running': trader_running_flag})


@app.route('/api/config', methods=['POST'])
def update_config():
    data = request.json or {}
    if 'lookback' in data:
        STRATEGY['lookback'] = int(data['lookback'])
    if 'threshold' in data:
        STRATEGY['threshold'] = float(data['threshold'])
    if 'interval' in data:
        STRATEGY['interval'] = int(data['interval'])
    save_state()
    return jsonify({'status': 'ok', 'strategy': STRATEGY})


# === TRADER CONTROL ===
trader_thread = None
trader_running_flag = False

def start_trader():
    global trader_thread, trader_running_flag, running
    
    if trader_thread is None or not trader_thread.is_alive():
        running = True
        trader_running_flag = True
        trader_thread = threading.Thread(target=update_loop, daemon=True)
        trader_thread.start()
        
        # Initialize baseline and prices
        test_prices = fetch_all_prices()
        if test_prices:
            with prices_lock:
                current_prices.update(test_prices)
            if not portfolio.baseline:
                init_baseline()
        
        return True
    return False


def stop_trader():
    global trader_running_flag, running
    running = False
    trader_running_flag = False
    return True


def restart_trader():
    stop_trader()
    time.sleep(1)
    return start_trader()


DASHBOARD_HTML = '''
<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CHAMPION ULTIMATE - Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 100%);
            color: #fff;
            min-height: 100vh;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }
        
        header {
            text-align: center;
            padding: 30px 0;
            border-bottom: 1px solid #333;
        }
        
        h1 {
            font-size: 2.5em;
            background: linear-gradient(90deg, #00d4ff, #9b59b6);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 10px;
        }
        
        .subtitle {
            color: #888;
            font-size: 1.1em;
        }
        
        .controls {
            display: flex;
            justify-content: center;
            gap: 15px;
            margin: 30px 0;
        }
        
        .btn {
            padding: 15px 40px;
            font-size: 1.1em;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.3s;
            font-weight: bold;
        }
        
        .btn-run {
            background: linear-gradient(135deg, #27ae60, #2ecc71);
            color: white;
        }
        
        .btn-stop {
            background: linear-gradient(135deg, #e74c3c, #c0392b);
            color: white;
        }
        
        .btn-restart {
            background: linear-gradient(135deg, #f39c12, #e67e22);
            color: white;
        }
        
        .btn-reset {
            background: linear-gradient(135deg, #9b59b6, #8e44ad);
            color: white;
        }
        
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 20px rgba(0,0,0,0.3);
        }
        
        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }
        
        .status-badge {
            display: inline-block;
            padding: 8px 20px;
            border-radius: 20px;
            font-size: 0.9em;
            margin-left: 20px;
        }
        
        .status-running {
            background: #27ae60;
        }
        
        .status-stopped {
            background: #e74c3c;
        }
        
        .grid {
            display: grid;
            grid-template-columns: 1fr 2fr;
            gap: 20px;
            margin-top: 30px;
        }
        
        .card {
            background: rgba(255,255,255,0.05);
            border-radius: 15px;
            padding: 25px;
            border: 1px solid rgba(255,255,255,0.1);
        }
        
        .card-title {
            font-size: 1.3em;
            margin-bottom: 20px;
            color: #00d4ff;
            border-bottom: 1px solid #333;
            padding-bottom: 10px;
        }
        
        .portfolio-item {
            display: flex;
            justify-content: space-between;
            padding: 15px;
            background: rgba(0,0,0,0.2);
            border-radius: 10px;
            margin-bottom: 10px;
        }
        
        .portfolio-label {
            color: #888;
        }
        
        .portfolio-value {
            font-size: 1.2em;
            font-weight: bold;
        }
        
        .portfolio-value.positive {
            color: #2ecc71;
        }
        
        .portfolio-value.negative {
            color: #e74c3c;
        }
        
        .matrix-container {
            max-height: 500px;
            overflow-y: auto;
        }
        
        .matrix-table {
            width: 100%;
            border-collapse: collapse;
        }
        
        .matrix-table th, .matrix-table td {
            padding: 8px 12px;
            text-align: left;
            border-bottom: 1px solid #333;
        }
        
        .matrix-table th {
            color: #888;
            font-weight: normal;
            position: sticky;
            top: 0;
            background: rgba(26,26,46,0.95);
        }
        
        .matrix-table tr:hover {
            background: rgba(255,255,255,0.05);
        }
        
        .token-holding {
            background: rgba(0,212,255,0.2) !important;
        }
        
        .momentum-positive {
            color: #2ecc71;
        }
        
        .momentum-negative {
            color: #e74c3c;
        }
        
        .swaps-list {
            max-height: 400px;
            overflow-y: auto;
        }
        
        .swap-item {
            padding: 15px;
            background: rgba(0,0,0,0.2);
            border-radius: 10px;
            margin-bottom: 10px;
            border-left: 4px solid #9b59b6;
        }
        
        .swap-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 10px;
        }
        
        .swap-tokens {
            font-size: 1.1em;
            font-weight: bold;
        }
        
        .swap-arrow {
            color: #00d4ff;
            margin: 0 10px;
        }
        
        .swap-details {
            font-size: 0.9em;
            color: #888;
        }
        
        .config-form {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 15px;
            margin-top: 15px;
        }
        
        .config-item {
            background: rgba(0,0,0,0.2);
            padding: 15px;
            border-radius: 10px;
        }
        
        .config-item label {
            display: block;
            color: #888;
            margin-bottom: 8px;
        }
        
        .config-item input {
            width: 100%;
            padding: 10px;
            border: 1px solid #333;
            border-radius: 5px;
            background: #0f0f1a;
            color: #fff;
            font-size: 1.1em;
        }
        
        .refresh-info {
            text-align: center;
            color: #666;
            margin-top: 20px;
            font-size: 0.9em;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        
        .live-indicator {
            display: inline-block;
            width: 10px;
            height: 10px;
            background: #2ecc71;
            border-radius: 50%;
            margin-right: 8px;
            animation: pulse 1.5s infinite;
        }
        
        .live-indicator.stopped {
            background: #e74c3c;
            animation: none;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🚀 CHAMPION ULTIMATE</h1>
            <p class="subtitle">Real-Time Trading z MEXC API <span id="status-badge" class="status-badge status-stopped">STOPPED</span></p>
        </header>
        
        <div class="controls">
            <button class="btn btn-run" onclick="control('start')">▶️ RUN</button>
            <button class="btn btn-stop" onclick="control('stop')">⏹️ STOP</button>
            <button class="btn btn-restart" onclick="control('restart')">🔄 RESTART</button>
            <button class="btn btn-reset" onclick="control('reset')">🗑️ RESET</button>
        </div>
        
        <div class="grid">
            <div>
                <div class="card">
                    <h3 class="card-title">📊 Portfolio</h3>
                    <div class="portfolio-item">
                        <span class="portfolio-label">Holding</span>
                        <span class="portfolio-value" id="holding-token">BTCUSDT</span>
                    </div>
                    <div class="portfolio-item">
                        <span class="portfolio-label">Ilość</span>
                        <span class="portfolio-value" id="holding-amount">1.0000</span>
                    </div>
                    <div class="portfolio-item">
                        <span class="portfolio-label">Wartość USDT</span>
                        <span class="portfolio-value" id="value-usdt">$0.00</span>
                    </div>
                    <div class="portfolio-item">
                        <span class="portfolio-label">Baseline</span>
                        <span class="portfolio-value" id="baseline">0.0000</span>
                    </div>
                    <div class="portfolio-item">
                        <span class="portfolio-label">Gain %</span>
                        <span class="portfolio-value" id="gain-pct">+0.00%</span>
                    </div>
                    <div class="portfolio-item">
                        <span class="portfolio-label">BTC Price</span>
                        <span class="portfolio-value" id="btc-price">$0.00</span>
                    </div>
                    <div class="portfolio-item">
                        <span class="portfolio-label">Swaps</span>
                        <span class="portfolio-value" id="total-swaps">0</span>
                    </div>
                    <div class="portfolio-item">
                        <span class="portfolio-label">Tokens Tracked</span>
                        <span class="portfolio-value" id="tokens-tracked">0</span>
                    </div>
                </div>
                
                <div class="card" style="margin-top: 20px;">
                    <h3 class="card-title">⚙️ Konfiguracja</h3>
                    <div class="config-form">
                        <div class="config-item">
                            <label>Lookback</label>
                            <input type="number" id="cfg-lookback" value="5" onchange="updateConfig()">
                        </div>
                        <div class="config-item">
                            <label>Threshold %</label>
                            <input type="number" id="cfg-threshold" value="2" step="0.1" onchange="updateConfig()">
                        </div>
                        <div class="config-item">
                            <label>Interval (s)</label>
                            <input type="number" id="cfg-interval" value="10" onchange="updateConfig()">
                        </div>
                    </div>
                </div>
            </div>
            
            <div>
                <div class="card">
                    <h3 class="card-title">📈 Matrix Momentum <span id="live-indicator" class="live-indicator stopped"></span></h3>
                    <div class="matrix-container">
                        <table class="matrix-table">
                            <thead>
                                <tr>
                                    <th>Token</th>
                                    <th>Momentum</th>
                                    <th>Baseline</th>
                                    <th>Price</th>
                                </tr>
                            </thead>
                            <tbody id="matrix-body">
                                <tr><td colspan="4" style="text-align:center;color:#888">Ładowanie...</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>
                
                <div class="card" style="margin-top: 20px;">
                    <h3 class="card-title">💱 Historia Swapów</h3>
                    <div class="swaps-list" id="swaps-list">
                        <p style="text-align:center;color:#888;padding:20px;">Brak swapów</p>
                    </div>
                </div>
            </div>
        </div>
        
        <p class="refresh-info">Automatyczne odświeżanie co 1 sekundę | <span id="last-update">Ostatni update: --</span></p>
    </div>
    
    <script>
        let isRunning = false;
        let lastUpdate = 0;
        
        async function fetchStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                updateUI(data);
                lastUpdate = Date.now();
                document.getElementById('last-update').textContent = 'Ostatni update: ' + new Date().toLocaleTimeString();
                document.getElementById('last-update').style.color = '#666';
            } catch (e) {
                console.error('Error:', e);
            }
        }
        
        function updateUI(data) {
            const p = data.portfolio;
            isRunning = data.trader_running;
            
            // Status badge
            const badge = document.getElementById('status-badge');
            const indicator = document.getElementById('live-indicator');
            if (isRunning) {
                badge.textContent = 'RUNNING';
                badge.className = 'status-badge status-running';
                indicator.className = 'live-indicator';
            } else {
                badge.textContent = 'STOPPED';
                badge.className = 'status-badge status-stopped';
                indicator.className = 'live-indicator stopped';
            }
            
            // Portfolio
            document.getElementById('holding-token').textContent = p.holding_token;
            document.getElementById('holding-amount').textContent = p.holding_amount.toFixed(4);
            document.getElementById('value-usdt').textContent = '$' + p.holding_value_usdt.toFixed(2);
            document.getElementById('baseline').textContent = p.baseline_amount.toFixed(4);
            
            const gainEl = document.getElementById('gain-pct');
            const gain = p.gain_pct;
            gainEl.textContent = (gain >= 0 ? '+' : '') + gain.toFixed(2) + '%';
            gainEl.className = 'portfolio-value ' + (gain >= 0 ? 'positive' : 'negative');
            
            document.getElementById('btc-price').textContent = '$' + p.btc_price.toFixed(2);
            document.getElementById('total-swaps').textContent = p.total_swaps;
            document.getElementById('tokens-tracked').textContent = p.tokens_tracked;
            
            // Config
            document.getElementById('cfg-lookback').value = p.strategy.lookback;
            document.getElementById('cfg-threshold').value = (p.strategy.threshold * 100).toFixed(1);
            document.getElementById('cfg-interval').value = p.strategy.interval;
            
            // Matrix
            const momentum = data.momentum;
            const prices = data.prices;
            const btc_price = p.btc_price || 1;
            const holding = p.holding_token;
            const holding_amount = p.holding_amount || 1;
            
            // Calculate baseline per token (if 1 BTC was invested at start)
            // baseline_token = BTC_value_at_start / price_at_start_of_token
            const btc_at_start = btc_price; // approximate - should store actual BTC price at init
            const baseline_per_token = {};
            Object.keys(prices).forEach(token => {
                const price = prices[token]?.bid || 1;
                baseline_per_token[token] = btc_at_start / price;
            });
            
            const sortedTokens = Object.keys(momentum).sort((a, b) => momentum[a] - momentum[b]);
            
            let html = '';
            sortedTokens.forEach(token => {
                const mom = momentum[token];
                const price = prices[token] ? prices[token].bid : 0;
                const isHolding = token === holding;
                const bl = baseline_per_token[token] || 0;
                
                html += `<tr class="${isHolding ? 'token-holding' : ''}">
                    <td>${token.replace('USDT', '')} ${isHolding ? '◄◄' : ''}</td>
                    <td class="${mom >= 0 ? 'momentum-positive' : 'momentum-negative'}">${(mom * 100).toFixed(3)}%</td>
                    <td>${bl.toFixed(2)}</td>
                    <td>$${price.toFixed(4)}</td>
                </tr>`;
            });
            document.getElementById('matrix-body').innerHTML = html;
            
            // Swaps
            const swaps = data.swaps;
            if (swaps.length > 0) {
                html = '';
                swaps.reverse().forEach(s => {
                    html += `<div class="swap-item">
                        <div class="swap-header">
                            <span class="swap-tokens">${s.from_token.replace('USDT','')} <span class="swap-arrow">→</span> ${s.to_token.replace('USDT','')}</span>
                            <span>${new Date(s.timestamp).toLocaleTimeString()}</span>
                        </div>
                        <div class="swap-details">
                            ${s.from_amount.toFixed(2)} @ $${s.from_price.toFixed(4)} → ${s.to_amount.toFixed(2)} @ $${s.to_price.toFixed(4)}
                        </div>
                    </div>`;
                });
                document.getElementById('swaps-list').innerHTML = html;
            }
        }
        
        async function control(action) {
            await fetch('/api/control', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({action})
            });
            setTimeout(fetchStatus, 500);
        }
        
        async function updateConfig() {
            const lookback = parseInt(document.getElementById('cfg-lookback').value);
            const threshold = parseFloat(document.getElementById('cfg-threshold').value) / 100;
            const interval = parseInt(document.getElementById('cfg-interval').value);
            
            await fetch('/api/config', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({lookback, threshold, interval})
            });
        }
        
        // Start polling - refresh every second
        fetchStatus();
        setInterval(fetchStatus, 1000);
        
        // Visual feedback on update
        setInterval(() => {
            const now = Date.now();
            const elapsed = Math.floor((now - lastUpdate) / 1000);
            if (elapsed > 3) {
                document.getElementById('last-update').textContent = 'Brak połączenia...';
                document.getElementById('last-update').style.color = '#e74c3c';
            }
        }, 2000);
    </script>
</body>
</html>
'''


if __name__ == '__main__':
    # Load existing state
    load_state()
    
    # Try to fetch initial prices
    try:
        test_prices = fetch_all_prices()
        if test_prices:
            with prices_lock:
                current_prices.update(test_prices)
            if not portfolio.baseline:
                init_baseline()
    except:
        pass
    
    print("""
╔═══════════════════════════════════════════════════════════════╗
║     CHAMPION ULTIMATE - DASHBOARD                     ║
║                                                         ║
║     Dashboard: http://localhost:12000                   ║
║                                                         ║
║     Controls:                                            ║
║       ▶ RUN     - Start trading                         ║
║       ⏹ STOP    - Stop trading                          ║
║       🔄 RESTART - Restart from scratch                  ║
║       🗑 RESET   - Clear portfolio                       ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    app.run(host='0.0.0.0', port=12000, debug=False, use_reloader=False)
