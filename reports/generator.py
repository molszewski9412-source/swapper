"""Report generator for multi-format export."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import json
import csv


@dataclass
class BacktestReport:
    """Complete backtest report data."""
    strategy_name: str
    params: dict[str, Any]
    start_time: str
    end_time: str
    n_records: int
    score_result: dict[str, Any]
    swap_history: list[dict[str, Any]]
    benchmark_history: list[dict[str, Any]]
    metadata: dict[str, Any]


class ReportGenerator:
    """Generates reports in multiple formats."""

    def __init__(
        self,
        output_dir: Path = Path("./output")
    ):
        """Initialize report generator.
        
        Args:
            output_dir: Directory for output files
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(
        self,
        report: BacktestReport,
        formats: list[str] = None,
        filename_prefix: str = "backtest"
    ) -> dict[str, Path]:
        """Generate reports in specified formats.
        
        Args:
            report: BacktestReport with all data
            formats: List of formats ["json", "csv", "html"] or None for all
            filename_prefix: Prefix for output files
        
        Returns:
            Dictionary of {format: output_path}
        """
        formats = formats or ["json", "csv", "html"]
        outputs = {}
        
        if "json" in formats:
            outputs["json"] = self._generate_json(report, filename_prefix)
        
        if "csv" in formats:
            outputs["csv"] = self._generate_csv(report, filename_prefix)
        
        if "html" in formats:
            outputs["html"] = self._generate_html(report, filename_prefix)
        
        return outputs

    def _generate_json(
        self,
        report: BacktestReport,
        prefix: str
    ) -> Path:
        """Generate JSON report."""
        output_path = self.output_dir / f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        data = {
            "strategy_name": report.strategy_name,
            "params": report.params,
            "timing": {
                "start": report.start_time,
                "end": report.end_time,
                "records": report.n_records,
            },
            "metrics": report.score_result,
            "swap_history": report.swap_history,
            "benchmark_history": report.benchmark_history,
            "metadata": report.metadata,
        }
        
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        
        return output_path

    def _generate_csv(
        self,
        report: BacktestReport,
        prefix: str
    ) -> Path:
        """Generate CSV reports (swap log + benchmark history)."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Swap history CSV
        swap_path = self.output_dir / f"{prefix}_swaps_{timestamp}.csv"
        self._write_swap_csv(report.swap_history, swap_path)
        
        # Benchmark history CSV
        benchmark_path = self.output_dir / f"{prefix}_benchmarks_{timestamp}.csv"
        self._write_benchmark_csv(report.benchmark_history, benchmark_path)
        
        # Summary CSV
        summary_path = self.output_dir / f"{prefix}_summary_{timestamp}.csv"
        self._write_summary_csv(report, summary_path)
        
        return summary_path

    def _write_swap_csv(
        self,
        swap_history: list[dict[str, Any]],
        path: Path
    ) -> None:
        """Write swap history to CSV."""
        if not swap_history:
            return
        
        fieldnames = [
            "timestamp", "record_index", "from_token", "to_token",
            "amount_in", "amount_out", "fee", "price_in", "price_out",
            "potential_before", "potential_after"
        ]
        
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for swap in swap_history:
                row = {k: swap.get(k, "") for k in fieldnames}
                writer.writerow(row)

    def _write_benchmark_csv(
        self,
        benchmark_history: list[dict[str, Any]],
        path: Path
    ) -> None:
        """Write benchmark history to CSV."""
        if not benchmark_history:
            return
        
        # Get all tokens from first snapshot
        first = benchmark_history[0]
        potential_keys = list(first.get("potential", {}).keys())
        actual_keys = list(first.get("actual", {}).keys())
        all_tokens = sorted(set(potential_keys + actual_keys))
        
        fieldnames = ["timestamp", "record_index", "holding_token", "holding_amount"] + \
                     [f"{t}_potential" for t in all_tokens] + \
                     [f"{t}_actual" for t in all_tokens]
        
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for snapshot in benchmark_history:
                row = {
                    "timestamp": snapshot.get("timestamp", ""),
                    "record_index": snapshot.get("record_index", ""),
                    "holding_token": snapshot.get("holding_token", ""),
                    "holding_amount": snapshot.get("holding_amount", ""),
                }
                
                potential = snapshot.get("potential", {})
                actual = snapshot.get("actual", {})
                
                for token in all_tokens:
                    row[f"{token}_potential"] = potential.get(token, "")
                    row[f"{token}_actual"] = actual.get(token, "")
                
                writer.writerow(row)

    def _write_summary_csv(
        self,
        report: BacktestReport,
        path: Path
    ) -> None:
        """Write summary report to CSV."""
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            
            writer.writerow(["Backtest Summary"])
            writer.writerow([])
            
            writer.writerow(["Strategy", report.strategy_name])
            writer.writerow(["Records", report.n_records])
            writer.writerow(["Start Time", report.start_time])
            writer.writerow(["End Time", report.end_time])
            writer.writerow([])
            
            writer.writerow(["Parameters"])
            for key, value in report.params.items():
                writer.writerow([key, value])
            writer.writerow([])
            
            writer.writerow(["Metrics"])
            for key, value in report.score_result.items():
                writer.writerow([key, value])
            writer.writerow([])
            
            writer.writerow(["Metadata"])
            for key, value in report.metadata.items():
                writer.writerow([key, value])

    def _generate_html(
        self,
        report: BacktestReport,
        prefix: str
    ) -> Path:
        """Generate HTML report with visualizations."""
        output_path = self.output_dir / f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        
        metrics = report.score_result
        
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Swapper Backtest Report - {report.strategy_name}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        .card {{
            background: white;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        h1, h2 {{ color: #333; }}
        .metric {{ display: inline-block; margin: 10px 20px 10px 0; }}
        .metric-label {{ color: #666; font-size: 14px; }}
        .metric-value {{ font-size: 24px; font-weight: bold; color: #2196F3; }}
        .positive {{ color: #4CAF50; }}
        .negative {{ color: #F44336; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #eee; }}
        th {{ background: #f9f9f9; }}
        .params {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px; }}
        .param {{ background: #f9f9f9; padding: 10px; border-radius: 4px; }}
        .param-name {{ color: #666; font-size: 12px; }}
        .param-value {{ font-weight: bold; }}
    </style>
</head>
<body>
    <h1>Swapper Backtest Report</h1>
    <p>Strategy: <strong>{report.strategy_name}</strong></p>
    <p>Records: {report.n_records} | {report.start_time} to {report.end_time}</p>
    
    <div class="card">
        <h2>Performance Metrics</h2>
        <div class="metric">
            <div class="metric-label">Final Token Count</div>
            <div class="metric-value">{metrics.get('final_token_count', 'N/A'):.4f}</div>
        </div>
        <div class="metric">
            <div class="metric-label">ROI</div>
            <div class="metric-value {'positive' if metrics.get('roi_percent', 0) >= 0 else 'negative'}">
                {metrics.get('roi_percent', 0):.2f}%
            </div>
        </div>
        <div class="metric">
            <div class="metric-label">vs Hold Return</div>
            <div class="metric-value {'positive' if metrics.get('vs_hold_return', 0) >= 0 else 'negative'}">
                {metrics.get('vs_hold_return', 0):.2f}%
            </div>
        </div>
        <div class="metric">
            <div class="metric-label">Total Swaps</div>
            <div class="metric-value">{metrics.get('total_swaps', 0)}</div>
        </div>
        <div class="metric">
            <div class="metric-label">Win Rate</div>
            <div class="metric-value">{metrics.get('win_rate', 0):.1f}%</div>
        </div>
        <div class="metric">
            <div class="metric-label">Max Drawdown</div>
            <div class="metric-value negative">{metrics.get('max_drawdown_percent', 0):.2f}%</div>
        </div>
    </div>
    
    <div class="card">
        <h2>Parameters</h2>
        <div class="params">
            {"".join(f'<div class="param"><div class="param-name">{k}</div><div class="param-value">{v}</div></div>' for k, v in report.params.items())}
        </div>
    </div>
    
    <div class="card">
        <h2>Recent Swaps ({min(10, len(report.swap_history))} of {len(report.swap_history)})</h2>
        <table>
            <tr>
                <th>Time</th>
                <th>From</th>
                <th>To</th>
                <th>Amount In</th>
                <th>Amount Out</th>
                <th>Fee</th>
            </tr>
            {"".join(f'''<tr>
                <td>{s.get('timestamp', '')}</td>
                <td>{s.get('from_token', '')}</td>
                <td>{s.get('to_token', '')}</td>
                <td>{s.get('amount_in', 0):.4f}</td>
                <td>{s.get('amount_out', 0):.4f}</td>
                <td>{s.get('fee', 0):.6f}</td>
            </tr>''' for s in report.swap_history[-10:])}
        </table>
    </div>
    
    <div class="card">
        <p>Generated by Swapper Backtesting Engine</p>
    </div>
</body>
</html>"""
        
        with open(output_path, "w") as f:
            f.write(html_content)
        
        return output_path

    def generate_comparison(
        self,
        results: dict[str, Any],
        filename: str = "comparison"
    ) -> Path:
        """Generate comparison report for multiple strategies."""
        output_path = self.output_dir / f"{filename}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        
        rows = ""
        for name, result in sorted(results.items(), key=lambda x: x[1].get("roi_percent", 0), reverse=True):
            roi = result.get("roi_percent", 0)
            swaps = result.get("total_swaps", 0)
            win_rate = result.get("win_rate", 0)
            rows += f"""<tr>
                <td><strong>{name}</strong></td>
                <td class="{'positive' if roi >= 0 else 'negative'}">{roi:.2f}%</td>
                <td>{swaps}</td>
                <td>{win_rate:.1f}%</td>
            </tr>"""
        
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Strategy Comparison</title>
    <style>
        body {{ font-family: sans-serif; max-width: 1000px; margin: 20px auto; padding: 20px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #eee; }}
        th {{ background: #f9f9f9; }}
        .positive {{ color: #4CAF50; }}
        .negative {{ color: #F44336; }}
    </style>
</head>
<body>
    <h1>Strategy Comparison</h1>
    <table>
        <tr>
            <th>Strategy</th>
            <th>ROI</th>
            <th>Total Swaps</th>
            <th>Win Rate</th>
        </tr>
        {rows}
    </table>
</body>
</html>"""
        
        with open(output_path, "w") as f:
            f.write(html)
        
        return output_path
