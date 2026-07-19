#!/usr/bin/env python3
"""
CHAMPION ULTIMATE - REALTIME BACKTESTER
Modern architecture with WebSocket support
"""

import json
import os
import time
import requests
import threading
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from flask import Flask, jsonify, request, send_from_directory
from flask_socketio import SocketIO, emit

# === KONFIGURACJA ===
STRATEGY = {
    'name': 'CHAMPION_ULTIMATE',
    'lookback': 5,
    'threshold': 0.03,  # 3% - oryginalne ustawienie z champion_ultimate
    'interval': 10
}

INITIAL_USDT = 1000.0  # Start z 1000 USDT

# Tokeny do śledzenia (pogrupowane)
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

API_BASE = 'https://api.mexc.com'
UPDATE_INTERVAL = 1.0  # 1 second
STATE_FILE = 'portfolio_state.json'

# Flask + SocketIO
app = Flask(__name__)
app.config['SECRET_KEY'] = 'champion-ultimate-secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

running = False
update_thread = None

@dataclass
class Price:
    symbol: str
    bid: float
    ask: float
    price: float  # mid price
    timestamp: str
    
    @property
    def spread_pct(self) -> float:
        return (self.ask - self.bid) / self.ask * 100 if self.ask > 0 else 0

@dataclass
class Swap:
    timestamp: str
    from_token: str
    to_token: str
    from_amount: float
    to_amount: float
    from_price: float
    to_price: float
    fee_pct: float
    holding_momentum: float
    target_momentum: float

@dataclass
class Portfolio:
    """Portfolio z baseline w ilości tokenów, nie w USDT"""
    holding_token: str
    holding_amount: float  # Ilość posiadanego tokena
    total_swaps: int
    swap_history: List[Swap] = field(default_factory=list)
    start_time: str = ""
    start_value_usdt: float = 0.0
    price_history: Dict[str, List[float]] = field(default_factory=dict)
    # Baseline - stałe ilości tokenów (np. 0.01 BTC, 100 XRP)
    baseline_amounts: Dict[str, float] = field(default_factory=dict)
    # Timestamp ostatniej aktualizacji
    last_update: str = ""

# Global state
current_prices: Dict[str, Price] = {}
portfolio = Portfolio(
    holding_token='BTCUSDT',
    holding_amount=0.0,
    total_swaps=0,
    swap_history=[],
    start_time="",
    start_value_usdt=0.0,
    price_history={},
    baseline_amounts={}
)

def get_mid_price(symbol: str) -> float:
    """Pobiera średnią cenę (bid+ask)/2 z current_prices"""
    p = current_prices.get(symbol)
    if p:
        return (p.bid + p.ask) / 2
    return 0.0

def fetch_all_prices() -> Dict[str, Price]:
    """Pobiera ceny bid/ask używając bookTicker endpoint"""
    prices = {}
    try:
        # Batch request dla wszystkich cen
        resp = requests.get(
            f'{API_BASE}/api/v3/ticker/bookTicker',
            timeout=5
        )
        if resp.status_code == 200:
            data = resp.json()
            for item in data:
                symbol = item.get('symbol', '')
                if symbol in TRACKED_SYMBOLS:
                    bid = float(item.get('bidPrice', 0))
                    ask = float(item.get('askPrice', 0))
                    if bid > 0 and ask > 0:
                        mid = (bid + ask) / 2
                        prices[symbol] = Price(
                            symbol=symbol,
                            bid=bid,
                            ask=ask,
                            price=mid,
                            timestamp=datetime.now().isoformat()
                        )
    except Exception as e:
        print(f"[ERROR] fetch_all_prices: {e}")
    return prices

def get_momentum(symbol: str, period: int = 5) -> float:
    """Oblicza momentum: (current - past) / past"""
    history = portfolio.price_history.get(symbol, [])
    if len(history) < period + 1:
        return 0.0
    
    past = history[-period - 1]
    current = history[-1]
    
    if past <= 0:
        return 0.0
    
    return (current - past) / past

