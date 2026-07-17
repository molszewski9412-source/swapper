# Swapper - Crypto Backtesting Engine

Modular cryptocurrency backtesting engine that maximizes token holdings through intelligent swap strategies.

## Features

- **Matrix-based analysis** - Pre-compute all 20×20 swap pairs for O(1) lookups
- **Realistic simulation** - Fees (~0.08% total), bid/ask spreads, slippage
- **Record tracking** - "Could have had" vs "Actually had" benchmarking
- **Multiple strategies** - Hold, Threshold, Momentum, RSI, Grid-based
- **Optimization** - Grid search, Random search, Genetic algorithm
- **AI Discovery** - Strategy evolution using genetic programming
- **Multi-format reports** - JSON, CSV, HTML with visualizations

## Installation

```bash
pip install -e .
```

## Quick Start

```bash
# Run a backtest with threshold strategy
python app.py backtest -s threshold --params threshold=1.05 interval=5

# Optimize strategy parameters
python app.py optimize -n 100 --threshold-range 0.9,2.0

# List available strategies
python app.py list
```

## Project Structure

```
swapper/
├── app.py              # CLI entry point
├── config/             # Configuration
├── core/               # Core engine
│   ├── models.py       # Data models
│   ├── portfolio.py    # Portfolio tracking
│   ├── records.py      # Record tracking
│   ├── simulator.py   # Swap simulation
│   └── engine.py       # Main backtest engine
├── data/              # Data loading/caching
├── strategies/        # Trading strategies
├── optimizer/         # Optimization algorithms
├── scoring/           # Performance scoring
├── reports/           # Report generation
└── tests/             # Unit tests
```

## Usage

```python
from core.engine import BacktestEngine
from strategies.factory import create_strategy

# Setup engine
engine = BacktestEngine()
engine.setup()

# Create and run strategy
strategy = create_strategy("threshold", threshold=1.05, min_swap_interval=5)
result = engine.run(strategy)

print(f"ROI: {result.score_result.roi_percent:.2f}%")
print(f"Swaps: {result.score_result.total_swaps}")
```

## Testing

```bash
pytest tests/ -v
```
