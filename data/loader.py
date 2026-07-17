"""Data loader for market.csv files."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional
import csv
import logging

from core.models import PricePoint, PriceMatrix


logger = logging.getLogger(__name__)


@dataclass
class DataLoader:
    """Efficient loader for market.csv files.
    
    Handles parsing of wide-format CSV files with timestamp and multiple token pairs.
    Expected format: Timestamp, SOLUSDT_BID, SOLUSDT_ASK, ETHUSDT_BID, ETHUSDT_ASK, ...
    """
    file_path: Path
    encoding: str = "utf-8"
    batch_size: int = 10000

    def __post_init__(self) -> None:
        if isinstance(self.file_path, str):
            self.file_path = Path(self.file_path)
        if not self.file_path.exists():
            raise FileNotFoundError(f"Data file not found: {self.file_path}")

    def detect_tokens(self) -> list[str]:
        """Detect all tokens in the CSV header."""
        tokens = []
        with open(self.file_path, "r", encoding=self.encoding) as f:
            reader = csv.reader(f)
            header = next(reader)
        
        for col in header[1:]:  # Skip timestamp column
            if col.endswith("_BID"):
                token = col.replace("_BID", "")
                if token not in tokens:
                    tokens.append(token)
        
        logger.info(f"Detected {len(tokens)} tokens: {tokens}")
        return tokens

    def parse_timestamp(self, ts_str: str) -> int:
        """Parse timestamp string to Unix timestamp in milliseconds."""
        try:
            dt = datetime.strptime(ts_str, "%m/%d/%Y %H:%M:%S")
            return int(dt.timestamp() * 1000)
        except ValueError:
            try:
                dt = datetime.fromisoformat(ts_str)
                return int(dt.timestamp() * 1000)
            except ValueError as e:
                logger.warning(f"Failed to parse timestamp '{ts_str}': {e}")
                return 0

    def _read_header(self) -> tuple[list[str], dict[str, tuple[int, int]]]:
        """Read header and build token column mapping."""
        with open(self.file_path, "r", encoding=self.encoding) as f:
            reader = csv.reader(f)
            header = next(reader)
        
        tokens: list[str] = []
        token_cols: dict[str, tuple[int, int]] = {}
        
        for idx, col in enumerate(header[1:], start=1):
            if col.endswith("_BID"):
                token = col.replace("_BID", "")
                if token not in token_cols:
                    tokens.append(token)
                token_cols[token] = (token_cols.get(token, (0, 0))[0], idx)
            elif col.endswith("_ASK"):
                token = col.replace("_ASK", "")
                if token not in token_cols:
                    tokens.append(token)
                token_cols[token] = (token_cols.get(token, (0, 0))[0], idx)
        
        # Rebuild token_cols with both bid and ask indices
        final_token_cols: dict[str, tuple[int, int]] = {}
        for token in tokens:
            bid_idx = header.index(f"{token}_BID") if f"{token}_BID" in header else -1
            ask_idx = header.index(f"{token}_ASK") if f"{token}_ASK" in header else -1
            final_token_cols[token] = (bid_idx, ask_idx)
        
        return tokens, final_token_cols

    def count_records(self) -> int:
        """Count total number of records (excluding header)."""
        with open(self.file_path, "r", encoding=self.encoding) as f:
            return sum(1 for _ in f) - 1

    def iter_records(self) -> Iterator[tuple[int, int, dict[str, tuple[float, float]]]]:
        """Iterate over records yielding (record_idx, timestamp, prices).
        
        Yields:
            Tuple of (record_index, timestamp_ms, {token: (bid, ask)})
        """
        tokens, token_cols = self._read_header()
        
        with open(self.file_path, "r", encoding=self.encoding) as f:
            reader = csv.reader(f)
            next(reader)  # Skip header
            
            for record_idx, row in enumerate(reader):
                if not row or not row[0]:
                    continue
                
                timestamp = self.parse_timestamp(row[0])
                prices: dict[str, tuple[float, float]] = {}
                
                for token, (bid_col, ask_col) in token_cols.items():
                    try:
                        if bid_col > 0 and ask_col > 0:
                            bid = float(row[bid_col])
                            ask = float(row[ask_col])
                            if bid > 0 and ask > 0:
                                prices[token] = (bid, ask)
                    except (ValueError, IndexError):
                        continue
                
                if prices:
                    yield record_idx, timestamp, prices

    def load_to_matrix(
        self,
        max_records: Optional[int] = None,
        progress_callback: Optional[callable] = None
    ) -> PriceMatrix:
        """Load data into a PriceMatrix for fast access.
        
        Args:
            max_records: Maximum number of records to load (None for all)
            progress_callback: Optional callback(loaded, total) for progress
        
        Returns:
            PriceMatrix with all prices indexed by token
        """
        tokens = self.detect_tokens()
        total_records = self.count_records()
        
        if max_records:
            total_records = min(total_records, max_records)
        
        matrix = PriceMatrix.create(total_records, len(tokens), tokens)
        
        for record_idx, timestamp, prices in self.iter_records():
            if record_idx >= total_records:
                break
            
            matrix.set_prices(record_idx, timestamp, prices)
            
            if progress_callback and record_idx % 10000 == 0:
                progress_callback(record_idx, total_records)
        
        if progress_callback:
            progress_callback(total_records, total_records)
        
        logger.info(f"Loaded {matrix.n_records} records for {matrix.n_tokens} tokens")
        return matrix

    def iter_batches(self, batch_size: Optional[int] = None) -> Iterator[list[PricePoint]]:
        """Iterate over data in batches of PricePoints.
        
        Args:
            batch_size: Size of each batch (uses self.batch_size if None)
        
        Yields:
            List of PricePoint objects for each batch
        """
        batch_size = batch_size or self.batch_size
        batch: list[PricePoint] = []
        
        for record_idx, timestamp, prices in self.iter_records():
            dt = datetime.fromtimestamp(timestamp / 1000)
            
            for token, (bid, ask) in prices.items():
                batch.append(PricePoint(
                    timestamp=dt,
                    token=token,
                    bid=bid,
                    ask=ask
                ))
            
            if len(batch) >= batch_size:
                yield batch
                batch = []
        
        if batch:
            yield batch
