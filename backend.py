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

# === BACKTEST DATA LOGGER ===
class BacktestLogger:
    """Logger for all backtest events"""
    
    def __init__(self):
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.data_dir = "backtest_logs"
        os.makedirs(self.data_dir, exist_ok=True)
        
        self.ticks = []        # All price ticks
        self.swaps = []        # All swap events
        self.decisions = []    # Swap decisions (why swap happened)
        self.prices = {}       # Latest prices per symbol
        self.status_snapshots = []  # Periodic status snapshots
        
        # Start logging thread
        self.running = True
        self._lock = threading.Lock()
        self._tick_counter = 0
        self._snapshot_interval = 10  # Snapshot every N ticks
        
    def log_tick(self, symbol: str, price: float, timestamp: str):
        """Log a single price tick"""
        with self._lock:
            self.ticks.append({
                'tick_id': self._tick_counter,
                'symbol': symbol,
                'price': price,
                'timestamp': timestamp
            })
            self.prices[symbol] = price
            self._tick_counter += 1
            
            # Periodic snapshot
            if self._tick_counter % self._snapshot_interval == 0:
                self._take_snapshot()
    
    def log_swap(self, from_token: str, to_token: str, from_amount: float, 
                 to_amount: float, from_price: float, to_price: float,
                 confidence: float, holding_mom: float, target_mom: float,
                 timestamp: str,
                 # Detailed breakdown
                 from_value_usdt: float = None,
                 from_after_fee: float = None,
                 to_before_fee: float = None,
                 # Bid/Ask/Spread
                 bid_price: float = None,
                 ask_price: float = None,
                 from_spread_pct: float = None,
                 to_spread_pct: float = None):
        """Log a swap event with full calculation breakdown"""
        with self._lock:
            fv = from_value_usdt or (from_amount * from_price)
            faf = from_after_fee or (from_amount * from_price * 0.9996)
            tb = to_before_fee or (faf / to_price if to_price else 0)
            ta = to_amount
            
            # Calculate total fee in USDT terms
            fee_sell_usdt = fv - faf  # Fee from selling A
            fee_buy_usdt = tb * to_price - ta * to_price  # Fee from buying B (in USDT)
            total_fee_usdt = fee_sell_usdt + fee_buy_usdt
            
            self.swaps.append({
                'swap_id': len(self.swaps),
                'from_token': from_token,
                'to_token': to_token,
                # From token (A)
                'from_amount': from_amount,
                'from_price': from_price,  # BID price
                'from_bid_price': bid_price,
                'from_spread_pct': from_spread_pct or 0,
                'from_value_usdt': fv,
                # After selling A (1st fee 0.04%)
                'from_after_fee': faf,
                'fee_sell_usdt': fee_sell_usdt,
                # Buying B
                'to_price': to_price,  # ASK price
                'to_ask_price': ask_price,
                'to_spread_pct': to_spread_pct or 0,
                # Before buying B
                'to_before_fee': tb,
                # After buying B (2nd fee 0.04%)
                'to_amount': ta,
                'fee_buy_usdt': fee_buy_usdt,
                # Total spread (bid-ask impact)
                'total_spread_pct': (from_spread_pct or 0) + (to_spread_pct or 0),
                # Final values
                'usdt_value_before': fv,
                'usdt_value_after': ta * to_price,
                # Fees
                'fee_pct': 0.04,  # 0.04% per side, 0.08% total
                'fee_amount_usdt': total_fee_usdt,
                # Strategy
                'confidence': confidence,
                'holding_momentum': holding_mom,
                'target_momentum': target_mom,
                'momentum_diff': target_mom - holding_mom,
                'timestamp': timestamp
            })
    
    def log_decision(self, reason: str, details: dict, timestamp: str):
        """Log a swap decision (why swap did/didn't happen)"""
        with self._lock:
            self.decisions.append({
                'decision_id': len(self.decisions),
                'reason': reason,
                'details': details,
                'timestamp': timestamp
            })
    
    def _take_snapshot(self):
        """Take a status snapshot"""
        # Calculate portfolio value
        portfolio_value = 0.0
        holding_token = None
        try:
            holding_token = portfolio.holding_token
            holding_price = self.prices.get(holding_token, 0)
            portfolio_value = portfolio.holding_amount * holding_price
        except:
            pass
        
        self.status_snapshots.append({
            'snapshot_id': len(self.status_snapshots),
            'timestamp': datetime.now().isoformat(),
            'tick_count': self._tick_counter,
            'swap_count': len(self.swaps),
            'portfolio_value_usdt': portfolio_value,
            'holding_token': holding_token,
            'prices': dict(self.prices)
        })
    
    def export(self, filename: str = None) -> str:
        """Export all data to JSON file"""
        if filename is None:
            filename = f"backtest_{self.session_id}.json"
        
        filepath = os.path.join(self.data_dir, filename)
        
        with self._lock:
            data = {
                'session_id': self.session_id,
                'export_time': datetime.now().isoformat(),
                'config': {
                    'strategy': STRATEGY,
                    'tracked_symbols': TRACKED_SYMBOLS
                },
                'stats': {
                    'total_ticks': len(self.ticks),
                    'total_swaps': len(self.swaps),
                    'total_decisions': len(self.decisions),
                    'total_snapshots': len(self.status_snapshots),
                    'duration_seconds': 0  # Will be calculated
                },
                'ticks': self.ticks,
                'swaps': self.swaps,
                'decisions': self.decisions,
                'status_snapshots': self.status_snapshots,
                'final_prices': dict(self.prices)
            }
            
            # Calculate duration
            if self.ticks and self.status_snapshots:
                try:
                    first_tick = datetime.fromisoformat(self.ticks[0]['timestamp'])
                    last_snapshot = datetime.fromisoformat(self.status_snapshots[-1]['timestamp'])
                    data['stats']['duration_seconds'] = (last_snapshot - first_tick).total_seconds()
                except:
                    pass
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        return filepath
    
    def get_summary(self) -> dict:
        """Get quick summary of logged data"""
        with self._lock:
            return {
                'session_id': self.session_id,
                'total_ticks': len(self.ticks),
                'total_swaps': len(self.swaps),
                'total_decisions': len(self.decisions)
            }

