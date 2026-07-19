export interface Swap {
  timestamp: string;
  from_token: string;
  to_token: string;
  from_amount: number;
  to_amount: number;
  fee_pct: number;
  holding_momentum: number;
  target_momentum: number;
}

export interface MatrixRow {
  token: string;
  symbol: string;
  baseline_amount: number;
  baseline_usdt: number;
  actual_usdt: number;
  gain_pct: number;
  momentum: number;
  current_price: number;
  is_holding: boolean;
  has_data: boolean;
}

export interface Portfolio {
  holding_token: string;
  holding_amount: number;
  holding_value_usdt: number;
  start_value_usdt: number;
  total_gain_pct: number;
  total_swaps: number;
  start_time: string;
  last_update: string;
  tokens_tracked: number;
}

export interface Strategy {
  name: string;
  lookback: number;
  threshold: number;
  interval: number;
}

export interface Status {
  running: boolean;
  strategy: Strategy;
  portfolio: Portfolio;
  matrix: MatrixRow[];
  swaps: Swap[];
}
