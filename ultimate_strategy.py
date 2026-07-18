#!/usr/bin/env python3
"""
ULTIMATE STRATEGY FINDER - Szukamy najlepszej kombinacji strategii
"""

import csv
import json
from collections import defaultdict

FEE = 0.9996 * 0.9996

# Load data
tokens = []
prices = {}

with open('market.csv', 'r') as f:
    reader = csv.reader(f)
    header = next(reader)
    for i, col in enumerate(header):
        if col.endswith('_BID'):
            t = col.replace('_BID', '')
            tokens.append(t)
            prices[t] = []
    for row in reader:
        for i, t in enumerate(tokens):
            idx = 1 + i * 2
            if idx < len(row):
                try:
                    prices[t].append(float(row[idx]))
                except:
                    pass

min_len = min(len(prices[t]) for t in tokens)

def momentum(t, idx, period):
    if idx < period: return 0
    return (prices[t][idx] - prices[t][idx-period]) / prices[t][idx-period]

def detect_regime(idx, lookback=50):
    btc_now = prices['BTCUSDT'][idx]
    btc_then = prices['BTCUSDT'][max(0, idx-lookback)]
    change = (btc_now - btc_then) / btc_then
    if change > 0.05: return 'bullish'
    elif change < -0.05: return 'bearish'
    return 'neutral'

def run_strategy(start, end, lb=10, th=0.015, iv=15, regime_adaptive=False):
    """Uruchom strategię."""
    holding = 'BTCUSDT'
    amount = 1.0
    last_swap = 0
    
    for idx in range(start, end):
        if idx - last_swap < iv:
            continue
        
        # Regime-adaptive parameters
        if regime_adaptive:
            regime = detect_regime(idx)
            if regime == 'bearish':
                use_lb, use_th = 5, 0.010
            elif regime == 'bullish':
                use_lb, use_th = 20, 0.025
            else:
                use_lb, use_th = lb, th
        else:
            use_lb, use_th = lb, th
        
        holding_mom = momentum(holding, idx, use_lb)
        best_token = None
        best_mom = 999
        
        for token in tokens:
            if token == holding:
                continue
            token_mom = momentum(token, idx, use_lb)
            if token_mom < best_mom and token_mom < holding_mom:
                best_mom = token_mom
                best_token = token
        
        if best_token and (holding_mom - best_mom) > use_th:
            from_p = prices[holding][idx]
            to_p = prices[best_token][idx]
            amount = amount * from_p * FEE / to_p
            holding = best_token
            last_swap = idx
    
    return holding, amount

def get_gain(start, end, holding, amount):
    value = amount * prices[holding][end]
    btc = prices['BTCUSDT'][end]
    return ((value / btc) - 1) * 100

print("""
╔═══════════════════════════════════════════════════════════════╗
║     ULTIMATE STRATEGY FINDER                            ║
║     Szukamy najlepszej kombinacji                      ║
╚═══════════════════════════════════════════════════════════════╝
""")

# Analyze regime distribution
print("=== ANALIZA REGIME ===")
periods = [
    (100, 60000, "OKRES 1"),
    (60000, 120000, "OKRES 2"),
    (120000, 180000, "OKRES 3"),
    (180000, min_len-1, "OKRES 4"),
]

for start, end, name in periods:
    regimes = {'bullish': 0, 'neutral': 0, 'bearish': 0}
    for idx in range(start, min(end, start+10000)):
        r = detect_regime(idx)
        regimes[r] += 1
    total = sum(regimes.values())
    print(f"{name}:")
    for k, v in regimes.items():
        print(f"  {k}: {v/total*100:.1f}%")
    print()

print("=== TESTUJ RÓŻNE PODEJŚCIA ===")
print()

# Podejscie 1: Best single
print("1. Best single (L10 T1.5% I15):")
results1 = []
for start, end, name in periods:
    h, a = run_strategy(start, end, lb=10, th=0.015, iv=15)
    g = get_gain(start, end, h, a)
    results1.append(g)
    print(f"  {name}: {g:+.1f}%")
print(f"  MIN: {min(results1):+.1f}%, AVG: {sum(results1)/4:+.1f}%")

# Podejscie 2: Regime-adaptive
print()
print("2. Regime-adaptive (różne params na różne regime):")
results2 = []
for start, end, name in periods:
    h, a = run_strategy(start, end, regime_adaptive=True)
    g = get_gain(start, end, h, a)
    results2.append(g)
    print(f"  {name}: {g:+.1f}%")
print(f"  MIN: {min(results2):+.1f}%, AVG: {sum(results2)/4:+.1f}%")

# Podejscie 3: Grid search all
print()
print("3. Grid search all combinations:")

best_result = None
best_min = -999

for lb in [5, 10, 15, 20, 30]:
    for th in [0.005, 0.010, 0.015, 0.020, 0.025, 0.030]:
        for iv in [5, 10, 15, 20, 30]:
            gains = []
            for start, end, _ in periods:
                h, a = run_strategy(start, end, lb, th, iv)
                g = get_gain(start, end, h, a)
                gains.append(g)
            
            min_gain = min(gains)
            
            if min_gain > best_min:
                best_min = min_gain
                best_result = (lb, th, iv, gains)

lb, th, iv, gains = best_result
print(f"  Best: L{lb} T{th} I{iv}")
for i, (start, end, name) in enumerate(periods):
    print(f"    {name}: {gains[i]:+.1f}%")
print(f"  MIN: {best_min:+.1f}%, AVG: {sum(gains)/4:+.1f}%")