# Global logger instance
backtest_logger = BacktestLogger()

# === KONFIGURACJA ===
STRATEGY = {
    'name': 'TOP_EQ_HUNTER',
    'lookback': 3,
    'threshold': 0.002,  # 0.2% gain required from top_eq
    'interval': 1,
    'max_spread': 0.5  # Max 0.5% spread (unika wysokiego slippage)
}

INITIAL_USDT = 1000.0  # Start z 1000 USDT

# Tokeny do śledzenia - TOP VOLUME z MEXC (high volume = low spread)
TRACKED_SYMBOLS = [
    # TOP VOLUME (liquid pairs)
    'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'BNBUSDT',
    'LTCUSDT', 'TRXUSDT', 'DOGEUSDT', 'ADAUSDT', 'ZECUSDT',
    'XMRUSDT', 'DOTUSDT', 'SUIUSDT', 'FILUSDT', 'TAOUSDT',
    'INJUSDT', 'APTUSDT', 'ARBUSDT', 'OPUSDT', 'NEARUSDT',
    'ATOMUSDT', 'LINKUSDT', 'AVAXUSDT', 'UNIUSDT', 'LDOUSDT',
    'MKRUSDT', 'AAVEUSDT', 'SNXUSDT', 'CRVUSDT', 'APEUSDT',
    # HIGH VOLUME ALTCOINS
    'BONKUSDT', 'WLDUSDT', 'SHIBUSDT', 'PEPEUSDT', 'WENUSDT',
    'JASMYUSDT', 'SEIUSDT', 'TIAUSDT', 'SANDUSDT', 'MANAUSDT',
    'GALAUSDT', 'IMXUSDT', 'ALGOUSDT', 'VETUSDT', 'HBARUSDT',
    'XTZUSDT', 'CAKEUSDT', 'RUNEUSDT', 'KAVAUSDT', 'ENSUSDT',
    'COMPUSDT', 'YFIUSDT', 'GMXUSDT', 'DYDXUSDT', 'MAGICUSDT',
    'GRTUSDT', 'FETUSDT', 'ZILUSDT', 'CHZUSDT', 'ENJUSDT',
    'BATUSDT', 'SLPUSDT', 'GODSUSDT', 'HIGHUSDT', 'SPELLUSDT',
    'RAYUSDT', 'MAPUSDT', 'SCRTUSDT', 'REQUSDT', 'UNCUSDT',
    'OOBUSDT', 'HNSUSDT', 'MRVLONUSDT', 'AGLDUSDT', 'BIT1USDT',
    'ZKUUSDT', 'RLSUSDT', 'ZEUSUSDT', 'NILUSDT', 'AUCUSDT',
    'PERMUSDT', 'EFCUSDT', 'OUSDT', 'VISTAUSDT', 'RICEUSDT',
    'STOPUSDT', 'PUNDIAIUSDT', 'BBUSDT', 'SIXUSDT', 'QBXUSDT',
    'CRMONUSDT', 'XEPUSDT', 'RPLUSDT', 'ALUUSDT', 'SFPUSDT',
    'QNTUSDT', 'CROUSDT', 'AXSUSDT', 'INJUSDT', 'ETHFIUSDT',
    'HYPEUSDT', 'LABUSDT', 'SUIUSDT', 'XECUSDT'
]

