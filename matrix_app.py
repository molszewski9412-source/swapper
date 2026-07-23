"""
Live Matrix - Token swapping strategy simulator
"""
import os
import json
import random
import sqlite3
import requests
from datetime import datetime
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO

app = Flask(__name__)
app.config['DATABASE'] = 'matrix.db'
app.config['SECRET_KEY'] = 'matrix-secret'
socketio = SocketIO(app, cors_allowed_origins="*")

# Constants
TOKENS = ["BTC", "ETH", "BNB", "XRP", "SOL", "ADA", "DOGE", "AVAX", "DOT", "LINK",
          "MATIC", "SHIB", "LTC", "UNI", "ATOM", "XLM", "ETC", "FIL", "APT", "ARJ",
          "VET", "HBAR", "ICP", "EGLD", "SAND", "MANA", "AXS", "THETA", "AAVE", "FTM",
          "CRO", "NEAR", "ALGO", "QNT", "EOS", "XTZ", "FLOW", "CHZ", "APE", "ZIL",
          "ENJ", "WAXP", "BAT", "1INCH", "COMP", "MKR", "SNX", "CRV", "LDO", "RPL"]

FEE = 0.002  # 0.2% total fee
DEFAULT_HOLD = 1.0
DEFAULT_THRESHOLD = 5.0

# Global state
tick_history = []
backtest_results = {}

