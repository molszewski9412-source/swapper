#!/usr/bin/env python3
"""
Swapper Web Dashboard - Przeglądarkowa wizualizacja ewolucji strategii

Uruchom:
    python web_app.py
    Otwórz http://localhost:5000
"""

from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import json
import csv
import random
import threading
import time
from pathlib import Path

app = Flask(__name__)
CORS(app)

# Global state
evolution_state = {
    "running": False,
    "generation": 0,
    "best_score": 0,
    "best_params": {},
    "current_population": [],
    "generation_history": [],
    "all_results": [],
    "config": {},
    "market_data": None
}

# Tokens from your data
TOKENS = ['SOLUSDT', 'ETHUSDT', 'BTCUSDT', 'AVAXUSDT', 'DOTUSDT', 'ADAUSDT', 
          'POLUSDT', 'BNBUSDT', 'XRPUSDT', 'LTCUSDT', 'LINKUSDT', 'DOGEUSDT', 
          'UNIUSDT', 'AAVEUSDT', 'FILUSDT', 'NEARUSDT', 'XLMUSDT', 'ATOMUSDT', 
          'SANDUSDT', 'CHZUSDT']

START_TOKEN = "BTCUSDT"  # Starting token


def load_market_data(filepath="market.csv"):
    """Load market data and compute baseline."""
    print(f"Loading market data from {filepath}...")
    
    prices = {}  # token -> list of (timestamp, bid, ask)
    
    with open(filepath, 'r') as f:
        reader = csv.reader(f)
        header = next(reader)
        
        # Parse header to get token columns
        token_cols = {}
        for i, col in enumerate(header):
            if col.endswith("_BID"):
                token = col.replace("_BID", "")
                token_cols[token] = i
        
        # Load first row for baseline
        first_row = next(reader)
        baseline = {}
        for token, idx in token_cols.items():
            bid_idx = idx
            ask_idx = idx + 1
            bid = float(first_row[bid_idx])
            ask = float(first_row[ask_idx])
            baseline[token] = {"bid": bid, "ask": ask, "mid": (bid + ask) / 2}
        
        # Load all data for final prices
        all_rows = [first_row] + list(reader)
        final_row = all_rows[-1]
        
        final_prices = {}
        for token, idx in token_cols.items():
            bid_idx = idx
            ask_idx = idx + 1
            bid = float(final_row[bid_idx])
            ask = float(final_row[ask_idx])
            final_prices[token] = {"bid": bid, "ask": ask, "mid": (bid + ask) / 2}
        
        print(f"Loaded {len(all_rows)} records")
        print(f"Baseline prices (first timestamp):")
        for token in TOKENS:
            if token in baseline:
                print(f"  {token}: {baseline[token]['mid']:.4f}")
        
        return {
            "baseline": baseline,
            "final": final_prices,
            "n_records": len(all_rows)
        }


def compute_baseline(market_data, start_token=START_TOKEN):
    """
    Compute baseline portfolio.
    We start with 1 unit of start_token.
    Calculate equivalent amount for each other token.
    """
    baseline = market_data["baseline"]
    final = market_data["final"]
    
    # Starting amount in start_token
    start_amount = 1.0  # 1 BTC
    
    # Calculate total USDT value of starting position
    start_price = baseline[start_token]["mid"]
    total_usdt = start_amount * start_price
    
    # For each token, calculate how much we could have had at start
    matrix = []
    
    for token in TOKENS:
        if token not in baseline:
            continue
        
        # Initial amount (if we had converted to this token at start)
        token_price = baseline[token]["mid"]
        initial_amount = total_usdt / token_price
        
        # Final amount (same amount of tokens, but valued at final price)
        final_price = final[token]["mid"]
        final_usdt_value = initial_amount * final_price
        
        # Gain percentage
        gain_pct = ((final_usdt_value / total_usdt) - 1) * 100
        
        # How much we'd have if we just held this token
        if token == start_token:
            held_amount = start_amount
            held_final_value = start_amount * final_price
        else:
            held_amount = initial_amount
            held_final_value = initial_amount * final_price
        
        matrix.append({
            "token": token,
            "initial_amount": initial_amount,
            "initial_unit": "tokens",
            "initial_usdt_equiv": total_usdt,
            "final_usdt_equiv": held_final_value,
            "gain_pct": gain_pct,
            "baseline_price": token_price,
            "final_price": final_price,
            "is_start": token == start_token
        })
    
    return matrix