API_BASE = 'https://api.mexc.com'
UPDATE_INTERVAL = 1.0  # 1 second
STATE_FILE = 'portfolio_state.json'

# === SPREAD & VALUE CHECK ===
MIN_VALUE_IMPROVEMENT = 0.995  # Only swap if resulting value > baseline * 0.995 (allow 0.5% tolerance)
MAX_SPREAD_PCT = 10.0  # Max 10% spread (very permissive - calculations handle it)

def get_token_spread(symbol: str) -> float:
    """Pobiera spread procentowy dla tokena"""
    p = current_prices.get(symbol)
    if p and p.ask > 0:
        return (p.ask - p.bid) / p.ask * 100
    return 0.0

def calculate_swap_value(from_symbol: str, to_symbol: str, from_amount: float) -> float:
    """
    Oblicza ile USDT dostaniemy po swapie A->B używając prawdziwych bid/ask.
    Spread jest uwzględniony w obliczeniu.
    """
    bid = get_bid_price(from_symbol)
    ask = get_ask_price(to_symbol)
    mid = get_mid_price(to_symbol)
    
    if bid <= 0 or ask <= 0 or mid <= 0:
        return 0.0
    
    # Calculate: SELL A at BID -> USDT -> BUY B at ASK
    fee_factor = 0.9996  # 0.04% per side
    usdt_after_sell = from_amount * bid * fee_factor
    b_tokens = usdt_after_sell / ask * fee_factor
    
    # Return value in USDT (what B tokens are worth at current price)
    return b_tokens * mid

def get_equivalent_value(symbol: str) -> float:
    """
    Zwraca ile USDT warte byłyby baseline tokens tokena.
    Używa matrix data - actual_equivalent_qty vs baseline_amount.
    """
    # Znajdź token w matrix
    for entry in matrix_cache:
        if entry['symbol'] == symbol:
            # Jeśli token jest powyżej baseline, zwróć więcej USDT
            return entry['actual_equivalent_qty']
    return 0.0

# Flask + SocketIO
app = Flask(__name__)
app.config['SECRET_KEY'] = 'champion-ultimate-secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

running = False
update_thread = None
matrix_cache = []  # Cache for matrix data

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
    """Portfolio z baseline w cenach, nie w ilościach"""
    holding_token: str
    holding_amount: float  # Ilość posiadanego tokena
    total_swaps: int
    swap_history: List[Swap] = field(default_factory=list)
    start_time: str = ""
    start_value_usdt: float = 0.0
    price_history: Dict[str, List[float]] = field(default_factory=dict)
    # Baseline prices - ceny przy starcie (np. BTC=$64350, ETH=$3500)
    baseline_prices: Dict[str, float] = field(default_factory=dict)
    # Top EQ - najwyższy actual_equivalent_qty dla każdego tokena
    top_eq: Dict[str, float] = field(default_factory=dict)
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
    baseline_prices={}
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

