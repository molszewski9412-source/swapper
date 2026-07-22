"""
Alert System for Matrix Swap v2

Sends free notifications via Telegram when threshold is reached.
Tracks purchases and monitors from each buy tick.

FREE Options:
1. Telegram Bot - completely free, no limits ✅
2. ntfy.sh - free, open source
3. Discord Webhook - free
4. Email (Gmail App Password) - free
"""

import json
import time
import threading
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional, List
from config import FEE, INITIAL_USDT, POLL_INTERVAL_SEC


@dataclass
class PurchaseRecord:
    """Record of a token purchase."""
    symbol: str
    quantity: float
    buy_price: float  # Ask price at purchase
    buy_time: str
    buy_idx: int      # Tick index
    top_eq_at_buy: float  # Top EQ for this token at purchase
    usdt_value_at_buy: float  # USDT value at purchase


@dataclass
class AlertRecord:
    """Record of an alert sent."""
    timestamp: str
    alert_type: str  # "threshold_reached", "swap_executed", "summary"
    from_symbol: str
    to_symbol: str
    gain_pct: float
    message: str


class AlertSystem:
    """
    Alert system that tracks purchases and monitors for threshold alerts.
    
    Logic:
    1. When we BUY a token, record the purchase tick
    2. Monitor all tokens from that moment
    3. When ANY token reaches threshold (7%), send alert
    4. After swap, reset and track from new purchase
    """
    
    def __init__(self, telegram_token: str = None, telegram_chat_id: str = None):
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        
        # Purchase tracking
        self.current_purchase: Optional[PurchaseRecord] = None
        self.purchase_history: List[PurchaseRecord] = []
        
        # Alert tracking
        self.alerts: List[AlertRecord] = []
        self.last_alert_time = None
        
        # Monitored tokens at purchase time
        self.tokens_at_purchase: dict = {}
        
    def record_purchase(self, symbol: str, quantity: float, buy_price: float, 
                       buy_idx: int, top_eq: float, usdt_value: float):
        """Record a token purchase."""
        purchase = PurchaseRecord(
            symbol=symbol,
            quantity=quantity,
            buy_price=buy_price,
            buy_time=datetime.now().isoformat(),
            buy_idx=buy_idx,
            top_eq_at_buy=top_eq,
            usdt_value_at_buy=usdt_value
        )
        
        self.current_purchase = purchase
        self.purchase_history.append(purchase)
        
        self.send_telegram(
            f"🟢 **ZAKUP**\n\n"
            f"Token: {symbol}\n"
            f"Ilość: {quantity:.6f}\n"
            f"Cena: ${buy_price:.4f}\n"
            f"Wartość: ${usdt_value:.2f}\n"
            f"Threshold: 7%\n\n"
            f"_Czekam na okazję..._"
        )
        
    def check_threshold(self, tokens: dict, current_symbol: str) -> Optional[dict]:
        """
        Check if any token has reached threshold from purchase time.
        Returns token info if threshold reached, None otherwise.
        """
        if not self.current_purchase:
            return None
        
        purchase = self.current_purchase
        
        # Calculate USDT value of our current holding
        current_token = tokens.get(current_symbol)
        if not current_token:
            return None
        
        current_bid = current_token.get('current_bid', 0)
        current_ask = current_token.get('current_ask', 0)
        current_qty = self.get_current_quantity()
        
        if current_qty <= 0 or current_bid <= 0:
            return None
        
        usdt_value = current_qty * current_bid * (1 - FEE)
        
        # Check each token
        best_candidate = None
        best_gain = 0
        
        for symbol, token in tokens.items():
            if symbol == current_symbol:
                continue
            
            ask = token.get('current_ask', 0)
            if ask <= 0:
                continue
            
            # How many of this token could we buy?
            token_eq = usdt_value / (ask * (1 + FEE))
            
            # Compare to top_eq at purchase time for this token
            top_eq_at_purchase = self.tokens_at_purchase.get(symbol, {}).get('top_eq', token_eq)
            
            # Calculate gain from purchase moment
            if top_eq_at_purchase > 0:
                gain_pct = (token_eq - top_eq_at_purchase) / top_eq_at_purchase * 100
            else:
                gain_pct = 0
            
            if gain_pct > best_gain:
                best_gain = gain_pct
                best_candidate = {
                    'symbol': symbol,
                    'gain_pct': gain_pct,
                    'actual_eq': token_eq,
                    'top_eq': top_eq_at_purchase,
                    'current_ask': ask,
                    'current_bid': token.get('current_bid', 0)
                }
        
        # Check if current holding also gained
        holding_gain = (usdt_value - purchase.usdt_value_at_buy) / purchase.usdt_value_at_buy * 100
        
        # Return if threshold reached
        if best_gain >= 7.0 or holding_gain >= 7.0:
            return {
                'best_candidate': best_candidate if best_gain >= 7.0 else None,
                'best_gain': max(best_gain, holding_gain),
                'holding_gain': holding_gain,
                'usdt_value': usdt_value,
                'purchase': asdict(purchase)
            }
        
        return None
    
    def get_current_quantity(self) -> float:
        """Get current holding quantity from matrix."""
        # This will be updated by the main app
        return getattr(self, '_current_quantity', 0.0)
    
    def set_current_quantity(self, qty: float):
        """Set current holding quantity."""
        self._current_quantity = qty
    
    def capture_tokens_at_purchase(self, tokens: dict):
        """Capture token state at purchase moment."""
        self.tokens_at_purchase = {}
        for symbol, token in tokens.items():
            self.tokens_at_purchase[symbol] = {
                'top_eq': token.get('top_eq', 0),
                'actual_eq': token.get('actual_eq', 0),
                'gain_pct': token.get('gain_pct', 0)
            }
    
    def send_telegram(self, message: str):
        """Send message via Telegram (free!)."""
        if not self.telegram_token or not self.telegram_chat_id:
            print(f"[ALERT] {message}")
            return
        
        import requests
        
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        data = {
            'chat_id': self.telegram_chat_id,
            'text': message,
            'parse_mode': 'Markdown'
        }
        
        try:
            requests.post(url, data=data, timeout=10)
        except Exception as e:
            print(f"Telegram error: {e}")
    
    def send_swap_alert(self, from_symbol: str, to_symbol: str, gain_pct: float,
                        from_qty: float, to_qty: float, price: float):
        """Send alert when swap is executed."""
        alert = AlertRecord(
            timestamp=datetime.now().isoformat(),
            alert_type="swap_executed",
            from_symbol=from_symbol,
            to_symbol=to_symbol,
            gain_pct=gain_pct,
            message=f"SWAP: {from_symbol} → {to_symbol} | Gain: {gain_pct:.2f}%"
        )
        self.alerts.append(alert)
        
        self.send_telegram(
            f"🔄 **SWAP WYKONANY**\n\n"
            f"Z: {from_symbol}\n"
            f"Do: {to_symbol}\n"
            f"Ilość: {from_qty:.6f} → {to_qty:.4f}\n"
            f"Cena: ${price:.4f}\n"
            f"Gain: *{gain_pct:.2f}%*\n\n"
            f"_Resetuję monitoring od nowa..._"
        )
    
    def send_threshold_alert(self, best_candidate: dict, holding_gain: float):
        """Send alert when threshold is reached."""
        msg = f"🚨 **THRESHOLD 7% OSIĄGNIĘTY!**\n\n"
        
        if best_candidate and best_candidate.get('gain_pct', 0) >= 7.0:
            msg += f"Token: {best_candidate['symbol']}\n"
            msg += f"Gain: *{best_candidate['gain_pct']:.2f}%*\n"
            msg += f"Top EQ: {best_candidate['top_eq']:.2f}\n"
            msg += f"Actual EQ: {best_candidate['actual_eq']:.2f}\n\n"
        
        if holding_gain >= 7.0:
            msg += f"📈 HODL Gain: *{holding_gain:.2f}%*\n\n"
        
        msg += f"Sprawdzam możliwość swapu..."
        
        self.send_telegram(msg)
    
    def send_daily_summary(self, swap_count: int, current_symbol: str, 
                          usdt_value: float, best_gain: float):
        """Send daily summary."""
        self.send_telegram(
            f"📊 **PODSUMOWANIE DNIA**\n\n"
            f"Holding: {current_symbol}\n"
            f"Swapy: {swap_count}\n"
            f"Wartość: ${usdt_value:.2f}\n"
            f"Best opportunity: {best_gain:.2f}%\n\n"
            f"_Threshold: 7%_"
        )
    
    def get_status(self) -> dict:
        """Get current alert system status."""
        return {
            'current_purchase': asdict(self.current_purchase) if self.current_purchase else None,
            'purchase_count': len(self.purchase_history),
            'alert_count': len(self.alerts),
            'last_alert': asdict(self.alerts[-1]) if self.alerts else None
        }
    
    def save_state(self, filepath: str = 'alert_state.json'):
        """Save alert state to file."""
        data = {
            'current_purchase': asdict(self.current_purchase) if self.current_purchase else None,
            'purchase_history': [asdict(p) for p in self.purchase_history],
            'alerts': [asdict(a) for a in self.alerts]
        }
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
    
    def load_state(self, filepath: str = 'alert_state.json') -> bool:
        """Load alert state from file."""
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            if data.get('current_purchase'):
                self.current_purchase = PurchaseRecord(**data['current_purchase'])
            
            self.purchase_history = [
                PurchaseRecord(**p) for p in data.get('purchase_history', [])
            ]
            
            self.alerts = [
                AlertRecord(**a) for a in data.get('alerts', [])
            ]
            
            return True
        except Exception as e:
            print(f"Error loading alert state: {e}")
            return False


