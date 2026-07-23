"""
Live Matrix - Prototype
50 tokens displaying real-time equity, updates every second.
Baseline saved on RUN, actual_eq updated on each tick.
"""
import random
import time
import threading
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'live-matrix-secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# 50 tokens
TOKENS = [
    "BTC", "ETH", "BNB", "XRP", "SOL", "ADA", "DOGE", "AVAX", "DOT", "LINK",
    "MATIC", "SHIB", "LTC", "UNI", "ATOM", "XLM", "ETC", "FIL", "APT", "ARJ",
    "VET", "HBAR", "ICP", "EGLD", "SAND", "MANA", "AXS", "THETA", "AAVE", "FTM",
    "CRO", "NEAR", "ALGO", "QNT", "EOS", "XTZ", "FLOW", "CHZ", "APE", "ZIL",
    "ENJ", "WAXP", "BAT", "1INCH", "COMP", "MKR", "SNX", "CRV", "LDO", "RPL"
]

class LiveMatrix:
    def __init__(self):
        self.is_running = False
        self.baseline_eq = None
        self.tick = 0
        self.tokens_data = {}
        self.init_tokens()  # Initialize tokens immediately
        
    def init_tokens(self):
        """Initialize tokens with base equity."""
        self.tokens_data = {}
        for token in TOKENS:
            self.tokens_data[token] = {
                "eq": round(random.uniform(1000, 10000), 2),
                "price": round(random.uniform(10, 50000), 2),
                "change_24h": round(random.uniform(-10, 10), 2),
                "rank": 0
            }
        self.update_ranks()
    
    def update_ranks(self):
        """Update token ranks by equity."""
        sorted_tokens = sorted(
            self.tokens_data.items(), 
            key=lambda x: x[1]["eq"], 
            reverse=True
        )
        for rank, (token, _) in enumerate(sorted_tokens, 1):
            self.tokens_data[token]["rank"] = rank
    
    def tick_update(self):
        """Update all tokens on each tick."""
        self.tick += 1
        for token in TOKENS:
            # Simulate price movement
            price_change = random.uniform(-0.02, 0.02)
            self.tokens_data[token]["price"] *= (1 + price_change)
            self.tokens_data[token]["price"] = round(self.tokens_data[token]["price"], 2)
            
            # Simulate equity change based on price
            eq_change = random.uniform(-0.05, 0.05)
            self.tokens_data[token]["eq"] *= (1 + eq_change)
            self.tokens_data[token]["eq"] = round(self.tokens_data[token]["eq"], 2)
            
            # Update 24h change
            self.tokens_data[token]["change_24h"] = round(
                random.uniform(-15, 15), 2
            )
        
        self.update_ranks()
        return self.get_matrix_data()
    
    def get_matrix_data(self):
        """Get current matrix state."""
        sorted_tokens = sorted(
            TOKENS, 
            key=lambda t: self.tokens_data[t]["rank"]
        )
        return {
            "tick": self.tick,
            "baseline_eq": self.baseline_eq,
            "is_running": self.is_running,
            "tokens": {token: self.tokens_data[token] for token in sorted_tokens},
            "total_eq": round(sum(t["eq"] for t in self.tokens_data.values()), 2)
        }
    
    def start(self):
        """Start the matrix."""
        self.init_tokens()
        self.is_running = True
        self.tick = 0
        # Save baseline
        self.baseline_eq = round(sum(t["eq"] for t in self.tokens_data.values()), 2)
        return self.get_matrix_data()
    
    def stop(self):
        """Stop the matrix."""
        self.is_running = False
        return self.get_matrix_data()

# Global instance
matrix = LiveMatrix()

@app.route('/')
def index():
    return render_template('live_matrix.html')

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
    matrix.baseline_eq = None
    matrix.tick = 0
    emit('update', matrix.get_matrix_data())

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
