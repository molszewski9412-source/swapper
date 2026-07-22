#!/usr/bin/env python3
"""
Matrix Swap - Flask Web Application

Real-time token swap matrix with Mexc integration + Alert System.
"""

from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import threading
import time
import json
import os

from config import INITIAL_USDT, DEFAULT_THRESHOLD, POLL_INTERVAL_SEC, FEE
from matrix import Matrix
from api import MexcClient, get_top_volume_tokens
from alerts import AlertSystem

app = Flask(__name__)
CORS(app)

# Global state
matrix = Matrix(initial_usdt=INITIAL_USDT)
api_client = MexcClient()
is_running = False
poll_thread = None

# Alert system (Telegram - FREE!)
alert_system = AlertSystem()

# Load Telegram config from env or config file
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
    alert_system.telegram_token = TELEGRAM_TOKEN
    alert_system.telegram_chat_id = TELEGRAM_CHAT_ID
    print(f"[ALERT] Telegram configured: {TELEGRAM_CHAT_ID[:5]}...")
else:
    print("[ALERT] Telegram not configured - alerts will be printed to console")


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
                
                # Update alert system with current quantity
                alert_system.set_current_quantity(matrix.portfolio.quantity)
                
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
                    
                    # Send swap alert
                    alert_system.send_swap_alert(
                        swap.from_symbol, swap.to_symbol, swap.gain_pct,
                        swap.from_qty, swap.to_qty, swap.price_before
                    )
                    
                    # Record new purchase for monitoring
                    # Calculate USDT value at purchase
                    usdt_value = swap.from_qty * swap.price_before * (1 - FEE)
                    alert_system.record_purchase(
                        swap.to_symbol, swap.to_qty, swap.price_before,
                        matrix.swap_count, swap.to_qty, usdt_value
                    )
                    # Capture token state at new purchase moment
                    alert_system.capture_tokens_at_purchase(matrix.get_state()['tokens'])
                
                # Check threshold for alerts (only if no swap happened)
                if not swap and matrix.initialized:
                    state = matrix.get_state()
                    threshold_info = alert_system.check_threshold(
                        state['tokens'], state['current_holding']['symbol']
                    )
                    if threshold_info:
                        print(f"[ALERT] Threshold reached! Gain: {threshold_info['best_gain']:.2f}%")
                        alert_system.send_threshold_alert(
                            threshold_info['best_candidate'],
                            threshold_info['holding_gain']
                        )
                
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
    
    # Record initial purchase for alert tracking
    holding = result['current_holding']
    first_token = holding['symbol']
    qty = holding['quantity']
    
    # Get buy price (ask at initialization)
    token_data = result['tokens'].get(first_token, {})
    buy_price = token_data.get('current_ask', 0)
    top_eq = holding['top_eq']
    
    # Calculate USDT value
    usdt_value = qty * buy_price * (1 - FEE) if buy_price > 0 else INITIAL_USDT
    
    alert_system.record_purchase(first_token, qty, buy_price, 0, top_eq, usdt_value)
    alert_system.capture_tokens_at_purchase(result['tokens'])
    alert_system.set_current_quantity(qty)
    
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


# ===== ALERT SYSTEM ENDPOINTS =====

@app.route('/api/alerts/status')
def alerts_status():
    """Get alert system status."""
    return jsonify(alert_system.get_status())


@app.route('/api/alerts/configure', methods=['POST'])
def configure_alerts():
    """Configure Telegram alerts."""
    data = request.get_json() or {}
    
    token = data.get('telegram_token', '')
    chat_id = data.get('telegram_chat_id', '')
    
    if token and chat_id:
        alert_system.telegram_token = token
        alert_system.telegram_chat_id = chat_id
        
        # Send test message
        alert_system.send_telegram("✅ *Matrix Swap Alert System Connected!*\n\nBot started and monitoring...")
        
        return jsonify({
            "success": True,
            "message": "Telegram configured successfully!",
            "telegram": {"token": token[:10] + "...", "chat_id": chat_id}
        })
    else:
        return jsonify({
            "success": False,
            "message": "Please provide telegram_token and telegram_chat_id"
        }), 400


@app.route('/api/alerts/test', methods=['POST'])
def test_alert():
    """Send test alert."""
    alert_system.send_telegram("🧪 *TEST ALERT*\n\nMatrix Swap alert system is working!")
    return jsonify({"success": True, "message": "Test alert sent"})


@app.route('/api/alerts/purchases')
def get_purchases():
    """Get purchase history."""
    from dataclasses import asdict
    purchases = [asdict(p) for p in alert_system.purchase_history]
    return jsonify({
        "current_purchase": asdict(alert_system.current_purchase) if alert_system.current_purchase else None,
        "history": purchases
    })


@app.route('/api/alerts/history')
def get_alerts_history():
    """Get alerts history."""
    from dataclasses import asdict
    return jsonify({
        "alerts": [asdict(a) for a in alert_system.alerts]
    })


if __name__ == '__main__':
    print("""
╔═══════════════════════════════════════════════════════════════╗
║              MATRIX SWAP v2 - Token Accumulator               ║
║                  + Alert System                             ║
╠═══════════════════════════════════════════════════════════════╣
║  Web Interface: http://localhost:5000                       ║
║  Mexc API polling: Every 1 second                           ║
║  Threshold: 7%                                              ║
║                                                               ║
║  ALERTS (Telegram - FREE!):                                 ║
║  1. Open @BotFather on Telegram                             ║
║  2. Create bot, get TOKEN                                    ║
║  3. Start chat with bot                                      ║
║  4. Use /api/alerts/configure to connect                     ║
║                                                               ║
║  Goal: Maximize TOKEN COUNT, not USDT value!                 ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    app.run(debug=True, host='0.0.0.0', port=5000)
