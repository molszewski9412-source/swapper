"""Simple dashboard for monitoring evolution in real-time."""

import os
import sys
import time
import json
from pathlib import Path
from datetime import datetime


class Dashboard:
    """Real-time dashboard for monitoring evolution."""

    def __init__(self, output_dir: str = "output/evolution"):
        self.output_dir = Path(output_dir)
        self.last_gen = 0

    def update(self, stats: dict) -> None:
        """Update dashboard display."""
        # Clear screen
        os.system('cls' if os.name == 'nt' else 'clear')
        
        elapsed = stats.get("elapsed_minutes", 0)
        
        print(f"""
╔══════════════════════════════════════════════════════════════════╗
║              SWAPPER - Autonomous Strategy Evolution              ║
╠══════════════════════════════════════════════════════════════════╣
║ Status:          {stats.get('status', 'unknown'):<38}║
║ Generation:      {stats.get('generation', 0):<38}║
║ Total Backtests: {stats.get('total_backtests', 0):<38}║
╠══════════════════════════════════════════════════════════════════╣
║ BEST SCORE:      {stats.get('best_score', 0):>10.4f}                            ║
║ CURRENT BEST:    {stats.get('current_best', 0):>10.4f}                            ║
╠══════════════════════════════════════════════════════════════════╣
║ No Improvement:  {stats.get('no_improvement', 0):<38}║
║ LLM API Calls:  {stats.get('llm_calls', 0):<38}║
║ Elapsed:        {elapsed:>10.1f} min                              ║
╚══════════════════════════════════════════════════════════════════╝
        """)
        
        # Show recent history
        history_file = sorted(self.output_dir.glob("checkpoint_gen*.json"))
        if history_file:
            print("\nRecent Performance:")
            print("-" * 60)
            print(f"{'Gen':<8} {'Best':<12} {'Avg':<12} {'Worst':<12} {'Time':<10}")
            print("-" * 60)
            
            for checkpoint in history_file[-10:]:
                with open(checkpoint) as f:
                    data = json.load(f)
                    gen = data.get("generation", 0)
                    stats_data = data.get("stats", {})
                    history = data.get("generation_history", [])
                    
                    if history:
                        last = history[-1]
                        print(
                            f"{gen:<8} "
                            f"{stats_data.get('best_score', 0):<12.4f} "
                            f"{last.get('avg_score', 0):<12.4f} "
                            f"{last.get('worst_score', 0):<12.4f} "
                            f"{last.get('time_taken', 0):<10.1f}s"
                        )

    def watch(self, loop) -> None:
        """Watch loop and update dashboard."""
        try:
            while loop.is_running():
                stats = loop.get_status()
                self.update(stats)
                time.sleep(5)  # Update every 5 seconds
        except KeyboardInterrupt:
            pass


def main():
    """Run dashboard standalone."""
    dashboard = Dashboard()
    
    # Load latest checkpoint
    output_dir = Path("output/evolution")
    checkpoints = sorted(output_dir.glob("checkpoint_gen*.json"))
    
    if checkpoints:
        with open(checkpoints[-1]) as f:
            data = json.load(f)
            stats = data.get("stats", {})
            stats["generation"] = data.get("generation", 0)
            stats["status"] = "completed"
            stats["elapsed_minutes"] = 0
            dashboard.update(stats)
    else:
        print("No checkpoints found. Run main.py first!")


if __name__ == "__main__":
    main()
