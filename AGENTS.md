# Swapper Project - Session Notes

## Branch: feature/live-matrix

## Current Working Code (2024-07-23)

### Key Fixes Applied:

1. **Swap Logic** - `_try_swap()` in `backtest_app.py`
   - Now checks: if any token has `gain_top >= threshold`, swap to that token
   - Gain is calculated as: `actual_equivalent / baseline - 1` for each token
   - Selects token with highest gain that meets threshold

2. **Fee Changed** - `backtest_app.py` line 23
   - Changed from `0.001` (0.1%) to `0.0004` (0.04%)
   - Total swap fee = 0.08% (0.04% × 2 trades: token→USDT→token)

3. **Decimal Separator Fix**
   - Both frontend (JS) and backend (Python) now handle comma as decimal separator
   - `set_threshold()` in `backtest_app.py` handles `',''` → `'.'`
   - Same for `initialize()`

4. **Gain % Top Display**
   - For held token: shows `actual / top - 1` (0% right after swap)
   - For other tokens: shows gain relative to their own top

5. **Top Logic** - `_execute_swap()`
   - Top of sent token: stays unchanged
   - Top of received token: `max(old_top, new_amount)`
   - For other tokens: updates if equivalent > current top

### Deployment

- **PythonAnywhere**: branch `feature/live-matrix`
- **URL**: `https://your_username.pythonanywhere.com`
- **Clone command**: `git clone -b feature/live-matrix https://github.com/molszewski9412-source/swapper.git`

### Files Modified:
- `backtest_app.py` - Main app with swap logic
- `templates/backtest.html` - Frontend with comma handling
- `DEPLOY_PYTHONANYWHERE.md` - Deployment guide
- `wsgi.py` - WSGI config for PythonAnywhere

### To Run Locally:
```bash
git pull
del backtest.db
python backtest_app.py
# Open http://localhost:8080
```

### Known Issues Fixed:
- Swap not triggering despite gain > threshold (decimal separator issue)
- Gain % Top showing wrong value after swap
- Fee calculation (was 0.1%, now 0.04% per trade)