def should_swap() -> Optional[tuple]:
    """
    Strategia CHAMPION_ULTIMATE:
    Znajduje token z najniższym momentum (największy spadek).
    Jeśli różnica > threshold, zwraca ten token.
    """
    lb = STRATEGY['lookback']
    th = STRATEGY['threshold']
    holding = portfolio.holding_token
    holding_mom = get_momentum(holding, lb)
    
    # Znajdź token z najniższym momentum (najgorszy)
    worst_token = None
    worst_mom = 0.0  # Start od 0, szukaj tokenów poniżej
    
    for symbol in TRACKED_SYMBOLS:
        if symbol == holding:
            continue
        if len(portfolio.price_history.get(symbol, [])) < lb + 1:
            continue
        
        token_mom = get_momentum(symbol, lb)
        if token_mom < worst_mom:
            worst_mom = token_mom
            worst_token = symbol
    
    if worst_token and (holding_mom - worst_mom) > th:
        return (worst_token, holding_mom - worst_mom, holding_mom, worst_mom)
    
    return None

def execute_swap(target_token: str, confidence: float, holding_mom: float, target_mom: float) -> bool:
    """Wykonuje symulowany swap"""
    global current_prices
    
    holding_price = get_mid_price(portfolio.holding_token)
    target_price = get_mid_price(target_token)
    
    if holding_price <= 0 or target_price <= 0:
        return False
    
    # Fee 0.08% (0.04% * 2)
    fee_factor = 0.9996
    amount = portfolio.holding_amount
    usdt = amount * holding_price * fee_factor
    new_amount = usdt / target_price * fee_factor
    
    swap = Swap(
        timestamp=datetime.now().isoformat(),
        from_token=portfolio.holding_token,
        to_token=target_token,
        from_amount=amount,
        to_amount=new_amount,
        from_price=holding_price,
        to_price=target_price,
        fee_pct=0.08,
        holding_momentum=holding_mom,
        target_momentum=target_mom
    )
    
    portfolio.swap_history.append(swap)
    portfolio.holding_token = target_token
    portfolio.holding_amount = new_amount
    portfolio.total_swaps += 1
    
    # Emit swap event via WebSocket
    socketio.emit('swap_executed', {
        'swap': {
            'timestamp': swap.timestamp,
            'from_token': swap.from_token,
            'to_token': swap.to_token,
            'from_amount': swap.from_amount,
            'to_amount': swap.to_amount,
            'fee_pct': swap.fee_pct
        },
        'holding_token': portfolio.holding_token,
        'holding_amount': portfolio.holding_amount
    })
    
    return True

def get_matrix() -> List[Dict]:
    """
    Zwraca macierz wszystkich tokenów z:
    - token: nazwa
    - baseline_amount: stała ilość tokena (zapisana przy starcie)
    - actual_equivalent_qty: ile tokenów reprezentujących obecną wartość portfela
    - baseline_usdt: ile USDT zainwestowane na początku
    - actual_usdt: obecna wartość baseline w USDT
    - gain_pct: procent gain vs baseline_usdt
    """
    matrix = []
    usdt_per_token = INITIAL_USDT / len(TRACKED_SYMBOLS)
    
    # Aktualna wartość portfela (aby obliczyć actual_equivalent_qty)
    holding_price = get_mid_price(portfolio.holding_token)
    current_portfolio_value = portfolio.holding_amount * holding_price
    
    for symbol in TRACKED_SYMBOLS:
        baseline_amount = portfolio.baseline_amounts.get(symbol, 0)
        current_price = get_mid_price(symbol)
        
        # Baseline USDT - ile USDT byśmy mieli gdybyśmy trzymali cały początkowy portfel w tym tokenie
        baseline_usdt = usdt_per_token  # Każdy token dostaje równo USDT_per_token
        
        # Aktualny ekwiwalent w USDT = baseline_amount * current_price
        if baseline_amount > 0 and current_price > 0:
            actual_usdt = baseline_amount * current_price
        else:
            actual_usdt = baseline_usdt
        
        # Actual Equivalent Qty = obecna wartość portfela / cena tokena
        # (ile tokenów obecnie "mamy" w ekwivalencie)
        if current_price > 0:
            actual_equivalent_qty = current_portfolio_value / current_price
        else:
            actual_equivalent_qty = 0
        
        # Gain % = ile % zarobiliśmy na tym tokenie vs początkowy portfel
        if baseline_usdt > 0:
            gain_pct = ((actual_usdt / baseline_usdt) - 1) * 100
        else:
            gain_pct = 0
        
        # Momentum
        momentum = get_momentum(symbol, STRATEGY['lookback'])
        
        matrix.append({
            'token': symbol.replace('USDT', ''),
            'symbol': symbol,
            'baseline_amount': baseline_amount,
            'actual_equivalent_qty': actual_equivalent_qty,
            'baseline_usdt': baseline_usdt,
            'actual_usdt': actual_usdt,
            'gain_pct': gain_pct,
            'momentum': momentum,
            'current_price': current_price,
            'is_holding': symbol == portfolio.holding_token,
            'has_data': len(portfolio.price_history.get(symbol, [])) >= STRATEGY['lookback'] + 1
        })
    
    # Sortuj po gain_pct descending
    matrix.sort(key=lambda x: x['gain_pct'], reverse=True)
    
    return matrix

