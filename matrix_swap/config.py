"""
Configuration for Matrix Swap
"""

# Mexc API
MEXC_API_URL = "https://api.mexc.com/api/v3/ticker/bookTicker"

# Trading fees (0.04% per side = 0.08% total for round trip)
FEE = 0.0004  # 0.04%

# Polling interval
POLL_INTERVAL_SEC = 1

# Initial portfolio value in USDT
INITIAL_USDT = 1000.0

# Top tokens by volume (will be fetched)
TOP_N_TOKENS = 50

# Swap threshold (gain % required to swap)
DEFAULT_THRESHOLD = 0.02  # 2%

# Storage
STORAGE_FILE = "matrix_data.json"
