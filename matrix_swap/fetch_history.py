#!/usr/bin/env python3
"""
Pobiera historyczne dane kryptowalutowe z Binance/Mexc do backtestu.
"""

import requests
import time
import csv
from datetime import datetime, timedelta
import os

# Konfiguracja
OUTPUT_FILE = "historical_data.csv"
TIMEFRAME = "15m"  # 1m, 5m, 15m, 1h, 4h, 1d
YEARS_BACK = 2  # Ile lat wstecz
TOP_N = 50  # Ile top tokenów pobrać

# Tokeny do śledzenia (główne) - Mexc format
TRACKED_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT",
    "ADAUSDT", "DOGEUSDT", "TRXUSDT", "AVAXUSDT", "DOTUSDT",
    "LINKUSDT", "MATICUSDT", "SHIBUSDT", "LTCUSDT", "ATOMUSDT",
    "UNIUSDT", "XLMUSDT", "ETCUSDT", "NEARUSDT", "APTUSDT",
    "FILUSDT", "ICPUSDT", "VETUSDT", "ALGOUSDT", "SANDUSDT",
    "MANAUSDT", "AXSUSDT", "AAVEUSDT", "THETAUSDT", "EGLDUSDT",
    "FTMUSDT", "EOSUSDT", "XTZUSDT", "MKRUSDT", "SNXUSDT",
    "COMPUSDT", "YFIUSDT", "CRVUSDT", "LRCUSDT", "ENJUSDT",
    "CHZUSDT", "ZECUSDT", "DASHUSDT", "KAVAUSDT", "BATUSDT",
    "HBARUSDT", "ZILUSDT", "INJUSDT", "SUIUSDT", "SEIUSDT"
]

# Binance ma BNBUSDT, Mexc ma BNBUSDT ale nie wszystkie tokeny

def get_binance_klines(symbol, interval, start_time, end_time):
    """Pobiera klines z Binance API"""
    url = "https://api.binance.com/api/v3/klines"
    all_klines = []
    
    start_ts = int(start_time.timestamp() * 1000)
    end_ts = int(end_time.timestamp() * 1000)
    
    while start_ts < end_ts:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": start_ts,
            "endTime": end_ts,
            "limit": 1000  # Max na request
        }
        
        try:
            response = requests.get(url, params=params, timeout=30)
            data = response.json()
            
            if isinstance(data, list) and len(data) > 0:
                all_klines.extend(data)
                # Następny request zacznij od ostatniego timestamp + 1
                start_ts = int(data[-1][0]) + 1
                print(f"  {symbol}: {len(all_klines)} records...")
            else:
                break
                
        except Exception as e:
            print(f"  Error: {e}")
            break
        
        time.sleep(0.2)  # Rate limit
    
    return all_klines

def get_mexc_klines(symbol, interval, start_time, end_time):
    """Pobiera klines z Mexc API"""
    url = f"https://api.mexc.com/api/v3/klines"
    all_klines = []
    
    # Mexc wymaga timestamp w sekundach
    start_ts = int(start_time.timestamp())
    end_ts = int(end_time.timestamp())
    
    interval_map = {
        "1m": "1m", "5m": "5m", "15m": "15m", 
        "1h": "1h", "4h": "4h", "1d": "1d"
    }
    mexc_interval = interval_map.get(interval, "15m")
    
    while start_ts < end_ts:
        params = {
            "symbol": symbol,
            "interval": mexc_interval,
            "startTime": start_ts,
            "endTime": end_ts,
            "limit": 1000
        }
        
        try:
            response = requests.get(url, params=params, timeout=30)
            data = response.json()
            
            if isinstance(data, list) and len(data) > 0:
                all_klines.extend(data)
                # Następny request
                start_ts = int(data[-1][0] / 1000) + 60
                print(f"  {symbol}: {len(all_klines)} records...")
            else:
                break
                
        except Exception as e:
            print(f"  Error: {e}")
            break
        
        time.sleep(0.2)
    
    return all_klines

def convert_to_bid_ask(klines):
    """
    Konwertuje OHLCV do BID/ASK.
    Używamy:
    - OPEN jako timestamp
    - HIGH jako ask (optymistyczna cena)
    - LOW jako bid (pesymistyczna cena)
    """
    result = []
    for k in klines:
        try:
            timestamp = int(k[0] / 1000) if isinstance(k[0], (int, float)) else int(float(k[0]))
            open_price = float(k[1])
            high_price = float(k[2])
            low_price = float(k[3])
            close_price = float(k[4])
            volume = float(k[5])
            
            # Bid = niska cena (pesymistyczna), Ask = wysoka (optymistyczna)
            bid = low_price
            ask = high_price
            
            result.append({
                'timestamp': timestamp,
                'bid': bid,
                'ask': ask,
                'close': close_price,
                'volume': volume
            })
        except:
            continue
    
    return result