def get_status() -> Dict[str, Any]:
    """Zwraca pełny status systemu"""
    holding_price = get_mid_price(portfolio.holding_token)
    current_value = portfolio.holding_amount * holding_price
    
    return {
        'running': running,
        'strategy': STRATEGY,
        'portfolio': {
            'holding_token': portfolio.holding_token,
            'holding_amount': portfolio.holding_amount,
            'holding_value_usdt': current_value,
            'start_value_usdt': portfolio.start_value_usdt,
            'total_gain_pct': ((current_value / portfolio.start_value_usdt) - 1) * 100 if portfolio.start_value_usdt > 0 else 0,
            'total_swaps': portfolio.total_swaps,
            'start_time': portfolio.start_time,
            'last_update': portfolio.last_update,
            'tokens_tracked': len(TRACKED_SYMBOLS)
        },
        'matrix': get_matrix(),
        'swaps': [
            {
                'timestamp': s.timestamp,
                'from_token': s.from_token.replace('USDT', ''),
                'to_token': s.to_token.replace('USDT', ''),
                'from_amount': s.from_amount,
                'to_amount': s.to_amount,
                'fee_pct': s.fee_pct,
                'holding_momentum': s.holding_momentum,
                'target_momentum': s.target_momentum
            }
            for s in portfolio.swap_history[-20:]  # Ostatnie 20 swapów
        ]
    }

def init_portfolio():
    """Inicjalizuje portfolio z 1000 USDT"""
    global portfolio, current_prices
    
    # Pobierz ceny
    current_prices = fetch_all_prices()
    
    if not current_prices:
        print("[ERROR] Nie udało się pobrać cen")
        return False
    
    # Oblicz ile USDT na token
    usdt_per_token = INITIAL_USDT / len(TRACKED_SYMBOLS)
    
    # Oblicz ilości tokenów dla baseline
    baseline_amounts = {}
    for symbol in TRACKED_SYMBOLS:
        price = get_mid_price(symbol)
        if price > 0:
            baseline_amounts[symbol] = usdt_per_token / price
    
    # Zainicjuj portfolio z pierwszym tokenem (BTC)
    portfolio = Portfolio(
        holding_token='BTCUSDT',
        holding_amount=INITIAL_USDT / get_mid_price('BTCUSDT') if get_mid_price('BTCUSDT') > 0 else 0,
        total_swaps=0,
        swap_history=[],
        start_time=datetime.now().isoformat(),
        start_value_usdt=INITIAL_USDT,
        price_history={symbol: [] for symbol in TRACKED_SYMBOLS},
        baseline_amounts=baseline_amounts,
        last_update=datetime.now().isoformat()
    )
    
    # Uzupełnij historię cen
    for symbol, price in current_prices.items():
        portfolio.price_history[symbol].append(price.price)
    
    print(f"[INIT] Portfolio zainicjalizowane: {INITIAL_USDT} USDT")
    print(f"[INIT] Baseline: {len(baseline_amounts)} tokenów")
    print(f"[INIT] BTC amount: {portfolio.holding_amount:.8f}")
    
    return True

