"""
Live Matrix v3 - Persistent State, Backtester
- State persists across restarts
- Initialize Portfolio -> Start -> Stop -> Resume
- Backtester: test multiple thresholds simultaneously
"""
import random
import time
import threading
import sqlite3
import json
import os
from datetime import datetime
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'live-matrix-v3'
app.config['DATABASE'] = 'live_matrix.db'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# 50 tokens
TOKENS = [
    "BTC", "ETH", "BNB", "XRP", "SOL", "ADA", "DOGE", "AVAX", "DOT", "LINK",
    "MATIC", "SHIB", "LTC", "UNI", "ATOM", "XLM", "ETC", "FIL", "APT", "ARJ",
    "VET", "HBAR", "ICP", "EGLD", "SAND", "MANA", "AXS", "THETA", "AAVE", "FTM",
    "CRO", "NEAR", "ALGO", "QNT", "EOS", "XTZ", "FLOW", "CHZ", "APE", "ZIL",
    "ENJ", "WAXP", "BAT", "1INCH", "COMP", "MKR", "SNX", "CRV", "LDO", "RPL"
]

# Default settings
DEFAULT_THRESHOLD = 5.0  # Trigger swap when underwater by this %
DEFAULT_BACKTEST_RANGE = {"min": 0.5, "max": 10.0, "step": 0.5}

FEE_BUY = 0.001   # 0.1% fee on buy
FEE_SWAP = 0.001  # 0.1% fee on swap

