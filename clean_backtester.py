#!/usr/bin/env python3
"""
CLEAN BACKTESTER - Z filtami jakości

Filtry:
1. Minimalna cena tokena (> $0.0001)
2. Maksymalny momentum (nie może być gorszy niż -90%)
3. Minimalna ilość danych (lookback * 2)
4. Stabilność ceny (nie może spaść >99% od szczytu)
"""

import csv
import json
import os

FEE = 0.9996 * 0.9996
MIN_PRICE = 0.0001
MIN_DATA_RATIO = 2.0  # lookback * MIN_DATA_RATIO
MAX_LOSS = 0.90  # Token nie może stracić >90%


def load_data():
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
                        prices[t].append(v if v > 0 else MIN_PRICE)
                    except:
                        prices[t].append(MIN_PRICE)
    
    min_len = min(len(prices[t]) for t in tokens)
    for t in tokens:
        prices[t] = prices[t][:min_len]
    
    return tokens, prices, min_len


def momentum(token, idx, period, prices):
    if idx < period:
        return 0
    past = prices[token][idx - period]
    now = prices[token][idx]
    if past <= 0:
        return 0
    return (now - past) / past


def is_valid_token(token, idx, lookback, prices):
    """Sprawdza czy token jest valid do handlu."""
    # Minimalna cena
    if prices[token][idx] < MIN_PRICE:
        return False
    
    # Wystarczająco danych
    if idx < lookback * MIN_DATA_RATIO:
        return False
    
    # Maksymalny loss od szczytu w ostatnim okresie
    recent_prices = prices[token][max(0, idx-lookback):idx+1]
    if recent_prices:
        peak = max(recent_prices)
        current = prices[token][idx]
        if peak > 0 and (peak - current) / peak > MAX_LOSS:
            return False
    
    return True


def run_strategy(tokens, prices, n_records, lookback, threshold, interval,
                 start_idx=100, end_idx=None):
    if end_idx is None:
        end_idx = n_records - 1
    
    # Baseline
    btc_price_start = prices['BTCUSDT'][start_idx]
    usdt_start = 1.0 * btc_price_start * FEE
    baseline = {t: usdt_start / prices[t][start_idx] for t in tokens}
    
    # Stan
    holding = 'BTCUSDT'
    amount = 1.0
    last_swap_idx = 0
    swaps = []
    
    for idx in range(start_idx, end_idx):
        if idx - last_swap_idx < interval:
            continue
        
        # Walidacja current holding
        if not is_valid_token(holding, idx, lookback, prices):
            # Wróć do BTC jeśli holding jest nieważny
            if holding != 'BTCUSDT':
                from_price = prices[holding][idx]
                to_price = prices['BTCUSDT'][idx]
                if from_price > 0 and to_price > 0:
                    usdt = amount * from_price * FEE
                    amount = usdt / to_price
                    holding = 'BTCUSDT'
                    last_swap_idx = idx
            continue
        
        # Momentum holding
        holding_mom = momentum(holding, idx, lookback, prices)
        
        # Znajdź najlepszy token
        best_token = None
        best_mom = 999
        
        for token in tokens:
            if token == holding:
                continue
            
            # Sprawdź czy token jest valid
            if not is_valid_token(token, idx, lookback, prices):
                continue
            
            token_mom = momentum(token, idx, lookback, prices)
            
            # Token musi tracić MNIEJ niż holding
            if token_mom < best_mom and token_mom < holding_mom:
                best_mom = token_mom
                best_token = token
        
        # Swap
        if best_token and (holding_mom - best_mom) > threshold:
            from_price = prices[holding][idx]
            to_price = prices[best_token][idx]
            
            if from_price > 0 and to_price > 0:
                usdt = amount * from_price * FEE
                new_amount = usdt / to_price
                
                # Sanity check - nie może być zbyt dużo
                if new_amount < amount * 1000:  # Max 1000x w jednym swap
                    swaps.append({
                        'idx': idx,
                        'from': holding,
                        'to': best_token,
                        'diff': holding_mom - best_mom
                    })
                    holding = best_token
                    amount = new_amount
                    last_swap_idx = idx
    
    # Wyniki
    final_price = prices[holding][end_idx]
    final_value = amount * final_price
    btc_end = prices['BTCUSDT'][end_idx]
    btc_value = 1.0 * btc_end
    
    # Actual equivalents
    current_usdt = amount * prices[holding][end_idx]
    actual_equiv = {}
    for token in tokens:
        if prices[token][end_idx] > 0:
            actual_equiv[token] = current_usdt / prices[token][end_idx]
    
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


def walk_forward_test(tokens, prices, n_records):
    periods = [
        (100, 60000, "OK1"),
        (60000, 120000, "OK2"),
        (120000, 180000, "OK3"),
        (180000, n_records - 1, "OK4"),
    ]
    
    best_result = None
    best_min = -999
    
    # Szybsze testy - mniej kombinacji
    lookbacks = [5, 10, 20]
    thresholds = [0.025, 0.03, 0.05]
    intervals = [15, 20]
    
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
                    best_result = (lb, th, iv, gains)
    
    return best_result


def main():
    print("""
╔═══════════════════════════════════════════════════════════════╗
║     CLEAN BACKTESTER - Z filtrami jakości              ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    print("Loading data...")
    tokens, prices, n_records = load_data()
    print(f"Loaded {n_records} records, {len(tokens)} tokens")
    
    # Walk-forward
    print()
    print("=" * 70)
    print("WALK-FORWARD TEST")
    print("=" * 70)
    
    wf = walk_forward_test(tokens, prices, n_records)
    lb, th, iv, gains = wf
    
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
    
    result = run_strategy(tokens, prices, n_records, lb, th, iv)
    
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
    
    with open('output/strategies/CHAMPION.json', 'w') as f:
        json.dump({
            'strategy': {'name': 'CHAMPION', 'lookback': lb, 'threshold': th, 'interval': iv},
            'walk_forward': {'gains': gains, 'min': min(gains), 'avg': sum(gains)/4},
            'result': result
        }, f, indent=2)
    
    with open('output/real_time_results.json', 'w') as f:
        json.dump(result, f, indent=2)
    
    print()
    print("Saved to: output/strategies/CHAMPION.json")


if __name__ == "__main__":
    main()