def update_loop():
    """Główna pętla aktualizacji"""
    global running, current_prices
    
    last_swap_time = 0
    
    while running:
        try:
            # Pobierz ceny
            new_prices = fetch_all_prices()
            if new_prices:
                current_prices = new_prices
            
            # Aktualizuj historię cen
            for symbol, price in current_prices.items():
                if symbol not in portfolio.price_history:
                    portfolio.price_history[symbol] = []
                portfolio.price_history[symbol].append(price.price)
                # Keep only last 100 prices
                if len(portfolio.price_history[symbol]) > 100:
                    portfolio.price_history[symbol] = portfolio.price_history[symbol][-100:]
            
            portfolio.last_update = datetime.now().isoformat()
            
            # Emituj update via WebSocket
            socketio.emit('status_update', get_status())
            
            # Sprawdź czy wykonać swap
            current_time = time.time()
            if current_time - last_swap_time >= STRATEGY['interval']:
                result = should_swap()
                if result:
                    target_token, confidence, holding_mom, target_mom = result
                    if execute_swap(target_token, confidence, holding_mom, target_mom):
                        last_swap_time = current_time
                        save_state()
            
        except Exception as e:
            print(f"[ERROR] update_loop: {e}")
        
        time.sleep(UPDATE_INTERVAL)

