"""
Mexc API client for fetching ticker data.
"""

import json
import requests
from datetime import datetime
from typing import Dict, List

from config import MEXC_API_URL, TOP_N_TOKENS


class MexcClient:
    """
    Client for Mexc exchange API.
    """
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (MatrixSwap/1.0)',
            'Accept': 'application/json'
        })
        self.top_symbols: List[str] = []
        self.tick_log: List[dict] = []  # Log all ticks for verification
    
    def fetch_all_tickers(self) -> Dict[str, dict]:
        """Fetch all available tickers from Mexc."""
        try:
            response = self.session.get(MEXC_API_URL, timeout=10)
            
            if response.status_code != 200:
                print(f"Mexc API error: {response.status_code}")
                return {}
            
            data = response.json()
            
            result = {}
            for ticker in data:
                symbol = ticker.get('symbol', '')
                bid = self._parse_float(ticker.get('bidPrice') or ticker.get('bid'))
                ask = self._parse_float(ticker.get('askPrice') or ticker.get('ask'))
                
                if symbol and bid > 0 and ask > 0:
                    result[symbol] = {'bid': bid, 'ask': ask}
            
            return result
            
        except Exception as e:
            print(f"Error fetching tickers: {e}")
            return {}
    
    def get_top_tokens(self, all_tickers: Dict[str, dict], n: int = TOP_N_TOKENS) -> Dict[str, dict]:
        """Filter tickers to top N."""
        usdt_pairs = {
            symbol: data 
            for symbol, data in all_tickers.items() 
            if symbol.endswith('USDT')
        }
        
        sorted_symbols = sorted(usdt_pairs.keys())
        top_symbols = sorted_symbols[:n]
        
        self.top_symbols = top_symbols
        
        return {symbol: usdt_pairs[symbol] for symbol in top_symbols}
    
    def fetch_top_tokens(self) -> Dict[str, dict]:
        """Fetch only the top N tokens."""
        all_tickers = self.fetch_all_tickers()
        return self.get_top_tokens(all_tickers, TOP_N_TOKENS)
    
    def fetch_specific_tokens(self, symbols: List[str]) -> Dict[str, dict]:
        """Fetch specific tokens by symbol."""
        all_tickers = self.fetch_all_tickers()
        
        result = {}
        for symbol in symbols:
            if symbol in all_tickers:
                result[symbol] = all_tickers[symbol]
        
        return result
    
    def log_tick(self, token_prices: Dict[str, dict], holding: str, qty: float, swap_info: dict = None):
        """Log tick data for verification."""
        tick = {
            'timestamp': datetime.now().isoformat(),
            'holding': holding,
            'qty': qty,
            'prices': {s: {'bid': p['bid'], 'ask': p['ask']} for s, p in token_prices.items()},
            'swap': swap_info
        }
        self.tick_log.append(tick)
        
        if len(self.tick_log) > 10000:
            self.tick_log = self.tick_log[-10000:]
    
    def save_tick_log(self, filepath: str = "tick_log.json"):
        """Save tick log to file."""
        with open(filepath, 'w') as f:
            json.dump({
                'logged_at': datetime.now().isoformat(),
                'total_ticks': len(self.tick_log),
                'ticks': self.tick_log
            }, f, indent=2)
        print(f"✅ Saved {len(self.tick_log)} ticks to {filepath}")
    
    @staticmethod
    def _parse_float(value) -> float:
        """Safely parse float from various formats."""
        if value is None:
            return 0.0
        try:
            return float(str(value).replace(',', '.'))
        except (ValueError, TypeError):
            return 0.0


def get_top_volume_tokens(client: MexcClient, n: int = TOP_N_TOKENS) -> List[str]:
    """Get top N tokens by volume."""
    high_volume_tokens = [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
        "ADAUSDT", "AVAXUSDT", "DOTUSDT", "LINKUSDT", "MATICUSDT",
        "UNIUSDT", "LTCUSDT", "ATOMUSDT", "NEARUSDT", "APTUSDT",
        "ARBUSDT", "OPUSDT", "INJUSDT", "SUIUSDT", "SEIUSDT",
        "FTMUSDT", "ALGOUSDT", "XLMUSDT", "VETUSDT", "ICPUSDT",
        "FILUSDT", "HBARUSDT", "AAVEUSDT", "GRTUSDT", "SANDUSDT",
        "MANAUSDT", "AXSUSDT", "EOSUSDT", "THETAUSDT", "XTZUSDT",
        "CHZUSDT", "ENJUSDT", "ZILUSDT", "BATUSDT", "CRVUSDT",
        "1INCHUSDT", "LRCUSDT", "KAVAUSDT", "DASHUSDT",
        "COMPUSDT", "MKRUSDT", "SNXUSDT", "YFIUSDT", "ZECUSDT"
    ]
    
    return high_volume_tokens[:n]