def calculate_actual_swap_value(from_symbol: str, to_symbol: str) -> tuple:
    """
    Oblicza ile USDT faktycznie otrzymamy po swapie A->B.
    Używa REALNYCH cen bid/ask z uwzględnieniem fees.
    
    Returns: (usdt_after_swap, spread_cost_pct, fee_cost_pct)
    """
    # Pobierz ceny
    bid_from = get_bid_price(from_symbol)  # Cena sprzedaży A (niższa)
    ask_from = get_ask_price(from_symbol)  # Cena kupna A (wyższa)
    bid_to = get_bid_price(to_symbol)      # Cena sprzedaży B
    ask_to = get_ask_price(to_symbol)      # Cena kupna B (wyższa)
    
    if bid_from <= 0 or ask_to <= 0:
        return (0, 0, 0)
    
    # Obecna wartość portfela po mid price
    mid_from = get_mid_price(from_symbol)
    if mid_from <= 0:
        return (0, 0, 0)
    
    current_value = portfolio.holding_amount * mid_from
    
    # Fee 0.04% * 2 strony = 0.08%
    fee_factor = 0.9996
    fee_cost_pct = (1 - fee_factor ** 2) * 100  # ~0.08%
    
    # Spread cost: ile tracimy przez bid/ask spread
    # Sprzedajemy A po BID (poniżej mid)
    # Kupujemy B po ASK (powyżej mid)
    # Spread = (mid_from - bid_from)/mid_from + (ask_to - mid_to)/mid_to
    mid_to = get_mid_price(to_symbol)
    spread_from = (mid_from - bid_from) / mid_from * 100 if mid_from > 0 else 0
    spread_to = (ask_to - mid_to) / mid_to * 100 if mid_to > 0 else 0
    spread_cost_pct = spread_from + spread_to
    
    # Całkowity koszt = spread + fees
    total_cost_pct = spread_cost_pct + fee_cost_pct
    
    # Oblicz ile USDT dostaniemy po swapie:
    # 1. Sprzedaj A po BID z fee
    usdt_after_sell = portfolio.holding_amount * bid_from * fee_factor
    # 2. Kup B po ASK z fee
    b_tokens = usdt_after_sell / ask_to * fee_factor
    # 3. Wartość B po mid price (ile byśmy dostali gdybyśmy sprzedali od razu)
    usdt_after_swap = b_tokens * mid_to
    
    return (usdt_after_swap, spread_cost_pct, fee_cost_pct)


def should_swap() -> Optional[tuple]:
    """
    Strategia TOP_EQ_PROFITABLE:
    Szuka tokenu z najwyższym gain% od top_eq, ale tylko jeśli gain pokrywa spread+fees.
    """
    holding = portfolio.holding_token
    
    # Fee 0.04% * 2 strony = 0.08%
    fee_cost_pct = (1 - 0.9996 ** 2) * 100  # ~0.08%
    
    # Minimalny buffer na spread (dla top volume pairs spread jest ~0.01-0.1%)
    spread_buffer = 0.01  # dodatkowe 0.01% na spread
    min_gain_required = fee_cost_pct + spread_buffer  # ~0.09%
    
    # Znajdź token z najlepszym gain% od top_eq
    best_token = None
    best_gain_pct = 0.0
    
    for symbol in TRACKED_SYMBOLS:
        if symbol == holding:
            continue
        
        # Sprawdź spread - unikaj tokenów z wysokim slippage
        spread = get_token_spread(symbol)
        if spread > 0.5:  # max 0.5% spread
            continue
        
        # Pobierz actual_eq dla tego tokena
        actual_eq = get_equivalent_value(symbol)
        if actual_eq <= 0:
            continue
        
        # Pobierz top_eq dla tego tokena
        top_eq = portfolio.top_eq.get(symbol, 0)
        if top_eq <= 0:
            continue
        
        # Oblicz gain% od top_eq
        gain_pct = (actual_eq / top_eq - 1) * 100 if top_eq > 0 else 0
        
        # Swap tylko jeśli gain pokrywa spread + fees + buffer
        required_gain = min_gain_required + spread
        if gain_pct > required_gain and gain_pct > best_gain_pct:
            best_gain_pct = gain_pct
            best_token = symbol
    
    if best_token:
        top_eq = portfolio.top_eq.get(best_token, 0)
        actual_eq = get_equivalent_value(best_token)
        net_gain_pct = best_gain_pct - min_gain_required - get_token_spread(best_token)
        
        print(f"[SWAP] {holding.replace('USDT','')} -> {best_token.replace('USDT','')} | gain: +{best_gain_pct:.3f}% (need: >{min_gain_required:.3f}%) | net: +{net_gain_pct:.4f}%")
        backtest_logger.log_decision(
            reason='SWAP',
            details={
                'from_token': holding,
                'to_token': best_token,
                'gain_pct': best_gain_pct,
                'required_gain': min_gain_required
            },
            timestamp=datetime.now().isoformat()
        )
        return (best_token, net_gain_pct, 0, 0)
    
    return None

