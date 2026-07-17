#!/usr/bin/env python3
"""Main entry point for Swapper backtesting engine."""

import argparse
import logging
import sys
from pathlib import Path

from config.settings import Settings
from core.engine import BacktestEngine
from strategies.factory import list_available_strategies, create_strategy


def setup_logging(level: str = "INFO") -> None:
    """Setup logging configuration."""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def run_backtest(args: argparse.Namespace) -> None:
    """Run a single backtest."""
    settings = Settings()
    
    if args.data:
        settings.data_path = Path(args.data)
    
    engine = BacktestEngine(settings)
    engine.setup()
    
    # Create strategy
    strategy = create_strategy(args.strategy, **vars(args.params) if args.params else {})
    
    print(f"Running backtest: {strategy.name}")
    print(f"Data: {settings.data_path}")
    print(f"Records: {engine.n_records}")
    print(f"Tokens: {len(engine.tokens)}")
    print()
    
    # Run backtest
    result = engine.run(
        strategy=strategy,
        start_idx=args.start or 0,
        end_idx=args.end,
    )
    
    # Print results
    if result.score_result:
        print("\n" + "=" * 50)
        print("BACKTEST RESULTS")
        print("=" * 50)
        print(f"Strategy: {result.strategy_name}")
        print(f"Records: {result.n_records}")
        print(f"Elapsed: {result.elapsed_time:.2f}s")
        print()
        print(f"Final Token Count: {result.score_result.final_token_count:.6f}")
        print(f"ROI: {result.score_result.roi_percent:.2f}%")
        print(f"vs Hold: {result.score_result.vs_hold_return:.2f}%")
        print(f"Total Swaps: {result.score_result.total_swaps}")
        print(f"Win Rate: {result.score_result.win_rate:.1f}%")
        print(f"Max Drawdown: {result.score_result.max_drawdown_percent:.2f}%")
        print()
        
        # Parameters
        print("Parameters:")
        for k, v in result.params.items():
            print(f"  {k}: {v}")
        
        # Recent swaps
        if result.swap_history:
            print()
            print(f"Last {min(5, len(result.swap_history))} Swaps:")
            for swap in result.swap_history[-5:]:
                print(f"  {swap['from_token']} -> {swap['to_token']}: {swap['amount_in']:.4f} -> {swap['amount_out']:.4f}")
    
    # Generate reports
    if args.report:
        outputs = engine.generate_report(result, formats=args.format.split(",") if args.format else None)
        print()
        print("Reports generated:")
        for fmt, path in outputs.items():
            print(f"  {fmt}: {path}")


def run_optimization(args: argparse.Namespace) -> None:
    """Run strategy optimization."""
    settings = Settings()
    
    if args.data:
        settings.data_path = Path(args.data)
    
    engine = BacktestEngine(settings)
    engine.setup()
    
    print(f"Optimizing strategy: {args.strategy}")
    print(f"Data: {settings.data_path}")
    print(f"Method: {args.method}")
    print(f"Iterations: {args.iterations}")
    print()
    
    # Parse param space
    param_space = {}
    if args.threshold_range:
        min_t, max_t = map(float, args.threshold_range.split(","))
        param_space["threshold"] = (min_t, max_t)
    if args.interval_range:
        min_i, max_i = map(int, args.interval_range.split(","))
        param_space["min_swap_interval"] = (min_i, max_i)
    
    if not param_space:
        param_space = {"threshold": (0.9, 2.0), "min_swap_interval": (1, 20)}
    
    print(f"Parameter space: {param_space}")
    print()
    
    # Run optimization
    from strategies.threshold import ThresholdStrategy
    
    results = engine.run_optimization(
        strategy_class=ThresholdStrategy,
        param_space=param_space,
        n_iterations=args.iterations,
        method=args.method,
    )
    
    print("\n" + "=" * 50)
    print("OPTIMIZATION RESULTS")
    print("=" * 50)
    print(f"Best Score: {results['best_score']:.2f}%")
    print(f"Best Parameters:")
    for k, v in results["best_params"].items():
        print(f"  {k}: {v}")


def list_strategies_handler(args: argparse.Namespace) -> None:
    """List available strategies."""
    strategies = list_available_strategies()
    print("Available strategies:")
    for name in strategies:
        print(f"  - {name}")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Swapper - Crypto Backtesting Engine")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--data", type=str, help="Path to market.csv")
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # Backtest command
    backtest_parser = subparsers.add_parser("backtest", help="Run a backtest")
    backtest_parser.add_argument("--strategy", "-s", default="threshold", help="Strategy name")
    backtest_parser.add_argument("--params", nargs="*", help="Strategy params (key=value)")
    backtest_parser.add_argument("--start", type=int, help="Start record index")
    backtest_parser.add_argument("--end", type=int, help="End record index")
    backtest_parser.add_argument("--report", action="store_true", help="Generate report")
    backtest_parser.add_argument("--format", type=str, help="Report formats (comma-separated)")
    
    # Optimize command
    optimize_parser = subparsers.add_parser("optimize", help="Optimize strategy")
    optimize_parser.add_argument("--strategy", "-s", default="threshold", help="Strategy to optimize")
    optimize_parser.add_argument("--iterations", "-n", type=int, default=100, help="Number of iterations")
    optimize_parser.add_argument("--method", "-m", default="random", choices=["grid", "random", "genetic"])
    optimize_parser.add_argument("--threshold-range", type=str, help="Threshold range (e.g., 0.9,2.0)")
    optimize_parser.add_argument("--interval-range", type=str, help="Interval range (e.g., 1,20)")
    
    # List strategies
    list_parser = subparsers.add_parser("list", help="List available strategies")
    
    args = parser.parse_args()
    
    setup_logging(args.log_level)
    
    if args.command == "backtest":
        # Parse params
        params = {}
        if args.params:
            for p in args.params:
                if "=" in p:
                    k, v = p.split("=", 1)
                    try:
                        params[k] = eval(v)
                    except:
                        params[k] = v
        args.params = params
        
        run_backtest(args)
    
    elif args.command == "optimize":
        run_optimization(args)
    
    elif args.command == "list":
        list_strategies_handler(args)
    
    else:
        parser.print_help()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
