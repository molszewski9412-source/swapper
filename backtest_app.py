"""
Backtester - Token swapping strategy simulator
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

# Top 50 tokens by volume (approximate)
TOKENS = ["BTC", "ETH", "BNB", "XRP", "SOL", "ADA", "DOGE", "AVAX", "DOT", "LINK",
          "MATIC", "SHIB", "LTC", "UNI", "ATOM", "XLM", "ETC", "FIL", "APT", "ARJ",
          "VET", "HBAR", "ICP", "EGLD", "SAND", "MANA", "AXS", "THETA", "AAVE", "FTM",
          "CRO", "NEAR", "ALGO", "QNT", "EOS", "XTZ", "FLOW", "CHZ", "APE", "ZIL",
          "ENJ", "WAXP", "BAT", "1INCH", "COMP", "MKR", "SNX", "CRV", "LDO", "RPL"]

FEE = 0.002  # 0.2% total (0.1% buy + 0.1% sell)
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
    # MEXC mapping for API
    MEXC_IDS = {t: f"{t}USDT" for t in TOKENS}
    
    def __init__(self):
        self.session_id = None
        self.held_token = None
        self.hold_amount = DEFAULT_HOLD
        self.threshold = DEFAULT_THRESHOLD
        self.status = "uninitialized"
        self.holdings = {}
        self.baseline = {}
        self.top = {}
        self.prices = {}
        self.tick = 0
        self.total_swaps = 0
        self.swap_history = []
        self.total_ticks = 0  # Global tick counter
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
    
    # CoinGecko IDs for price fetch
    COINGECKO_IDS = {
        "BTC": "bitcoin", "ETH": "ethereum", "BNB": "binancecoin", "XRP": "ripple",
        "SOL": "solana", "ADA": "cardano", "DOGE": "dogecoin", "AVAX": "avalanche-2",
        "DOT": "polkadot", "LINK": "chainlink", "MATIC": "matic-network", "SHIB": "shiba-inu",
        "LTC": "litecoin", "UNI": "uniswap", "ATOM": "cosmos", "XLM": "stellar",
        "ETC": "ethereum-classic", "FIL": "filecoin", "APT": "aptos", "ARJ": "airdao",
        "VET": "vechain", "HBAR": "hedera-hashgraph", "ICP": "internet-computer",
        "EGLD": "multiversx", "SAND": "the-sandbox", "MANA": "decentraland", "AXS": "axie-infinity",
        "THETA": "theta-token", "AAVE": "aave", "FTM": "fantom", "CRO": "crypto-com-chain",
        "NEAR": "near", "ALGO": "algorand", "QNT": "quant-network", "EOS": "eos",
        "XTZ": "tezos", "FLOW": "flow", "CHZ": "chiliz", "APE": "apecoin",
        "ZIL": "zilliqa", "ENJ": "enjincoin", "WAXP": "wax", "BAT": "basic-attention-token",
        "1INCH": "1inch", "COMP": "compound-governance-token", "MKR": "maker",
        "SNX": "havven", "CRV": "curve-dao-token", "LDO": "lido-dao", "RPL": "rocket-pool"
    }
    
    def _fetch_prices_mexc(self):
        """Fetch prices from CoinGecko (reliable) with simulated bid/ask spread"""
        prices = {}
        
        try:
            # Fetch all prices at once from CoinGecko
            ids = [self.COINGECKO_IDS.get(t, t.lower()) for t in TOKENS]
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={','.join(ids)}&vs_currencies=usd"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                for token, cg_id in self.COINGECKO_IDS.items():
                    if cg_id in data:
                        mid = data[cg_id].get('usd', 0)
                        if mid > 0:
                            # Simulate 0.1% spread for bid/ask
                            spread = mid * 0.001
                            prices[token] = {
                                "bid": round(mid - spread, 8),  # We sell at bid
                                "ask": round(mid + spread, 8),  # We buy at ask
                                "mid": round(mid, 8)
                            }
        except Exception as e:
            print(f"Price fetch error: {e}")
        
        # Fill missing with fallback
        for token in TOKENS:
            if token not in prices:
                base_price = round(random.uniform(10, 50000), 2)
                spread = base_price * 0.001
                prices[token] = {
                    "bid": round(base_price - spread, 8),
                    "ask": round(base_price + spread, 8),
                    "mid": round(base_price, 8)
                }
        
        return prices
    
    def initialize(self, held_token=None, threshold=None, hold_amount=None):
        """Initialize - fetch prices and create matrix"""
        if threshold:
            self.threshold = threshold
        
        if held_token and held_token in TOKENS:
            self.held_token = held_token
        else:
            self.held_token = "BTC"  # Default
        
        if hold_amount:
            self.hold_amount = float(hold_amount)
        
        # Fetch prices from MEXC
        self.prices = self._fetch_prices_mexc()
        
        # Calculate baseline and top
        # For held token: baseline = hold_amount
        # For other tokens: baseline = what we'd have if we sold held and bought this token (with fees)
        
        held_price_bid = self.prices.get(self.held_token, {}).get('bid', 1)  # We sell at bid
        held_value_usdt = self.hold_amount * held_price_bid * (1 - FEE)  # After sell fee
        
        self.holdings = {token: 0 for token in TOKENS}
        self.holdings[self.held_token] = self.hold_amount
        
        for token in TOKENS:
            if token == self.held_token:
                self.baseline[token] = self.hold_amount
                self.top[token] = self.hold_amount
            else:
                ask_price = self.prices.get(token, {}).get('ask', 0)
                if ask_price > 0 and held_value_usdt > 0:
                    # Buy at ask, after buy fee
                    amount = (held_value_usdt / ask_price) * (1 - FEE)
                else:
                    amount = 0
                self.baseline[token] = amount
                self.top[token] = amount  # Initially top = baseline
        
        self.status = "initialized"
        self.tick = 0
        self.total_swaps = 0
        self.swap_history = []
        
        # Save to DB
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        c.execute("""UPDATE sessions SET held_token=?, hold_amount=?, threshold=?, status=?, holdings=?, baseline=?, top=?, tick=0, total_swaps=0 WHERE id=?""",
                  (self.held_token, self.hold_amount, self.threshold, self.status,
                   json.dumps(self.holdings), json.dumps(self.baseline), json.dumps(self.top), self.session_id))
        conn.commit()
        conn.close()
        
        # Save initial tick
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
        """Full restart - clear everything"""
        conn = sqlite3.connect(app.config['DATABASE'])
        c = conn.cursor()
        
        # Delete all ticks and swaps for this session
        c.execute("DELETE FROM ticks WHERE session_id=?", (self.session_id,))
        c.execute("DELETE FROM swaps WHERE session_id=?", (self.session_id,))
        
        # Reset session
        c.execute("""UPDATE sessions SET held_token='BTC', hold_amount=?, threshold=?, status='uninitialized', 
                      holdings='{}', baseline='{}', top='{}', tick=0, total_swaps=0 WHERE id=?""",
                  (DEFAULT_HOLD, self.threshold, self.session_id))
        
        conn.commit()
        conn.close()
        
        # Reset state
        self.held_token = "BTC"
        self.hold_amount = DEFAULT_HOLD
        self.status = "uninitialized"
        self.holdings = {}
        self.baseline = {}
        self.top = {}
        self.prices = {}
        self.tick = 0
        self.total_swaps = 0
        self.swap_history = []
        self.total_ticks = 0
        
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
        """Fetch new prices and update"""
        if self.status != "running":
            return self.get_state()
        
        self.tick += 1
        self.total_ticks += 1
        
        # Fetch new prices
        self.prices = self._fetch_prices_mexc()
        
        # Check for swap every tick
        self._try_swap()
        
        # Save tick
        self._save_tick()
        
        # Run extra backtest in background
        self._run_extra_backtest()
        
        return self.get_state()
    
    def _try_swap(self):
        """Check if we should swap"""
        if not self.held_token or self.held_token not in self.holdings:
            return
        
        held = self.held_token
        held_amount = self.holdings.get(held, 0)
        
        if held_amount <= 0:
            return
        
        held_price_bid = self.prices.get(held, {}).get('bid', 0)
        if held_price_bid <= 0:
            return
        
        current_value = held_amount * held_price_bid
        current_top = self.top.get(held, held_amount)
        
        # Calculate loss from top (in token equivalent)
        if current_top > 0:
            loss_pct = (1 - current_value / (current_top * held_price_bid)) * 100
        else:
            loss_pct = 0
        
        # Only consider swap if threshold met
        if loss_pct < self.threshold:
            return
        
        # Find best target
        best_target = None
        best_gain = -999
        
        for token in TOKENS:
            if token == held:
                continue
            
            ask_price = self.prices.get(token, {}).get('ask', 0)
            if ask_price <= 0:
                continue
            
            # Calculate what we'd get
            usd = held_amount * held_price_bid * (1 - FEE)  # Sell at bid, pay fee
            amount_to = (usd / ask_price) * (1 - FEE)  # Buy at ask, pay fee
            value_to = amount_to * ask_price
            
            gain_pct = (value_to / current_value - 1) * 100
            
            if gain_pct > best_gain:
                best_gain = gain_pct
                best_target = token
        
        if best_target and best_gain > self.threshold:
            self._execute_swap(held, best_target, held_price_bid)
    
    def _execute_swap(self, token_from, token_to, price_from):
        """Execute swap"""
        amount_from = self.holdings.get(token_from, 0)
        if amount_from <= 0:
            return
        
        price_to = self.prices.get(token_to, {}).get('ask', 0)  # Buy at ask
        if price_to <= 0:
            return
        
        # Calculate amounts with proper fee handling
        usd_after_sell = amount_from * price_from * (1 - FEE)  # Sell at bid, pay fee
        amount_to = (usd_after_sell / price_to) * (1 - FEE)  # Buy at ask, pay fee
        
        fee_paid = amount_from * price_from - usd_after_sell + usd_after_sell - amount_to * price_to
        
        # Update holdings
        self.holdings[token_from] = 0
        self.holdings[token_to] = amount_to
        old_held = self.held_token
        self.held_token = token_to
        
        # Update top for new token if we got more than before
        if amount_to > self.top.get(token_to, 0):
            self.top[token_to] = amount_to
        
        # Record swap
        swap = {
            "tick": self.tick,
            "timestamp": datetime.now().isoformat(),
            "token_from": token_from,
            "token_to": token_to,
            "amount_from": amount_from,
            "amount_to": amount_to,
            "price_from": price_from,
            "price_to": price_to,
            "fee_paid": fee_paid,
            "threshold": self.threshold,
            "gain_pct": round(best_gain if 'best_gain' in dir() else 0, 2)
        }
        
        # Calculate actual gain
        old_top = self.top.get(token_from, amount_from)
        new_value = amount_to * price_to
        old_value = amount_from * price_from
        if old_value > 0:
            swap["gain_pct"] = round((new_value / old_value - 1) * 100, 2)
        
        self.swap_history.append(swap)
        self.total_swaps += 1
        
        # Save to DB
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
    
    def _run_extra_backtest(self):
        """Run backtest with different thresholds"""
        if self.tick < 10:
            return
        
        # This would run in background - for now just log
        pass
    
    def get_state(self):
        """Get current state"""
        if not self.prices:
            # Initialize with random prices if not initialized
            for token in TOKENS:
                base = round(random.uniform(10, 50000), 2)
                spread = base * 0.001
                self.prices[token] = {"bid": base - spread, "ask": base + spread, "mid": base}
        
        tokens = {}
        held_price_bid = self.prices.get(self.held_token, {}).get('bid', 1)
        held_amount = self.holdings.get(self.held_token, 0)
        
        for token in TOKENS:
            price_data = self.prices.get(token, {})
            bid = price_data.get('bid', 0)
            ask = price_data.get('ask', 0)
            
            if token == self.held_token:
                actual = held_amount
            else:
                if ask > 0 and held_amount > 0 and held_price_bid > 0:
                    usd = held_amount * held_price_bid * (1 - FEE)
                    actual = (usd / ask) * (1 - FEE)
                else:
                    actual = 0
            
            baseline = self.baseline.get(token, actual)
            top = self.top.get(token, baseline)
            
            gain_top = round((actual / top - 1) * 100, 2) if top > 0 else 0
            gain_baseline = round((actual / baseline - 1) * 100, 2) if baseline > 0 else 0
            
            # Calculate USDT value
            usdt_value = 0
            if token == self.held_token:
                usdt_value = actual * held_price_bid * (1 - FEE)
            elif bid > 0:
                usdt_value = actual * bid * (1 - FEE)
            
            tokens[token] = {
                "actual": round(actual, 8),
                "top": round(top, 8),
                "baseline": round(baseline, 8),
                "gain_top": gain_top,
                "gain_baseline": gain_baseline,
                "price": round(price_data.get('mid', bid), 8),
                "bid": round(bid, 8),
                "ask": round(ask, 8),
                "is_held": token == self.held_token,
                "holding": self.holdings.get(token, 0),
                "usdt_value": round(usdt_value, 2)
            }
        
        # Sort by actual token amount
        sorted_tokens = sorted(TOKENS, key=lambda t: tokens[t]["actual"], reverse=True)
        for i, token in enumerate(sorted_tokens):
            tokens[token]["rank"] = i + 1
        
        # Portfolio info
        portfolio = {}
        if self.status in ["initialized", "running", "stopped"]:
            held = self.held_token
            held_baseline = self.baseline.get(held, self.hold_amount)
            gain_baseline = round((held_amount / held_baseline - 1) * 100, 2) if held_baseline > 0 else 0
            usdt_val = held_amount * held_price_bid * (1 - FEE) if held_price_bid > 0 else 0
            
            portfolio = {
                "token": held,
                "amount": round(held_amount, 8),
                "gain_baseline": gain_baseline,
                "usdt_value": round(usdt_val, 2)
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

# Initialize
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
    c.execute("SELECT tick, timestamp, prices FROM ticks WHERE session_id=? ORDER BY tick DESC LIMIT 100", (state.session_id,))
    ticks = []
    for row in c.fetchall():
        ticks.append({
            "tick": row[0],
            "timestamp": row[1],
            "prices_count": len(json.loads(row[2])) if row[2] else 0
        })
    conn.close()
    return jsonify({"ticks": ticks})

@app.route('/api/ticks/detail')
def get_ticks_detail():
    conn = sqlite3.connect(app.config['DATABASE'])
    c = conn.cursor()
    c.execute("SELECT tick, timestamp, prices FROM ticks WHERE session_id=? ORDER BY tick DESC LIMIT 10", (state.session_id,))
    ticks = []
    for row in c.fetchall():
        prices = json.loads(row[2]) if row[2] else {}
        # Show first 5 tokens prices
        sample = {t: prices[t] for t in list(prices.keys())[:5]}
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
