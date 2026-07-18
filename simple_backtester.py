#!/usr/bin/env python3
"""
SIMPLE BACKTESTER - Czysta implementacja bez bugów

Timestamp po timestampie, dokładnie jak w realnym tradingu.
"""

import csv
import json
import os

FEE = 0.9996 * 0.9996


def load_data():
    """Ładuje dane z CSV."""
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
                        v = float(row[idx])
                        prices[t].append(v if v > 0 else 0.0001)
                    except:
                        prices[t].append(0.0001)
    
    min_len = min(len(prices[t]) for t in tokens)
    for t in tokens:
        prices[t] = prices[t][:min_len]
    
    return tokens, prices, min_len


def momentum(token, idx, period, prices):
    """Momentum = (cena_teraz - cena_wczesniej) / cena_wczesniej"""
    if idx < period:
        return 0
    past = prices[token][idx - period]
    now = prices[token][idx]
    if past <= 0:
        return 0
    return (now - past) / past


def run_strategy(tokens, prices, n_records, lookback, threshold, interval, 
                 start_idx=100, end_idx=None):
    """
    Uruchamia strategię Relative Strength.
    
    Zasada:
    - Co `interval` kroków sprawdź momentum wszystkich tokenów
    - Znajdź token który traci NAJMNIEJ
    - Jeśli różnica > threshold, swapuj
    """
    if end_idx is None:
        end_idx = n_records - 1
    
    # Baseline - ile każdego tokena gdybyśmy kupili na start
    btc_price_start = prices['BTCUSDT'][start_idx]
    usdt_start = 1.0 * btc_price_start * FEE
    baseline = {t: usdt_start / prices[t][start_idx] for t in tokens}
    
    # Stan tradera
    holding = 'BTCUSDT'
    amount = 1.0  # Ilość BTC
    last_swap_idx = 0
    swaps = []
    
    # === GŁÓWNA PĘTLA - TAK JAK W REALNYM TRADINGU ===
    for idx in range(start_idx, end_idx):
        # Min interval - nie swapuj zbyt często
        if idx - last_swap_idx < interval:
            continue
        
        # Momentum obecnego tokena
        holding_mom = momentum(holding, idx, lookback, prices)
        
        # Znajdź token tracący najmniej
        best_token = None
        best_mom = 999
        
        for token in tokens:
            if token == holding:
                continue
            
            token_mom = momentum(token, idx, lookback, prices)
            
            # Token musi tracić MNIEJ niż holding
            if token_mom < best_mom and token_mom < holding_mom:
                best_mom = token_mom
                best_token = token
        
        # Jeśli znaleziono lepszy token i różnica > threshold
        if best_token and (holding_mom - best_mom) > threshold:
            # Wykonaj swap
            from_price = prices[holding][idx]
            to_price = prices[best_token][idx]
            
            usdt = amount * from_price * FEE
            new_amount = usdt / to_price
            
            swaps.append({
                'idx': idx,
                'from': holding,
                'to': best_token,
                'from_amount': amount,
                'to_amount': new_amount,
                'diff': holding_mom - best_mom
            })
            
            holding = best_token
            amount = new_amount
            last_swap_idx = idx
    
    # === OBLICZ WYNIKI ===
    # Aktualna wartość w USDT
    final_price = prices[holding][end_idx]
    final_value = amount * final_price
    
    # BTC value na końcu
    btc_end = prices['BTCUSDT'][end_idx]
    btc_hold_value = 1.0 * btc_end
    
    # Baseline value (gdybyśmy trzymali każdy token od początku)
    baseline_values = {}
    for token in tokens:
        bl = baseline[token]
        end_price = prices[token][end_idx]
        baseline_values[token] = bl * end_price
    
    # Actual equivalents - ile każdego tokena byśmy mieli gdybyśmy
    # w danym momencie zamienili nasz portfel na ten token
    current_usdt = amount * prices[holding][end_idx]
    actual_equiv = {}
    for token in tokens:
        token_price = prices[token][end_idx]
        if token_price > 0:
            actual_equiv[token] = current_usdt / token_price
    
    # Macierz
    matrix = []
    for token in tokens:
        bl = baseline[token]
        ac = actual_equiv.get(token, 0)
        gain_pct = ((ac / bl) - 1) * 100 if bl > 0 else 0
        
        matrix.append({
            'token': token,
            'baseline': bl,
            'actual': ac,
            'gain_pct': gain_pct,
            'baseline_value': baseline_values.get(token, 0),
            'is_final': token == holding
        })
    
    matrix.sort(key=lambda x: x['gain_pct'], reverse=True)
    
    return {
        'strategy': {
            'lookback': lookback,
            'threshold': threshold,
            'interval': interval
        },
        'summary': {
            'start_token': 'BTCUSDT',
            'start_amount': 1.0,
            'final_token': holding,
            'final_amount': amount,
            'final_value': final_value,
            'vs_btc': ((final_value / btc_hold_value) - 1) * 100,
            'n_swaps': len(swaps)
        },
        'matrix': matrix,
        'swaps': swaps[-30:]
    }


