#!/usr/bin/env python3
"""
PROPER BACKTESTER - Prawidłowe użycie BID/ASK

Swap: SELL BTC_BID → BUY ALT_ASK
Fee: 0.04% x 2 = 0.08%
"""

import csv
import json
import os

FEE_SELL = 0.9996
FEE_BUY = 0.9996


def load_data():
    tokens = []
    bid_prices = {}
    ask_prices = {}
    
    with open('market.csv', 'r') as f:
        reader = csv.reader(f)
        header = next(reader)
        
        for i, col in enumerate(header):
            if col.endswith('_BID'):
                t = col.replace('_BID', '')
                tokens.append(t)
                bid_prices[t] = []
            elif col.endswith('_ASK'):
                t = col.replace('_ASK', '')
                if t not in ask_prices:
                    ask_prices[t] = []
        
        for row in reader:
            for i, t in enumerate(tokens):
                bid_idx = 1 + i * 2
                ask_idx = bid_idx + 1
                
                if bid_idx < len(row) and ask_idx < len(row):
                    try:
                        bid_prices[t].append(float(row[bid_idx]))
                    except:
                        bid_prices[t].append(0)
                    try:
                        ask_prices[t].append(float(row[ask_idx]))
                    except:
                        ask_prices[t].append(0)
    
    min_len = min(len(bid_prices[t]) for t in tokens)
    for t in tokens:
        bid_prices[t] = bid_prices[t][:min_len]
        ask_prices[t] = ask_prices[t][:min_len]
    
    return tokens, bid_prices, ask_prices, min_len


def momentum(token, idx, period, bid_prices):
    if idx < period:
        return 0
    past = bid_prices[token][idx - period]
    now = bid_prices[token][idx]
    if past <= 0:
        return 0
    return (now - past) / past


def run_strategy(tokens, bid_prices, ask_prices, n_records, 
                lookback, threshold, interval, start_idx=100, end_idx=None):
    if end_idx is None:
        end_idx = n_records - 1
    
    btc_ask_start = ask_prices['BTCUSDT'][start_idx]
    usdt = 1.0 * btc_ask_start
    
    baseline = {}
    for token in tokens:
        token_ask_start = ask_prices[token][start_idx]
        if token_ask_start > 0:
            baseline[token] = usdt / token_ask_start
        else:
            baseline[token] = 0
    
    holding = 'BTCUSDT'
    amount = 1.0
    last_swap_idx = 0
    swaps = []
    
    for idx in range(start_idx, end_idx):
        if idx - last_swap_idx < interval:
            continue
        if idx < lookback:
            continue
        
        holding_mom = momentum(holding, idx, lookback, bid_prices)
        
        best_token = None
        best_mom = 999
        
        for token in tokens:
            if token == holding:
                continue
            if bid_prices[token][idx] < 0.001:
                continue
            
            token_mom = momentum(token, idx, lookback, bid_prices)
            
            if token_mom < best_mom and token_mom < holding_mom:
                best_mom = token_mom
                best_token = token
        
        if best_token and (holding_mom - best_mom) > threshold:
            from_bid = bid_prices[holding][idx]
            to_ask = ask_prices[best_token][idx]
            
            if from_bid > 0 and to_ask > 0:
                usdt_out = amount * from_bid * FEE_SELL
                new_amount = usdt_out / to_ask * FEE_BUY
                
                swaps.append({
                    'idx': idx,
                    'from': holding,
                    'to': best_token,
                    'diff': holding_mom - best_mom
                })
                
                holding = best_token
                amount = new_amount
                last_swap_idx = idx
    
    final_bid = bid_prices[holding][end_idx]
    final_value = amount * final_bid
    btc_final_bid = bid_prices['BTCUSDT'][end_idx]
    btc_value = 1.0 * btc_final_bid
    
    current_usdt = amount * final_bid
    actual = {}
    for token in tokens:
        token_ask_end = ask_prices[token][end_idx]
        if token_ask_end > 0:
            actual[token] = current_usdt / token_ask_end
    
    matrix = []
    for token in tokens:
        bl = baseline[token]
        ac = actual.get(token, 0)
        gain = ((ac / bl) - 1) * 100 if bl > 0 else 0
        matrix.append({
            'token': token,
            'baseline': bl,
            'actual': ac,
            'gain_pct': gain,
            'is_final': token == holding
        })
    
    matrix.sort(key=lambda x: x['gain_pct'], reverse=True)
    
    return {
        'strategy': {'lookback': lookback, 'threshold': threshold, 'interval': interval},
        'summary': {
            'final_token': holding,
            'final_amount': amount,
            'final_value': final_value,
            'vs_btc': ((final_value / btc_value) - 1) * 100,
            'n_swaps': len(swaps)
        },
        'matrix': matrix,
        'swaps': swaps[-30:]
    }