def update_top_eq_after_swap(new_token: str, new_amount: float):
    """
    Aktualizuj top_eq po swapie.
    Dla każdego tokena sprawdź czy actual_eq > top_eq i zaktualizuj.
    """
    # Token który otrzymaliśmy w swap - jego top_eq = to co dostaliśmy
    portfolio.top_eq[new_token] = new_amount
    
    # Dla wszystkich innych tokenów, sprawdź czy pobili rekord
    for symbol in TRACKED_SYMBOLS:
        if symbol == new_token:
            continue
        
        actual_eq = get_equivalent_value(symbol)
        current_top = portfolio.top_eq.get(symbol, 0)
        
        # Jeśli actual_eq > top_eq, zaktualizuj
        if actual_eq > current_top and current_top > 0:
            portfolio.top_eq[symbol] = actual_eq
            print(f"[TOP_EQ] {symbol}: {current_top:.4f} -> {actual_eq:.4f} (+{((actual_eq/current_top-1)*100):.2f}%)")

def get_momentum(token: str, lookback: int) -> float:
    """Zwraca momentum jako % zmiany ceny"""
    history = portfolio.price_history.get(token, [])
    if len(history) < lookback + 1:
        return 0.0
    
    current = history[-1]
    past = history[-lookback]
    
    if past <= 0:
        return 0.0
    
    return (current - past) / past

def get_relative_momentum(token_a: str, token_b: str, lookback: int) -> float:
    """Zwraca momentum tokena B względem A"""
    mom_a = get_momentum(token_a, lookback)
    mom_b = get_momentum(token_b, lookback)
    return mom_b - mom_a

def get_bid_price(symbol: str) -> float:
    """Pobiera cenę bid (sprzedaż)"""
    p = current_prices.get(symbol)
    return p.bid if p else 0

def get_ask_price(symbol: str) -> float:
    """Pobiera cenę ask (zakup)"""
    p = current_prices.get(symbol)
    return p.ask if p else 0