def init_db():
    """Initialize database with full schema."""
    conn = sqlite3.connect(app.config['DATABASE'])
    c = conn.cursor()
    
    # Test sessions
    c.execute('''CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        threshold REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'initialized',
        baseline_eq REAL,
        current_eq REAL,
        total_swaps INTEGER DEFAULT 0,
        last_tick INTEGER DEFAULT 0
    )''')
    
    # Tick history for active session
    c.execute('''CREATE TABLE IF NOT EXISTS ticks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        tick INTEGER NOT NULL,
        timestamp TEXT NOT NULL,
        total_eq REAL NOT NULL,
        data TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    )''')
    
    # Swaps history
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
        top_from_before REAL NOT NULL,
        top_to_after REAL NOT NULL,
        threshold_used REAL NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    )''')
    
    # Backtest results
    c.execute('''CREATE TABLE IF NOT EXISTS backtests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        threshold REAL NOT NULL,
        final_eq REAL NOT NULL,
        total_swaps INTEGER NOT NULL,
        gain_pct REAL NOT NULL,
        top_eq REAL NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(id)
    )''')
    
    conn.commit()
    conn.close()

class MatrixState:
    """Persistent state manager."""
    
    def __init__(self):
        self.session_id = None
        self.prices = {}
        self.holdings = {}
        self.top_eq = {}
        self.is_running = False
        self.threshold = DEFAULT_THRESHOLD
        self.tick = 0
        self.baseline_eq = None
        self.swap_history = []
        self.last_swap_token = None
        self._load_or_create_session()
    
    def _load_or_create_session(self):
        """Load existing session or create new one."""
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        
        # Check for existing active session
        c.execute("SELECT id, threshold, status, baseline_eq, last_tick FROM sessions ORDER BY id DESC LIMIT 1")
        row = c.fetchone()
        
        if row:
            self.session_id = row[0]
            self.threshold = row[1]
            status = row[2]
            self.baseline_eq = row[3]
            self.tick = row[4]
            self.is_running = (status == 'running')
            
            # Load prices from last tick
            c.execute("SELECT data FROM ticks WHERE session_id=? ORDER BY tick DESC LIMIT 1", (self.session_id,))
            tick_row = c.fetchone()
            if tick_row:
                data = json.loads(tick_row[0])
                self.prices = data.get("prices", {})
                self.holdings = data.get("holdings", {})
                self.top_eq = data.get("top_eq", {})
                self.last_swap_token = data.get("last_swap_token")
            
            # Load swap history
            c.execute("SELECT * FROM swaps WHERE session_id=? ORDER BY tick", (self.session_id,))
            for row in c.fetchall():
                self.swap_history.append({
                    "tick": row[2], "timestamp": row[3], "token_from": row[4],
                    "token_to": row[5], "amount_from": row[6], "amount_to": row[7],
                    "price_from": row[8], "price_to": row[9], "fee": row[10],
                    "top_from": row[11], "top_to": row[12], "threshold": row[13]
                })
        else:
            # Create new session
            self.session_id = self._create_session()
        
        conn.close()
    
    def _create_session(self):
        """Create new session in DB."""
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute("INSERT INTO sessions (created_at, threshold, status) VALUES (?, ?, 'initialized')",
                  (datetime.now().isoformat(), self.threshold))
        conn.commit()
        session_id = c.lastrowid
        conn.close()
        return session_id
    
    def initialize_portfolio(self, threshold=None):
        """Initialize/reset portfolio."""
        if threshold:
            self.threshold = threshold
        
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        
        # Update session threshold
        c.execute("UPDATE sessions SET threshold=?, status='initialized' WHERE id=?", 
                  (self.threshold, self.session_id))
        conn.commit()
        conn.close()
        
        # Reset prices and holdings
        self.prices = {}
        for token in TOKENS:
            self.prices[token] = {
                "price": round(random.uniform(0.01, 50000), 4),
                "volatility": random.uniform(0.005, 0.03)
            }
            usd_value = 1000
            self.holdings[token] = usd_value / self.prices[token]["price"]
            self.top_eq[token] = usd_value
        
        self.holdings["USDT"] = 50000
        self.top_eq["USDT"] = 50000
        self.last_swap_token = "USDT"
        
        self.is_running = False
        self.tick = 0
        self.baseline_eq = None
        self.swap_history = []
        
        return self.get_state()
    
    def start(self):
        """Start the matrix."""
        if self.tick == 0:
            # Fresh start - initialize prices
            self.initialize_portfolio()
        
        self.is_running = True
        
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute("UPDATE sessions SET status='running' WHERE id=?", (self.session_id,))
        conn.commit()
        conn.close()
        
        return self.get_state()
    
    def stop(self):
        """Stop the matrix without resetting."""
        self.is_running = False
        
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute("UPDATE sessions SET status='stopped', current_eq=?, last_tick=?, total_swaps=? WHERE id=?",
                  (self.get_total_eq(), self.tick, len(self.swap_history), self.session_id))
        conn.commit()
        conn.close()
        
        return self.get_state()
    
    def restart(self):
        """Full restart - create new session."""
        # Delete old ticks and swaps for this session
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute("DELETE FROM ticks WHERE session_id=?", (self.session_id,))
        c.execute("DELETE FROM swaps WHERE session_id=?", (self.session_id,))
        c.execute("DELETE FROM backtests WHERE session_id=?", (self.session_id,))
        c.execute("UPDATE sessions SET status='initialized', baseline_eq=NULL, current_eq=NULL, total_swaps=0, last_tick=0 WHERE id=?", (self.session_id,))
        conn.commit()
        conn.close()
        
        # Reset state
        self.prices = {}
        for token in TOKENS:
            self.prices[token] = {
                "price": round(random.uniform(0.01, 50000), 4),
                "volatility": random.uniform(0.005, 0.03)
            }
            usd_value = 1000
            self.holdings[token] = usd_value / self.prices[token]["price"]
            self.top_eq[token] = usd_value
        
        self.holdings["USDT"] = 50000
        self.top_eq["USDT"] = 50000
        self.last_swap_token = "USDT"
        
        self.is_running = False
        self.tick = 0
        self.baseline_eq = None
        self.swap_history = []
        
        return self.get_state()
    
    def update_threshold(self, threshold):
        """Update threshold setting."""
        self.threshold = threshold
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute("UPDATE sessions SET threshold=? WHERE id=?", (threshold, self.session_id))
        conn.commit()
        conn.close()
        return self.get_state()
    
    def get_total_eq(self):
        """Calculate total equity."""
        total = 0
        for token in TOKENS + ["USDT"]:
            amount = self.holdings.get(token, 0)
            price = self.prices.get(token, {}).get("price", 1)
            total += amount * price
        return total
    
    def get_actual_eq(self):
        """Calculate actual equity per token."""
        results = {}
        total = 0
        held_token = None
        
        for token in TOKENS + ["USDT"]:
            amount = self.holdings.get(token, 0)
            price = self.prices.get(token, {}).get("price", 1)
            value = amount * price
            total += value
            if amount > 0:
                held_token = token
                results[token] = {
                    "actual": value,
                    "top": self.top_eq.get(token, 0),
                    "gain_top": 0,
                    "rank": 0,
                    "is_held": True,
                    "holding": amount,
                    "price": price
                }
        
        if held_token is None:
            held_token = "USDT"
            results["USDT"] = {
                "actual": self.holdings.get("USDT", 0),
                "top": self.top_eq.get("USDT", 50000),
                "gain_top": 0,
                "rank": 0,
                "is_held": True,
                "holding": self.holdings.get("USDT", 0),
                "price": 1
            }
        
        for token, data in results.items():
            if data["top"] > 0:
                data["gain_top"] = round((data["actual"] / data["top"] - 1) * 100, 2)
        
        sorted_tokens = sorted(
            [(t, d) for t, d in results.items() if t != "USDT"],
            key=lambda x: x[1]["actual"],
            reverse=True
        )
        
        for i, (token, data) in enumerate(sorted_tokens):
            data["rank"] = i + 1
        
        if "USDT" in results:
            results["USDT"]["rank"] = len(sorted_tokens) + 1
        
        return results, total
    
    def update_prices(self):
        """Update prices with random walk."""
        for token in TOKENS:
            change = random.gauss(0, self.prices[token]["volatility"])
            self.prices[token]["price"] *= (1 + change)
            self.prices[token]["price"] = max(0.0001, self.prices[token]["price"])
        
        results, _ = self.get_actual_eq()
        for token, data in results.items():
            if data["actual"] > data["top"]:
                self.top_eq[token] = data["actual"]
    
    def simulate_swap(self, token_from, token_to, threshold_used):
        """Simulate a swap."""
        amount_from = self.holdings.get(token_from, 0)
        if amount_from <= 0:
            return None
        
        price_from = self.prices[token_from]["price"]
        price_to = self.prices[token_to]["price"]
        
        usd_value = amount_from * price_from
        usd_after_fee1 = usd_value * (1 - FEE_BUY)
        usd_after_fees = usd_after_fee1 * (1 - FEE_SWAP)
        
        amount_to = usd_after_fees / price_to
        value_during_swap = amount_to * price_to
        
        old_top_from = self.top_eq.get(token_from, 0)
        old_top_to = self.top_eq.get(token_to, 0)
        
        self.holdings[token_from] = 0
        self.holdings[token_to] = self.holdings.get(token_to, 0) + amount_to
        self.last_swap_token = token_to
        
        if value_during_swap > old_top_to:
            self.top_eq[token_to] = value_during_swap
        
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
            "top_from": round(old_top_from, 2),
            "top_to": round(self.top_eq.get(token_to, 0), 2),
            "threshold": threshold_used
        }
        self.swap_history.append(swap_record)
        
        # Save to DB
        self._save_swap(swap_record)
        
        return swap_record
    
    def auto_swap(self):
        """Find and execute best swaps based on threshold."""
        results, _ = self.get_actual_eq()
        
        underwater = [(t, d) for t, d in results.items() 
                      if t != "USDT" and d["gain_top"] < -self.threshold]
        
        if not underwater:
            return None
        
        underwater.sort(key=lambda x: x[1]["gain_top"])
        token_from = underwater[0][0]
        
        potential_targets = []
        for token in TOKENS + ["USDT"]:
            if token == token_from:
                continue
            price_to = self.prices.get(token, {}).get("price", 1)
            amount_from = self.holdings.get(token_from, 0)
            price_from = self.prices[token_from]["price"]
            
            if amount_from <= 0 or price_to <= 0:
                continue
            
            usd_value = amount_from * price_from * (1 - FEE_BUY) * (1 - FEE_SWAP)
            amount_to = usd_value / price_to
            value_after_swap = amount_to * price_to
            
            current_top = self.top_eq.get(token, 0)
            current_gain = results.get(token, {}).get("gain_top", 0)
            
            potential_targets.append({
                "token": token,
                "value_after": value_after_swap,
                "current_top": current_top,
                "new_top": value_after_swap > current_top,
                "current_gain": current_gain
            })
        
        if not potential_targets:
            return None
        
        potential_targets.sort(key=lambda x: (-int(x["new_top"]), -x["current_gain"]))
        token_to = potential_targets[0]["token"]
        
        return self.simulate_swap(token_from, token_to, self.threshold)
    
    def tick_update(self):
        """Update all tokens on each tick."""
        self.tick += 1
        self.update_prices()
        
        if self.tick % 5 == 0:
            self.auto_swap()
        
        data = self.get_state()
        self._save_tick(data)
        
        return data
    
    def get_state(self):
        """Get current state for frontend."""
        results, total_eq = self.get_actual_eq()
        
        sorted_items = sorted(
            [(t, d) for t, d in results.items() if t != "USDT"],
            key=lambda x: x[1]["rank"]
        )
        
        gain_global = 0
        if self.baseline_eq:
            gain_global = round((total_eq / self.baseline_eq - 1) * 100, 2)
        
        return {
            "session_id": self.session_id,
            "tick": self.tick,
            "threshold": self.threshold,
            "baseline_eq": self.baseline_eq,
            "actual_eq": round(total_eq, 2),
            "gain_global": gain_global,
            "top_total": round(sum(self.top_eq.get(t, 0) for t in TOKENS + ["USDT"]), 2),
            "is_running": self.is_running,
            "status": "running" if self.is_running else ("initialized" if self.tick == 0 else "stopped"),
            "prices": {t: round(self.prices[t]["price"], 4) for t in TOKENS} if self.prices else {},
            "tokens": {t: {
                "actual": round(d["actual"], 2),
                "top": round(d["top"], 2),
                "gain_top": d["gain_top"],
                "rank": d["rank"],
                "is_held": d["is_held"],
                "holding": round(d["holding"], 6),
                "price": round(d.get("price", 0), 4)
            } for t, d in sorted_items},
            "usdt": {
                "actual": round(results.get("USDT", {}).get("actual", 0), 2),
                "top": round(self.top_eq.get("USDT", 0), 2),
                "gain_top": round(results.get("USDT", {}).get("gain_top", 0), 2),
                "rank": results.get("USDT", {}).get("rank", 51),
                "is_held": results.get("USDT", {}).get("is_held", True),
                "holding": round(results.get("USDT", {}).get("holding", 0), 2)
            },
            "swaps": self.swap_history[-10:] if self.swap_history else [],
            "total_swaps": len(self.swap_history)
        }
    
    def _save_tick(self, data):
        """Save tick to database."""
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        tick_data = {
            "prices": self.prices,
            "holdings": self.holdings,
            "top_eq": self.top_eq,
            "last_swap_token": self.last_swap_token
        }
        c.execute('''INSERT INTO ticks (session_id, tick, timestamp, total_eq, data)
                     VALUES (?, ?, ?, ?, ?)''',
                  (self.session_id, data["tick"], datetime.now().isoformat(), 
                   data["actual_eq"], json.dumps(tick_data)))
        conn.commit()
        conn.close()
    
    def _save_swap(self, swap):
        """Save swap to database."""
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute('''INSERT INTO swaps (session_id, tick, timestamp, token_from, token_to, amount_from, amount_to,
                     price_from, price_to, fee_paid, top_from, top_to, threshold_used)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (self.session_id, swap["tick"], swap["timestamp"], swap["token_from"], swap["token_to"],
                   swap["amount_from"], swap["amount_to"], swap["price_from"], swap["price_to"],
                   swap["fee"], swap["top_from"], swap["top_to"], swap["threshold"]))
        conn.commit()
        conn.close()
    
    def run_backtest(self, params=None):
        """Run backtest with multiple thresholds."""
        if params is None:
            params = DEFAULT_BACKTEST_RANGE
        
        min_t = params.get("min", 0.5)
        max_t = params.get("max", 10.0)
        step_t = params.get("step", 0.5)
        
        # Get all ticks for this session
        conn = sqlite3.connect(app.config['DATABASE'])
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        c.execute("SELECT tick, data FROM ticks WHERE session_id=? ORDER BY tick", (self.session_id,))
        ticks = [dict(row) for row in c.fetchall()]
        c.execute("SELECT * FROM swaps WHERE session_id=? ORDER BY tick", (self.session_id,))
        swaps = [dict(row) for row in c.fetchall()]
        conn.close()
        
        if not ticks:
            return {"error": "No tick data to backtest"}
        
        # Run backtest for each threshold
        results = []
        threshold = min_t
        
        while threshold <= max_t:
            backtest_result = self._backtest_single_threshold(threshold, ticks, swaps)
            results.append(backtest_result)
            
            # Save to DB
            self._save_backtest(backtest_result)
            
            threshold += step_t
            threshold = round(threshold, 2)
        
        return {"backtests": results, "params": params}
    
    def _backtest_single_threshold(self, threshold, ticks, swaps):
        """Backtest with single threshold using historical data."""
        # Clone state from first tick
        if not ticks:
            return None
        
        first_tick = json.loads(ticks[0]["data"])
        prices = first_tick["prices"]
        holdings = first_tick["holdings"]
        top_eq = first_tick["top_eq"]
        
        total_swaps = 0
        swap_history = []
        
        # Process each tick
        for tick_data in ticks[1:]:
            tick_num = tick_data["tick"]
            data = json.loads(tick_data["data"])
            prices = data["prices"]
            
            # Check if swap happened at this tick
            tick_swaps = [s for s in swaps if s["tick"] == tick_num]
            
            for swap in tick_swaps:
                token_from = swap["token_from"]
                token_to = swap["token_to"]
                
                amount_from = holdings.get(token_from, 0)
                if amount_from <= 0:
                    continue
                
                price_from = prices.get(token_from, {}).get("price", 1)
                price_to = prices.get(token_to, {}).get("price", 1)
                
                usd_value = amount_from * price_from
                usd_after_fees = usd_value * (1 - FEE_BUY) * (1 - FEE_SWAP)
                amount_to = usd_after_fees / price_to
                
                holdings[token_from] = 0
                holdings[token_to] = holdings.get(token_to, 0) + amount_to
                
                # Update top
                value_during = amount_to * price_to
                if value_during > top_eq.get(token_to, 0):
                    top_eq[token_to] = value_during
                
                total_swaps += 1
                swap_history.append({
                    "token_from": token_from,
                    "token_to": token_to,
                    "threshold": threshold
                })
        
        # Calculate final equity
        total_eq = sum(holdings.get(t, 0) * prices.get(t, {}).get("price", 1) 
                       for t in TOKENS + ["USDT"])
        top_total = sum(top_eq.values())
        
        initial_eq = 100000
        gain_pct = round((total_eq / initial_eq - 1) * 100, 2)
        
        return {
            "threshold": threshold,
            "final_eq": round(total_eq, 2),
            "total_swaps": total_swaps,
            "gain_pct": gain_pct,
            "top_eq": round(top_total, 2)
        }
    
    def _save_backtest(self, result):
        """Save backtest result to DB."""
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute('''INSERT INTO backtests (session_id, threshold, final_eq, total_swaps, gain_pct, top_eq, created_at)
                     VALUES (?, ?, ?, ?, ?, ?, ?)''',
                  (self.session_id, result["threshold"], result["final_eq"], result["total_swaps"],
                   result["gain_pct"], result["top_eq"], datetime.now().isoformat()))
        conn.commit()
        conn.close()
    
    def export_history(self):
        """Export full history as JSON."""
        conn = sqlite3.connect(app.config['DATABASE'])
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        session = c.execute("SELECT * FROM sessions WHERE id=?", (self.session_id,)).fetchone()
        ticks = [dict(row) for row in c.execute('SELECT * FROM ticks WHERE session_id=? ORDER BY tick', (self.session_id,))]
        swaps = [dict(row) for row in c.execute('SELECT * FROM swaps WHERE session_id=? ORDER BY id', (self.session_id,))]
        backtests = [dict(row) for row in c.execute('SELECT * FROM backtests WHERE session_id=? ORDER BY threshold', (self.session_id,))]
        
        conn.close()
        return {
            "session": dict(session) if session else None,
            "ticks": ticks,
            "swaps": swaps,
            "backtests": backtests
        }


