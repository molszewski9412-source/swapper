# 1. OBJECTIVE

Build a modular cryptocurrency backtesting engine called **Swapper** that maximizes the quantity of held tokens through intelligent swap strategies. The system will:

- Load and cache market data from `market.csv` (timestamp, token, bid, ask)
- Model the market as a weighted directed graph with tokens as vertices and USDT-mediated swaps as edges
- Simulate swap operations with realistic fees (~0.08% total), bid/ask spreads, and slippage
- **Track and record every swap with benchmark records** - for each token, maintain "could have had" (max potential) and "had" (actual) values
- **Matrix-based analysis (20Ă—20)** - pre-compute all swap pairs as vectors for O(1) lookups
- Discover and optimize swap strategies using grid search, random search, genetic algorithms, and AI
- Generate comprehensive reports (JSON, CSV, HTML) with ROI, token counts, drawdown, and performance metrics
- Validate strategies across multiple time windows to prevent overfitting

**Record Tracking System:**
- For each timestamp: calculate potential max of ALL tokens based on current holdings
- On each swap: record actual outcome, update benchmarks
- Maintain history of: potential_best, actual_had, swap_decisions, threshold_hits

**Example Flow (1 BTC start):**
```
t0: BTC=1, potential_ETH=100, potential_XRP=1000
t1: potential_ETH=111, potential_XRP=1100  (prices changed)
t2: SWAP BTCâ†’XRP â†’ actual_XRP=1099 (after fee)
     Records: BTC_potential=1.1, ETH_potential=111, XRP_actual=1099
t3: potential_BTC=1.1, potential_ETH=1050
t4: SWAP XRPâ†’BTC â†’ actual_BTC=1.099
     Records: BTC_actual=1.099, ETH_potential=111, XRP_actual=1099
```

# 2. CONTEXT SUMMARY

**Current State:** Repository is empty (skeleton only) with:
- `market.csv` (67MB) - market data with ~20 tokens per timestamp
- `index.html` - minimal placeholder
- `README.md` - basic title

**Data Format (market.csv):**
- Columns: timestamp, token, bid, ask
- Each timestamp has data for ~20 tokens

**Key Technical Constraints:**
- Python 3.12+
- Type Hints required
- SOLID, DRY, KISS, PEP8 principles
- pytest for testing
- ~0.08% total swap fee (0.04% Ă— 2 legs via USDT)

**Project Structure:**
```
swapper/
â”śâ”€â”€ app.py              # Main entry point
â”śâ”€â”€ config/             # Configuration files
â”śâ”€â”€ core/               # Core engine components
â”śâ”€â”€ data/               # Data loading and caching
â”śâ”€â”€ indicators/         # Technical indicators
â”śâ”€â”€ optimizer/          # Optimization algorithms
â”śâ”€â”€ reports/            # Report generation
â”śâ”€â”€ scoring/            # Strategy scoring
â”śâ”€â”€ strategies/         # Trading strategies
â””â”€â”€ tests/              # Unit and integration tests
```

# 3. APPROACH OVERVIEW

**Implementation Strategy:** Incremental, bottom-up approach following the roadmap in IMPLEMENTATION.md:

1. **Foundation Layer** - Data loading, caching, and core data structures
2. **Simulation Layer** - Portfolio management and swap simulation with realistic conditions
3. **Strategy Layer** - Basic to advanced strategy implementations
4. **Optimization Layer** - Grid search, random search, genetic algorithm
5. **Intelligence Layer** - AI-driven strategy discovery
6. **Reporting Layer** - Multi-format report generation
7. **Integration** - End-to-end testing and benchmarking

**Why This Approach:**
- Modular design allows testing each component independently
- Building foundation first ensures stability
- Progressive complexity matches the strategy evolution described in the spec
- Multiple optimization methods provide flexibility for different use cases

# 4. IMPLEMENTATION STEPS

## Phase 1: Foundation & Data Layer

