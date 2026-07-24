"""
Backtester - Token swapping strategy simulator
Uses MEXC API for real bid/ask prices
"""
import os
import json
import random
import sqlite3
import requests
from datetime import datetime
from flask import Flask, render_template, jsonify, request

app = Flask(__name__)
app.config['DATABASE'] = 'backtest.db'

# Top 50 tokens by volume
TOKENS = ["BTC", "ETH", "BNB", "XRP", "SOL", "ADA", "DOGE", "AVAX", "DOT", "LINK",
          "MATIC", "SHIB", "LTC", "UNI", "ATOM", "XLM", "ETC", "FIL", "APT", "ARJ",
          "VET", "HBAR", "ICP", "EGLD", "SAND", "MANA", "AXS", "THETA", "AAVE", "FTM",
          "CRO", "NEAR", "ALGO", "QNT", "EOS", "XTZ", "FLOW", "CHZ", "APE", "ZIL",
          "ENJ", "WAXP", "BAT", "1INCH", "COMP", "MKR", "SNX", "CRV", "LDO", "RPL"]

FEE = 0.0004  # 0.04% fee per trade (MEXC market order), 0.08% total per swap
DEFAULT_HOLD = 1.0
DEFAULT_THRESHOLD = 1.0

def init_db():
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
        fee_paid REAL NOT NULL,
        threshold REAL NOT NULL,
        gain_pct REAL NOT NULL
    )''')
    
    conn.commit()
    conn.close()


class BacktestState:
    def __init__(self):
        self.session_id = None
        self.held_token = None
        self.hold_amount = DEFAULT_HOLD
        self.threshold = DEFAULT_THRESHOLD
        self.status = "uninitialized"
        self.holdings = {}
        self.baseline = {}
        self.top = {}
        self.baseline_prices = {}  # Store prices at initialization
        self.prices = {}
        self.tick = 0
        self.total_swaps = 0
        self.swap_history = []
        self.total_ticks = 0
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
            self.holdings = json.loads(row[6]) if row[6] else {}
            self.baseline = json.loads(row[7]) if row[7] else {}
            self.top = json.loads(row[8]) if row[8] else {}
            self.tick = row[9]
            self.total_swaps = row[10]
            
            c.execute("SELECT prices FROM ticks WHERE session_id=? ORDER BY tick DESC LIMIT 1", (self.session_id,))
            tick_row = c.fetchone()
            if tick_row:
                self.prices = json.loads(tick_row[0])
            
            c.execute("SELECT COUNT(*) FROM ticks")
            self.total_ticks = c.fetchone()[0] or 0
            
            c.execute("SELECT * FROM swaps WHERE session_id=? ORDER BY tick", (self.session_id,))
            for s in c.fetchall():
                self.swap_history.append({
                    "tick": s[2], "timestamp": s[3], "token_from": s[4], "token_to": s[5],
                    "amount_from": s[6], "amount_to": s[7], "price_from": s[8], "price_to": s[9],
                    "fee_paid": s[10], "threshold": s[11], "gain_pct": s[12]
                })
        else:
            self._create_session()
        
        conn.close()
    
    def _create_session(self):
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute("""INSERT INTO sessions (created_at, held_token, hold_amount, threshold, status, holdings, baseline, top, tick, total_swaps)
                      VALUES (?, ?, ?, ?, 'uninitialized', '{}', '{}', '{}', 0, 0)""",
                  (datetime.now().isoformat(), "BTC", DEFAULT_HOLD, self.threshold))
        self.session_id = c.lastrowid
        conn.commit()
        conn.close()
    
    def _fetch_prices_mexc(self):
        """Fetch prices from MEXC 24hr API (includes bid/ask)"""
        prices = {}
        
        try:
            url = "https://api.mexc.com/api/v3/ticker/24hr"
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                for item in data:
                    symbol = item.get('symbol', '')
                    if not symbol.endswith('USDT'):
                        continue
                    
                    token = symbol[:-4]
                    if token not in TOKENS:
                        continue
                    
                    bid = float(item.get('bidPrice', 0))
                    ask = float(item.get('askPrice', 0))
                    last = float(item.get('lastPrice', 0))
                    
                    if bid > 0 and ask > 0:
                        prices[token] = {
                            "bid": bid,
                            "ask": ask,
                            "last": last
                        }
        except Exception as e:
            print(f"MEXC API error: {e}")
        
        for token in TOKENS:
            if token not in prices:
                prices[token] = self._get_fallback_price(token)
        
        return prices
    
    def _get_fallback_price(self, token):
        fallbacks = {
            "BTC": 65000, "ETH": 1880, "BNB": 580, "XRP": 0.52, "SOL": 145,
            "ADA": 0.45, "DOGE": 0.08, "AVAX": 35, "DOT": 7, "LINK": 15,
            "MATIC": 0.55, "SHIB": 0.000008, "LTC": 70, "UNI": 7, "ATOM": 9,
            "XLM": 0.11, "ETC": 20, "FIL": 5, "APT": 8, "ARJ": 0.8,
            "VET": 0.02, "HBAR": 0.07, "ICP": 10, "EGLD": 30, "SAND": 0.4,
            "MANA": 0.35, "AXS": 7, "THETA": 1, "AAVE": 80, "FTM": 0.3,
            "CRO": 0.08, "NEAR": 5, "ALGO": 0.15, "QNT": 100, "EOS": 0.7,
            "XTZ": 0.9, "FLOW": 0.7, "CHZ": 0.06, "APE": 1.2, "ZIL": 0.02,
            "ENJ": 0.3, "WAXP": 0.05, "BAT": 0.2, "1INCH": 0.25, "COMP": 50,
            "MKR": 1500, "SNX": 2.5, "CRV": 0.5, "LDO": 2, "RPL": 25
        }
        base = fallbacks.get(token, 10)
        spread = base * 0.001
        return {"bid": base - spread, "ask": base + spread, "last": base}
    
    def _calculate_equivalent(self, from_token, to_token, amount, prices):
        """Calculate equivalent with proper fee handling"""
        from_price = prices.get(from_token, {}).get('bid', 0)
        to_price = prices.get(to_token, {}).get('ask', 0)
        
        if from_price <= 0 or to_price <= 0 or amount <= 0:
            return 0
        
        usdt_before_fee = amount * from_price
        usdt_after_sell = usdt_before_fee * (1 - FEE)
        tokens_before_fee = usdt_after_sell / to_price
        tokens_after_fee = tokens_before_fee * (1 - FEE)
        
        return tokens_after_fee
    
    def initialize(self, held_token=None, threshold=None, hold_amount=None):
        # Handle both comma and dot as decimal separator
        if threshold:
            if isinstance(threshold, str):
                threshold = threshold.replace(',', '.')
            self.threshold = float(threshold)
        
        if held_token and held_token in TOKENS:
            self.held_token = held_token
        else:
            self.held_token = "BTC"
        
        if hold_amount:
            if isinstance(hold_amount, str):
                hold_amount = hold_amount.replace(',', '.')
            self.hold_amount = float(hold_amount)
        
        self.prices = self._fetch_prices_mexc()
        
        self.holdings = {token: 0 for token in TOKENS}
        self.holdings[self.held_token] = self.hold_amount
        
        for token in TOKENS:
            if token == self.held_token:
                self.baseline[token] = self.hold_amount
                self.top[token] = self.hold_amount
            else:
                equiv = self._calculate_equivalent(
                    self.held_token, token, self.hold_amount, self.prices
                )
                self.baseline[token] = equiv
                self.top[token] = equiv
        
        # Save baseline prices for gain calculation
        self.baseline_prices = {token: self.prices.get(token, {}).get('bid', 0) for token in TOKENS}
        
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
        
        self._save_tick()
        
        return self.get_state()
    
    def start(self):
        if self.status != "initialized" and self.status != "stopped":
            return self.get_state()
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
        
        c.execute("""UPDATE sessions SET held_token='BTC', hold_amount=?, threshold=?, status='uninitialized', 
                      holdings='{}', baseline='{}', top='{}', tick=0, total_swaps=0 WHERE id=?""",
                  (DEFAULT_HOLD, self.threshold, self.session_id))
        
        conn.commit()
        conn.close()
        
        self.held_token = "BTC"
        self.hold_amount = DEFAULT_HOLD
        self.status = "uninitialized"
        self.holdings = {}
        self.baseline = {}
        self.top = {}
        self.baseline_prices = {}
        self.prices = {}
        self.tick = 0
        self.total_swaps = 0
        self.swap_history = []
        self.total_ticks = 0
        
        return self.get_state()
    
    def set_threshold(self, threshold):
        # Handle both comma and dot as decimal separator
        if isinstance(threshold, str):
            threshold = threshold.replace(',', '.')
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
        self.total_ticks += 1
        
        self.prices = self._fetch_prices_mexc()
        
        self._try_swap()
        
        self._save_tick()
        
        return self.get_state()
    
    def _try_swap(self):
        """Check if we should swap based on gain_top of any token"""
        if not self.held_token:
            return
        
        held = self.held_token
        held_amount = self.holdings.get(held, 0)
        
        if held_amount <= 0:
            return
        
        held_price_bid = self.prices.get(held, {}).get('bid', 0)
        if held_price_bid <= 0:
            return
        
        # Update top for held token
        self.top[held] = held_amount
        
        # Find best target: token with highest gain_top >= threshold
        best_target = None
        best_gain = -999
        
        for token in TOKENS:
            # Calculate actual equivalent if we swapped to this token
            equiv = self._calculate_equivalent(held, token, held_amount, self.prices)
            
            # Get baseline for this token
            baseline = self.baseline.get(token, equiv)
            
            # Calculate gain_top (gain from baseline)
            if baseline > 0:
                gain_pct = (equiv / baseline - 1) * 100
            else:
                gain_pct = 0
            
            # Check if gain >= threshold and this is the best so far
            if gain_pct >= self.threshold and gain_pct > best_gain:
                best_gain = gain_pct
                best_target = token
        

        
        # Swap if we found a target with gain >= threshold
        if best_target:
            self._execute_swap(held, best_target, held_price_bid)
    
    def _execute_swap(self, token_from, token_to, price_from):
        amount_from = self.holdings.get(token_from, 0)
        if amount_from <= 0:
            return
        
        price_to = self.prices.get(token_to, {}).get('ask', 0)
        if price_to <= 0:
            return
        
        # Calculate amount received with proper fee handling
        usd_before_fee = amount_from * price_from
        usd_after_sell = usd_before_fee * (1 - FEE)
        tokens_before_fee = usd_after_sell / price_to
        amount_to = tokens_before_fee * (1 - FEE)
        total_fee = usd_before_fee - usd_after_sell + usd_after_sell - amount_to * price_to
        
        # Update holdings
        self.holdings[token_from] = 0
        self.holdings[token_to] = amount_to
        self.held_token = token_to
        
        # Update Top values - key logic:
        # 1. Top of token_from stays the same (we gave away at previous top)
        # 2. Top of token_to = max(old top, new amount received)
        # 3. For all other tokens: if equivalent > current top, update top
        
        # Update all token tops based on new held amount
        for token in TOKENS:
            if token == token_to:
                # For received token: update if we got more than before
                if amount_to > self.top.get(token, 0):
                    self.top[token] = amount_to
            elif token == token_from:
                # For sent token: top stays the same
                pass
            else:
                # For other tokens: update if equivalent > top
                equiv = self._calculate_equivalent(token_to, token, amount_to, self.prices)
                if equiv > self.top.get(token, 0):
                    self.top[token] = equiv
        
        # Calculate gain for the swap record
        new_value = amount_to * price_to
        old_value = amount_from * price_from
        if old_value > 0:
            gain_pct = (new_value / old_value - 1) * 100
        else:
            gain_pct = 0
        
        swap = {
            "tick": self.tick,
            "timestamp": datetime.now().isoformat(),
            "token_from": token_from,
            "token_to": token_to,
            "amount_from": amount_from,
            "amount_to": amount_to,
            "price_from": price_from,
            "price_to": price_to,
            "fee_paid": total_fee,
            "threshold": self.threshold,
            "gain_pct": round(gain_pct, 2)
        }
        
        self.swap_history.append(swap)
        self.total_swaps += 1
        
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute("""INSERT INTO swaps (session_id, tick, timestamp, token_from, token_to, amount_from, amount_to, price_from, price_to, fee_paid, threshold, gain_pct)
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                  (self.session_id, swap["tick"], swap["timestamp"], swap["token_from"], swap["token_to"],
                   swap["amount_from"], swap["amount_to"], swap["price_from"], swap["price_to"],
                   swap["fee_paid"], swap["threshold"], swap["gain_pct"]))
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
    
    def get_state(self):
        if not self.prices:
            for token in TOKENS:
                self.prices[token] = self._get_fallback_price(token)
        
        tokens = {}
        held_price = self.prices.get(self.held_token, {}).get('bid', 0)
        held_amount = self.holdings.get(self.held_token, 0)
        
        for token in TOKENS:
            price_data = self.prices.get(token, {})
            bid = price_data.get('bid', 0)
            
            if token == self.held_token:
                actual = held_amount
                # For held token, gain_top is 0 because actual = top (after swap)
                # We just got this amount, so we haven't lost any equivalent value
                top_amount = self.top.get(token, actual)
                gain_top = round((actual / top_amount - 1) * 100, 2) if top_amount > 0 else 0
            else:
                actual = self._calculate_equivalent(
                    self.held_token, token, held_amount, self.prices
                )
                # For non-held tokens, gain_top is relative to their own top
                top_amount = self.top.get(token, actual)
                gain_top = round((actual / top_amount - 1) * 100, 2) if top_amount > 0 else 0
            
            baseline = self.baseline.get(token, actual)
            top = self.top.get(token, baseline)
            
            gain_baseline = round((actual / baseline - 1) * 100, 2) if baseline > 0 else 0
            
            tokens[token] = {
                "actual": actual,
                "top": top,
                "baseline": baseline,
                "gain_top": gain_top,
                "gain_baseline": gain_baseline,
                "price": price_data.get('last', 0),
                "is_held": token == self.held_token,
                "holding": self.holdings.get(token, 0)
            }
        
        # Get sort_by from request
        sort_by = "actual"  # default
        
        if sort_by == "gain_top":
            sorted_tokens = sorted(TOKENS, key=lambda t: tokens[t]["gain_top"], reverse=True)
        elif sort_by == "gain_baseline":
            sorted_tokens = sorted(TOKENS, key=lambda t: tokens[t]["gain_baseline"], reverse=True)
        elif sort_by == "price":
            sorted_tokens = sorted(TOKENS, key=lambda t: tokens[t]["price"], reverse=True)
        else:  # actual (default)
            sorted_tokens = sorted(TOKENS, key=lambda t: tokens[t]["actual"], reverse=True)
        for i, token in enumerate(sorted_tokens):
            tokens[token]["rank"] = i + 1
        
        portfolio = {}
        if self.status in ["initialized", "running", "stopped"] and self.held_token:
            held = self.held_token
            held_baseline = self.baseline.get(held, self.hold_amount)
            gain_baseline = round((held_amount / held_baseline - 1) * 100, 2) if held_baseline > 0 else 0
            
            portfolio = {
                "token": held,
                "amount": held_amount,
                "gain_baseline": gain_baseline
            }
        
        return {
            "status": self.status,
            "tick": self.tick,
            "total_ticks": self.total_ticks,
            "held_token": self.held_token,
            "threshold": self.threshold,
            "is_running": self.status == "running",
            "total_swaps": self.total_swaps,
            "portfolio": portfolio,
            "tokens": {t: tokens[t] for t in sorted_tokens},
            "swaps": self.swap_history[-20:] if self.swap_history else []
        }


init_db()
state = BacktestState()

@app.route('/')
def index():
    return render_template('backtest.html')

@app.route('/api/state')
def get_state():
    return jsonify(state.get_state())

@app.route('/api/initialize', methods=['POST'])
def initialize():
    data = request.json or {}
    return jsonify(state.initialize(
        data.get("held_token", "BTC"),
        data.get("threshold", DEFAULT_THRESHOLD),
        data.get("hold_amount", DEFAULT_HOLD)
    ))

@app.route('/api/start', methods=['POST'])
def start():
    return jsonify(state.start())

@app.route('/api/stop', methods=['POST'])
def stop():
    return jsonify(state.stop())

@app.route('/api/restart', methods=['POST'])
def restart():
    return jsonify(state.restart())

@app.route('/api/set_threshold', methods=['POST'])
def set_threshold():
    data = request.json or {}
    return jsonify(state.set_threshold(data.get("threshold", DEFAULT_THRESHOLD)))

@app.route('/api/tick', methods=['POST'])
def tick():
    return jsonify(state.tick_update())

@app.route('/api/ticks')
def get_ticks():
    conn = sqlite3.connect(app.config['DATABASE'])
    c = conn.cursor()
    c.execute("SELECT tick, timestamp, prices FROM ticks WHERE session_id=? ORDER BY tick DESC LIMIT 50", (state.session_id,))
    ticks = []
    for row in c.fetchall():
        prices = json.loads(row[2]) if row[2] else {}
        sample = {t: prices[t] for t in list(prices.keys())[:5]} if prices else {}
        ticks.append({
            "tick": row[0],
            "timestamp": row[1],
            "sample_prices": sample
        })
    conn.close()
    return jsonify({"ticks": ticks})

@app.route('/api/swaps')
def get_swaps():
    conn = sqlite3.connect(app.config['DATABASE'])
    c = conn.cursor()
    c.execute("SELECT * FROM swaps WHERE session_id=? ORDER BY tick", (state.session_id,))
    swaps = []
    for row in c.fetchall():
        swaps.append({
            "tick": row[2],
            "timestamp": row[3],
            "token_from": row[4],
            "token_to": row[5],
            "amount_from": row[6],
            "amount_to": row[7],
            "price_from": row[8],
            "price_to": row[9],
            "fee_paid": row[10],
            "gain_pct": row[12]
        })
    conn.close()
    return jsonify({"swaps": swaps})

@app.route('/api/extra_backtest', methods=['POST'])
def run_extra_backtest():
    """Run backtest with different thresholds using saved tick data"""
    data = request.json or {}
    start_threshold = float(data.get("start", 0.01))
    end_threshold = float(data.get("end", 10.0))
    step = float(data.get("step", 0.01))
    
    # Get all saved ticks
    conn = sqlite3.connect(app.config['DATABASE'])
    c = conn.cursor()
    c.execute("SELECT tick, prices, holdings, top, baseline FROM ticks WHERE session_id=? ORDER BY tick", (state.session_id,))
    ticks_data = c.fetchall()
    conn.close()
    
    if not ticks_data:
        return jsonify({"error": "No tick data found. Run some ticks first."})
    
    results = []
    threshold = start_threshold
    
    while threshold <= end_threshold:
        # Simulate with this threshold
        holdings = {token: 0 for token in TOKENS}
        holdings[state.held_token] = state.hold_amount
        baseline = dict(state.baseline)
        top = dict(state.top)
        held_token = state.held_token
        total_swaps = 0
        final_value = 0
        
        for tick_row in ticks_data:
            tick_num = tick_row[0]
            prices = json.loads(tick_row[1])
            
            # Get held token amount
            held_amount = holdings.get(held_token, 0)
            if held_amount <= 0:
                continue
            
            held_price_bid = prices.get(held_token, {}).get('bid', 0)
            if held_price_bid <= 0:
                continue
            
            current_top = top.get(held_token, held_amount)
            
            # Calculate loss from top
            current_value = held_amount * held_price_bid
            if current_top > 0:
                top_value = current_top * held_price_bid
                loss_pct = (1 - current_value / top_value) * 100
            else:
                loss_pct = 0
            
            if loss_pct < threshold:
                continue
            
            # Find best target
            best_target = None
            best_gain = -999
            
            for token in TOKENS:
                if token == held_token:
                    continue
                
                token_ask = prices.get(token, {}).get('ask', 0)
                if token_ask <= 0:
                    continue
                
                # Calculate equivalent
                usd = held_amount * held_price_bid * (1 - FEE)
                equiv = (usd / token_ask) * (1 - FEE)
                
                # Calculate gain
                token_bid = prices.get(token, {}).get('bid', 0)
                if token_bid > 0:
                    new_value = equiv * token_bid * (1 - FEE)
                    old_value = held_amount * held_price_bid * (1 - FEE)
                    gain_pct = (new_value / old_value - 1) * 100
                    
                    if gain_pct > best_gain:
                        best_gain = gain_pct
                        best_target = token
            
            if best_target and best_gain > threshold:
                # Execute swap
                token_ask = prices[best_target]['ask']
                usd = held_amount * held_price_bid * (1 - FEE)
                amount_to = (usd / token_ask) * (1 - FEE)
                
                holdings[held_token] = 0
                holdings[best_target] = amount_to
                
                if amount_to > top.get(best_target, 0):
                    top[best_target] = amount_to
                
                held_token = best_target
                total_swaps += 1
        
        # Calculate final value
        final_held = holdings.get(held_token, 0)
        final_price = prices.get(held_token, {}).get('bid', 0)
        final_value = final_held * final_price * (1 - FEE) if final_price > 0 else 0
        
        # Calculate initial value
        initial_price = prices.get("BTC", {}).get('bid', 65000)
        initial_value = 1.0 * initial_price * (1 - FEE)
        
        total_gain = ((final_value / initial_value) - 1) * 100 if initial_value > 0 else 0
        
        results.append({
            "threshold": round(threshold, 2),
            "swaps": total_swaps,
            "final_value": round(final_value, 2),
            "total_gain_pct": round(total_gain, 2)
        })
        
        threshold += step
    
    return jsonify({"results": results})

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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