def fetch_all_symbols(exchange="binance"):
    """Pobiera dane dla wszystkich symboli"""
    
    end_time = datetime.now()
    start_time = end_time - timedelta(days=365 * YEARS_BACK)
    
    print(f"📊 Pobieranie danych z {exchange.upper()}")
    print(f"   Timeframe: {TIMEFRAME}")
    print(f"   Okres: {start_time.strftime('%Y-%m-%d')} do {end_time.strftime('%Y-%m-%d')}")
    print(f"   Tokeny: {len(TRACKED_SYMBOLS)}")
    print()
    
    all_data = {}  # symbol -> list of klines
    
    for i, symbol in enumerate(TRACKED_SYMBOLS, 1):
        print(f"[{i}/{len(TRACKED_SYMBOLS)}] {symbol}...")
        
        if exchange == "binance":
            klines = get_binance_klines(symbol, TIMEFRAME, start_time, end_time)
        else:
            klines = get_mexc_klines(symbol, TIMEFRAME, start_time, end_time)
        
        if klines:
            all_data[symbol] = convert_to_bid_ask(klines)
            print(f"  ✓ {len(all_data[symbol])} records")
        else:
            print(f"  ✗ Brak danych")
        
        time.sleep(0.5)
    
    return all_data

def save_to_csv(all_data, output_file):
    """Zapisuje dane do CSV w formacie rynkowym"""
    
    if not all_data:
        print("❌ Brak danych do zapisania!")
        return
    
    # Znajdź wspólny zakres czasowy
    all_timestamps = set()
    for symbol, data in all_data.items():
        for d in data:
            all_timestamps.add(d['timestamp'])
    
    sorted_timestamps = sorted(all_timestamps)
    
    print(f"\n💾 Zapisywanie {len(sorted_timestamps)} timestampów...")
    
    # Header
    header = ["timestamp"]
    for symbol in sorted(all_data.keys()):
        header.extend([f"{symbol}_BID", f"{symbol}_ASK"])
    
    with open(output_file, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        
        # Zbuduj mapę danych
        data_map = {}
        for symbol, data in all_data.items():
            data_map[symbol] = {d['timestamp']: d for d in data}
        
        for ts in sorted_timestamps:
            row = [ts]
            for symbol in sorted(all_data.keys()):
                if ts in data_map[symbol]:
                    d = data_map[symbol][ts]
                    row.extend([d['bid'], d['ask']])
                else:
                    row.extend(['', ''])
            writer.writerow(row)
    
    print(f"✅ Zapisano do {output_file}")
    
    # Statystyki
    symbols_with_data = len([s for s, d in all_data.items() if d])
    total_records = len(sorted_timestamps)
    print(f"   Tokeny z danymi: {symbols_with_data}/{len(TRACKED_SYMBOLS)}")
    print(f"   Rekordy czasowe: {total_records}")
    print(f"   Okres: ~{total_records * 15 / 60 / 24:.1f} dni" if TIMEFRAME == "15m" else "")

def download_exchanges():
    """Pobiera dane z obu giełd"""
    
    # Binance
    print("\n" + "="*60)
    print("🟡 BINANCE")
    print("="*60)
    binance_data = fetch_all_symbols("binance")
    
    if binance_data:
        save_to_csv(binance_data, "binance_15m.csv")
    
    # Mexc
    print("\n" + "="*60)
    print("🟢 MEXC")
    print("="*60)
    mexc_data = fetch_all_symbols("mexc")
    
    if mexc_data:
        save_to_csv(mexc_data, "mexc_15m.csv")
    
    print("\n" + "="*60)
    print("📊 PODSUMOWANIE")
    print("="*60)
    print("Pobrane pliki:")
    print("  - binance_15m.csv")
    print("  - mexc_15m.csv")
    print("\nUżycie w backtest.py:")
    print("  python backtest.py --data binance_15m.csv")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Pobiera historyczne dane kryptowalutowe")
    parser.add_argument("--exchange", "-e", choices=["binance", "mexc", "both"], default="both",
                        help="Którą giełdę użyć")
    parser.add_argument("--timeframe", "-t", default="15m",
                        help="Timeframe: 1m, 5m, 15m, 1h, 4h, 1d")
    parser.add_argument("--years", "-y", type=int, default=2,
                        help="Ile lat wstecz")
    parser.add_argument("--output", "-o", 
                        help="Plik wyjściowy (dla pojedynczej giełdy)")
    
    args = parser.parse_args()
    
    TIMEFRAME = args.timeframe
    YEARS_BACK = args.years
    
    if args.exchange == "binance":
        data = fetch_all_symbols("binance")
        if data:
            save_to_csv(data, args.output or f"binance_{TIMEFRAME}.csv")
    elif args.exchange == "mexc":
        data = fetch_all_symbols("mexc")
        if data:
            save_to_csv(data, args.output or f"mexc_{TIMEFRAME}.csv")
    else:
        download_exchanges()