### Step 1.1: Project Setup and Configuration
- **Goal:** Create project structure and configuration system
- **Method:** Create `config/settings.py` with dataclasses for all configuration options (paths, fees, slippage, optimization params)
- **Files:** `config/__init__.py`, `config/settings.py`

### Step 1.2: Data Models with Matrix Support
- **Goal:** Define core data structures for tokens, prices, and market data with NumPy matrix support
- **Method:** Create type-safe dataclasses in `core/models.py`:
  - `Token` (symbol, decimals)
  - `PricePoint` (timestamp, token, bid, ask)
  - `MarketSnapshot` (timestamp, prices dict)
  - `PriceMatrix` (n_timestamps × n_tokens) for vectorized operations
  - Token index mapping for O(1) lookups
- **Files:** `core/__init__.py`, `core/models.py`

### Step 1.3: Data Loader
- **Goal:** Efficiently load and parse market.csv
- **Method:** Create `data/loader.py` with:
  - CSV parsing with proper type conversion
  - Timestamp parsing and sorting
  - Memory-efficient chunked reading for large files
- **Files:** `data/__init__.py`, `data/loader.py`

### Step 1.4: Data Cache with Matrix Indexing
- **Goal:** Provide fast access to cached market data with vectorized lookups
- **Method:** Create `data/cache.py` with:
  - NumPy arrays for bid/ask prices (O(1) indexing)
  - Token index mapping (symbol → column)
  - Timestamp index (record_number → timestamp)
  - Optional memory-mapped arrays for 67MB+ files
- **Files:** `data/cache.py`

### Step 1.5: Record Tracking System
- **Goal:** Track "could have had" vs "actually had" for each token
- **Method:** Create `core/records.py`:
  - `SwapRecord` - timestamp, from_token, to_token, amount_in, amount_out, fee
  - `BenchmarkSnapshot` - for each token: potential_best, actual_had, last_update
  - `RecordHistory` - list of all snapshots with timestamps
  - Methods: `update_potential()`, `record_swap()`, `get_records()`, `export_trades()`
- **Files:** `core/records.py`
  ```python
  # Example data structure:
  records = {
      'BTC': {'potential_best': 1.1, 'actual_had': 1.099, 'last_swap': t4},
      'ETH': {'potential_best': 111, 'actual_had': None, 'last_swap': None},
      'XRP': {'potential_best': 1100, 'actual_had': 0, 'last_swap': t2}
  }
  swap_history = [
      SwapRecord(t2, 'BTC', 'XRP', 1.0, 1099, 0.88),
      SwapRecord(t4, 'XRP', 'BTC', 1099, 1.099, 0.97),
  ]
  ```

## Phase 2: Simulation Layer

### Step 2.1: Portfolio Model
- **Goal:** Track token holdings and portfolio state
- **Method:** Create `core/portfolio.py`:
  - `Portfolio` class with token balances
  - Holdings tracking (token â†’ quantity)
  - USDT tracking for swap operations
  - History of portfolio states
- **Files:** `core/portfolio.py`

### Step 2.2: Matrix-Based Swap Simulator
- **Goal:** Realistically simulate swap operations with all costs using vectorized computation
- **Method:** Create `core/simulator.py`:
  - `SwapSimulator` class with matrix operations
  - **Compute all 400 swap outcomes in single vectorized operation:**
    ```python
    # Input: current_holdings (20,), prices (20,20) - bid/ask matrix
    # Output: swap_matrix (20,20) - tokens gained for each swap pair
    swap_matrix = compute_swap_returns(current_holdings, prices, fees)
    best_swap = argmax(swap_matrix[holding_token, :])
    ```
  - Fee calculation (0.04% per leg, 0.08% total)
  - Bid/ask spread handling
  - Slippage modeling
  - Minimum order size enforcement
  - Decimal rounding per exchange standards
  - Integration with RecordTracker for logging each swap
- **Files:** `core/simulator.py`

