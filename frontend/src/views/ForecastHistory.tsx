import React, { useState, useEffect } from 'react';
import { History, CheckCircle2, XCircle, Clock, CheckCheck, Filter, AlertCircle } from 'lucide-react';
import { api } from '../services/api';
import { ForecastHistoryResponse, SymbolInfo } from '../types';
import {
  formatCurrency,
  formatPercent,
  formatNumber,
  formatDateTime
} from '../utils/formatters';

export const ForecastHistory: React.FC = () => {
  const [data, setData] = useState<ForecastHistoryResponse | null>(null);
  const [symbols, setSymbols] = useState<SymbolInfo[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [symbolFilter, setSymbolFilter] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [reconciling, setReconciling] = useState<boolean>(false);
  const [reconcileResult, setReconcileResult] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const loadHistory = async () => {
    try {
      setLoading(true);
      setLoadError(null);
      const [res, syms] = await Promise.all([
        api.getForecasts(symbolFilter || undefined, statusFilter || undefined, 1, 100),
        api.getSymbols().catch(() => [])
      ]);
      setData(res);
      if (syms.length > 0) setSymbols(syms);
    } catch (err: any) {
      setLoadError(err?.message || 'Failed to load forecast audit ledger.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadHistory();
  }, [symbolFilter, statusFilter]);

  const handleReconcile = async () => {
    try {
      setReconciling(true);
      setReconcileResult(null);
      const res = await api.reconcileForecasts();
      setReconcileResult({
        type: 'success',
        text: `Reconciliation complete: evaluated ${res.reconciled_count} mature forecasts against exchange candles.`
      });
      await loadHistory();
    } catch (err: any) {
      setReconcileResult({
        type: 'error',
        text: `Reconciliation failed: ${err.message}`
      });
    } finally {
      setReconciling(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', width: '100%' }}>
      {/* 1. Header & Summary Stats */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h2 style={{ fontSize: '1.3rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
            <History size={20} color="var(--accent-cyan)" />
            Forecast Audit History & Realization Ledger
          </h2>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            Immutable audit trail of generated predictions, evaluated against actual realized market prices once closed.
          </p>
        </div>

        <button
          id="reconcile-forecasts-btn"
          className="btn btn-primary"
          onClick={handleReconcile}
          disabled={reconciling}
        >
          <CheckCheck size={16} />
          <span>{reconciling ? 'Checking Realizations...' : 'Reconcile Mature Forecasts'}</span>
        </button>
      </div>

      {loadError && (
        <div className="alert-banner error" style={{ justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <AlertCircle size={16} />
            <span>{loadError}</span>
          </div>
          <button className="btn btn-secondary btn-sm" onClick={loadHistory}>Retry</button>
        </div>
      )}

      {reconcileResult && (
        <div style={{
          padding: '0.75rem 1rem',
          borderRadius: 'var(--radius-md)',
          background: reconcileResult.type === 'error' ? 'rgba(244, 63, 94, 0.12)' : 'rgba(0, 242, 254, 0.1)',
          color: reconcileResult.type === 'error' ? 'var(--accent-red)' : 'var(--accent-cyan)',
          border: `1px solid ${reconcileResult.type === 'error' ? 'rgba(244, 63, 94, 0.3)' : 'rgba(0, 242, 254, 0.3)'}`,
          fontSize: '0.85rem',
          display: 'flex',
          alignItems: 'center',
          gap: '0.5rem'
        }}>
          {reconcileResult.type === 'error' ? <AlertCircle size={16} /> : <CheckCircle2 size={16} />}
          <span>{reconcileResult.text}</span>
        </div>
      )}

      {/* KPI Stats Grid */}
      <div className="grid-4">
        <div className="card">
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Total Forecasts Generated</span>
          <div style={{ fontSize: '1.8rem', fontWeight: 700, fontFamily: 'var(--font-mono)', margin: '0.25rem 0' }}>
            {formatNumber(data?.total_count || 0, 0)}
          </div>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Immutable Ledger Records</span>
        </div>

        <div className="card">
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Reconciled (Mature)</span>
          <div style={{ fontSize: '1.8rem', fontWeight: 700, fontFamily: 'var(--font-mono)', margin: '0.25rem 0' }}>
            {formatNumber(data?.reconciled_count || 0, 0)}
          </div>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Evaluated vs Realized Candles</span>
        </div>

        <div className="card">
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Directional Hit Rate</span>
          <div style={{ fontSize: '1.8rem', fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--accent-green)', margin: '0.25rem 0' }}>
            {data && data.reconciled_count > 0 ? `${data.direction_hit_rate_pct.toFixed(1)}%` : '—'}
          </div>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Sign Accuracy on Realized</span>
        </div>

        <div className="card">
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Mean Percentage Error</span>
          <div style={{ fontSize: '1.8rem', fontWeight: 700, fontFamily: 'var(--font-mono)', margin: '0.25rem 0' }}>
            {data && data.reconciled_count > 0 ? `${data.mean_percentage_error.toFixed(2)}%` : '—'}
          </div>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Average Absolute Deviation</span>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="card" style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap', padding: '0.85rem 1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
          <Filter size={15} />
          <span>Filters:</span>
        </div>

        <select
          id="filter-symbol-select"
          className="form-select"
          style={{ width: 'auto', padding: '0.4rem 0.8rem', fontSize: '0.85rem' }}
          value={symbolFilter}
          onChange={(e) => setSymbolFilter(e.target.value)}
          aria-label="Filter by asset symbol"
        >
          <option value="">All Symbols</option>
          {(symbols.length > 0 ? symbols.map((s) => s.symbol) : ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT']).map((sym) => (
            <option key={sym} value={sym}>{sym}</option>
          ))}
        </select>

        <select
          id="filter-status-select"
          className="form-select"
          style={{ width: 'auto', padding: '0.4rem 0.8rem', fontSize: '0.85rem' }}
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          aria-label="Filter by reconciliation status"
        >
          <option value="">All Statuses</option>
          <option value="PENDING">Pending Realization</option>
          <option value="RECONCILED">Reconciled</option>
        </select>
      </div>

      {/* Ledger Table */}
      <div className="card" style={{ padding: 0 }}>
        {loading ? (
          <div className="loading-box">
            <div className="spinner"></div>
            <span>Loading forecast audit ledger...</span>
          </div>
        ) : data && data.records.length > 0 ? (
          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Timestamp / Asset</th>
                  <th>Horizon</th>
                  <th>Reference Price</th>
                  <th>Predicted Target</th>
                  <th>Actual Realized</th>
                  <th>Pred vs Actual</th>
                  <th>Error %</th>
                  <th>Outcome</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {data.records.map((r) => {
                  return (
                    <tr key={r.id}>
                      <td>
                        <div style={{ fontWeight: 600, color: '#fff' }}>{r.symbol}</div>
                        <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                          {formatDateTime(r.forecast_timestamp)}
                        </div>
                      </td>
                      <td>{r.horizon_steps}h ({r.timeframe})</td>
                      <td>{formatCurrency(r.current_price)}</td>
                      <td style={{ fontWeight: 600, color: 'var(--accent-cyan)' }}>
                        {formatCurrency(r.predicted_price)}{' '}
                        <span style={{ fontSize: '0.78rem', color: r.predicted_return_pct >= 0 ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                          ({formatPercent(r.predicted_return_pct)})
                        </span>
                      </td>
                      <td>
                        {r.realized_price !== null && r.realized_price !== undefined ? (
                          formatCurrency(r.realized_price)
                        ) : (
                          <span style={{ color: 'var(--text-muted)' }}>Pending maturity</span>
                        )}
                      </td>
                      <td>
                        <span style={{ color: r.predicted_direction === 'UP' ? 'var(--accent-green)' : 'var(--accent-red)', fontWeight: 600 }}>
                          {r.predicted_direction}
                        </span>
                        {r.realized_direction && (
                          <span style={{ color: 'var(--text-muted)' }}> → {r.realized_direction}</span>
                        )}
                      </td>
                      <td>
                        {r.percentage_error !== null && r.percentage_error !== undefined ? (
                          `${r.percentage_error.toFixed(2)}%`
                        ) : (
                          '—'
                        )}
                      </td>
                      <td>
                        {r.status === 'RECONCILED' ? (
                          r.direction_correct ? (
                            <span className="badge badge-success" style={{ display: 'inline-flex', alignItems: 'center', gap: '0.2rem' }}>
                              <CheckCircle2 size={12} /> HIT
                            </span>
                          ) : (
                            <span className="badge badge-danger" style={{ display: 'inline-flex', alignItems: 'center', gap: '0.2rem' }}>
                              <XCircle size={12} /> MISS
                            </span>
                          )
                        ) : (
                          <span className="badge badge-warning" style={{ display: 'inline-flex', alignItems: 'center', gap: '0.2rem' }}>
                            <Clock size={12} /> Awaiting close
                          </span>
                        )}
                      </td>
                      <td>
                        <span className={`badge ${r.status === 'RECONCILED' ? 'badge-success' : 'badge-warning'}`}>
                          {r.status}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="loading-box">
            <p>No forecast records found matching the active filters.</p>
          </div>
        )}
      </div>
    </div>
  );
};
