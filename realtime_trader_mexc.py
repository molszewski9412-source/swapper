#!/usr/bin/env python3
"""
CHAMPION ULTIMATE - REAL-TIME TRADER z MEXC API

Pełna integracja:
- Pobieranie cen BID/ASK z MEXC
- Papierowe portfolio z symulacją swapów
- Testowanie strategii CHAMPION_ULTIMATE na live danych

Strategia: Relative Strength
- Lookback: 5
- Threshold: 3%
- Interval: 10
"""

import json
import os
import time
import requests
import threading
from datetime import datetime
from flask import Flask, jsonify, request
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# === KONFIGURACJA ===
STRATEGY = {
    'name': 'CHAMPION_ULTIMATE',
    'lookback': 5,
    'threshold': 0.03,
    'interval': 10
}

# Tokeny do śledzenia (100 par)
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

STATE_FILE = 'realtime_state.json'
API_BASE = 'https://api.mexc.com'
UPDATE_INTERVAL = 2

app = Flask(__name__)


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
    baseline: Dict[str, float] = field(default_factory=dict)  # baseline ilości tokenów (zapisane przy starcie)


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
    
    # Baseline NIE jest aktualizowane przy swapie - pozostaje stałe!
    
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
    
    print(f"[SWAP] {swap.from_token} -> {swap.to_token}")
    print(f"       {amount:.6f} @ ${bid_price:,.2f} -> {new_amount:.6f} @ ${ask_price:,.2f}")
    print(f"       Baseline: {portfolio.baseline.get(target_token, 0):.2f} | Gain: {get_gain_pct(target_token):+.2f}%")
    
    return True


def get_gain_pct(token: str) -> float:
    """Oblicza gain % od baseline."""
    baseline = portfolio.baseline.get(token, 0)
    actual = portfolio.holding_amount if token == portfolio.holding_token else 0
    
    if baseline <= 0:
        return 0.0
    
    return ((actual - baseline) / baseline) * 100


def init_baseline():
    """Inicjalizuje baseline przy starcie - zapisuje ile tokenów mielibyśmy gdybyśmy od razu wymienili 1 BTC."""
    global current_prices
    
    btc_price = current_prices.get('BTCUSDT')
    if not btc_price or btc_price.bid <= 0:
        return
    
    btc_value = 1.0 * btc_price.bid  # 1 BTC w USDT
    
    for symbol in TRACKED_SYMBOLS:
        price = current_prices.get(symbol)
        if price and price.ask > 0:
            # Baseline = ile tokenów gdybyśmy wymienili 1 BTC na ten token na początku
            portfolio.baseline[symbol] = btc_value / price.ask
    
    print(f"[BASELINE] Zapisano baseline dla {len(portfolio.baseline)} tokenów")
    print(f"[BASELINE] BTC start: ${btc_value:,.2f}")


def update_loop():
    global current_prices, running
    last_swap_time = 0
    
    while running:
        try:
            with prices_lock:
                current_prices = fetch_all_prices()
            
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
        'baseline': portfolio.baseline  # Zapisz baseline!
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
                    portfolio.baseline = data.get('baseline', {})  # Wczytaj baseline!
                    if 'strategy' in data:
                        STRATEGY.update(data['strategy'])
                    print(f"[STATE] Wczytano: {portfolio.holding_token}, swaps: {portfolio.total_swaps}")
                    print(f"[STATE] Baseline: {len(portfolio.baseline)} tokenów")
                    return True
        except Exception as e:
            print(f"[STATE] Błąd: {e}")
    print("[STATE] Nowy portfel - baseline zostanie zainicjowane")
    return False


@app.route('/api/status', methods=['GET'])
def get_status():
    with prices_lock:
        prices = {s: {'bid': p.bid, 'ask': p.ask, 'spread': p.spread}
                  for s, p in current_prices.items()}
    
    holding_price = current_prices.get(portfolio.holding_token)
    value_usdt = portfolio.holding_amount * holding_price.bid if holding_price else 0
    
    momentum_data = {}
    for symbol in TRACKED_SYMBOLS:
        if symbol in portfolio.price_history:
            momentum_data[symbol] = get_momentum(symbol, STRATEGY['lookback'])
    
    # Oblicz gain %
    baseline_amount = portfolio.baseline.get(portfolio.holding_token, 0)
    gain_pct = get_gain_pct(portfolio.holding_token)
    
    return jsonify({
        'portfolio': {
            'holding_token': portfolio.holding_token,
            'holding_amount': portfolio.holding_amount,
            'holding_value_usdt': value_usdt,
            'baseline_amount': baseline_amount,
            'gain_pct': gain_pct,
            'total_swaps': portfolio.total_swaps,
            'start_time': portfolio.start_time,
            'strategy': STRATEGY
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
        ]
    })


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


@app.route('/api/reset', methods=['POST'])
def reset():
    global portfolio
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
    return jsonify({'status': 'reset'})


@app.route('/api/swaps', methods=['GET'])
def get_swaps():
    limit = int(request.args.get('limit', 50))
    return jsonify({
        'swaps': [
            {
                'timestamp': s.timestamp,
                'from_token': s.from_token,
                'to_token': s.to_token,
                'from_amount': s.from_amount,
                'to_amount': s.to_amount,
                'from_price': s.from_price,
                'to_price': s.to_price
            }
            for s in portfolio.swap_history[-limit:]
        ],
        'total': portfolio.total_swaps
    })


if __name__ == '__main__':
    print("""
╔═══════════════════════════════════════════════════════════════╗
║     CHAMPION ULTIMATE - MEXC REALTIME TRADER        ║
║                                                         ║
║     API: /api/status                                    ║
║     Pobiera BID/ASK z MEXC                             ║
║     Paper trading - prawdziwe spready                  ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    load_state()
    
    print("\n[MEXC] Pobieranie BID/ASK...")
    test_prices = fetch_all_prices()
    
    if test_prices:
        print(f"[MEXC] Pobrano {len(test_prices)} cen")
        print("\nPrzykładowe BID/ASK:")
        for symbol in ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']:
            if symbol in test_prices:
                p = test_prices[symbol]
                print(f"  {symbol}: BID=${p.bid:,.2f} ASK=${p.ask:,.2f} SPREAD={p.spread*100:.3f}%")
        
        # Inicjalizuj baseline jeśli nie istnieje
        if not portfolio.baseline:
            with prices_lock:
                current_prices.update(test_prices)
            init_baseline()
    else:
        print("[MEXC] UWAGA: Nie udało się pobrać cen!")
    
    update_thread = threading.Thread(target=update_loop, daemon=True)
    update_thread.start()
    
    print(f"\n[SERVER] http://localhost:12000")
    print(f"[API] curl http://localhost:12000/api/status\n")
    
    app.run(host='0.0.0.0', port=12000, debug=False, use_reloader=False)
