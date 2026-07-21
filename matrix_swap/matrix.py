"""
Matrix - Core logic for token swap matrix

Key concepts:
- BASELINE: How many tokens we COULD have if we started with INITIAL_USDT at initialization
- ACTUAL_EQ: How many tokens we WOULD have if we swapped our current holding to USDT and bought target token
- TOP_EQ: Record high of ACTUAL_EQ for each token (only updated on swap!)
- GAIN: (actual_eq - top_eq) / top_eq - profit/loss vs record

Goal: Maximize TOKEN COUNT, not USDT value!
"""

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional
from datetime import datetime

from config import FEE, INITIAL_USDT


@dataclass
class TokenData:
    """Data for a single token in the matrix."""
    symbol: str          # e.g., "BTCUSDT"
    baseline: float      # Baseline quantity (from initialization)
    top_eq: float        # Record high actual equivalent
    current_bid: float  # Current bid price
    current_ask: float  # Current ask price
    actual_eq: float = 0.0  # Actual equivalent (updated every tick)
    gain_pct: float = 0.0   # Gain % vs top_eq
    baseline_updated_at: str = ""  # Timestamp


@dataclass
class Portfolio:
    """Current portfolio state."""
    symbol: str      # Currently held token
    quantity: float  # Amount held
    top_eq: float    # Top eq for this token (for reference)


@dataclass
class SwapRecord:
    """Record of a swap."""
    timestamp: str
    from_symbol: str
    to_symbol: str
    from_qty: float
    to_qty: float
    gain_pct: float
    price_before: float