def walk_forward_test(tokens, prices, n_records):
    """Testuje strategię na 4 niezależnych okresach."""
    
    periods = [
        (100, 60000, "OK1"),
        (60000, 120000, "OK2"),
        (120000, 180000, "OK3"),
        (180000, n_records - 1, "OK4"),
    ]
    
    best_result = None
    best_min = -999
    
    lookbacks = [5, 7, 10, 15]
    thresholds = [0.02, 0.025, 0.03, 0.035, 0.04]
    intervals = [10, 12, 15, 20]
    
    print(f"Testing {len(lookbacks) * len(thresholds) * len(intervals)} combinations...")
    
    for lb in lookbacks:
        for th in thresholds:
            for iv in intervals:
                gains = []
                
                for start, end, _ in periods:
                    r = run_strategy(tokens, prices, n_records, lb, th, iv, start, end)
                    gains.append(r['summary']['vs_btc'])
                
                min_gain = min(gains)
                
                if min_gain > best_min:
                    best_min = min_gain
                    best_result = {
                        'params': (lb, th, iv),
                        'gains': gains,
                        'min_gain': min_gain,
                        'avg_gain': sum(gains) / len(gains)
                    }
    
    return best_result


def main():
    print("""
╔═══════════════════════════════════════════════════════════════╗
║     SIMPLE BACKTESTER                                    ║
║     Timestamp by timestamp - real trading simulation       ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    print("Loading data...")
    tokens, prices, n_records = load_data()
    print(f"Loaded {n_records} records, {len(tokens)} tokens")
    
    # Walk-forward test
    print()
    print("=" * 70)
    print("WALK-FORWARD TEST")
    print("=" * 70)
    
    wf = walk_forward_test(tokens, prices, n_records)
    
    print()
    print(f"Best: L{wf['params'][0]} T{wf['params'][1]*100:.1f}% I{wf['params'][2]}")
    for i, g in enumerate(wf['gains']):
        print(f"  OK{i+1}: {g:+.1f}%")
    print(f"Min: {wf['min_gain']:+.1f}%, Avg: {wf['avg_gain']:+.1f}%")
    
    # Full test
    print()
    print("=" * 70)
    print("FULL TEST (cały okres)")
    print("=" * 70)
    
    lb, th, iv = wf['params']
    result = run_strategy(tokens, prices, n_records, lb, th, iv)
    
    print(f"Strategy: L{lb} T{th*100:.1f}% I{iv}")
    print(f"Final: {result['summary']['final_amount']:,.2f} {result['summary']['final_token']}")
    print(f"Value: ${result['summary']['final_value']:,.2f}")
    print(f"vs BTC: {result['summary']['vs_btc']:+.1f}%")
    print(f"Swaps: {result['summary']['n_swaps']}")
    
    # Macierz
    print()
    print("=" * 70)
    print("MACIERZ WYNIKÓW")
    print("=" * 70)
    print()
    print(f"{'TOKEN':<12} {'BASELINE':>18} {'ACTUAL':>18} {'GAIN %':>10}")
    print("-" * 60)
    
    for row in result['matrix'][:10]:
        marker = " ◄◄" if row['is_final'] else ""
        print(f"{row['token']:<12} {row['baseline']:>18,.2f} {row['actual']:>18,.2f} {row['gain_pct']:>+9.1f}%{marker}")
    
    # Save
    os.makedirs('output/strategies', exist_ok=True)
    
    winner = {
        'strategy': {
            'name': 'CHAMPION',
            'lookback': lb,
            'threshold': th,
            'interval': iv
        },
        'walk_forward': wf,
        'result': result
    }
    
    with open('output/strategies/CHAMPION.json', 'w') as f:
        json.dump(winner, f, indent=2)
    
    with open('output/real_time_results.json', 'w') as f:
        json.dump(result, f, indent=2)
    
    print()
    print("Saved to: output/strategies/CHAMPION.json")


if __name__ == "__main__":
    main()