def save_state():
    """Zapisuje stan do pliku"""
    data = {
        'portfolio': {
            'holding_token': portfolio.holding_token,
            'holding_amount': portfolio.holding_amount,
            'total_swaps': portfolio.total_swaps,
            'start_time': portfolio.start_time,
            'start_value_usdt': portfolio.start_value_usdt,
            'baseline_amounts': portfolio.baseline_amounts
        },
        'swap_history': [
            {
                'timestamp': s.timestamp,
                'from_token': s.from_token,
                'to_token': s.to_token,
                'from_amount': s.from_amount,
                'to_amount': s.to_amount,
                'from_price': s.from_price,
                'to_price': s.to_price,
                'fee_pct': s.fee_pct,
                'holding_momentum': s.holding_momentum,
                'target_momentum': s.target_momentum
            }
            for s in portfolio.swap_history
        ],
        'price_history': portfolio.price_history
    }
    
    with open(STATE_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def load_state():
    """
    Ładuje stan z pliku.
    UWAGA: baseline_amounts są ZAWSZE przeliczane od nowa na podstawie aktualnych cen!
    To gwarantuje że baseline jest stały i prawidłowy.
    """
    global portfolio, current_prices
    
    if not os.path.exists(STATE_FILE):
        return False
    
    try:
        with open(STATE_FILE, 'r') as f:
            data = json.load(f)
        
        p_data = data.get('portfolio', {})
        
        # Pobierz aktualne ceny dla przeliczenia baseline
        current_prices = fetch_all_prices()
        
        # Oblicz baseline_amounts na nowo (zawsze takie same dla danych cen)
        usdt_per_token = INITIAL_USDT / len(TRACKED_SYMBOLS)
        baseline_amounts = {}
        for symbol in TRACKED_SYMBOLS:
            price = get_mid_price(symbol)
            if price > 0:
                baseline_amounts[symbol] = usdt_per_token / price
        
        portfolio = Portfolio(
            holding_token=p_data.get('holding_token', 'BTCUSDT'),
            holding_amount=p_data.get('holding_amount', 0),
            total_swaps=p_data.get('total_swaps', 0),
            swap_history=[],
            start_time=p_data.get('start_time', ''),
            start_value_usdt=p_data.get('start_value_usdt', INITIAL_USDT),
            price_history=data.get('price_history', {}),
            baseline_amounts=baseline_amounts,
            last_update=datetime.now().isoformat()
        )
        
        # Reconstruct swaps
        for s in data.get('swap_history', []):
            portfolio.swap_history.append(Swap(
                timestamp=s['timestamp'],
                from_token=s['from_token'],
                to_token=s['to_token'],
                from_amount=s['from_amount'],
                to_amount=s['to_amount'],
                from_price=s['from_price'],
                to_price=s['to_price'],
                fee_pct=s.get('fee_pct', 0.08),
                holding_momentum=s.get('holding_momentum', 0),
                target_momentum=s.get('target_momentum', 0)
            ))
        
        print(f"[LOAD] Stan załadowany: {portfolio.total_swaps} swapów")
        return True
        
    except Exception as e:
        print(f"[ERROR] load_state: {e}")
        return False

# === REST API ===

@app.route('/api/status')
def api_status():
    """Zwraca pełny status"""
    return jsonify(get_status())

@app.route('/api/control', methods=['POST'])
def api_control():
    """Kontrola: start, stop, reset"""
    global running, update_thread
    
    data = request.get_json()
    action = data.get('action', '')
    
    if action == 'start':
        if running:
            return jsonify({'status': 'already_running'})
        
        # Inicjalizuj portfolio
        if not init_portfolio():
            return jsonify({'status': 'error', 'message': 'Nie udało się zainicjalizować portfolio'})
        
        running = True
        update_thread = threading.Thread(target=update_loop, daemon=True)
        update_thread.start()
        
        return jsonify({'status': 'ok', 'action': 'start'})
    
    elif action == 'stop':
        running = False
        save_state()
        return jsonify({'status': 'ok', 'action': 'stop'})
    
    elif action == 'reset':
        running = False
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
        return jsonify({'status': 'ok', 'action': 'reset'})
    
    elif action == 'restart':
        running = False
        time.sleep(1)
        if not init_portfolio():
            return jsonify({'status': 'error', 'message': 'Nie udało się zainicjalizować portfolio'})
        running = True
        update_thread = threading.Thread(target=update_loop, daemon=True)
        update_thread.start()
        return jsonify({'status': 'ok', 'action': 'restart'})
    
    return jsonify({'status': 'unknown_action'})

# === WebSocket Events ===

@socketio.on('connect')
def handle_connect():
    print(f"[WS] Klient połączony: {request.sid}")
    emit('status_update', get_status())

@socketio.on('disconnect')
def handle_disconnect():
    print(f"[WS] Klient odłączony: {request.sid}")

@socketio.on('request_status')
def handle_request_status():
    emit('status_update', get_status())

# === STATIC FILES (Frontend) ===
import os

FRONTEND_DIST = os.path.join(os.path.dirname(__file__), 'frontend', 'dist')

@app.route('/')
def serve_frontend():
    # Fallback: jeśli frontend nie zbudowany, zwróć JSON
    if not os.path.exists(os.path.join(FRONTEND_DIST, 'index.html')):
        return jsonify({
            'message': 'Frontend not built. Run: cd frontend && npm install && npm run build',
            'api_docs': '/api/status - full status',
            'api_control': '/api/control - POST with {"action": "start|stop|reset"}'
        })
    return send_from_directory(FRONTEND_DIST, 'index.html')

@app.route('/assets/<path:filename>')
def serve_assets(filename):
    return send_from_directory(os.path.join(FRONTEND_DIST, 'assets'), filename)

# === MAIN ===

def main():
    print("""
╔═══════════════════════════════════════════════════════════════╗
║     CHAMPION ULTIMATE - REALTIME BACKTESTER                 ║
║     Strategy: CHAMPION_ULTIMATE | 93 tokens                 ║
║     Start: 1000 USDT | WebSocket ready                      ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    # Spróbuj załadować stan
    load_state()
    
    print(f"[CONFIG] Strategy: L{STRATEGY['lookback']} T{STRATEGY['threshold']*100:.0f}% I{STRATEGY['interval']}s")
    print(f"[CONFIG] Update interval: {UPDATE_INTERVAL}s")
    print()
    
    # Start serwera
    socketio.run(app, host='0.0.0.0', port=12000, debug=False, allow_unsafe_werkzeug=True)

if __name__ == '__main__':
    main()
