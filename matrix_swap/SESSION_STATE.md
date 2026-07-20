# Matrix Swap v2 - Session State

## Date: 2026-07-20

## What We Did

1. Created new project structure in `/workspace/project/swapper/matrix_swap/`
2. Implemented core Matrix logic with:
   - BASELINE - initial token quantities at initialization
   - ACTUAL_EQ - current equivalent based on prices
   - TOP_EQ - record high, only updated on swap
   - GAIN % - (actual_eq - top_eq) / top_eq

3. Integrated with Mexc API for real-time prices (every 1 second)

4. Created Flask web interface

5. Found and fixed a BUG:
   - Issue: `new_value_usdt = new_qty * ask_price` (used ASK without fee)
   - Fix: `new_value_usdt = new_qty * bid_price * (1 - fee)` (CORRECT)

## Current Status

- Server running on port 5000
- Initialized with 1000 USDT
- Monitoring for swaps

## Files Created

- `config.py` - Configuration
- `matrix.py` - Core logic (BUG FIXED)
- `api.py` - Mexc API client with tick logging
- `app.py` - Flask web app
- `templates/index.html` - Frontend
- `tick_log.json` - Tick history
- `DOCUMENTATION.md` - Technical documentation

## Next Steps

1. Wait for more data (5-10 minutes)
2. Verify swap calculations are now correct
3. Analyze gain% thresholds
4. Compare strategies (worst momentum vs median vs top)

## Verification Results

Swap BTC -> ALGO verification:
```
Sell: 0.015349399 BTC at bid 65119.22
USDT after sell (0.04% fee): 999.14 USDT
Buy ALGO at ask 0.0828, fee 0.04%
Expected ALGO: 12062.096597
Actual ALGO: 12062.096597
MATCH: True
```

## Key Metrics to Track

- Swap count over time
- Holding token changes
- Gain% distribution
- Threshold optimization