### Step 2.3: Market Matrix Engine (Core Optimization)
- **Goal:** Pre-compute and cache 20×20 swap matrices for O(1) lookups
- **Method:** Create `core/market_matrix.py`:
  - **Pre-compute swap return matrix at each timestamp:**
    ```python
    # At each record in market.csv:
    # 1. Build price vectors: bid_prices[20], ask_prices[20]
    # 2. Compute swap_matrix[from_token][to_token] = tokens_gained
    # 3. Cache for strategy evaluation
    ```
  - Memory-efficient storage: only store changed matrices
  - Vectorized NumPy operations for all 400 pairs simultaneously
  - Methods: `get_swap_matrix()`, `find_best_swap()`, `compute_potential()`
- **Files:** `core/market_matrix.py`

### Step 2.4: Market Graph (optional)
- **Goal:** Model market as weighted directed graph (for advanced path finding)
- **Method:** Create `core/market_graph.py`:
  - Graph representation with NetworkX or custom implementation
  - Nodes = tokens, Edges = USDT swap paths
  - Edge weights: bid, ask, fee, spread, predicted token count, historical success rate
- **Files:** `core/market_graph.py`

## Phase 3: Strategy Layer

### Step 3.1: Strategy Base Classes with Matrix Support
- **Goal:** Define interface for all strategies with matrix-based evaluation
- **Method:** Create `strategies/base.py`:
  - `Strategy` abstract base class
  - `Signal` dataclass (action, token_a, token_b, confidence, metadata)
  - Strategy validation framework
  - **Matrix evaluation interface:**
    ```python
    def evaluate(self, swap_matrix: np.ndarray, records: RecordHistory) -> Signal
    # swap_matrix: 20x20 pre-computed swap returns
    # returns best swap based on strategy logic
    ```
- **Files:** `strategies/__init__.py`, `strategies/base.py`

### Step 3.2: Basic Strategies
- **Goal:** Implement simple rule-based strategies
- **Method:** Create `strategies/basic.py`:
  - `BetterThanHoldingStrategy` - swap only if token count increases
  - `BestTokenStrategy` - always hold best-performing token
- **Files:** `strategies/basic.py`

### Step 3.3: Threshold Strategies
- **Goal:** Implement threshold-based strategies
- **Method:** Create `strategies/thresholds.py`:
  - Configurable profit thresholds
  - Minimum gain requirements
  - Fee-adjusted calculations
- **Files:** `strategies/thresholds.py`

### Step 3.4: Indicator-Based Strategies
- **Goal:** Add technical indicator support
- **Method:** Create `indicators/__init__.py` and `indicators/technical.py`:
  - Moving averages (SMA, EMA)
  - Volatility (stddev, ATR)
  - Momentum (ROC, RSI)
  - Correlation matrices
- **Files:** `indicators/__init__.py`, `indicators/technical.py`, `indicators/momentum.py`, `indicators/volatility.py`

### Step 3.5: Advanced Strategies
- **Goal:** Implement multi-factor strategies
- **Method:** Create `strategies/advanced.py`:
  - `MultiIndicatorStrategy` - combines multiple indicators
  - `FilteredStrategy` - applies volatility/factor filters
  - `MomentumStrategy` - follows price momentum
- **Files:** `strategies/advanced.py`

### Step 3.6: Strategy Factory
- **Goal:** Unified strategy instantiation
- **Method:** Create `strategies/factory.py` with registry pattern
- **Files:** `strategies/factory.py`

## Phase 4: Optimization Layer

### Step 4.1: Optimizer Base Class
- **Goal:** Define optimization interface
- **Method:** Create `optimizer/base.py`:
  - `Optimizer` abstract base class
  - `OptimizationResult` dataclass
  - Parameter space definition
- **Files:** `optimizer/__init__.py`, `optimizer/base.py`