def execute_swap(target_token: str, confidence: float, holding_mom: float, target_mom: float) -> bool:
    """Wykonuje symulowany swap"""
    global current_prices
    
    # Używamy REALNYCH cen bid/ask!
    # SELLING token A → używamy BID (co dostajemy za sprzedaż)
    # BUYING token B → używamy ASK (co płacimy za zakup)
    bid_price = get_bid_price(portfolio.holding_token)  # Cena sprzedaży A
    ask_price = get_ask_price(target_token)  # Cena zakupu B
    
    if bid_price <= 0 or ask_price <= 0:
        return False
    
    # Fee 0.08% (0.04% * 2)
    fee_factor = 0.9996
    amount = portfolio.holding_amount
    
    # Detailed calculation breakdown z REALNYMI cenami
    from_value_usdt = amount * bid_price  # Wartość A przy BID (ile USDT dostajemy za sprzedaż)
    from_after_fee = from_value_usdt * fee_factor  # USDT po sprzedaży A (po 1. fee)
    to_before_fee = from_after_fee / ask_price  # Ilość B przed fee (po BID -> USDT -> ASK)
    to_after_fee = to_before_fee * fee_factor  # Ilość B po zakupie (po 2. fee)
    
    swap = Swap(
        timestamp=datetime.now().isoformat(),
        from_token=portfolio.holding_token,
        to_token=target_token,
        from_amount=amount,
        to_amount=to_after_fee,
        from_price=bid_price,  # Używamy BID
        to_price=ask_price,   # Używamy ASK
        fee_pct=0.08,
        holding_momentum=holding_mom,
        target_momentum=target_mom
    )
    
    portfolio.swap_history.append(swap)
    portfolio.holding_token = target_token
    portfolio.holding_amount = to_after_fee
    portfolio.total_swaps += 1
    
    # Aktualizuj top_eq po swapie
    update_top_eq_after_swap(target_token, to_after_fee)
    
    # Calculate spreads for logging
    from_spread = get_token_spread(portfolio.holding_token)
    to_spread = get_token_spread(target_token)
    
    # Log swap z bid/ask i spreadem
    print(f"[SWAP] {swap.from_token.replace('USDT','')} -> {swap.to_token.replace('USDT','')} | spread: {from_spread:.3f}%/{to_spread:.3f}% | {swap.from_amount:.4f} -> {swap.to_amount:.4f} | ${from_value_usdt:.2f} -> ${to_after_fee*ask_price:.2f}")
    backtest_logger.log_swap(
        from_token=swap.from_token,
        to_token=swap.to_token,
        from_amount=swap.from_amount,
        to_amount=swap.to_amount,
        from_price=swap.from_price,  # BID
        to_price=swap.to_price,      # ASK
        confidence=confidence,
        holding_mom=holding_mom,
        target_mom=target_mom,
        timestamp=swap.timestamp,
        # Detailed breakdown
        from_value_usdt=from_value_usdt,
        from_after_fee=from_after_fee,
        to_before_fee=to_before_fee,
        # Bid/Ask/Spread
        bid_price=bid_price,
        ask_price=ask_price,
        from_spread_pct=from_spread,
        to_spread_pct=to_spread
    )
    
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
    - net_swap_gain: ile % byśmy zyskali gdybyśmy swapowali holding -> token (z fees + spread)
    """
    matrix = []
    
    # Aktualna wartość portfela
    holding_price = get_mid_price(portfolio.holding_token)
    current_portfolio_value = portfolio.holding_amount * holding_price
    
    for symbol in TRACKED_SYMBOLS:
        # Baseline amount = $1000 / cena tokena
        baseline_price = portfolio.baseline_prices.get(symbol, 0)
        if baseline_price > 0:
            baseline_amount = INITIAL_USDT / baseline_price
        else:
            baseline_amount = 0
        
        current_price = get_mid_price(symbol)
        
        # Actual Equivalent Qty
        if current_price > 0:
            actual_equivalent_qty = current_portfolio_value / current_price
        else:
            actual_equivalent_qty = 0
        
        # Gain % od baseline
        if baseline_amount > 0:
            gain_pct = ((actual_equivalent_qty / baseline_amount) - 1) * 100
        else:
            gain_pct = 0
        
        # Momentum
        momentum = get_momentum(symbol, STRATEGY['lookback'])
        
        # Spread
        spread_pct = get_token_spread(symbol)
        
        # Net swap gain (z fees + spread)
        swap_value, spread_cost, fee_cost = calculate_actual_swap_value(portfolio.holding_token, symbol)
        if swap_value > 0 and current_portfolio_value > 0:
            net_swap_gain_pct = ((swap_value / current_portfolio_value) - 1) * 100
        else:
            net_swap_gain_pct = 0
        
        matrix.append({
            'token': symbol.replace('USDT', ''),
            'symbol': symbol,
            'baseline_amount': baseline_amount,
            'actual_equivalent_qty': actual_equivalent_qty,
            'gain_pct': gain_pct,
            'momentum': momentum,
            'current_price': current_price,
            'spread_pct': spread_pct,
            'net_swap_gain_pct': net_swap_gain_pct,  # KLUCZOWE - zysk po swapie z wszystkimi kosztami
            'swap_cost_pct': spread_cost + fee_cost,
            'is_holding': symbol == portfolio.holding_token,
            'has_data': len(portfolio.price_history.get(symbol, [])) >= STRATEGY['lookback'] + 1
        })
    
    # Sortuj po net_swap_gain_pct descending
    matrix.sort(key=lambda x: x['net_swap_gain_pct'], reverse=True)
    
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
    
    # Zapisz ceny bazowe dla każdego tokena
    baseline_prices = {}
    for symbol in TRACKED_SYMBOLS:
        price = get_mid_price(symbol)
        if price > 0:
            baseline_prices[symbol] = price
    
    # Oblicz top_eq (początkowo = baseline_amount dla każdego tokena)
    # top_eq = ile tokenów byśmy mieli gdyby cena się nie zmieniła
    top_eq = {}
    for symbol in TRACKED_SYMBOLS:
        price = get_mid_price(symbol)
        if price > 0:
            # baseline_amount = ile tokenów = 1000 USDT / cena
            top_eq[symbol] = INITIAL_USDT / price
        else:
            top_eq[symbol] = 0
    
    # Zainicjuj portfolio z pierwszym tokenem (BTC)
    portfolio = Portfolio(
        holding_token='BTCUSDT',
        holding_amount=INITIAL_USDT / get_mid_price('BTCUSDT') if get_mid_price('BTCUSDT') > 0 else 0,
        total_swaps=0,
        swap_history=[],
        start_time=datetime.now().isoformat(),
        start_value_usdt=INITIAL_USDT,
        price_history={symbol: [] for symbol in TRACKED_SYMBOLS},
        baseline_prices=baseline_prices,
        top_eq=top_eq,
        last_update=datetime.now().isoformat()
    )
    
    # Uzupełnij historię cen
    for symbol, price in current_prices.items():
        portfolio.price_history[symbol].append(price.price)
    
    print(f"[INIT] Portfolio zainicjalizowane: {INITIAL_USDT} USDT")
    print(f"[INIT] Baseline prices: {len(baseline_prices)} tokenów")
    print(f"[INIT] Top EQ initialized: all tokens = {INITIAL_USDT} USDT")
    print(f"[INIT] BTC price: ${get_mid_price('BTCUSDT'):.2f}")
    print(f"[INIT] BTC amount: {portfolio.holding_amount:.8f}")
    
    return True

def update_loop():
    """Główna pętla aktualizacji"""
    global running, current_prices
    
    print("[UPDATE] Starting update loop...")
    last_swap_time = 0
    tick_count = 0
    
    while running:
        try:
            # Pobierz ceny
            new_prices = fetch_all_prices()
            if new_prices:
                current_prices = new_prices
            
            # Aktualizuj historię cen
            prices_updated = 0
            for symbol, price in current_prices.items():
                if symbol not in portfolio.price_history:
                    portfolio.price_history[symbol] = []
                portfolio.price_history[symbol].append(price.price)
                prices_updated += 1
                # Keep only last 100 prices
                if len(portfolio.price_history[symbol]) > 100:
                    portfolio.price_history[symbol] = portfolio.price_history[symbol][-100:]
                
                # Log tick to backtest logger
                backtest_logger.log_tick(symbol, price.price, datetime.now().isoformat())
            
            tick_count += 1
            if tick_count % 10 == 0:
                print(f"[TICK {tick_count}] Updated {prices_updated} prices, BTC history: {len(portfolio.price_history.get('BTCUSDT', []))}")
            
            # Update matrix cache
            global matrix_cache
            matrix_cache = get_matrix()
            
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
            'baseline_prices': portfolio.baseline_prices,
            'top_eq': portfolio.top_eq
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
    UWAGA: baseline_prices są ładowane z pliku i używane do obliczenia baseline_amount.
    """
    global portfolio, current_prices
    
    if not os.path.exists(STATE_FILE):
        return False
    
    try:
        with open(STATE_FILE, 'r') as f:
            data = json.load(f)
        
        p_data = data.get('portfolio', {})
        
        # Pobierz aktualne ceny
        current_prices = fetch_all_prices()
        
        # Ładuj baseline_prices z pliku
        baseline_prices = p_data.get('baseline_prices', {})
        
        # Ładuj top_eq z pliku
        top_eq = p_data.get('top_eq', {})
        
        portfolio = Portfolio(
            holding_token=p_data.get('holding_token', 'BTCUSDT'),
            holding_amount=p_data.get('holding_amount', 0),
            total_swaps=p_data.get('total_swaps', 0),
            swap_history=[],
            start_time=p_data.get('start_time', ''),
            start_value_usdt=p_data.get('start_value_usdt', INITIAL_USDT),
            price_history=data.get('price_history', {}),
            baseline_prices=baseline_prices,
            top_eq=top_eq,
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
    global running, update_thread, backtest_logger
    
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
        # Export current data before reset
        if backtest_logger.get_summary()['total_ticks'] > 0:
            filepath = backtest_logger.export()
            print(f"[EXPORT] Auto-exported: {os.path.basename(filepath)}")
        # Reset logger - create new instance
        backtest_logger = BacktestLogger()
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

@app.route('/api/export')
def api_export():
    """Eksportuje cały backtest do JSON"""
    try:
        filepath = backtest_logger.export()
        filename = os.path.basename(filepath)
        return send_from_directory(
            backtest_logger.data_dir,
            filename,
            as_attachment=True,
            download_name=f"backtest_{backtest_logger.session_id}.json"
        )
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/export/summary')
def api_export_summary():
    """Zwraca podsumowanie zalogowanych danych"""
    return jsonify(backtest_logger.get_summary())

@app.route('/api/export/list')
def api_export_list():
    """Lista wszystkich plików eksportu"""
    try:
        files = []
        for f in os.listdir(backtest_logger.data_dir):
            if f.endswith('.json'):
                filepath = os.path.join(backtest_logger.data_dir, f)
                files.append({
                    'filename': f,
                    'size': os.path.getsize(filepath),
                    'modified': datetime.fromtimestamp(os.path.getmtime(filepath)).isoformat()
                })
        return jsonify({'files': sorted(files, key=lambda x: x['modified'], reverse=True)})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

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