# Podejscie 4: Ensemble voting
print()
print("4. Ensemble voting (3 best strategies):")

def ensemble_vote(start, end):
    """Głosowanie 3 najlepszych strategii."""
    strategies = [
        (10, 0.015, 15),
        (20, 0.020, 15),
        (5, 0.010, 10),
    ]
    
    votes = defaultdict(float)
    holding = 'BTCUSDT'
    amount = 1.0
    last_swap = 0
    
    for idx in range(start, end):
        if idx - last_swap < 10:
            continue
        
        # Każda strategia głosuje
        token_scores = defaultdict(float)
        for lb, th, iv in strategies:
            holding_mom = momentum(holding, idx, lb)
            best_token = None
            best_mom = 999
            
            for token in tokens:
                if token == holding:
                    continue
                token_mom = momentum(token, idx, lb)
                if token_mom < best_mom and token_mom < holding_mom:
                    best_mom = token_mom
                    best_token = token
            
            if best_token and (holding_mom - best_mom) > th:
                token_scores[best_token] += 1
        
        # Decyduj przez głosowanie
        if token_scores:
            best = max(token_scores.items(), key=lambda x: x[1])
            if best[1] >= 2:  # Większość głosów
                to_token = best[0]
                if to_token != holding:
                    from_p = prices[holding][idx]
                    to_p = prices[to_token][idx]
                    amount = amount * from_p * FEE / to_p
                    holding = to_token
                    last_swap = idx
    
    return holding, amount

results4 = []
for start, end, name in periods:
    h, a = ensemble_vote(start, end)
    g = get_gain(start, end, h, a)
    results4.append(g)
    print(f"  {name}: {g:+.1f}%")
print(f"  MIN: {min(results4):+.1f}%, AVG: {sum(results4)/4:+.1f}%")

# Podejscie 5: Meta-strategy (switching strategies)
print()
print("5. Meta-strategy (switching strategies based on regime):")

def meta_strategy(start, end):
    """Switching między strategiami na podstawie regime."""
    holding = 'BTCUSDT'
    amount = 1.0
    last_swap = 0
    
    for idx in range(start, end):
        if idx - last_swap < 10:
            continue
        
        regime = detect_regime(idx)
        
        # Wybierz strategię na podstawie regime
        if regime == 'bearish':
            # Szybka, agresywna
            lb, th = 5, 0.010
        elif regime == 'bullish':
            # Wolna, konserwatywna
            lb, th = 20, 0.025
        else:
            # Normalna
            lb, th = 10, 0.015
        
        holding_mom = momentum(holding, idx, lb)
        best_token = None
        best_mom = 999
        
        for token in tokens:
            if token == holding:
                continue
            token_mom = momentum(token, idx, lb)
            if token_mom < best_mom and token_mom < holding_mom:
                best_mom = token_mom
                best_token = token
        
        if best_token and (holding_mom - best_mom) > th:
            from_p = prices[holding][idx]
            to_p = prices[best_token][idx]
            amount = amount * from_p * FEE / to_p
            holding = best_token
            last_swap = idx
    
    return holding, amount

results5 = []
for start, end, name in periods:
    h, a = meta_strategy(start, end)
    g = get_gain(start, end, h, a)
    results5.append(g)
    print(f"  {name}: {g:+.1f}%")
print(f"  MIN: {min(results5):+.1f}%, AVG: {sum(results5)/4:+.1f}%")

# PODSUMOWANIE
print()
print("=" * 70)
print("PODSUMOWANIE WSZYSTKICH PODEJŚĆ")
print("=" * 70)
print()
print(f"{'Podejscie':<30} {'MIN':<10} {'AVG':<10}")
print("-" * 50)
print(f"{'1. Best Single':<30} {min(results1):>+8.1f}% {sum(results1)/4:>+8.1f}%")
print(f"{'2. Regime-Adaptive':<30} {min(results2):>+8.1f}% {sum(results2)/4:>+8.1f}%")
print(f"{'3. Grid Search':<30} {best_min:>+8.1f}% {sum(best_result[3])/4:>+8.1f}%")
print(f"{'4. Ensemble Voting':<30} {min(results4):>+8.1f}% {sum(results4)/4:>+8.1f}%")
print(f"{'5. Meta-Strategy':<30} {min(results5):>+8.1f}% {sum(results5)/4:>+8.1f}%")

# Zapisz najlepsze
print()
print("=" * 70)
print("NAJLEPSZE PODEJŚCIE:")
all_results = [
    ("Best Single", min(results1), results1),
    ("Regime-Adaptive", min(results2), results2),
    ("Grid Search", best_min, best_result[3]),
    ("Ensemble Voting", min(results4), results4),
    ("Meta-Strategy", min(results5), results5),
]
all_results.sort(key=lambda x: x[1], reverse=True)

for i, (name, min_g, gains) in enumerate(all_results):
    print(f"{i+1}. {name}: min={min_g:+.1f}%, avg={sum(gains)/4:+.1f}%")

# Save to file
output = {
    'all_approaches': [
        {
            'name': name,
            'min_gain': min_g,
            'avg_gain': sum(gains)/4,
            'gains': gains
        }
        for name, min_g, gains in all_results
    ],
    'best_params': {
        'lookback': best_result[0],
        'threshold': best_result[1],
        'interval': best_result[2]
    }
}

import os
os.makedirs('output', exist_ok=True)
with open('output/ultimate_results.json', 'w') as f:
    json.dump(output, f, indent=2)

print()
print("Zapisano do: output/ultimate_results.json")