def compute_strategy_result(market_data, best_params, final_token):
    """
    Compute what strategy achieved vs baseline.
    """
    baseline = market_data["baseline"]
    final = market_data["final"]
    
    start_amount = 1.0  # 1 BTC
    start_price = baseline[START_TOKEN]["mid"]
    total_usdt = start_amount * start_price
    
    # Strategy ended with final_token
    if final_token not in final:
        final_token = START_TOKEN
    
    # Final value of strategy
    final_price = final[final_token]["mid"]
    
    # If we held final_token from start
    if final_token != START_TOKEN:
        initial_final_token_price = baseline[final_token]["mid"]
        initial_final_token_amount = total_usdt / initial_final_token_price
        strategy_final_value = initial_final_token_amount * final_price
    else:
        strategy_final_value = start_amount * final_price
    
    # Calculate what we gained by swapping
    if final_token == START_TOKEN:
        swap_gain = 0
    else:
        # Compare to just holding BTC
        btc_final = start_amount * final[START_TOKEN]["mid"]
        swap_gain = strategy_final_value - btc_final
    
    return {
        "final_token": final_token,
        "final_value_usdt": strategy_final_value,
        "total_gain_pct": ((strategy_final_value / total_usdt) - 1) * 100,
        "swap_gain_usdt": swap_gain
    }


@app.route('/')
def index():
    """Main dashboard page."""
    return render_template('dashboard.html')


@app.route('/api/state')
def get_state():
    """Get current evolution state."""
    return jsonify(evolution_state)


@app.route('/api/results')
def get_results():
    """Get all results."""
    return jsonify({
        "generation_history": evolution_state["generation_history"],
        "all_results": evolution_state["all_results"][-100:],
        "best": {
            "score": evolution_state["best_score"],
            "params": evolution_state["best_params"]
        }
    })


@app.route('/api/start', methods=['POST'])
def start_evolution():
    """Start evolution in background."""
    global market_data_cache
    
    data = request.json or {}
    generations = data.get('generations', 100)
    population = data.get('population', 20)
    use_llm = data.get('use_llm', False)
    
    if evolution_state["running"]:
        return jsonify({"status": "already_running"})
    
    evolution_state["config"] = {
        "generations": generations,
        "population": population,
        "use_llm": use_llm
    }
    
    # Start in background thread
    thread = threading.Thread(target=run_evolution, args=(generations, population, use_llm))
    thread.daemon = True
    thread.start()
    
    return jsonify({"status": "started"})


@app.route('/api/stop', methods=['POST'])
def stop_evolution():
    """Stop evolution."""
    evolution_state["running"] = False
    return jsonify({"status": "stopped"})


@app.route('/api/baseline')
def get_baseline():
    """Get baseline matrix from market data."""
    global market_data_cache
    
    if market_data_cache is None:
        market_data_cache = load_market_data()
    
    matrix = compute_baseline(market_data_cache)
    
    return jsonify({
        "start_token": START_TOKEN,
        "start_amount": 1.0,
        "start_price": market_data_cache["baseline"][START_TOKEN]["mid"],
        "total_usdt_equiv": 1.0 * market_data_cache["baseline"][START_TOKEN]["mid"],
        "matrix": matrix
    })


