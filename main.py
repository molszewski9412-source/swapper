#!/usr/bin/env python3
"""
Swapper - Autonomous Strategy Evolution Engine

Run this file to start the autonomous optimization loop.
It will continuously test strategies and use AI to evolve them.

Usage:
    python main.py                    # Run with defaults (Mock LLM)
    python main.py --openai           # Use OpenAI GPT-4
    python main.py --anthropic        # Use Claude
    python main.py --ollama           # Use local Ollama
    python main.py --config config.json  # Use config file

Press Ctrl+C to stop gracefully.
"""

import argparse
import logging
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from evolution.loop import EvolutionLoop
from ai.llm_engine import LLMProvider


def setup_argparse() -> argparse.ArgumentParser:
    """Setup argument parser."""
    parser = argparse.ArgumentParser(
        description="Swapper - Autonomous Strategy Evolution Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                           # Run with mock AI (no API needed)
  python main.py --openai                  # Use OpenAI GPT-4
  python main.py --anthropic               # Use Anthropic Claude
  python main.py --ollama                  # Use local Ollama (run: ollama serve)
  python main.py -g 100 -p 50             # Run 100 generations, 50 strategies each
  python main.py --data my_data.csv        # Use custom data file

Environment Variables:
  OPENAI_API_KEY        - Your OpenAI API key
  ANTHROPIC_API_KEY     - Your Anthropic API key
  OLLAMA_BASE_URL       - Ollama server URL (default: http://localhost:11434)

The program will run until:
  - You press Ctrl+C
  - Max generations reached
  - Strategy converges (no improvement for 100 generations)
        """
    )
    
    # LLM Provider
    llm_group = parser.add_argument_group("AI Provider (pick one)")
    llm_group.add_argument("--mock", action="store_true", help="Use mock AI (default, no API needed)")
    llm_group.add_argument("--openai", action="store_true", help="Use OpenAI GPT-4")
    llm_group.add_argument("--anthropic", action="store_true", help="Use Anthropic Claude")
    llm_group.add_argument("--ollama", action="store_true", help="Use local Ollama")
    llm_group.add_argument("--model", type=str, help="Specify model name")
    
    # Evolution settings
    evo_group = parser.add_argument_group("Evolution Settings")
    evo_group.add_argument("-g", "--generations", type=int, default=0, 
                          help="Max generations (0 = infinite)")
    evo_group.add_argument("-p", "--population", type=int, default=20,
                          help="Population size per generation")
    evo_group.add_argument("--llm-interval", type=int, default=10,
                          help="Generations between LLM calls")
    
    # Data settings
    data_group = parser.add_argument_group("Data Settings")
    data_group.add_argument("--data", type=str, default="market.csv",
                          help="Path to market data CSV")
    data_group.add_argument("--records", type=int, default=10000,
                          help="Records to use per backtest (0 = all)")
    
    # Output settings
    out_group = parser.add_argument_group("Output Settings")
    out_group.add_argument("-o", "--output", type=str, default="output/evolution",
                          help="Output directory")
    out_group.add_argument("--checkpoint", type=int, default=50,
                          help="Checkpoint interval")
    
    # Other
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--debug", action="store_true", help="Debug mode")
    
    return parser


def get_llm_provider(args: argparse.Namespace) -> LLMProvider:
    """Determine which LLM provider to use."""
    if args.openai:
        return LLMProvider.OPENAI
    elif args.anthropic:
        return LLMProvider.ANTHROPIC
    elif args.ollama:
        return LLMProvider.OLLAMA
    else:
        return LLMProvider.MOCK


def main():
    """Main entry point."""
    parser = setup_argparse()
    args = parser.parse_args()
    
    # Setup logging
    log_level = logging.DEBUG if args.debug else (logging.INFO if args.verbose else logging.WARNING)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    
    # Print banner
    print("""
╔══════════════════════════════════════════════════════════════════╗
║                                                                  ║
║   ███████╗██╗   ██╗██████╗ ███████╗██████╗ ███╗   ███╗██╗███╗   ██╗ █████╗ ██╗      ║
║   ██╔════╝██║   ██║██╔══██╗██╔════╝██╔══██╗████╗ ████║██║████╗  ██║██╔══██╗██║      ║
║   ███████╗██║   ██║██████╔╝█████╗  ██████╔╝██╔████╔██║██║██╔██╗ ██║███████║██║      ║
║   ╚════██║██║   ██║██╔══██╗██╔══╝  ██╔══██╗██║╚██╔╝██║██║██║╚██╗██║██╔══██║██║      ║
║   ███████║╚██████╔╝██║  ██║███████╗██║  ██║██║ ╚═╝ ██║██║██║ ╚████║██║  ██║███████╗ ║
║   ╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝╚══════╝ ║
║                                                                  ║
║   Autonomous Strategy Evolution Engine                           ║
║   Let AI discover the perfect trading strategy                   ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
    """)
    
    # Determine LLM provider
    llm_provider = get_llm_provider(args)
    
    print(f"[CONFIG]")
    print(f"  LLM Provider:    {llm_provider.value}")
    print(f"  Data:            {args.data}")
    print(f"  Generations:     {'infinite' if args.generations == 0 else args.generations}")
    print(f"  Population:     {args.population}")
    print(f"  Output:         {args.output}")
    print()
    
    # Check API keys for paid providers
    if llm_provider == LLMProvider.OPENAI:
        if not os.getenv("OPENAI_API_KEY"):
            print("ERROR: OPENAI_API_KEY environment variable not set")
            print("Set it with: export OPENAI_API_KEY=sk-...")
            sys.exit(1)
    
    elif llm_provider == LLMProvider.ANTHROPIC:
        if not os.getenv("ANTHROPIC_API_KEY"):
            print("ERROR: ANTHROPIC_API_KEY environment variable not set")
            print("Set it with: export ANTHROPIC_API_KEY=sk-ant-...")
            sys.exit(1)
    
    elif llm_provider == LLMProvider.OLLAMA:
        print("NOTE: Make sure Ollama is running: ollama serve")
        print("      And model is available: ollama pull llama3")
        print()
    
    else:
        print("NOTE: Using MOCK AI - strategies evolve randomly")
        print("      Use --openai, --anthropic, or --ollama for AI guidance")
        print()
    
    # Create and run evolution loop
    loop = EvolutionLoop(
        data_path=args.data,
        llm_provider=llm_provider,
        output_dir=args.output,
        max_generations=args.generations,
        population_size=args.population,
        checkpoint_interval=args.checkpoint,
    )
    
    # Setup
    try:
        loop.setup()
    except Exception as e:
        print(f"ERROR: Failed to setup: {e}")
        sys.exit(1)
    
    print(f"[READY] Engine initialized with {loop.backtest_engine.n_records} records")
    print()
    print("Starting evolution... Press Ctrl+C to stop gracefully.")
    print("=" * 70)
    print()
    
    # Run
    try:
        loop.run()
    except KeyboardInterrupt:
        print("\nReceived interrupt signal...")
        loop.stop()
    
    print("\nDone!")


if __name__ == "__main__":
    main()