def init_db():
    """Initialize database."""
    conn = sqlite3.connect(app.config['DATABASE'])
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        held_token TEXT NOT NULL,
        hold_amount REAL NOT NULL,
        threshold REAL NOT NULL,
        status TEXT NOT NULL,
        holdings TEXT,
        baseline TEXT,
        top TEXT,
        tick INTEGER DEFAULT 0,
        total_swaps INTEGER DEFAULT 0
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS ticks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        tick INTEGER NOT NULL,
        timestamp TEXT NOT NULL,
        prices TEXT NOT NULL,
        holdings TEXT NOT NULL,
        top TEXT NOT NULL,
        baseline TEXT NOT NULL
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
        fee REAL NOT NULL,
        threshold REAL NOT NULL
    )''')
    
    conn.commit()
    conn.close()

class MatrixState:
    def __init__(self):
        self.session_id = None
        self.held_token = None
        self.hold_amount = DEFAULT_HOLD
        self.threshold = DEFAULT_THRESHOLD
        self.status = "initialized"
        self.holdings = {}
        self.baseline = {}
        self.top = {}
        self.prices = {}
        self.tick = 0
        self.total_swaps = 0
        self.swap_history = []
        
        self._load_or_create()
    
    def _load_or_create(self):
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        
        c.execute("SELECT * FROM sessions ORDER BY id DESC LIMIT 1")
        row = c.fetchone()
        
        if row:
            self.session_id = row[0]
            self.held_token = row[2]
            self.hold_amount = row[3]
            self.threshold = row[4]
            self.status = row[5]
            self.holdings = json.loads(row[6]) if row[6] else {self.held_token: self.hold_amount}
            self.baseline = json.loads(row[7]) if row[7] else {}
            self.top = json.loads(row[8]) if row[8] else {}
            self.tick = row[9]
            self.total_swaps = row[10]
            
            c.execute("SELECT prices FROM ticks WHERE session_id=? ORDER BY tick DESC LIMIT 1", (self.session_id,))
            tick_row = c.fetchone()
            if tick_row:
                self.prices = json.loads(tick_row[0])
            else:
                self._init_prices()
            
            c.execute("SELECT * FROM swaps WHERE session_id=? ORDER BY tick", (self.session_id,))
            for s in c.fetchall():
                self.swap_history.append({
                    "tick": s[2], "timestamp": s[3], "token_from": s[4], "token_to": s[5],
                    "amount_from": s[6], "amount_to": s[7], "price_from": s[8], "price_to": s[9],
                    "fee": s[10], "threshold": s[11]
                })
        else:
            self._create_session()
        
        conn.close()
    
    def _create_session(self):
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        
        self.prices = self._fetch_prices()
        self.held_token = random.choice(TOKENS)
        self.hold_amount = DEFAULT_HOLD
        self.holdings = {self.held_token: self.hold_amount}
        
        held_price = self.prices.get(self.held_token, {}).get("price", 1)
        held_value = self.hold_amount * held_price * (1 - FEE)
        
        for token in TOKENS:
            if token == self.held_token:
                self.baseline[token] = self.hold_amount
                self.top[token] = self.hold_amount
            else:
                price = self.prices.get(token, {}).get("price", 0)
                if price > 0:
                    amount = held_value / price * (1 - FEE)
                else:
                    amount = 0
                self.baseline[token] = amount
                self.top[token] = amount
        
        c.execute("""INSERT INTO sessions (created_at, held_token, hold_amount, threshold, status, holdings, baseline, top, tick)
                      VALUES (?, ?, ?, ?, 'initialized', ?, ?, ?, 0)""",
                  (datetime.now().isoformat(), self.held_token, self.hold_amount, self.threshold,
                   json.dumps(self.holdings), json.dumps(self.baseline), json.dumps(self.top)))
        self.session_id = c.lastrowid
        conn.commit()
        conn.close()
    
    def _fetch_prices(self):
        prices = {}
        for token in TOKENS:
            try:
                url = f"https://api.mexc.com/api/v3/ticker/price?symbol={token}USDT"
                resp = requests.get(url, timeout=3)
                if resp.status_code == 200:
                    data = resp.json()
                    price = float(data.get('price', 0))
                    if price > 0:
                        prices[token] = {"price": price}
                        continue
            except:
                pass
            prices[token] = {"price": round(random.uniform(10, 50000), 2)}
        return prices
    
    def _init_prices(self):
        for token in TOKENS:
            self.prices[token] = {"price": round(random.uniform(10, 50000), 2)}
    
    def initialize(self, held_token=None, threshold=None, hold_amount=None):
        if threshold:
            self.threshold = threshold
        
        if held_token and held_token in TOKENS:
            self.held_token = held_token
        
        if not self.held_token:
            self.held_token = "BTC"
        
        if hold_amount:
            self.hold_amount = float(hold_amount)
        
        self.prices = self._fetch_prices()
        
        self.holdings = {token: 0 for token in TOKENS}
        self.holdings[self.held_token] = self.hold_amount
        
        held_price = self.prices.get(self.held_token, {}).get("price", 1)
        held_value = self.hold_amount * held_price * (1 - FEE)
        
        for token in TOKENS:
            if token == self.held_token:
                self.baseline[token] = self.hold_amount
                self.top[token] = self.hold_amount
            else:
                price = self.prices.get(token, {}).get("price", 0)
                if price > 0:
                    amount = held_value / price * (1 - FEE)
                else:
                    amount = 0
                self.baseline[token] = amount
                self.top[token] = amount
        
        self.status = "initialized"
        self.tick = 0
        self.total_swaps = 0
        self.swap_history = []
        
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute("""UPDATE sessions SET held_token=?, hold_amount=?, threshold=?, status=?, holdings=?, baseline=?, top=?, tick=0, total_swaps=0 WHERE id=?""",
                  (self.held_token, self.hold_amount, self.threshold, self.status,
                   json.dumps(self.holdings), json.dumps(self.baseline), json.dumps(self.top), self.session_id))
        conn.commit()
        conn.close()
        
        return self.get_state()
    
    def start(self):
        self.status = "running"
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute("UPDATE sessions SET status='running' WHERE id=?", (self.session_id,))
        conn.commit()
        conn.close()
        return self.get_state()
    
    def stop(self):
        self.status = "stopped"
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute("UPDATE sessions SET status='stopped' WHERE id=?", (self.session_id,))
        conn.commit()
        conn.close()
        return self.get_state()
    
    def restart(self):
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute("DELETE FROM ticks WHERE session_id=?", (self.session_id,))
        c.execute("DELETE FROM swaps WHERE session_id=?", (self.session_id,))
        conn.commit()
        conn.close()
        
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        self.prices = self._fetch_prices()
        self.held_token = random.choice(TOKENS)
        self.holdings = {self.held_token: self.hold_amount}
        
        held_price = self.prices.get(self.held_token, {}).get("price", 1)
        held_value = self.hold_amount * held_price * (1 - FEE)
        
        for token in TOKENS:
            if token == self.held_token:
                self.baseline[token] = self.hold_amount
                self.top[token] = self.hold_amount
            else:
                price = self.prices.get(token, {}).get("price", 0)
                if price > 0:
                    amount = held_value / price * (1 - FEE)
                else:
                    amount = 0
                self.baseline[token] = amount
                self.top[token] = amount
        
        c.execute("""INSERT INTO sessions (created_at, held_token, hold_amount, threshold, status, holdings, baseline, top, tick)
                      VALUES (?, ?, ?, ?, 'initialized', ?, ?, ?, 0)""",
                  (datetime.now().isoformat(), self.held_token, self.hold_amount, self.threshold,
                   json.dumps(self.holdings), json.dumps(self.baseline), json.dumps(self.top)))
        self.session_id = c.lastrowid
        self.tick = 0
        self.total_swaps = 0
        self.swap_history = []
        self.status = "initialized"
        conn.commit()
        conn.close()
        
        return self.get_state()
    
    def set_threshold(self, threshold):
        self.threshold = float(threshold)
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute("UPDATE sessions SET threshold=? WHERE id=?", (self.threshold, self.session_id))
        conn.commit()
        conn.close()
        return self.get_state()
    
    def tick_update(self):
        if self.status != "running":
            return self.get_state()
        
        self.tick += 1
        
        # Update prices
        for token in TOKENS:
            if token in self.prices:
                change = random.gauss(0, 0.01)
                self.prices[token]["price"] *= (1 + change)
                self.prices[token]["price"] = max(0.01, self.prices[token]["price"])
        
        # Check for swap every 5 ticks
        if self.tick % 5 == 0:
            self._try_swap()
        
        self._save_tick()
        self._run_backtest()
        
        return self.get_state()
    
    def _try_swap(self):
        held = self.held_token
        held_price = self.prices.get(held, {}).get("price", 1)
        held_amount = self.holdings.get(held, 0)
        
        if held_amount <= 0:
            return
        
        current_value = held_amount * held_price
        current_top = self.top.get(held, held_amount)
        
        if current_top > 0:
            loss_pct = (1 - current_value / (current_top * held_price)) * 100
        else:
            loss_pct = 0
        
        if loss_pct < self.threshold:
            return
        
        best_target = None
        best_gain = -999
        
        for token in TOKENS:
            if token == held:
                continue
            
            token_price = self.prices.get(token, {}).get("price", 0)
            if token_price <= 0:
                continue
            
            usd = held_amount * held_price * (1 - FEE)
            amount_to = usd * (1 - FEE) / token_price
            value_to = amount_to * token_price
            
            gain_pct = (value_to / current_value - 1) * 100
            
            if gain_pct > best_gain:
                best_gain = gain_pct
                best_target = token
        
        if best_target:
            self._execute_swap(held, best_target, held_price)
    
    def _execute_swap(self, token_from, token_to, price_from):
        amount_from = self.holdings.get(token_from, 0)
        if amount_from <= 0:
            return
        
        price_to = self.prices.get(token_to, {}).get("price", 1)
        
        usd = amount_from * price_from * (1 - FEE)
        usd_after = usd * (1 - FEE)
        amount_to = usd_after / price_to
        
        self.holdings[token_from] = 0
        self.holdings[token_to] = amount_to
        self.held_token = token_to
        
        if amount_to > self.top.get(token_to, 0):
            self.top[token_to] = amount_to
        
        if self.baseline.get(token_to, 0) == 0:
            self.baseline[token_to] = amount_to
        
        swap = {
            "tick": self.tick,
            "timestamp": datetime.now().isoformat(),
            "token_from": token_from,
            "token_to": token_to,
            "amount_from": amount_from,
            "amount_to": amount_to,
            "price_from": price_from,
            "price_to": price_to,
            "fee": usd - usd_after,
            "threshold": self.threshold
        }
        self.swap_history.append(swap)
        self.total_swaps += 1
        
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute("""INSERT INTO swaps (session_id, tick, timestamp, token_from, token_to, amount_from, amount_to, price_from, price_to, fee, threshold)
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                  (self.session_id, swap["tick"], swap["timestamp"], swap["token_from"], swap["token_to"],
                   swap["amount_from"], swap["amount_to"], swap["price_from"], swap["price_to"], swap["fee"], swap["threshold"]))
        c.execute("UPDATE sessions SET total_swaps=? WHERE id=?", (self.total_swaps, self.session_id))
        conn.commit()
        conn.close()
    
    def _save_tick(self):
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute("""INSERT INTO ticks (session_id, tick, timestamp, prices, holdings, top, baseline)
                      VALUES (?, ?, ?, ?, ?, ?, ?)""",
                  (self.session_id, self.tick, datetime.now().isoformat(),
                   json.dumps(self.prices), json.dumps(self.holdings),
                   json.dumps(self.top), json.dumps(self.baseline)))
        c.execute("UPDATE sessions SET tick=? WHERE id=?", (self.tick, self.session_id))
        conn.commit()
        conn.close()
        
        global tick_history
        tick_history.append({
            "tick": self.tick,
            "timestamp": datetime.now().isoformat(),
            "prices": {t: round(self.prices[t]["price"], 2) for t in TOKENS}
        })
        if len(tick_history) > 100:
            tick_history = tick_history[-100:]
    
    def _run_backtest(self):
        global backtest_results
        
        if self.tick < 10:
            return
        
        conn = sqlite3.connect(app.config['DATABASE'])
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT tick, prices, holdings, top FROM ticks WHERE session_id=? ORDER BY tick", (self.session_id,))
        ticks = [dict(row) for row in c.fetchall()]
        conn.close()
        
        if len(ticks) < 10:
            return
        
        for thresh in [round(x * 0.1, 1) for x in range(1, 101)]:
            result = self._simulate_backtest(thresh, ticks)
            backtest_results[thresh] = result
    
    def _simulate_backtest(self, threshold, ticks):
        first = json.loads(ticks[0]["holdings"])
        held_token = max(first.items(), key=lambda x: x[1])[0] if first else "BTC"
        held_amount = first.get(held_token, 1)
        
        current_held = held_token
        current_amount = held_amount
        swaps = 0
        
        for i in range(1, len(ticks)):
            prices = json.loads(ticks[i]["prices"])
            
            current_price = prices.get(current_held, {}).get("price", 1)
            current_value = current_amount * current_price
            
            best_target = None
            best_gain = -999
            
            for token in TOKENS:
                if token == current_held:
                    continue
                token_price = prices.get(token, {}).get("price", 0)
                if token_price <= 0:
                    continue
                
                usd = current_amount * current_price * (1 - FEE)
                amount_to = usd * (1 - FEE) / token_price
                value_to = amount_to * token_price
                gain_pct = (value_to / current_value - 1) * 100
                
                if gain_pct > best_gain:
                    best_gain = gain_pct
                    best_target = token
            
            if best_target and best_gain <= -threshold:
                token_price = prices.get(best_target, {}).get("price", 0)
                if token_price > 0:
                    usd = current_amount * current_price * (1 - FEE)
                    current_amount = usd * (1 - FEE) / token_price
                    current_held = best_target
                    swaps += 1
        
        final_prices = json.loads(ticks[-1]["prices"])
        final_price = final_prices.get(current_held, {}).get("price", 1)
        final_value = current_amount * final_price
        
        first_prices = json.loads(ticks[0]["prices"])
        first_price = first_prices.get(held_token, {}).get("price", 1)
        initial_value = held_amount * first_price
        
        gain_pct = round((final_value / initial_value - 1) * 100, 2) if initial_value > 0 else 0
        
        return {"final_value": round(final_value, 2), "swaps": swaps, "gain_pct": gain_pct}
    
    def get_state(self):
        if not self.prices:
            self._init_prices()
        
        tokens = {}
        held_price = self.prices.get(self.held_token, {}).get("price", 1)
        held_amount = self.holdings.get(self.held_token, 0)
        held_value = held_amount * held_price * (1 - FEE)
        
        for token in TOKENS:
            price = self.prices.get(token, {}).get("price", 0)
            
            if token == self.held_token:
                actual = held_amount
            else:
                if price > 0 and held_value > 0:
                    actual = held_value / price * (1 - FEE)
                else:
                    actual = 0
            
            top = self.top.get(token, actual)
            baseline = self.baseline.get(token, actual)
            
            gain_top = round((actual / top - 1) * 100, 2) if top > 0 else 0
            gain_base = round((actual / baseline - 1) * 100, 2) if baseline > 0 else 0
            
            tokens[token] = {
                "actual": round(actual, 6),
                "top": round(top, 6),
                "baseline": round(baseline, 6),
                "gain_top": gain_top,
                "gain_global": gain_base,
                "price": round(price, 2),
                "is_held": token == self.held_token,
                "holding": self.holdings.get(token, 0)
            }
        
        sorted_tokens = sorted(TOKENS, key=lambda t: tokens[t]["actual"], reverse=True)
        for i, token in enumerate(sorted_tokens):
            tokens[token]["rank"] = i + 1
        
        return {
            "session_id": self.session_id,
            "tick": self.tick,
            "held_token": self.held_token,
            "threshold": self.threshold,
            "status": self.status,
            "is_running": self.status == "running",
            "total_swaps": self.total_swaps,
            "tokens": {t: tokens[t] for t in sorted_tokens},
            "swaps": self.swap_history[-10:] if self.swap_history else []
        }

# Initialize
init_db()
state = MatrixState()

# Routes
@app.route('/')
def index():
    return render_template('matrix.html')

@app.route('/api/export')
def export_data():
    conn = sqlite3.connect(app.config['DATABASE'])
    c = conn.cursor()
    
    c.execute("SELECT * FROM sessions ORDER BY id DESC LIMIT 1")
    session = dict(c.fetchone())
    
    c.execute("SELECT * FROM swaps WHERE session_id=? ORDER BY tick", (session['id'],))
    swaps = [dict(row) for row in c.fetchall()]
    
    c.execute("SELECT * FROM ticks WHERE session_id=? ORDER BY tick", (session['id'],))
    ticks = [dict(row) for row in c.fetchall()]
    
    conn.close()
    
    return jsonify({"session": session, "swaps": swaps, "ticks": ticks})

@app.route('/api/ticks')
def get_ticks():
    global tick_history
    return jsonify({"ticks": tick_history[-50:]})

@app.route('/api/backtest_results')
def get_backtest():
    global backtest_results
    sorted_results = sorted(backtest_results.items(), key=lambda x: x[1].get("gain_pct", 0), reverse=True)
    return jsonify({"results": dict(sorted_results), "best": sorted_results[0] if sorted_results else (None, {})})

# Socket events
@socketio.on('connect')
def on_connect():
    emit('init', state.get_state())

@socketio.on('initialize')
def on_initialize(data):
    result = state.initialize(data.get("held_token") if data else None, data.get("threshold") if data else None, data.get("hold_amount") if data else None)
    emit('update', result)

@socketio.on('start')
def on_start():
    emit('update', state.start())

@socketio.on('stop')
def on_stop():
    emit('update', state.stop())

@socketio.on('restart')
def on_restart():
    emit('update', state.restart())

@socketio.on('set_threshold')
def on_set_threshold(data):
    emit('update', state.set_threshold(data.get("threshold")))

@socketio.on('tick')
def on_tick():
    emit('update', state.tick_update())

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
