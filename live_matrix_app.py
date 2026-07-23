"""
Live Matrix v2 - Token Monitor with DB & Swap Logic
- 50 tokens displaying real-time equity, updates every second
- Baseline saved on RUN
- Top EQ tracked per token (max achieved)
- Actual EQ = owned token + theoretical holdings from swapping
- Fee on buy (FEE1) and swap (FEE2)
"""
import random
import time
import threading
import sqlite3
import json
from datetime import datetime
from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'live-matrix-secret'
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

FEE_BUY = 0.001   # 0.1% fee on buy
FEE_SWAP = 0.001  # 0.1% fee on swap

def init_db():
    """Initialize database with schema."""
    conn = sqlite3.connect(app.config['DATABASE'])
    c = conn.cursor()
    
    # Tick history
    c.execute('''CREATE TABLE IF NOT EXISTS ticks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tick INTEGER NOT NULL,
        timestamp TEXT NOT NULL,
        total_eq REAL NOT NULL,
        baseline_eq REAL,
        top_total_eq REAL,
        gain_global REAL,
        data TEXT NOT NULL
    )''')
    
    # Swaps history
    c.execute('''CREATE TABLE IF NOT EXISTS swaps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tick INTEGER NOT NULL,
        timestamp TEXT NOT NULL,
        token_from TEXT NOT NULL,
        token_to TEXT NOT NULL,
        amount_from REAL NOT NULL,
        amount_to REAL NOT NULL,
        price_from REAL NOT NULL,
        price_to REAL NOT NULL,
        fee_paid REAL NOT NULL,
        top_from REAL NOT NULL,
        top_to REAL NOT NULL
    )''')
    
    conn.commit()
    conn.close()

