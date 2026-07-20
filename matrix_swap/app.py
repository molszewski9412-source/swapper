#!/usr/bin/env python3
"""
Matrix Swap - Flask Web Application

Real-time token swap matrix with Mexc integration.
"""

from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import threading
import time
import json

from config import INITIAL_USDT, DEFAULT_THRESHOLD, POLL_INTERVAL_SEC
from matrix import Matrix
from api import MexcClient, get_top_volume_tokens

app = Flask(__name__)
CORS(app)

# Global state
matrix = Matrix(initial_usdt=INITIAL_USDT)
api_client = MexcClient()
is_running = False
poll_thread = None


def poll_mexc():
    """Background thread to poll Mexc API."""
    global is_running, matrix
    
    print("Polling thread started")
    
    while is_running:
        try:
            # Fetch top tokens
            symbols = get_top_volume_tokens(api_client, n=50)
            token_prices = api_client.fetch_specific_tokens(symbols)
            
            if token_prices:
                # Update matrix prices
                matrix.update_prices(token_prices)
                
                # Check for swap
                swap = matrix.check_and_execute_swap()
                
                # Log tick
                swap_info = None
                if swap:
                    swap_info = {
                        'from': swap.from_symbol,
                        'to': swap.to_symbol,
                        'from_qty': swap.from_qty,
                        'to_qty': swap.to_qty,
                        'gain_pct': swap.gain_pct
                    }
                    print(f"SWAP: {swap.from_symbol} -> {swap.to_symbol} | Gain: {swap.gain_pct:.2f}%")
                
                api_client.log_tick(token_prices, matrix.portfolio.symbol, matrix.portfolio.quantity, swap_info)
        
        except Exception as e:
            print(f"Poll error: {e}")
        
        time.sleep(POLL_INTERVAL_SEC)
    
    print("Polling thread stopped")


@app.route('/')
def index():
    """Main page."""
    return render_template('index.html')


@app.route('/api/status')
def status():
    """Get current status."""
    return jsonify({
        "initialized": matrix.initialized,
        "is_running": is_running,
        "swap_count": matrix.swap_count,
        "last_tick": matrix.last_tick
    })


@app.route('/api/matrix')
def get_matrix():
    """Get full matrix state."""
    return jsonify(matrix.get_state())


@app.route('/api/initialize', methods=['POST'])
def initialize():
    """Initialize matrix with current prices."""
    global is_running, poll_thread, matrix
    
    # Stop if running
    if is_running:
        is_running = False
        if poll_thread:
            poll_thread.join(timeout=2)
    
    # Reset matrix
    matrix = Matrix(initial_usdt=INITIAL_USDT)
    
    # Fetch initial prices
    symbols = get_top_volume_tokens(api_client, n=50)
    token_prices = api_client.fetch_specific_tokens(symbols)
    
    if not token_prices:
        return jsonify({"error": "Failed to fetch prices from Mexc"}), 500
    
    # Initialize matrix
    result = matrix.initialize(token_prices)
    
    # Start polling
    is_running = True
    poll_thread = threading.Thread(target=poll_mexc, daemon=True)
    poll_thread.start()
    
    return jsonify({
        "success": True,
        "tokens_count": len(symbols),
        "matrix": result
    })


@app.route('/api/stop', methods=['POST'])
def stop():
    """Stop polling."""
    global is_running
    
    is_running = False
    
    return jsonify({
        "success": True,
        "is_running": False
    })


@app.route('/api/threshold', methods=['POST'])
def set_threshold():
    """Set swap threshold."""
    data = request.get_json()
    threshold = float(data.get('threshold', DEFAULT_THRESHOLD))
    
    matrix.set_threshold(threshold)
    
    return jsonify({
        "success": True,
        "threshold": threshold
    })


@app.route('/api/best_candidate')
def best_candidate():
    """Get best swap candidate."""
    candidate = matrix.get_best_swap_candidate()
    
    if candidate:
        return jsonify(candidate)
    else:
        return jsonify({"message": "No candidate"})


@app.route('/api/save_ticks', methods=['POST'])
def save_ticks():
    """Save tick log to file."""
    filepath = request.json.get('filepath', 'tick_log.json') if request.json else 'tick_log.json'
    api_client.save_tick_log(filepath)
    
    return jsonify({
        "success": True,
        "filepath": filepath,
        "tick_count": len(api_client.tick_log)
    })


if __name__ == '__main__':
    print("""
╔═══════════════════════════════════════════════════════════════╗
║              MATRIX SWAP v2 - Token Accumulator               ║
║                                                               ║
║  Web Interface: http://localhost:5000                         ║
║  Mexc API polling: Every 1 second                             ║
║                                                               ║
║  Goal: Maximize TOKEN COUNT, not USDT value!                   ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    app.run(debug=True, host='0.0.0.0', port=5000)
