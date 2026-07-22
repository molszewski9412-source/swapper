# Matrix Swap v2 - Session State

## Date: 2026-07-22 (Session continued)

## Current Status

- **Server**: Running on localhost:5000 ✅
- **Threshold**: 7.0% (optimal from backtest)
- **Holding**: BTCUSDT (initialized fresh)
- **Swaps**: 0 (no opportunities >7% yet)
- **Tokens tracked**: 49
- **Last tick**: 2026-07-22T20:28:22

## Git Branch: v2-matrix-swap

## Backtest Results (Key Findings)

| Threshold | Swaps | Gain % |
|-----------|-------|--------|
| **7.0%** | 61 | **+278%** |
| 7.5% | 51 | +248% |
| 0.1% | 248 | +16% |

**OKX Dataset (1 year, 10 tokens)**:
- Threshold 15% = **+68.75%** (6 swaps) - turned -0.49% B&H into profit!

## Key Insights

1. **Threshold depends on market conditions**:
   - Quiet market (B&H -0.5%): threshold 15% = +68.75% (6 swaps!)
   - Bull market: lower threshold (3-5%)
   - Bear market: higher threshold (7%+)
   
2. **Matrix Swap doesn't work on quiet markets**
3. **System verified working** - calculations correct

## Files

- `/workspace/project/swapper/matrix_swap/` - Main project
- `config.py` - Threshold 7.0% set as DEFAULT
- `matrix.py` - Core logic
- `backtest_results.json` - Historical backtest data
- `threshold_optimization.json` - Threshold optimization results

## Next Steps

1. Monitor for >7% gain opportunities
2. Run longer backtests with different datasets
3. Consider adaptive threshold based on market volatility
