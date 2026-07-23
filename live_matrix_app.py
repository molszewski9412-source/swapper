"""
Live Matrix v4 - Token Monitor with Per-Token Baseline
- One token held (e.g., 1 BTC) - user selects
- Other 49 tokens: baseline = actual EQ from first tick (1 unit * price)
- Init fetches real prices from MEXC API
- EQ displayed in token quantity (not USDT)
- Matrix as list (not tiles)
- Data tab to monitor incoming ticks
"""
import random
import time
import threading
import sqlite3
import json
import requests
from datetime import datetime
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'live-matrix-v4'
app.config['DATABASE'] = 'live_matrix_v4.db'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# 50 tokens with MEXC symbols
TOKENS = [
    "BTC", "ETH", "BNB", "XRP", "SOL", "ADA", "DOGE", "AVAX", "DOT", "LINK",
    "MATIC", "SHIB", "LTC", "UNI", "ATOM", "XLM", "ETC", "FIL", "APT", "ARJ",
    "VET", "HBAR", "ICP", "EGLD", "SAND", "MANA", "AXS", "THETA", "AAVE", "FTM",
    "CRO", "NEAR", "ALGO", "QNT", "EOS", "XTZ", "FLOW", "CHZ", "APE", "ZIL",
    "ENJ", "WAXP", "BAT", "1INCH", "COMP", "MKR", "SNX", "CRV", "LDO", "RPL"
]

DEFAULT_THRESHOLD = 5.0
DEFAULT_BACKTEST_RANGE = {"min": 0.5, "max": 10.0, "step": 0.5}
DEFAULT_HOLD_AMOUNT = 1.0  # How many units of held token we have

FEE_BUY = 0.001
FEE_SWAP = 0.001

# Store raw tick data for the Data tab
tick_history = []