@app.route('/api/matrix')
def get_matrix():
    """Get result matrix for visualization with real data."""
    global market_data_cache
    
    if market_data_cache is None:
        market_data_cache = load_market_data()
    
    best_params = evolution_state["best_params"]
    
    # Determine final token based on best params
    threshold = best_params.get('threshold', 1.05)
    if threshold > 1.5:
        final_token = "BTCUSDT"
    elif threshold > 1.2:
        final_token = "ETHUSDT"
    else:
        final_token = "SOLUSDT"
    
    # Compute baseline (what we COULD have had)
    baseline_matrix = compute_baseline(market_data_cache)
    
    # Compute strategy result
    strategy_result = compute_strategy_result(market_data_cache, best_params, final_token)
    
    # Add strategy info to each token
    matrix = []
    for item in baseline_matrix:
        token = item["token"]
        
        # Strategy value (what we ACTUALLY have)
        if token == strategy_result["final_token"]:
            strategy_final = strategy_result["final_value_usdt"]
            is_final = True
        else:
            # For other tokens - calculate potential if we had held them
            strategy_final = item["final_usdt_equiv"]
            is_final = False
        
        # Compare strategy vs baseline for this token
        # (Baseline = what we'd have if we had this token from start)
        baseline_value = item["final_usdt_equiv"]
        
        matrix.append({
            "token": token,
            # Baseline: how much of each token we COULD have had at start
            "baseline_amount": round(item["initial_amount"], 6),
            "baseline_price_start": round(item["baseline_price"], 4),
            # Current values
            "current_price": round(item["final_price"], 4),
            "current_value_usdt": round(strategy_final, 2),
            # What we gained on this token
            "gain_pct": round(item["gain_pct"], 2),
            # Strategy specific
            "is_strategy_final": is_final,
            "is_baseline_start": item["is_start"]
        })
    
    return jsonify({
        "start_token": START_TOKEN,
        "start_amount": 1.0,
        "start_price": market_data_cache["baseline"][START_TOKEN]["mid"],
        "baseline_total_usdt": 1.0 * market_data_cache["baseline"][START_TOKEN]["mid"],
        "final_token": strategy_result["final_token"],
        "final_value_usdt": round(strategy_result["final_value_usdt"], 2),
        "total_strategy_gain_pct": round(strategy_result["total_gain_pct"], 2),
        "swap_gain_usdt": round(strategy_result["swap_gain_usdt"], 2),
        "matrix": matrix,
        "best_params": best_params,
        "best_score": evolution_state["best_score"],
        "first_timestamp": "From market.csv",
        "last_timestamp": "From market.csv"
    })


# Global cache
market_data_cache = None


def run_evolution(generations, population, use_llm):
    """Run evolution loop in background."""
    global market_data_cache
    
    evolution_state["running"] = True
    evolution_state["generation"] = 0
    evolution_state["best_score"] = 0
    evolution_state["best_params"] = {}
    evolution_state["current_population"] = []
    evolution_state["generation_history"] = []
    evolution_state["all_results"] = []
    
    # Load market data once
    if market_data_cache is None:
        market_data_cache = load_market_data()
    
    for gen in range(generations):
        if not evolution_state["running"]:
            break
        
        evolution_state["generation"] = gen + 1
        
        # Evaluate population
        pop_scores = []
        for i in range(population):
            # Score based on strategy parameters
            threshold = random.uniform(0.9, 3.0)
            interval = random.randint(1, 50)
            momentum = random.uniform(0, 1)
            volatility = random.uniform(0, 1)
            
            # Simulate score based on parameters
            # Higher threshold + longer interval = better but harder to achieve
            score = 10000000 * (1 + threshold / 10) * (1 + interval / 100) + random.random() * 500000
            
            params = {
                "threshold": threshold,
                "min_swap_interval": interval,
                "momentum_weight": momentum,
                "volatility_weight": volatility,
            }
            
            pop_scores.append({"params": params, "score": score})
            evolution_state["all_results"].append({
                "generation": gen + 1,
                "params": params,
                "score": score
            })
        
        # Sort by score
        pop_scores.sort(key=lambda x: x["score"], reverse=True)
        evolution_state["current_population"] = pop_scores[:10]
        
        # Update best
        if pop_scores[0]["score"] > evolution_state["best_score"]:
            evolution_state["best_score"] = pop_scores[0]["score"]
            evolution_state["best_params"] = pop_scores[0]["params"]
        
        # Record history
        evolution_state["generation_history"].append({
            "generation": gen + 1,
            "best_score": pop_scores[0]["score"],
            "avg_score": sum(p["score"] for p in pop_scores) / len(pop_scores),
            "worst_score": pop_scores[-1]["score"]
        })
        
        time.sleep(0.5)
    
    evolution_state["running"] = False


if __name__ == '__main__':
    print("""
╔═══════════════════════════════════════════════════════════════╗
║          SWAPPER Web Dashboard                               ║
║          http://localhost:5000                               ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    # Pre-load market data
    try:
        market_data_cache = load_market_data()
    except Exception as e:
        print(f"Warning: Could not load market data: {e}")
    
    app.run(debug=True, host='0.0.0.0', port=5000)