# Initialize DB
init_db()

# Global state
state = MatrixState()

@app.route('/')
def index():
    return render_template('live_matrix_v3.html')

@app.route('/api/export')
def export_data():
    return jsonify(state.export_history())

@app.route('/api/backtest', methods=['POST'])
def run_backtest():
    params = request.json or DEFAULT_BACKTEST_RANGE
    return jsonify(state.run_backtest(params))

@socketio.on('connect')
def on_connect():
    emit('init', state.get_state())

@socketio.on('initialize')
def on_initialize(data=None):
    threshold = data.get("threshold") if data else None
    emit('update', state.initialize_portfolio(threshold))

@socketio.on('start')
def on_start():
    if state.baseline_eq is None and state.tick > 0:
        # Resume from stopped state - keep existing baseline
        pass
    elif state.baseline_eq is None:
        # Fresh start - set baseline
        state.baseline_eq = state.get_total_eq()
    emit('update', state.start())

@socketio.on('stop')
def on_stop():
    emit('update', state.stop())

@socketio.on('restart')
def on_restart():
    emit('update', state.restart())

@socketio.on('set_threshold')
def on_set_threshold(data):
    threshold = data.get("threshold", DEFAULT_THRESHOLD)
    emit('update', state.update_threshold(threshold))

@socketio.on('run_backtest')
def on_run_backtest(data=None):
    params = data or DEFAULT_BACKTEST_RANGE
    result = state.run_backtest(params)
    emit('backtest_result', result)

def run_ticks():
    """Background task to emit ticks."""
    while True:
        if state.is_running:
            data = state.tick_update()
            socketio.emit('update', data)
        time.sleep(1)

if __name__ == '__main__':
    thread = threading.Thread(target=run_ticks, daemon=True)
    thread.start()
    socketio.run(app, host='0.0.0.0', port=12000, debug=False, allow_unsafe_werkzeug=True)