class Matrix:
    """
    Main matrix class that tracks all tokens and handles swap logic.
    
    The matrix shows:
    - For each token: baseline, top_eq, actual_eq, gain_pct
    - Current portfolio state
    - Swap history
    """
    
    def __init__(self, initial_usdt: float = INITIAL_USDT, fee: float = FEE):
        self.initial_usdt = initial_usdt
        self.fee = fee
        
        # Token data keyed by symbol
        self.tokens: Dict[str, TokenData] = {}
        
        # Current portfolio
        self.portfolio = Portfolio(symbol="", quantity=0.0, top_eq=0.0)
        
        # Swap history
        self.swaps: List[SwapRecord] = []
        
        # Tracking state
        self.initialized = False
        self.last_tick = None
        self.swap_count = 0
        
        # Settings
        self.threshold = 7.0  # 7% gain required to swap (optimal from backtest)
    
    def initialize(self, token_prices: Dict[str, dict]) -> dict:
        """
        Initialize matrix with current prices.
        
        Args:
            token_prices: Dict of {symbol: {"bid": float, "ask": float}}
        
        Returns:
            Initialization result with baseline calculations
        """
        self.tokens = {}
        self.swaps = []
        self.swap_count = 0
        
        timestamp = datetime.now().isoformat()
        
        # Calculate baseline for each token
        # BASELINE = how many tokens we could have bought for INITIAL_USDT
        # We buy at ASK price (market buy), so: qty = USDT / (ask * (1 + fee))
        
        for symbol, prices in token_prices.items():
            bid = float(prices.get('bid', 0))
            ask = float(prices.get('ask', 0))
            
            if ask <= 0:
                continue
                
            # Baseline: how many tokens for INITIAL_USDT at ask price
            baseline_qty = self.initial_usdt / (ask * (1 + self.fee))
            
            self.tokens[symbol] = TokenData(
                symbol=symbol,
                baseline=baseline_qty,
                top_eq=baseline_qty,  # Top starts at baseline
                current_bid=bid,
                current_ask=ask,
                actual_eq=baseline_qty,  # Initially equal to baseline
                gain_pct=0.0,
                baseline_updated_at=timestamp
            )
        
        # Set initial portfolio to first token (or USDT)
        if self.tokens:
            first_symbol = list(self.tokens.keys())[0]
            first_token = self.tokens[first_symbol]
            
            # If we start with USDT, convert to first token
            # We buy at ask: qty = USDT / (ask * (1 + fee))
            initial_qty = self.initial_usdt / (first_token.current_ask * (1 + self.fee))
            
            self.portfolio = Portfolio(
                symbol=first_symbol,
                quantity=initial_qty,
                top_eq=first_token.top_eq
            )
        
        self.initialized = True
        self.last_tick = timestamp
        
        return self.get_state()
    
    def update_prices(self, token_prices: Dict[str, dict]) -> dict:
        """
        Update prices and recalculate actual_eq for all tokens.
        
        This is called on every tick. It only updates prices and calculates
        actual_eq - it does NOT update top_eq (that only happens on swap).
        
        Args:
            token_prices: Dict of {symbol: {"bid": float, "ask": float}}
        
        Returns:
            Updated state
        """
        if not self.initialized:
            return {"error": "Matrix not initialized"}
        
        # Update prices
        for symbol, prices in token_prices.items():
            if symbol not in self.tokens:
                continue
            
            bid = float(prices.get('bid', 0))
            ask = float(prices.get('ask', 0))
            
            if bid <= 0 or ask <= 0:
                continue
            
            self.tokens[symbol].current_bid = bid
            self.tokens[symbol].current_ask = ask
        
        # Calculate actual_eq for ALL tokens
        # ACTUAL_EQ = how many of this token we COULD have if we:
        # 1. Sold our current holding at BID (market sell)
        # 2. Bought target token at ASK (market buy)
        
        current_symbol = self.portfolio.symbol
        current_qty = self.portfolio.quantity
        
        if current_qty > 0 and current_symbol in self.tokens:
            current_bid = self.tokens[current_symbol].current_bid
            if current_bid > 0:
                # USDT we get from selling our holding
                usdt_value = current_qty * current_bid * (1 - self.fee)
                
                # Now calculate actual_eq for each token
                for symbol, token in self.tokens.items():
                    if token.current_ask > 0:
                        # How many of this token could we buy?
                        token.actual_eq = usdt_value / (token.current_ask * (1 + self.fee))
                        
                        # Gain % vs top_eq
                        if token.top_eq > 0:
                            token.gain_pct = (token.actual_eq - token.top_eq) / token.top_eq * 100
                        else:
                            token.gain_pct = 0.0
        
        self.last_tick = datetime.now().isoformat()
        
        return self.get_state()
    
    def check_and_execute_swap(self) -> Optional[SwapRecord]:
        """
        Check if we should swap and execute if conditions are met.
        
        SWAP LOGIC:
        1. Find token with highest gain_pct (best candidate)
        2. If gain_pct > threshold, swap to that token
        3. Update top_eq for the new token
        
        Returns:
            SwapRecord if swap executed, None otherwise
        """
        if not self.initialized:
            return None
        
        current_symbol = self.portfolio.symbol
        current_token = self.tokens.get(current_symbol)
        
        if not current_token:
            return None
        
        # Find best candidate (highest gain_pct, excluding current holding)
        best_candidate = None
        best_gain = self.threshold  # Must exceed threshold
        
        for symbol, token in self.tokens.items():
            if symbol == current_symbol:
                continue
            
            # Only consider tokens with positive gain
            if token.gain_pct > best_gain:
                best_gain = token.gain_pct
                best_candidate = (symbol, token)
        
        if not best_candidate:
            return None
        
        target_symbol, target_token = best_candidate
        
        # Execute swap
        # 1. Sell current holding at BID
        current_qty = self.portfolio.quantity
        current_bid = current_token.current_bid
        
        if current_bid <= 0:
            return None
        
        usdt_after_sell = current_qty * current_bid * (1 - self.fee)
        
        # 2. Buy target token at ASK
        target_ask = target_token.current_ask
        if target_ask <= 0:
            return None
        
        new_qty = usdt_after_sell / (target_ask * (1 + self.fee))
        
        # 3. Update top_eq for ALL tokens based on new holding
        # Key insight: After swap, we have new_qty of target token
        # For the NEW token, top_eq = new_qty (that's our new record!)
        # For OTHER tokens, calculate based on USDT value
        
        target_token.top_eq = new_qty  # Direct record for the token we just bought
        
        # Calculate USDT value of our new holding (what we'd get if we sold)
        target_bid = target_token.current_bid
        if target_bid > 0:
            usdt_value = new_qty * target_bid * (1 - self.fee)
            
            # Update other tokens based on this USDT value
            for symbol, token in self.tokens.items():
                if symbol != target_symbol and token.current_ask > 0:
                    potential_eq = usdt_value / (token.current_ask * (1 + self.fee))
                    if potential_eq > token.top_eq:
                        token.top_eq = potential_eq
        
        # 4. Update portfolio
        old_symbol = self.portfolio.symbol
        self.portfolio.symbol = target_symbol
        self.portfolio.quantity = new_qty
        self.portfolio.top_eq = target_token.top_eq
        
        # 5. Record swap
        swap_record = SwapRecord(
            timestamp=datetime.now().isoformat(),
            from_symbol=old_symbol,
            to_symbol=target_symbol,
            from_qty=current_qty,
            to_qty=new_qty,
            gain_pct=best_gain,
            price_before=target_ask
        )
        
        self.swaps.append(swap_record)
        self.swap_count += 1
        
        return swap_record
    
    def get_state(self) -> dict:
        """Get current matrix state as dict."""
        return {
            "initialized": self.initialized,
            "initial_usdt": self.initial_usdt,
            "current_holding": {
                "symbol": self.portfolio.symbol,
                "quantity": self.portfolio.quantity,
                "top_eq": self.portfolio.top_eq
            },
            "tokens": {
                symbol: {
                    "symbol": t.symbol,
                    "baseline": t.baseline,
                    "top_eq": t.top_eq,
                    "current_bid": t.current_bid,
                    "current_ask": t.current_ask,
                    "actual_eq": t.actual_eq,
                    "gain_pct": t.gain_pct
                }
                for symbol, t in self.tokens.items()
            },
            "tokens_sorted_by_gain": sorted(
                [
                    {"symbol": t.symbol, "gain_pct": t.gain_pct, "actual_eq": t.actual_eq, "top_eq": t.top_eq}
                    for t in self.tokens.values()
                ],
                key=lambda x: x['gain_pct'],
                reverse=True
            ),
            "swap_count": self.swap_count,
            "last_tick": self.last_tick,
            "threshold": self.threshold,
            "recent_swaps": [
                asdict(s) for s in self.swaps[-10:]
            ]
        }
    
    def set_threshold(self, threshold: float):
        """Set swap threshold (as decimal, e.g., 0.02 for 2%)."""
        self.threshold = threshold
    
    def get_best_swap_candidate(self) -> Optional[dict]:
        """Get the best candidate for swapping."""
        if not self.initialized:
            return None
        
        candidates = [
            {
                "symbol": t.symbol,
                "gain_pct": t.gain_pct,
                "actual_eq": t.actual_eq,
                "top_eq": t.top_eq,
                "current_ask": t.current_ask
            }
            for t in self.tokens.values()
            if t.symbol != self.portfolio.symbol and t.gain_pct > 0
        ]
        
        if not candidates:
            return None
        
        candidates.sort(key=lambda x: x['gain_pct'], reverse=True)
        return candidates[0]
    
    def save(self, filepath: str):
        """Save matrix state to file."""
        data = self.get_state()
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
    
    def load(self, filepath: str) -> bool:
        """Load matrix state from file. Returns True if successful."""
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            # Restore tokens
            self.tokens = {}
            for symbol, tdata in data.get('tokens', {}).items():
                self.tokens[symbol] = TokenData(
                    symbol=tdata['symbol'],
                    baseline=tdata['baseline'],
                    top_eq=tdata['top_eq'],
                    current_bid=tdata['current_bid'],
                    current_ask=tdata['current_ask'],
                    actual_eq=tdata['actual_eq'],
                    gain_pct=tdata['gain_pct'],
                    baseline_updated_at=tdata.get('baseline_updated_at', '')
                )
            
            # Restore portfolio
            hold = data.get('current_holding', {})
            self.portfolio = Portfolio(
                symbol=hold.get('symbol', ''),
                quantity=hold.get('quantity', 0),
                top_eq=hold.get('top_eq', 0)
            )
            
            self.initialized = data.get('initialized', False)
            self.swap_count = data.get('swap_count', 0)
            self.last_tick = data.get('last_tick')
            self.threshold = data.get('threshold', 0.02)
            
            return True
        except Exception as e:
            print(f"Error loading matrix: {e}")
            return False
