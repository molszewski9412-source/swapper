import { useEffect, useState, useCallback } from 'react';
import {
  connectWebSocket,
  disconnectWebSocket,
  fetchStatus,
  startTrader,
  stopTrader,
  resetTrader,
} from './api';
import type { Status, MatrixRow } from './types';
import './App.css';

const formatNumber = (n: number, decimals = 2) => {
  return n.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
};

const formatPercent = (n: number) => {
  const sign = n >= 0 ? '+' : '';
  return `${sign}${n.toFixed(2)}%`;
};

const formatAmount = (n: number) => {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(2)}K`;
  if (n >= 1) return n.toFixed(4);
  return n.toFixed(8);
};

function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState<'gain' | 'momentum' | 'name' | 'price'>('gain');

  const handleUpdate = useCallback((newStatus: Status) => {
    setStatus(newStatus);
    setError(null);
  }, []);

  useEffect(() => {
    connectWebSocket(handleUpdate);
    
    // Fallback to polling if WebSocket doesn't connect
    const pollInterval = setInterval(async () => {
      try {
        const data = await fetchStatus();
        handleUpdate(data);
      } catch (e) {
        console.error('Polling error:', e);
      }
    }, 2000);

    return () => {
      disconnectWebSocket();
      clearInterval(pollInterval);
    };
  }, [handleUpdate]);

  const handleStart = async () => {
    setLoading(true);
    try {
      await startTrader();
    } catch (e: any) {
      setError(e.message);
    }
    setLoading(false);
  };

  const handleStop = async () => {
    setLoading(true);
    try {
      await stopTrader();
    } catch (e: any) {
      setError(e.message);
    }
    setLoading(false);
  };

  const handleReset = async () => {
    if (!confirm('Czy na pewno chcesz zresetować portfolio?')) return;
    setLoading(true);
    try {
      await resetTrader();
      setStatus(null);
    } catch (e: any) {
      setError(e.message);
    }
    setLoading(false);
  };

  const getGainColor = (gain: number) => {
    if (gain > 0) return 'text-green-400';
    if (gain < 0) return 'text-red-400';
    return 'text-gray-400';
  };

  const getSortedMatrix = (matrix: MatrixRow[]) => {
    const sorted = [...matrix];
    switch (sortBy) {
      case 'gain':
        sorted.sort((a, b) => b.gain_pct - a.gain_pct);
        break;
      case 'momentum':
        sorted.sort((a, b) => b.momentum - a.momentum);
        break;
      case 'name':
        sorted.sort((a, b) => a.token.localeCompare(b.token));
        break;
      case 'price':
        sorted.sort((a, b) => b.current_price - a.current_price);
        break;
    }
    return sorted;
  };

  const renderMatrixRow = (row: MatrixRow, index: number) => {
    const gainColor = getGainColor(row.gain_pct);
    const momentumColor = getGainColor(row.momentum * 100);

    return (
      <tr
        key={row.symbol}
        className={`border-b border-gray-800 hover:bg-gray-800/50 transition-colors ${
          row.is_holding ? 'bg-green-900/20 border-l-4 border-l-green-500' : ''
        }`}
      >
        <td className="py-3 px-4">
          <div className="flex items-center gap-2">
            <span className="text-gray-500 text-sm">{index + 1}</span>
            <span className={`font-bold ${row.is_holding ? 'text-green-400' : 'text-white'}`}>
              {row.token}
            </span>
            {row.is_holding && (
              <span className="px-2 py-0.5 text-xs bg-green-500/20 text-green-400 rounded">
                HOLDING
              </span>
            )}
          </div>
        </td>
        <td className="py-3 px-4 text-right font-mono text-sm text-gray-300">
          {formatAmount(row.baseline_amount)}
        </td>
        <td className="py-3 px-4 text-right font-mono text-sm text-white font-semibold">
          {formatAmount(row.actual_equivalent_qty)}
        </td>
        <td className={`py-3 px-4 text-right font-mono font-bold ${gainColor}`}>
          {formatPercent(row.gain_pct)}
        </td>
        <td className={`py-3 px-4 text-right font-mono ${momentumColor}`}>
          {formatPercent(row.momentum * 100)}
        </td>
      </tr>
    );
  };

  if (error) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="bg-red-900/50 border border-red-500 rounded-lg p-6 max-w-md">
          <h2 className="text-red-400 font-bold text-lg mb-2">Error</h2>
          <p className="text-red-300">{error}</p>
          <button
            onClick={() => setError(null)}
            className="mt-4 px-4 py-2 bg-red-600 hover:bg-red-700 rounded text-white"
          >
            Dismiss
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {/* Header */}
      <header className="bg-gray-900 border-b border-gray-800 sticky top-0 z-10">
        <div className="container mx-auto px-4 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold bg-gradient-to-r from-green-400 to-blue-500 bg-clip-text text-transparent">
                CHAMPION ULTIMATE
              </h1>
              <p className="text-gray-500 text-sm">Real-time Momentum Trading Backtester</p>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={handleStart}
                disabled={loading || status?.running}
                className={`px-4 py-2 rounded-lg font-semibold transition-all ${
                  status?.running
                    ? 'bg-gray-700 text-gray-500 cursor-not-allowed'
                    : 'bg-green-600 hover:bg-green-500 text-white'
                }`}
              >
                ▶ START
              </button>
              <button
                onClick={handleStop}
                disabled={loading || !status?.running}
                className={`px-4 py-2 rounded-lg font-semibold transition-all ${
                  !status?.running
                    ? 'bg-gray-700 text-gray-500 cursor-not-allowed'
                    : 'bg-red-600 hover:bg-red-500 text-white'
                }`}
              >
                ⏹ STOP
              </button>
              <button
                onClick={handleReset}
                disabled={loading}
                className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg font-semibold transition-all"
              >
                🔄 RESET
              </button>
            </div>
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-6">
        {/* Strategy Info */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
          <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
            <div className="text-gray-500 text-sm mb-1">Strategy</div>
            <div className="text-xl font-bold text-green-400">
              {status?.strategy.name || 'N/A'}
            </div>
          </div>
          <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
            <div className="text-gray-500 text-sm mb-1">Parameters</div>
            <div className="text-lg font-mono">
              L{status?.strategy.lookback} T{((status?.strategy.threshold || 0) * 100).toFixed(0)}% I
              {status?.strategy.interval}s
            </div>
          </div>
          <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
            <div className="text-gray-500 text-sm mb-1">Tokens Tracked</div>
            <div className="text-2xl font-bold">{status?.portfolio.tokens_tracked || 0}</div>
          </div>
          <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
            <div className="text-gray-500 text-sm mb-1">Status</div>
            <div className={`text-xl font-bold ${status?.running ? 'text-green-400' : 'text-gray-500'}`}>
              {status?.running ? '● RUNNING' : '○ STOPPED'}
            </div>
          </div>
        </div>

        {/* Portfolio Stats */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
          <div className="bg-green-900/30 rounded-lg p-4 border-2 border-green-500">
            <div className="text-green-400 text-sm mb-1 font-semibold">🎯 YOUR PORTFOLIO HOLDS</div>
            <div className="text-2xl font-bold text-white">
              {status?.portfolio.holding_token.replace('USDT', '') || 'N/A'}
            </div>
            <div className="text-gray-300 font-mono text-sm mt-1">
              {formatAmount(status?.portfolio.holding_amount || 0)} tokens
            </div>
          </div>
          <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
            <div className="text-gray-500 text-sm mb-1">Portfolio Value</div>
            <div className="text-2xl font-bold text-white">
              ${formatNumber(status?.portfolio.holding_value_usdt || 0)}
            </div>
          </div>
          <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
            <div className="text-gray-500 text-sm mb-1">Total Gain</div>
            <div className={`text-2xl font-bold ${getGainColor(status?.portfolio.total_gain_pct || 0)}`}>
              {formatPercent(status?.portfolio.total_gain_pct || 0)}
            </div>
          </div>
          <div className="bg-gray-900 rounded-lg p-4 border border-gray-800">
            <div className="text-gray-500 text-sm mb-1">Total Swaps</div>
            <div className="text-2xl font-bold text-white">
              {status?.portfolio.total_swaps || 0}
            </div>
          </div>
        </div>

        {/* Main Content */}
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
          {/* Matrix Table */}
          <div className="xl:col-span-2 bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
            <div className="p-4 border-b border-gray-800 flex items-center justify-between flex-wrap gap-2">
              <h2 className="text-lg font-bold">📊 What if you held each token?</h2>
              <div className="flex items-center gap-4">
                <select
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value as typeof sortBy)}
                  className="bg-gray-800 text-white text-sm px-3 py-1 rounded border border-gray-700 focus:outline-none focus:border-blue-500"
                >
                  <option value="gain">Sort: Gain %</option>
                  <option value="momentum">Sort: Momentum</option>
                  <option value="name">Sort: Name A-Z</option>
                  <option value="price">Sort: Price</option>
                </select>
                <span className="text-gray-500 text-sm">
                  Updated: {status?.portfolio.last_update
                    ? new Date(status.portfolio.last_update).toLocaleTimeString()
                    : 'N/A'}
                </span>
              </div>
            </div>
            <div className="px-4 py-2 bg-blue-900/30 border-b border-gray-800 text-sm text-blue-300">
              💡 This shows how each token performed if you had bought $1000 of each at start. 
              Your actual portfolio holds only ONE token at a time (see above).
            </div>
            <div className="overflow-x-auto max-h-[600px] overflow-y-auto">
              <table className="w-full">
                <thead className="bg-gray-800 sticky top-0">
                  <tr>
                    <th className="py-3 px-4 text-left text-gray-400 font-semibold text-sm">Token</th>
                    <th className="py-3 px-4 text-right text-gray-400 font-semibold text-sm">Baseline Qty</th>
                    <th className="py-3 px-4 text-right text-gray-400 font-semibold text-sm">Actual Eq Qty</th>
                    <th className="py-3 px-4 text-right text-gray-400 font-semibold text-sm">Gain %</th>
                    <th className="py-3 px-4 text-right text-gray-400 font-semibold text-sm">Momentum</th>
                  </tr>
                </thead>
                <tbody>
                  {status?.matrix && getSortedMatrix(status.matrix).map((row, index) => renderMatrixRow(row, index))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Swap History */}
          <div className="bg-gray-900 rounded-lg border border-gray-800 overflow-hidden">
            <div className="p-4 border-b border-gray-800">
              <h2 className="text-lg font-bold">Swap History</h2>
            </div>
            <div className="overflow-y-auto max-h-[600px]">
              {status?.swaps && status.swaps.length > 0 ? (
                <div className="divide-y divide-gray-800">
                  {[...status.swaps].reverse().map((swap, index) => (
                    <div key={index} className="p-4 hover:bg-gray-800/50 transition-colors">
                      <div className="flex items-center justify-between mb-2">
                        <span className="font-bold text-green-400">{swap.from_token}</span>
                        <span className="text-gray-500">→</span>
                        <span className="font-bold text-blue-400">{swap.to_token}</span>
                      </div>
                      <div className="text-gray-400 text-sm font-mono">
                        {formatAmount(swap.from_amount)} → {formatAmount(swap.to_amount)}
                      </div>
                      <div className="text-gray-500 text-xs mt-1">
                        Fee: {swap.fee_pct.toFixed(2)}%
                      </div>
                      <div className="text-gray-600 text-xs">
                        {new Date(swap.timestamp).toLocaleTimeString()}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="p-8 text-center text-gray-500">
                  <div className="text-4xl mb-4">📊</div>
                  <p>No swaps yet</p>
                  <p className="text-sm mt-2">Start the trader to begin</p>
                </div>
              )}
            </div>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-gray-800 mt-8 py-4">
        <div className="container mx-auto px-4 text-center text-gray-500 text-sm">
          CHAMPION ULTIMATE • Real-time Backtester • WebSocket Connected: {status ? '✓' : '✗'}
        </div>
      </footer>
    </div>
  );
}

export default App;
