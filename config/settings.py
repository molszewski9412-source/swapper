"""Configuration settings for Swapper backtesting engine."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any


@dataclass
class FeesConfig:
    """Fee configuration for swap operations."""
    swap_fee_per_leg: float = 0.0004  # 0.04% per leg
    slippage_bps: float = 0.0  # basis points slippage
    min_order_value: float = 10.0  # minimum order value in USDT

    @property
    def total_fee(self) -> float:
        """Total fee for a round-trip swap (2 legs)."""
        return self.swap_fee_per_leg * 2


@dataclass
class SimulationConfig:
    """Configuration for simulation parameters."""
    initial_capital: float = 1.0  # Starting capital in USDT equivalent
    starting_token: str = "BTCUSDT"
    time_windows: list[int] = field(default_factory=lambda: [5000, 10000, 25000, 50000])
    validation_samples: int = 5  # Number of random samples for validation
    min_swap_interval: int = 1  # Minimum records between swaps


@dataclass
class OptimizationConfig:
    """Configuration for optimization algorithms."""
    grid_search_points: int = 1000
    random_search_iterations: int = 5000
    genetic_population: int = 100
    genetic_generations: int = 50
    genetic_mutation_rate: float = 0.1
    genetic_elite_ratio: float = 0.1
    parallel_workers: int = 4
    early_stopping_patience: int = 10


@dataclass
class Settings:
    """Main settings class for Swapper engine."""
    project_root: Path = field(default_factory=lambda: Path(__file__).parent.parent)
    data_path: Any = field(default_factory=lambda: str(Path(__file__).parent.parent / "market.csv"))
    
    # Components
    fees: FeesConfig = field(default_factory=FeesConfig)
    simulation: SimulationConfig = field(default_factory=SimulationConfig)
    optimization: OptimizationConfig = field(default_factory=OptimizationConfig)
    
    # Output
    output_dir: Path = field(default_factory=lambda: Path(__file__).parent.parent / "output")
    reports_format: list[str] = field(default_factory=lambda: ["json", "csv", "html"])
    
    # Logging
    log_level: str = "INFO"
    progress_update_interval: int = 1000
    
    # Performance
    cache_enabled: bool = True
    matrix_precompute: bool = True
    
    def __post_init__(self) -> None:
        """Ensure directories exist."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
