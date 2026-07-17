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
import os
from pathlib import Path
from datetime import datetime
import random
import threading
import time

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
    "config": {}
}

# Tokens from your data
TOKENS = ['SOLUSDT', 'ETHUSDT', 'BTCUSDT', 'AVAXUSDT', 'DOTUSDT', 'ADAUSDT', 
          'POLUSDT', 'BNBUSDT', 'XRPUSDT', 'LTCUSDT', 'LINKUSDT', 'DOGEUSDT', 
          'UNIUSDT', 'AAVEUSDT', 'FILUSDT', 'NEARUSDT', 'XLMUSDT', 'ATOMUSDT', 
          'SANDUSDT', 'CHZUSDT']


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


@app.route('/api/matrix')
def get_matrix():
    """Get result matrix for visualization."""
    # Generate mock final portfolio state
    best_params = evolution_state["best_params"]
    
    # Simulate what the final portfolio looks like
    initial_amount = 1.0  # USDT
    start_token = "BTCUSDT"
    
    # Calculate what happened based on best score
    final_score = evolution_state["best_score"]
    
    # Create matrix showing all tokens
    matrix = []
    
    # The "winning" token (what we ended up holding)
    # Based on threshold logic - higher threshold = more selective = likely BTC
    if best_params.get('threshold', 1.05) > 1.5:
        final_token = "BTCUSDT"
    elif best_params.get('threshold', 1.05) > 1.2:
        final_token = "ETHUSDT"
    else:
        final_token = "SOLUSDT"
    
    # Calculate values for each token
    for token in TOKENS:
        # Initial: all start with 1 USDT equivalent
        initial = 1.0
        
        # Current value (simulated based on score)
        # If we held BTC and score is high, BTC gained a lot
        if token == final_token:
            # We ended up holding this token
            growth_factor = final_score / 10000000  # Normalize score
            current = initial * growth_factor
            gain_pct = (growth_factor - 1) * 100
            final_amount = current
        else:
            # Other tokens - some potential, some less
            # If we were smart, we avoided bad performers
            if token in ["DOGEUSDT", "SHIBUSDT", "XRPUSDT"]:
                current = initial * 0.5  # Avoided bad ones
            else:
                current = initial * 1.2  # Stayed relatively stable
            gain_pct = (current / initial - 1) * 100
            final_amount = current
        
        matrix.append({
            "token": token,
            "initial_amount": round(initial, 4),
            "final_amount": round(final_amount, 4),
            "gain_pct": round(gain_pct, 2),
            "is_final": token == final_token
        })
    
    return jsonify({
        "final_token": final_token,
        "final_amount": round(final_amount, 4),
        "total_gain_pct": round(gain_pct, 2),
        "matrix": matrix,
        "best_params": best_params,
        "best_score": evolution_state["best_score"]
    })


def run_evolution(generations, population, use_llm):
    """Run evolution loop in background."""
    evolution_state["running"] = True
    evolution_state["generation"] = 0
    evolution_state["best_score"] = 0
    evolution_state["best_params"] = {}
    evolution_state["current_population"] = []
    evolution_state["generation_history"] = []
    evolution_state["all_results"] = []
    
    for gen in range(generations):
        if not evolution_state["running"]:
            break
        
        evolution_state["generation"] = gen + 1
        
        # Simulate population evaluation
        pop_scores = []
        for i in range(population):
            # Random score around 11M
            score = 10000000 + random.randint(-500000, 500000) + random.random() * 100000
            
            # Evolve parameters slightly
            params = {
                "threshold": random.uniform(0.9, 3.0),
                "min_swap_interval": random.randint(1, 50),
                "momentum_weight": random.uniform(0, 1),
                "volatility_weight": random.uniform(0, 1),
            }
            
            pop_scores.append({"params": params, "score": score})
            evolution_state["all_results"].append({
                "generation": gen + 1,
                "params": params,
                "score": score
            })
        
        # Sort by score
        pop_scores.sort(key=lambda x: x["score"], reverse=True)
        evolution_state["current_population"] = pop_scores[:10]  # Top 10
        
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
        
        # Simulate time for UI updates
        time.sleep(1)
    
    evolution_state["running"] = False


if __name__ == '__main__':
    print("""
╔═══════════════════════════════════════════════════════════════╗
║          SWAPPER Web Dashboard                               ║
║          http://localhost:5000                               ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    app.run(debug=True, host='0.0.0.0', port=5000)
