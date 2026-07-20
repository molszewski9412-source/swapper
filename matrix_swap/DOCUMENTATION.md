# Matrix Swap v2 - Documentation

## Architecture

### Core Components
- `config.py` - Configuration (API, fees, polling)
- `api.py` - Mexc API client with tick logging
- `matrix.py` - Core swap matrix logic
- `app.py` - Flask web application

## Key Concepts

### BASELINE
How many tokens we COULD have if we started with INITIAL_USDT at initialization.
Calculated as: `INITIAL_USDT / (ask_price * (1 + fee))`

### ACTUAL_EQ
How many tokens we WOULD have if we:
1. Sold our current holding at BID (market sell)
2. Bought target token at ASK (market buy)
Formula: `current_qty * bid * (1 - fee) / (ask * (1 + fee))`

### TOP_EQ
Record high of ACTUAL_EQ for each token. Only updated on SWAP, not on every tick.
This ensures we only swap when we can beat our previous best.

### GAIN %
`(actual_eq - top_eq) / top_eq * 100`
- Positive = we're beating our record
- Negative = below record

## Swap Logic

1. Every tick (1s):
   - Fetch prices from Mexc
   - Calculate actual_eq for all tokens
   - Do NOT update top_eq

2. Check for swap:
   - Find token with highest gain%
   - If gain% > threshold (default 2%):
     - Sell current holding at BID
     - Buy target at ASK
     - Update top_eq for ALL tokens

## Known Issues / Decisions

### Bug Fixed (v2.1)
**Issue**: `new_value_usdt` was calculated as `new_amount * ask_price` without fee.
**Fix**: Should use `new_amount * bid_price * (1 - fee)` because that's what we'd get if we sold.

### Current Implementation (v2)
Uses ASK price without fee for new_value_usdt:
```python
new_value_usdt = new_amount * prices[target][idx]  # Uses ASK
```

This results in slightly LOWER top_eq, which:
- Makes gain% appear slightly higher
- Makes it EASIER to trigger swaps (lower threshold to beat)

### Alternative Approach
Use BID price with fee:
```python
new_value_usdt = new_amount * prices[target][idx]['bid'] * (1 - fee)
```

This would be more conservative but might reduce swap frequency.

## Files Generated

- `tick_log.json` - Full tick history for verification
- `server.log` - Server logs

## Running

```bash
cd matrix_swap
python app.py
# Open http://localhost:5000
```

## API Endpoints

- `POST /api/initialize` - Start with fresh 1000 USDT
- `POST /api/stop` - Stop polling
- `GET /api/matrix` - Full state
- `POST /api/threshold` - Set threshold (body: {"threshold": 0.02})
- `POST /api/save_ticks` - Save tick log to file

## Verification Results (2026-07-20)

Tested swap BTC -> ALGO:
- From Qty: 0.015349399 BTC
- BTC bid at swap: 65119.22
- ALGO ask at swap: 0.0828
- To Qty: 12062.096597 ALGO
- Fee calculation: CORRECT

Formula verification:
```
USDT after sell = 0.015349399 * 65119.22 * (1 - 0.0004) = 999.14 USDT
ALGO qty = 999.14 / (0.0828 * 1.0004) = 12062.09 ALGO
```
