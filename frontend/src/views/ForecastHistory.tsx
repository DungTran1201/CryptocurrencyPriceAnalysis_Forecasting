import React, { useState, useEffect } from 'react';
import { History, CheckCircle2, XCircle, Clock, CheckCheck, Filter } from 'lucide-react';
import { api } from '../services/api';
import { ForecastHistoryResponse } from '../types';

export const ForecastHistory: React.FC = () => {
  const [data, setData] = useState<ForecastHistoryResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [symbolFilter, setSymbolFilter] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [reconciling, setReconciling] = useState<boolean>(false);
  const [reconcileResult, setReconcileResult] = useState<string | null>(null);

  const loadHistory = async () => {
    try {
      setLoading(true);
      const res = await api.getForecasts(
        symbolFilter || undefined,
        statusFilter || undefined,
        1,
        100
      );
      setData(res);
    } catch (err: any) {
      console.error('Failed to load forecast history:', err);
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
      setReconcileResult(`Reconciliation complete. Reconciled ${res.reconciled_count} mature forecasts.`);
      await loadHistory();
    } catch (err: any) {
      setReconcileResult(`Reconciliation failed: ${err.message}`);
    } finally {
      setReconciling(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* 1. Header & Summary Stats */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h2 style={{ fontSize: '1.3rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <History size={20} color="var(--accent-cyan)" />
            Forecast Audit History & Realization Ledger
          </h2>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            Immutable audit record of all generated forecasts, evaluated against actual realized market prices once closed.
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

      {reconcileResult && (
        <div style={{ padding: '0.6rem 1rem', background: 'rgba(0, 242, 254, 0.1)', color: 'var(--accent-cyan)', borderRadius: 'var(--radius-md)', fontSize: '0.85rem' }}>
          {reconcileResult}
        </div>
      )}

      {/* KPI Stats Grid */}
      <div className="grid-4">
        <div className="card">
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Total Forecasts</span>
          <div style={{ fontSize: '1.8rem', fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
            {data?.total_count || 0}
          </div>
        </div>

        <div className="card">
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Reconciled (Mature)</span>
          <div style={{ fontSize: '1.8rem', fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
            {data?.reconciled_count || 0}
          </div>
        </div>

        <div className="card">
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Directional Hit Rate</span>
          <div style={{ fontSize: '1.8rem', fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--accent-green)' }}>
            {data?.direction_hit_rate_pct || 0}%
          </div>
        </div>

        <div className="card">
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Mean Percentage Error</span>
          <div style={{ fontSize: '1.8rem', fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
            {data?.mean_percentage_error || 0}%
          </div>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="card" style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap', padding: '0.8rem 1.25rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
          <Filter size={15} />
          <span>Filters:</span>
        </div>

        <select
          className="form-select"
          style={{ width: 'auto', padding: '0.4rem 0.8rem', fontSize: '0.85rem' }}
          value={symbolFilter}
          onChange={(e) => setSymbolFilter(e.target.value)}
        >
          <option value="">All Symbols</option>
          <option value="BTCUSDT">BTCUSDT</option>
          <option value="ETHUSDT">ETHUSDT</option>
          <option value="SOLUSDT">SOLUSDT</option>
          <option value="BNBUSDT">BNBUSDT</option>
        </select>

        <select
          className="form-select"
          style={{ width: 'auto', padding: '0.4rem 0.8rem', fontSize: '0.85rem' }}
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
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
                  <th>Timestamp / Symbol</th>
                  <th>Horizon</th>
                  <th>Reference Price</th>
                  <th>Predicted Target</th>
                  <th>Actual Realized</th>
                  <th>Pred vs Actual Dir</th>
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
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                          {r.forecast_timestamp.slice(0, 16).replace('T', ' ')}
                        </div>
                      </td>
                      <td>{r.horizon_steps}h ({r.timeframe})</td>
                      <td>${r.current_price.toFixed(2)}</td>
                      <td style={{ fontWeight: 600, color: 'var(--accent-cyan)' }}>
                        ${r.predicted_price.toFixed(2)} ({r.predicted_return_pct > 0 ? '+' : ''}{r.predicted_return_pct.toFixed(2)}%)
                      </td>
                      <td>
                        {r.realized_price !== null && r.realized_price !== undefined ? (
                          `$${r.realized_price.toFixed(2)}`
                        ) : (
                          <span style={{ color: 'var(--text-muted)' }}>Pending realization</span>
                        )}
                      </td>
                      <td>
                        <span style={{ color: r.predicted_direction === 'UP' ? 'var(--accent-green)' : 'var(--accent-red)' }}>
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
                          '-'
                        )}
                      </td>
                      <td>
                        {r.status === 'RECONCILED' ? (
                          r.direction_correct ? (
                            <span className="badge badge-success" style={{ display: 'inline-flex', alignItems: 'center', gap: '0.2rem' }}>
                              <CheckCircle2 size={12} /> WIN
                            </span>
                          ) : (
                            <span className="badge badge-danger" style={{ display: 'inline-flex', alignItems: 'center', gap: '0.2rem' }}>
                              <XCircle size={12} /> MISS
                            </span>
                          )
                        ) : (
                          <span className="badge badge-warning" style={{ display: 'inline-flex', alignItems: 'center', gap: '0.2rem' }}>
                            <Clock size={12} /> Awaiting target
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
            <p>No forecast records found matching filters.</p>
          </div>
        )}
      </div>
    </div>
  );
};