class LiveMatrix:
    def __init__(self):
        self.is_running = False
        self.baseline_eq = None
        self.tick = 0
        self.prices = {}
        self.holdings = {}  # How many of each token we own
        self.top_eq = {}    # Top value ever achieved per token (in USD)
        self.swap_history = []
        self.last_swap_token = None  # Track which token we last held
        self.init_prices()  # Initialize immediately
        
    def init_prices(self):
        """Initialize prices and holdings."""
        self.prices = {}
        for token in TOKENS:
            self.prices[token] = {
                "price": round(random.uniform(0.01, 50000), 4),
                "volatility": random.uniform(0.005, 0.03)
            }
            # Start with equal USD value in each token
            usd_value = 1000
            self.holdings[token] = usd_value / self.prices[token]["price"]
            # Initialize top as current value
            self.top_eq[token] = usd_value
        
        # Start holding USDT equivalent
        self.holdings["USDT"] = 50000
        self.top_eq["USDT"] = 50000
        self.last_swap_token = "USDT"
    
    def get_actual_eq(self):
        """
        Calculate actual equity based on what we currently hold.
        - Actual eq = our holdings value in USD
        - For each token: top = max USD value ever held
        - Gain from top = (current / top - 1) * 100
        """
        results = {}
        
        # Our actual USD value from what we hold
        actual_total = 0
        held_token = None
        
        for token in TOKENS + ["USDT"]:
            amount = self.holdings.get(token, 0)
            price = self.prices.get(token, {}).get("price", 1)
            value = amount * price
            actual_total += value
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
        
        # Calculate gains from top
        for token, data in results.items():
            if data["top"] > 0:
                data["gain_top"] = round((data["actual"] / data["top"] - 1) * 100, 2)
        
        # If no token held, show USDT as held
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
        
        # Sort by actual value for ranking
        sorted_tokens = sorted(
            [(t, d) for t, d in results.items() if t != "USDT"],
            key=lambda x: x[1]["actual"],
            reverse=True
        )
        
        for i, (token, data) in enumerate(sorted_tokens):
            data["rank"] = i + 1
        
        # Add USDT at the end
        if "USDT" in results:
            results["USDT"]["rank"] = len(sorted_tokens) + 1
        
        return results, actual_total
    
    def update_prices(self):
        """Update prices with random walk."""
        for token in TOKENS:
            change = random.gauss(0, self.prices[token]["volatility"])
            self.prices[token]["price"] *= (1 + change)
            self.prices[token]["price"] = max(0.0001, self.prices[token]["price"])
        
        # Update top for held tokens based on current value
        results, _ = self.get_actual_eq()
        for token, data in results.items():
            if data["actual"] > data["top"]:
                self.top_eq[token] = data["actual"]
    
    def simulate_swap(self, token_from, token_to):
        """
        Simulate a swap: sell token_from to buy token_to
        - FEE 1: paid when buying the output token
        - FEE 2: paid during the swap itself
        """
        amount_from = self.holdings.get(token_from, 0)
        if amount_from <= 0:
            return None
        
        price_from = self.prices[token_from]["price"]
        price_to = self.prices[token_to]["price"]
        
        # Value in USD before fees
        usd_value = amount_from * price_from
        
        # Fee 1: buy fee (0.1%)
        usd_after_fee1 = usd_value * (1 - FEE_BUY)
        
        # Fee 2: swap fee (0.1%)
        usd_after_fees = usd_after_fee1 * (1 - FEE_SWAP)
        
        # How much token_to we get
        amount_to = usd_after_fees / price_to
        
        # Calculate value during swap (after fees applied but before price changes)
        value_during_swap = amount_to * price_to
        
        # Old top for token_from (in USD)
        old_top_from = self.top_eq.get(token_from, 0)
        
        # Check if we should update top for token_from
        # We spent it, so check if the value we had was a new record
        # Actually, top tracks max USD value ever held
        # We already held amount_from * price_from, so if this was a record, it was already set
        
        # Update holdings
        self.holdings[token_from] = 0
        self.holdings[token_to] = self.holdings.get(token_to, 0) + amount_to
        self.last_swap_token = token_to
        
        # Update top for token_to
        # Top should be max of: old top OR value during swap
        old_top_to = self.top_eq.get(token_to, 0)
        if value_during_swap > old_top_to:
            self.top_eq[token_to] = value_during_swap
        
        # Check if we should update top for other tokens
        # During the swap, all tokens have some theoretical value
        # We only update if we achieved a new record
        
        # Record swap
        swap_record = {
            "tick": self.tick,
            "token_from": token_from,
            "token_to": token_to,
            "amount_from": round(amount_from, 8),
            "amount_to": round(amount_to, 8),
            "price_from": round(price_from, 4),
            "price_to": round(price_to, 4),
            "fee": round(usd_value - usd_after_fees, 2),
            "top_from_before": round(old_top_from, 2),
            "top_to_before": round(old_top_to, 2),
            "top_to_after": round(self.top_eq.get(token_to, 0), 2)
        }
        self.swap_history.append(swap_record)
        
        # Save to DB
        self.save_swap(swap_record)
        
        return swap_record
    
    def auto_swap(self):
        """Automatically find and execute best swaps based on top EQ."""
        results, _ = self.get_actual_eq()
        
        # Find tokens with negative gain from top (underwater)
        underwater = [(t, d) for t, d in results.items() 
                      if t != "USDT" and d["gain_top"] < -5]
        
        if not underwater:
            return None
        
        # Sort by most negative (worst performers)
        underwater.sort(key=lambda x: x[1]["gain_top"])
        
        # Sell the worst performer
        token_from = underwater[0][0]
        
        # Find a good target - prefer tokens with positive gain or less underwater
        # Also consider tokens where we'd get a new top
        potential_targets = []
        for token in TOKENS + ["USDT"]:
            if token == token_from:
                continue
            price_to = self.prices.get(token, {}).get("price", 1)
            amount_from = self.holdings.get(token_from, 0)
            price_from = self.prices[token_from]["price"]
            
            if amount_from <= 0 or price_to <= 0:
                continue
            
            # Calculate how much we'd get
            usd_value = amount_from * price_from * (1 - FEE_BUY) * (1 - FEE_SWAP)
            amount_to = usd_value / price_to
            value_after_swap = amount_to * price_to
            
            current_top = self.top_eq.get(token, 0)
            
            # Score: prefer tokens where we'd get a new top or already have positive gain
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
        
        # Prefer targets that give us a new top, then by current gain
        potential_targets.sort(key=lambda x: (-int(x["new_top"]), -x["current_gain"]))
        
        token_to = potential_targets[0]["token"]
        
        return self.simulate_swap(token_from, token_to)
    
    def tick_update(self):
        """Update all tokens on each tick."""
        self.tick += 1
        self.update_prices()
        
        # Auto-swap logic (every 5 ticks)
        if self.tick % 5 == 0:
            swap = self.auto_swap()
        
        # Get current state
        data = self.get_matrix_data()
        
        # Save to DB
        self.save_tick(data)
        
        return data
    
    def get_matrix_data(self):
        """Get current matrix state."""
        results, total_eq = self.get_actual_eq()
        
        # Sort by rank
        sorted_items = sorted(
            [(t, d) for t, d in results.items() if t != "USDT"],
            key=lambda x: x[1]["rank"]
        )
        
        # Calculate global gain
        gain_global = 0
        if self.baseline_eq:
            gain_global = round((total_eq / self.baseline_eq - 1) * 100, 2)
        
        return {
            "tick": self.tick,
            "baseline_eq": self.baseline_eq,
            "actual_eq": round(total_eq, 2),
            "gain_global": gain_global,
            "top_total": round(sum(self.top_eq.get(t, 0) for t in TOKENS + ["USDT"]), 2),
            "is_running": self.is_running,
            "prices": {t: round(self.prices[t]["price"], 4) for t in TOKENS},
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
            "swaps": self.swap_history[-10:] if self.swap_history else []
        }
    
    def start(self):
        """Start the matrix."""
        self.init_prices()
        self.is_running = True
        self.tick = 0
        self.swap_history = []
        # Save baseline
        data = self.get_matrix_data()
        self.baseline_eq = round(data["actual_eq"], 2)
        data["baseline_eq"] = self.baseline_eq
        return data
    
    def stop(self):
        """Stop the matrix."""
        self.is_running = False
        return self.get_matrix_data()
    
    def reset(self):
        """Reset the matrix."""
        self.baseline_eq = None
        self.tick = 0
        self.swap_history = []
        self.init_prices()
        return self.get_matrix_data()
    
    def save_tick(self, data):
        """Save tick to database."""
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute('''INSERT INTO ticks (tick, timestamp, total_eq, baseline_eq, top_total_eq, gain_global, data)
                     VALUES (?, ?, ?, ?, ?, ?, ?)''',
                  (data["tick"], datetime.now().isoformat(), data["actual_eq"], 
                   self.baseline_eq, data["top_total"], data["gain_global"],
                   json.dumps(data["tokens"])))
        conn.commit()
        conn.close()
    
    def save_swap(self, swap):
        """Save swap to database."""
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute('''INSERT INTO swaps (tick, timestamp, token_from, token_to, amount_from, amount_to,
                     price_from, price_to, fee_paid, top_from, top_to)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (swap["tick"], datetime.now().isoformat(), swap["token_from"], swap["token_to"],
                   swap["amount_from"], swap["amount_to"], swap["price_from"], swap["price_to"],
                   swap["fee"], swap["top_from_before"], swap["top_to_after"]))
        conn.commit()
        conn.close()
    
    def export_history(self):
        """Export full history as JSON."""
        conn = sqlite3.connect(app.config['DATABASE'])
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        ticks = [dict(row) for row in c.execute('SELECT * FROM ticks ORDER BY tick')]
        swaps = [dict(row) for row in c.execute('SELECT * FROM swaps ORDER BY id')]
        
        conn.close()
        return {"ticks": ticks, "swaps": swaps}


# Initialize DB
init_db()

# Global instance
matrix = LiveMatrix()

@app.route('/')
def index():
    return render_template('live_matrix.html')

@app.route('/api/export')
def export_data():
    return jsonify(matrix.export_history())

@socketio.on('connect')
def on_connect():
    emit('init', matrix.get_matrix_data())

@socketio.on('run')
def on_run():
    data = matrix.start()
    emit('update', data)

@socketio.on('stop')
def on_stop():
    data = matrix.stop()
    emit('update', data)

@socketio.on('reset')
def on_reset():
    data = matrix.reset()
    emit('update', data)

def run_ticks():
    """Background task to emit ticks."""
    while True:
        if matrix.is_running:
            data = matrix.tick_update()
            socketio.emit('update', data)
        time.sleep(1)

if __name__ == '__main__':
    thread = threading.Thread(target=run_ticks, daemon=True)
    thread.start()
    socketio.run(app, host='0.0.0.0', port=12000, debug=False, allow_unsafe_werkzeug=True)