def main():
    print("""
╔═══════════════════════════════════════════════════════════════╗
║     PROPER BACKTESTER - Prawidłowe BID/ASK           ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    print("Loading data...")
    tokens, bid_prices, ask_prices, n_records = load_data()
    print(f"Loaded {n_records} records, {len(tokens)} tokens")
    
    # Walk-forward
    periods = [
        (100, 60000, "OK1"),
        (60000, 120000, "OK2"),
        (120000, 180000, "OK3"),
        (180000, n_records - 1, "OK4"),
    ]
    
    best_result = None
    best_min = -999
    
    lookbacks = [5, 7, 10]
    thresholds = [0.02, 0.025, 0.03]
    intervals = [10, 12, 15]
    
    print(f"Testing {len(lookbacks) * len(thresholds) * len(intervals)} combinations...")
    
    for lb in lookbacks:
        for th in thresholds:
            for iv in intervals:
                gains = []
                for start, end, _ in periods:
                    r = run_strategy(tokens, bid_prices, ask_prices, n_records, lb, th, iv, start, end)
                    gains.append(r['summary']['vs_btc'])
                
                min_gain = min(gains)
                if min_gain > best_min:
                    best_min = min_gain
                    best_result = (lb, th, iv, gains)
    
    lb, th, iv, gains = best_result
    
    print()
    print(f"Best: L{lb} T{th*100:.1f}% I{iv}")
    for i, g in enumerate(gains):
        print(f"  OK{i+1}: {g:+.1f}%")
    print(f"Min: {min(gains):+.1f}%, Avg: {sum(gains)/4:+.1f}%")
    
    # Full test
    print()
    print("=" * 70)
    print("FULL TEST")
    print("=" * 70)
    
    result = run_strategy(tokens, bid_prices, ask_prices, n_records, lb, th, iv)
    
    print(f"Strategy: L{lb} T{th*100:.1f}% I{iv}")
    print(f"Final: {result['summary']['final_amount']:,.2f} {result['summary']['final_token']}")
    print(f"Value: ${result['summary']['final_value']:,.2f}")
    print(f"vs BTC: {result['summary']['vs_btc']:+.1f}%")
    print(f"Swaps: {result['summary']['n_swaps']}")
    
    # Matrix
    print()
    print("=" * 70)
    print("MACIERZ")
    print("=" * 70)
    print()
    print(f"{'TOKEN':<12} {'BASELINE':>15} {'ACTUAL':>15} {'GAIN %':>10}")
    print("-" * 55)
    
    for row in result['matrix'][:10]:
        marker = " ◄◄" if row['is_final'] else ""
        print(f"{row['token']:<12} {row['baseline']:>15,.2f} {row['actual']:>15,.2f} {row['gain_pct']:>+9.1f}%{marker}")
    
    # Save
    os.makedirs('output/strategies', exist_ok=True)
    with open('output/strategies/CHAMPION_PROPER.json', 'w') as f:
        json.dump({
            'strategy': {'name': 'CHAMPION_PROPER', 'lookback': lb, 'threshold': th, 'interval': iv},
            'walk_forward': {'gains': gains},
            'result': result
        }, f, indent=2)
    
    with open('output/real_time_results.json', 'w') as f:
        json.dump(result, f, indent=2)
    
    print()
    print(f"Saved to: output/strategies/CHAMPION_PROPER.json")


if __name__ == "__main__":
    main()