### Step 4.2: Grid Search with Matrix Optimization
- **Goal:** Exhaustive parameter search with vectorized evaluation
- **Method:** Create `optimizer/grid_search.py`:
  - Cartesian product of parameter grids
  - **Batch evaluation of multiple parameter sets using matrix operations**
  - Parallel execution support (multiprocessing)
  - Progress tracking with ETA
- **Files:** `optimizer/grid_search.py`

### Step 4.3: Random Search
- **Goal:** Randomized parameter exploration
- **Method:** Create `optimizer/random_search.py`:
  - Uniform and Gaussian sampling
  - Adaptive sampling
  - Early stopping criteria
- **Files:** `optimizer/random_search.py`

### Step 4.4: Genetic Algorithm
- **Goal:** Evolutionary optimization
- **Method:** Create `optimizer/genetic.py`:
  - Population management
  - Selection, crossover, mutation operators
  - Fitness evaluation
  - Elitism and diversity preservation
- **Files:** `optimizer/genetic.py`

### Step 4.5: Optimizer Orchestrator
- **Goal:** Unified optimization interface
- **Method:** Create `optimizer/orchestrator.py`:
  - Strategy selection based on problem characteristics
  - Multi-objective optimization support
- **Files:** `optimizer/orchestrator.py`

## Phase 5: Intelligence Layer

### Step 5.1: Strategy Discovery Engine
- **Goal:** AI-powered strategy generation
- **Method:** Create `optimizer/discovery.py`:
  - Rule combination engine
  - Genetic programming for strategy evolution
  - Hypothesis generation and testing
- **Files:** `optimizer/discovery.py`

## Phase 6: Scoring & Reports

### Step 6.1: Scoring Engine
- **Goal:** Evaluate strategy performance
- **Method:** Create `scoring/__init__.py` and `scoring/engine.py`:
  - Token count metrics (primary)
  - ROI calculations
  - Drawdown analysis
  - Sharpe ratio, win rate, swap frequency
  - Out-of-sample validation
- **Files:** `scoring/__init__.py`, `scoring/engine.py`

### Step 6.2: Report Generator
- **Goal:** Multi-format reporting with complete swap history
- **Method:** Create `reports/__init__.py` and `reports/generator.py`:
  - JSON export (full backtest results, all records)
  - CSV export (swap-by-swap trade log, benchmark history)
  - HTML report with charts
  - Backtest summary with metrics
  - **Record export:**
    ```csv
    timestamp,token,potential_best,actual_had,swap_from,swap_to,amount,threshold_hit
    t0,BTC,1.0,1.0,,,
    t2,XRP,1100,1099,BTC,XRP,1.0,true
    t4,BTC,1.1,1.099,XRP,BTC,1099,true
    ```
- **Files:** `reports/__init__.py`, `reports/generator.py`

## Phase 7: Integration & Engine

### Step 7.1: Core Engine with Record-by-Record Processing
- **Goal:** Orchestrate all components with efficient per-record processing
- **Method:** Create `core/engine.py`:
  - `BacktestEngine` class
  - Component initialization and wiring
  - **Main backtest loop (optimized):**
    ```python
    for record_idx in range(n_records):
        # 1. Load snapshot (O(1) from matrix)
        snapshot = cache.get_snapshot(record_idx)
        
        # 2. Update potential records for all tokens
        records.update_potential(snapshot, holdings)
        
        # 3. Get pre-computed swap matrix (20x20)
        swap_matrix = matrix.get(record_idx)
        
        # 4. Strategy evaluates matrix → generates signal
        signal = strategy.evaluate(swap_matrix, records)
        
        # 5. If threshold met → execute swap
        if signal.should_swap():
            result = simulator.execute(signal)
            records.record_swap(result)  # logs the swap
        
        # 6. Update holdings
        holdings.update(result)
    ```
  - Progress reporting and early stopping
  - Event system for extensibility
- **Files:** `core/engine.py`

### Step 7.2: Strategy Engine
- **Goal:** Manage strategy execution
- **Method:** Create `core/strategy_engine.py`:
  - Strategy initialization
  - Signal generation
  - Position sizing
  - Risk management hooks