def create_telegram_bot() -> tuple:
    """
    Create a Telegram bot (FREE!).
    
    Steps:
    1. Open Telegram and search for @BotFather
    2. Send /newbot
    3. Follow instructions, get BOT_TOKEN
    4. Search for your bot username, start chat
    5. Send any message, then get your CHAT_ID from:
       https://api.telegram.org/bot<TOKEN>/getUpdates
    
    Returns:
        (token, chat_id)
    """
    print("""
╔═══════════════════════════════════════════════════════════════╗
║              TWORZENIE TELEGRAM BOTA                         ║
║                  (CAŁKOWICIE ZA DARMO!)                      ║
╚═══════════════════════════════════════════════════════════════╝

KROKI:
1. Otwórz Telegram i wyszukaj @BotFather
2. Wyślij /newbot
3. Postępuj zgodnie z instrukcjami
4. Skopiuj BOT_TOKEN
5. Wyszukaj swojego bota i kliknij Start
6. Wyślij dowolną wiadomość
7. Pobierz CHAT_ID z linku (BotFather poda)

Więcej info: https://core.telegram.org/bots
    """)
    
    token = input("Wklej BOT_TOKEN: ").strip()
    chat_id = input("Wklej CHAT_ID: ").strip()
    
    return token, chat_id


if __name__ == "__main__":
    # Test alert system
    alert = AlertSystem()
    print("Alert System initialized")
    print(alert.get_status())