def init_db():
    """Initialize database."""
    conn = sqlite3.connect(app.config['DATABASE'])
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        held_token TEXT NOT NULL,
        threshold REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'initialized',
        baseline_eq REAL,
        current_eq REAL,
        total_swaps INTEGER DEFAULT 0,
        last_tick INTEGER DEFAULT 0
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS ticks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        tick INTEGER NOT NULL,
        timestamp TEXT NOT NULL,
        prices TEXT NOT NULL,
        holdings TEXT NOT NULL,
        top_eq TEXT NOT NULL,
        baseline_per_token TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS swaps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        tick INTEGER NOT NULL,
        timestamp TEXT NOT NULL,
        token_from TEXT NOT NULL,
        token_to TEXT NOT NULL,
        amount_from REAL NOT NULL,
        amount_to REAL NOT NULL,
        price_from REAL NOT NULL,
        price_to REAL NOT NULL,
        fee_paid REAL NOT NULL,
        threshold_used REAL NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS backtests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        threshold REAL NOT NULL,
        final_eq REAL NOT NULL,
        total_swaps INTEGER NOT NULL,
        gain_pct REAL NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    )''')
    
    conn.commit()
    conn.close()

class MatrixState:
    """Persistent state manager with per-token baseline."""
    
    def __init__(self):
        self.session_id = None
        self.held_token = None  # The token we own
        self.prices = {}
        self.holdings = {}  # Only held_token has amount > 0
        self.top_eq = {}    # Top value per token
        self.baseline_per_token = {}  # Baseline EQ per token from first tick
        self.is_running = False
        self.threshold = DEFAULT_THRESHOLD
        self.tick = 0
        self.swap_history = []
        self._init_prices()  # Initialize prices first
        self._load_or_create_session()
    
    def _init_prices(self):
        """Initialize prices."""
        for token in TOKENS:
            self.prices[token] = {
                "price": round(random.uniform(10, 50000), 4),
                "volatility": random.uniform(0.005, 0.03)
            }
    
    def _load_or_create_session(self):
        """Load existing session or create new one."""
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        
        c.execute("SELECT id, held_token, threshold, status, baseline_eq, last_tick FROM sessions ORDER BY id DESC LIMIT 1")
        row = c.fetchone()
        
        if row:
            self.session_id = row[0]
            self.held_token = row[1]
            self.threshold = row[2]
            self.is_running = (row[3] == 'running')
            self.tick = row[5]
            
            # Load last tick data
            c.execute("SELECT prices, holdings, top_eq, baseline_per_token FROM ticks WHERE session_id=? ORDER BY tick DESC LIMIT 1", (self.session_id,))
            tick_row = c.fetchone()
            if tick_row:
                self.prices = json.loads(tick_row[0])
                self.holdings = json.loads(tick_row[1])
                self.top_eq = json.loads(tick_row[2])
                self.baseline_per_token = json.loads(tick_row[3])
            
            # Load swap history
            c.execute("SELECT tick, timestamp, token_from, token_to, amount_from, amount_to, price_from, price_to, fee_paid, threshold_used FROM swaps WHERE session_id=? ORDER BY id", (self.session_id,))
            for row in c.fetchall():
                self.swap_history.append({
                    "tick": row[0], "timestamp": row[1], "token_from": row[2],
                    "token_to": row[3], "amount_from": row[4], "amount_to": row[5],
                    "price_from": row[6], "price_to": row[7], "fee": row[8], "threshold": row[9]
                })
        else:
            self.session_id = self._create_session()
        
        conn.close()
    
    def _create_session(self):
        """Create new session."""
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        held = random.choice(TOKENS)
        c.execute("INSERT INTO sessions (created_at, held_token, threshold, status) VALUES (?, ?, ?, 'initialized')",
                  (datetime.now().isoformat(), held, self.threshold))
        conn.commit()
        session_id = c.lastrowid
        conn.close()
        return session_id
    
    def fetch_mexc_prices(self):
        """Fetch real prices from MEXC API."""
        prices = {}
        success_count = 0
        for token in TOKENS:
            symbol = f"{token}USDT"
            try:
                url = f"https://api.mexc.com/api/v3/ticker/price?symbol={symbol}"
                resp = requests.get(url, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    price = float(data.get('price', 0))
                    if price > 0:
                        prices[token] = {"price": price, "source": "mexc"}
                        success_count += 1
                        continue
            except Exception as e:
                print(f"Error fetching {token}: {e}")
            # Fallback to small random value if API fails (so it's obvious)
            prices[token] = {"price": round(random.uniform(0.01, 100), 4), "source": "fallback"}
        
        print(f"FETCH: Got {success_count}/{len(TOKENS)} prices from MEXC")
        if success_count == 0:
            print("WARNING: No prices from MEXC - using fallback!")
        return prices

    def initialize_portfolio(self, held_token=None, threshold=None, hold_amount=None):
        """Initialize portfolio - select one token to hold, fetch real MEXC prices."""
        print(f"INIT: held_token={held_token}, threshold={threshold}, hold_amount={hold_amount}")
        
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        
        if threshold:
            self.threshold = threshold
        
        # Use provided token or default to BTC
        if held_token and held_token in TOKENS:
            self.held_token = held_token
        elif not self.held_token:
            self.held_token = "BTC"
        
        hold_amt = float(hold_amount) if hold_amount else DEFAULT_HOLD_AMOUNT
        
        print(f"INIT: using held_token={self.held_token}, hold_amount={hold_amt}")
        
        c.execute("UPDATE sessions SET held_token=?, threshold=?, status='initialized' WHERE id=?", 
                  (self.held_token, self.threshold, self.session_id))
        conn.commit()
        conn.close()
        
        # Fetch real prices from MEXC
        self.prices = self.fetch_mexc_prices()
        print(f"INIT: fetched prices for {len(self.prices)} tokens")
        
        # We hold `hold_amount` units of the selected token
        self.holdings = {token: 0 for token in TOKENS}
        self.holdings[self.held_token] = hold_amt
        print(f"INIT: holdings set: {self.holdings}")
        
        # Baseline per token = actual EQ from first tick (1 unit * price)
        # - Held token: baseline = hold_amount (e.g., 1 BTC)
        # - Other tokens: baseline = 1 unit (theoretical if we held it)
        self.baseline_per_token = {}
        for token in TOKENS:
            if token == self.held_token:
                self.baseline_per_token[token] = hold_amt  # e.g., 1 BTC
            else:
                self.baseline_per_token[token] = 1.0  # 1 unit if we held it
        
        # Top EQ per token = baseline (initial best)
        self.top_eq = {}
        for token in TOKENS:
            self.top_eq[token] = self.baseline_per_token[token]
        
        self.is_running = False
        self.tick = 0
        self.swap_history = []
        
        # Clear tick history for Data tab
        global tick_history
        tick_history = []
        
        return self.get_state()
    
    def start(self):
        """Start the matrix."""
        if self.tick == 0:
            self.initialize_portfolio(self.held_token)
        
        self.is_running = True
        
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute("UPDATE sessions SET status='running' WHERE id=?", (self.session_id,))
        conn.commit()
        conn.close()
        
        return self.get_state()
    
    def stop(self):
        """Stop the matrix."""
        self.is_running = False
        
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute("UPDATE sessions SET status='stopped', last_tick=?, total_swaps=? WHERE id=?",
                  (self.tick, len(self.swap_history), self.session_id))
        conn.commit()
        conn.close()
        
        return self.get_state()
    
    def restart(self):
        """Full restart."""
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute("DELETE FROM ticks WHERE session_id=?", (self.session_id,))
        c.execute("DELETE FROM swaps WHERE session_id=?", (self.session_id,))
        c.execute("DELETE FROM backtests WHERE session_id=?", (self.session_id,))
        conn.commit()
        conn.close()
        
        self.prices = {}
        self.holdings = {}
        self.top_eq = {}
        self.baseline_per_token = {}
        self.is_running = False
        self.tick = 0
        self.swap_history = []
        
        return self.initialize_portfolio()
    
    def update_threshold(self, threshold):
        """Update threshold."""
        self.threshold = threshold
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute("UPDATE sessions SET threshold=? WHERE id=?", (threshold, self.session_id))
        conn.commit()
        conn.close()
        return self.get_state()
    
    def update_prices(self):
        """Update prices."""
        for token in TOKENS:
            change = random.gauss(0, self.prices[token]["volatility"])
            self.prices[token]["price"] *= (1 + change)
            self.prices[token]["price"] = max(0.01, self.prices[token]["price"])
        
        # Update top per token
        for token in TOKENS:
            current_value = self.prices[token]["price"]
            if current_value > self.top_eq.get(token, 0):
                self.top_eq[token] = current_value
    
    def get_token_data(self):
        """Get data for all tokens - EQ in token quantity, not USDT."""
        results = {}
        
        # Return empty if not initialized
        if not self.prices or not self.held_token:
            for token in TOKENS:
                results[token] = {
                    "actual": 0, "top": 0, "baseline": 0,
                    "gain_top": 0, "gain_baseline": 0,
                    "rank": 0, "is_held": False, "holding": 0, "price": 0
                }
            return results
        
        held_price = self.prices.get(self.held_token, {}).get("price", 1)
        
        # Debug: log holdings
        print(f"DEBUG: held_token={self.held_token}, holdings={self.holdings}")
        
        for token in TOKENS:
            if token not in self.prices:
                continue
            price = self.prices[token]["price"]
            holding = self.holdings.get(token, 0)
            
            if token == self.held_token:
                # Held token: actual = amount we hold (in token units)
                actual = holding
                top = self.top_eq.get(token, holding)
                baseline = self.baseline_per_token.get(token, holding)
            else:
                # Other tokens: show what we'd have if we swapped into this token
                # Actual EQ in terms of held token = (held_amount * held_price) / this_price
                if price > 0 and held_price > 0:
                    held_value_usdt = self.holdings.get(self.held_token, 0) * held_price
                    actual = held_value_usdt / price  # How many of this token we'd have
                else:
                    actual = 0
                top = self.top_eq.get(token, 1.0)
                baseline = self.baseline_per_token.get(token, 1.0)
            
            # Gain from top (percentage)
            gain_top = 0
            if top > 0:
                gain_top = round((actual / top - 1) * 100, 2)
            
            # Gain from baseline (percentage)
            gain_baseline = 0
            if baseline > 0:
                gain_baseline = round((actual / baseline - 1) * 100, 2)
            
            results[token] = {
                "actual": round(actual, 6),  # Token quantity
                "top": round(top, 6),
                "baseline": round(baseline, 6),
                "gain_top": gain_top,
                "gain_baseline": gain_baseline,
                "rank": 0,
                "is_held": token == self.held_token,
                "holding": holding,
                "price": round(price, 4)
            }
        
        # Sort by actual EQ (token quantity)
        sorted_tokens = sorted(TOKENS, key=lambda t: results[t]["actual"], reverse=True)
        for i, token in enumerate(sorted_tokens):
            results[token]["rank"] = i + 1
        
        return results
    
    def auto_swap(self):
        """Find and execute best swaps based on threshold."""
        token_data = self.get_token_data()
        
        # Check if held token is underwater from its top
        held_data = token_data[self.held_token]
        
        if held_data["gain_top"] >= -self.threshold:
            return None  # Not underwater enough
        
        # Find best target token (highest gain_top - positive momentum)
        candidates = [(t, d) for t, d in token_data.items() 
                    if t != self.held_token and d["gain_top"] > 0]
        
        if not candidates:
            # No positive momentum - find least underwater
            candidates = [(t, d) for t, d in token_data.items() 
                         if t != self.held_token]
            candidates.sort(key=lambda x: x[1]["gain_top"], reverse=True)
        
        if not candidates:
            return None
        
        token_to = candidates[0][0]
        
        # Execute swap
        return self.simulate_swap(self.held_token, token_to)
    
    def simulate_swap(self, token_from, token_to):
        """Simulate a swap."""
        amount_from = self.holdings.get(token_from, 0)
        if amount_from <= 0:
            return None
        
        price_from = self.prices[token_from]["price"]
        price_to = self.prices[token_to]["price"]
        
        # Calculate after fees
        usd_value = amount_from * price_from
        usd_after_fee1 = usd_value * (1 - FEE_BUY)
        usd_after_fees = usd_after_fee1 * (1 - FEE_SWAP)
        
        amount_to = usd_after_fees / price_to
        value_during_swap = amount_to * price_to
        
        # Record swap
        swap_record = {
            "tick": self.tick,
            "timestamp": datetime.now().isoformat(),
            "token_from": token_from,
            "token_to": token_to,
            "amount_from": round(amount_from, 8),
            "amount_to": round(amount_to, 8),
            "price_from": round(price_from, 4),
            "price_to": round(price_to, 4),
            "fee": round(usd_value - usd_after_fees, 2),
            "threshold": self.threshold
        }
        self.swap_history.append(swap_record)
        
        # Update holdings
        self.holdings[token_from] = 0
        self.holdings[token_to] = self.holdings.get(token_to, 0) + amount_to
        self.held_token = token_to
        
        # Update top for new token if value exceeds it
        if value_during_swap > self.top_eq.get(token_to, 0):
            self.top_eq[token_to] = value_during_swap
        
        # Save to DB
        self._save_swap(swap_record)
        
        return swap_record
    
    def tick_update(self):
        """Update on each tick."""
        self.tick += 1
        self.update_prices()
        
        # Track for Data tab - store current prices
        global tick_history
        tick_entry = {
            "tick": self.tick,
            "timestamp": datetime.now().isoformat(),
            "prices": {t: round(self.prices[t]["price"], 4) for t in TOKENS}
        }
        tick_history.append(tick_entry)
        if len(tick_history) > 200:
            tick_history = tick_history[-200:]
        
        # Set baseline on first tick - now in token quantity
        if self.tick == 1:
            for token in TOKENS:
                if token == self.held_token:
                    self.baseline_per_token[token] = self.holdings.get(token, DEFAULT_HOLD_AMOUNT)
                else:
                    self.baseline_per_token[token] = 1.0  # 1 unit if we held it
                self.top_eq[token] = self.baseline_per_token[token]
        
        # Auto-swap every 5 ticks
        if self.tick % 5 == 0:
            self.auto_swap()
        
        data = self.get_state()
        self._save_tick(data)
        
        return data
    
    def get_state(self):
        """Get current state."""
        # Ensure prices are initialized if empty
        if not self.prices:
            self._init_prices()
        
        # Ensure held_token has a default
        if not self.held_token:
            self.held_token = "BTC"
        
        results = self.get_token_data()
        sorted_items = sorted(TOKENS, key=lambda t: results[t]["rank"])
        
        # Calculate total portfolio value
        total_eq = sum(results[t]["actual"] for t in TOKENS)
        total_top = sum(results[t]["top"] for t in TOKENS)
        
        return {
            "session_id": self.session_id,
            "tick": self.tick,
            "held_token": self.held_token,
            "threshold": self.threshold,
            "is_running": self.is_running,
            "status": "running" if self.is_running else ("initialized" if self.tick == 0 else "stopped"),
            "total_eq": round(total_eq, 2),
            "total_top": round(total_top, 2),
            "prices": {t: round(self.prices[t]["price"], 4) for t in TOKENS} if self.prices else {},
            "tokens": {t: results[t] for t in sorted_items},
            "swaps": self.swap_history[-10:] if self.swap_history else [],
            "total_swaps": len(self.swap_history)
        }
    
    def _save_tick(self, data):
        """Save tick to DB."""
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute('''INSERT INTO ticks (session_id, tick, timestamp, prices, holdings, top_eq, baseline_per_token)
                     VALUES (?, ?, ?, ?, ?, ?, ?)''',
                  (self.session_id, data["tick"], datetime.now().isoformat(),
                   json.dumps(self.prices), json.dumps(self.holdings),
                   json.dumps(self.top_eq), json.dumps(self.baseline_per_token)))
        conn.commit()
        conn.close()
    
    def _save_swap(self, swap):
        """Save swap to DB."""
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute('''INSERT INTO swaps (session_id, tick, timestamp, token_from, token_to, amount_from, amount_to,
                     price_from, price_to, fee_paid, threshold_used)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (self.session_id, swap["tick"], swap["timestamp"], swap["token_from"], swap["token_to"],
                   swap["amount_from"], swap["amount_to"], swap["price_from"], swap["price_to"],
                   swap["fee"], swap["threshold"]))
        conn.commit()
        conn.close()
    
    def run_backtest(self, params=None):
        """Run backtest with multiple thresholds."""
        if params is None:
            params = DEFAULT_BACKTEST_RANGE
        
        min_t = params.get("min", 0.5)
        max_t = params.get("max", 10.0)
        step_t = params.get("step", 0.5)
        
        conn = sqlite3.connect(app.config['DATABASE'])
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        c.execute("SELECT tick, prices, holdings, top_eq, baseline_per_token FROM ticks WHERE session_id=? ORDER BY tick", (self.session_id,))
        ticks = [dict(row) for row in c.fetchall()]
        c.execute("SELECT * FROM swaps WHERE session_id=? ORDER BY tick", (self.session_id,))
        swaps = [dict(row) for row in c.fetchall()]
        conn.close()
        
        if not ticks:
            return {"error": "No tick data"}
        
        results = []
        threshold = min_t
        
        while threshold <= max_t:
            bt = self._backtest_single(threshold, ticks, swaps)
            results.append(bt)
            self._save_backtest(bt)
            threshold += step_t
            threshold = round(threshold, 2)
        
        return {"backtests": results, "params": params}
    
    def _backtest_single(self, threshold, ticks, swaps):
        """Backtest single threshold."""
        first = json.loads(ticks[0]["prices"])
        baseline = {t: first[t]["price"] for t in TOKENS}
        
        holdings = {t: 0 for t in TOKENS}
        held = ticks[0].get("holdings", {})
        if held:
            holdings = json.loads(held)
        
        total_swaps = 0
        
        for i, tick_data in enumerate(ticks[1:], 1):
            prices = json.loads(tick_data["prices"])
            tick_num = tick_data["tick"]
            
            # Check swaps at this tick
            tick_swaps = [s for s in swaps if s["tick"] == tick_num]
            
            for swap in tick_swaps:
                # Recalculate with different threshold (simplified)
                if abs(swap.get("threshold", 5) - threshold) < 0.01:
                    continue
                total_swaps += 1
            
            # Update values
            total_eq = sum(holdings.get(t, 0) * prices.get(t, {}).get("price", 0) for t in TOKENS)
        
        initial_eq = 100000  # Simplified
        final_eq = total_eq if 'total_eq' in locals() else initial_eq
        gain_pct = round((final_eq / initial_eq - 1) * 100, 2)
        
        return {
            "threshold": threshold,
            "final_eq": round(final_eq, 2),
            "total_swaps": total_swaps,
            "gain_pct": gain_pct
        }
    
    def _save_backtest(self, result):
        """Save backtest."""
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute('''INSERT INTO backtests (session_id, threshold, final_eq, total_swaps, gain_pct, created_at)
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (self.session_id, result["threshold"], result["final_eq"],
                   result["total_swaps"], result["gain_pct"], datetime.now().isoformat()))
        conn.commit()
        conn.close()
    
    def export_history(self):
        """Export all data."""
        conn = sqlite3.connect(app.config['DATABASE'])
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        session = c.execute("SELECT * FROM sessions WHERE id=?", (self.session_id,)).fetchone()
        ticks = [dict(row) for row in c.execute('SELECT * FROM ticks WHERE session_id=? ORDER BY tick', (self.session_id,))]
        swaps = [dict(row) for row in c.execute('SELECT * FROM swaps WHERE session_id=? ORDER BY id', (self.session_id,))]
        backtests = [dict(row) for row in c.execute('SELECT * FROM backtests WHERE session_id=? ORDER BY threshold', (self.session_id,))]
        
        conn.close()
        return {"session": dict(session) if session else None, "ticks": ticks, "swaps": swaps, "backtests": backtests}


init_db()
state = MatrixState()

@app.route('/')
def index():
    return render_template('live_matrix_v4.html')

@app.route('/api/export')
def export_data():
    return jsonify(state.export_history())

@app.route('/api/ticks')
def get_ticks():
    """Get tick history for Data tab."""
    return jsonify({"ticks": tick_history[-100:]})  # Last 100 ticks

@app.route('/api/backtest', methods=['POST'])
def run_backtest():
    return jsonify(state.run_backtest(request.json or DEFAULT_BACKTEST_RANGE))

@socketio.on('connect')
def on_connect():
    emit('init', state.get_state())

@socketio.on('initialize')
def on_initialize(data=None):
    try:
        held = data.get("held_token") if data else None
        threshold = data.get("threshold") if data else None
        hold_amount = data.get("hold_amount") if data else None
        result = state.initialize_portfolio(held, threshold, hold_amount)
        emit('update', result)
    except Exception as e:
        print(f"Error in initialize: {e}")
        import traceback
        traceback.print_exc()

@socketio.on('start')
def on_start():
    try:
        emit('update', state.start())
    except Exception as e:
        print(f"Error in start: {e}")
        import traceback
        traceback.print_exc()

@socketio.on('stop')
def on_stop():
    emit('update', state.stop())

@socketio.on('restart')
def on_restart():
    emit('update', state.restart())

@socketio.on('set_threshold')
def on_set_threshold(data):
    emit('update', state.update_threshold(data.get("threshold", DEFAULT_THRESHOLD)))

@socketio.on('run_backtest')
def on_run_backtest(data=None):
    emit('backtest_result', state.run_backtest(data or DEFAULT_BACKTEST_RANGE))

def run_ticks():
    """Background task."""
    while True:
        if state.is_running:
            socketio.emit('update', state.tick_update())
        time.sleep(1)

if __name__ == '__main__':
    thread = threading.Thread(target=run_ticks, daemon=True)
    thread.start()
    socketio.run(app, host='0.0.0.0', port=12000, debug=False, allow_unsafe_werkzeug=True)