- **Files:** `core/strategy_engine.py`

### Step 7.3: Main Application
- **Goal:** Entry point for the application
- **Method:** Create `app.py`:
  - CLI interface
  - Configuration loading
  - Engine initialization
  - Report generation
- **Files:** `app.py`

## Phase 8: Testing

### Step 8.1: Unit Tests
- **Goal:** Test individual components
- **Method:** Create `tests/__init__.py`, `tests/test_models.py`, `tests/test_loader.py`, `tests/test_simulator.py`, `tests/test_strategies.py`, `tests/test_optimizer.py`, `tests/test_records.py`
- **Files:** `tests/`, pytest configuration
- **Record tracking tests:**
  - Test potential update calculation
  - Test swap recording accuracy
  - Test record history export

### Step 8.2: Integration Tests
- **Goal:** Test component interactions
- **Method:** Create `tests/test_integration.py`:
  - End-to-end backtest tests
  - Multi-strategy tests
  - Optimization pipeline tests
- **Files:** `tests/test_integration.py`

### Step 8.3: Benchmark Tests
- **Goal:** Performance validation
- **Method:** Create `tests/test_benchmark.py`:
  - Load time benchmarks
  - Simulation speed tests
  - Optimization time tests
- **Files:** `tests/test_benchmark.py`

# 5. TESTING AND VALIDATION

## Success Criteria

1. **Functional Requirements:**
   - [ ] Successfully loads market.csv (67MB) within reasonable time
   - [ ] Correctly calculates swap fees (0.04% per leg)
   - [ ] Accurate bid/ask spread handling
   - [ ] Portfolio tracks token holdings correctly
   - [ ] **All 20×20 swap pairs computed via vectorized operations**
   - [ ] All optimization methods produce valid results
   - [ ] Reports export correctly in JSON, CSV, HTML formats

2. **Record Tracking:**
   - [ ] "Could have had" (potential_best) tracked for all tokens
   - [ ] "Actually had" (actual_had) updated on each swap
   - [ ] Every swap recorded with full context (from, to, amount, fee)
   - [ ] Records exportable to CSV for analysis

3. **Strategy Validation:**
   - [ ] Basic strategies execute without errors
   - [ ] Advanced strategies use technical indicators correctly
   - [ ] AI discovery generates novel strategies

4. **Backtest Robustness:**
   - [ ] Strategies tested on multiple time windows (5k, 10k, 25k, 50k records)
   - [ ] Random week/month sampling validation passes
   - [ ] No overfitting detected across different starting points

5. **Code Quality:**
   - [ ] All code passes type checking (mypy)
   - [ ] All tests pass (pytest)
   - [ ] PEP8 compliance verified
   - [ ] Type hints on all public APIs

## Validation Steps

1. **Unit Testing:** `pytest tests/ -v`
2. **Integration Testing:** `pytest tests/test_integration.py -v`
3. **Benchmark:** `python -m pytest tests/test_benchmark.py -v`
4. **Code Quality:** `mypy swapper/ && flake8 swapper/`
5. **Full Backtest:** Run complete backtest with sample strategy and verify output

## Expected Outputs

- Console output showing progress and final metrics
- JSON report with detailed results and all records
- CSV with trade-by-trade data (swap history):
  ```csv
  timestamp,from_token,to_token,amount_in,amount_out,fee,potential_before,potential_after
  t2,BTC,XRP,1.0,1099,0.88,1100,1100
  t4,XRP,BTC,1099,1.099,0.97,1.1,1.1
  ```
- CSV with benchmark history (potential vs actual):
  ```csv
  timestamp,BTC_potential,BTC_actual,ETH_potential,ETH_actual,...
  t0,1.0,1.0,100,None,...
  t1,1.05,1.0,105,None,...
  t2,1.1,1.0,111,None,...
  ```
- HTML report with visualizations
- Logs showing optimization results
