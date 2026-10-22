import React, { useState, useEffect } from 'react';
import { Activity, Database, Server, CheckCircle2, Shield, RefreshCw } from 'lucide-react';
import { api } from '../services/api';
import { SystemStatus } from '../types';
import { formatNumber, formatDateTime } from '../utils/formatters';

export const SystemStatusView: React.FC = () => {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  const loadStatus = async () => {
    try {
      setLoading(true);
      const res = await api.getSystemStatus();
      setStatus(res);
    } catch (err: any) {
      console.error('Failed to load system status:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStatus();
  }, []);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', width: '100%' }}>
      <div>
        <h2 style={{ fontSize: '1.3rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
          <Activity size={20} color="var(--accent-cyan)" />
          System Health, Freshness & Sync Diagnostics
        </h2>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
          Real-time diagnostics covering database connectivity, Kline candlestick synchronization checkpoints, deterministic gap detection, and model serving.
        </p>
      </div>

      {/* Main Status Grid */}
      <div className="grid-4">
        <div className="card">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
            <Server size={16} />
            <span>Operational State</span>
          </div>
          <div style={{ fontSize: '1.6rem', fontWeight: 700, color: status?.status === 'OPERATIONAL' ? 'var(--accent-green)' : 'var(--accent-red)', fontFamily: 'var(--font-mono)', margin: '0.25rem 0' }}>
            {status?.status || 'UNKNOWN'}
          </div>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            v{status?.version} [{status?.environment}]
          </span>
        </div>

        <div className="card">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
            <Database size={16} />
            <span>Total Stored Candlesticks</span>
          </div>
          <div style={{ fontSize: '1.6rem', fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--accent-cyan)', margin: '0.25rem 0' }}>
            {formatNumber(status?.total_candles_stored || 0, 0)}
          </div>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            Normalized UTC Candles
          </span>
        </div>

        <div className="card">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
            <CheckCircle2 size={16} />
            <span>Audited Forecasts</span>
          </div>
          <div style={{ fontSize: '1.6rem', fontWeight: 700, fontFamily: 'var(--font-mono)', margin: '0.25rem 0' }}>
            {formatNumber(status?.total_reconciled_forecasts || 0, 0)} / {formatNumber(status?.total_forecasts_generated || 0, 0)}
          </div>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            Reconciled vs Total
          </span>
        </div>

        <div className="card">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
            <Shield size={16} />
            <span>Active Production Models</span>
          </div>
          <div style={{ fontSize: '1.6rem', fontWeight: 700, fontFamily: 'var(--font-mono)', margin: '0.25rem 0' }}>
            {status?.active_models_count || 0}
          </div>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            Serving Live Predictions
          </span>
        </div>
      </div>

      {/* Sync Checkpoints Table */}
      <div className="card" style={{ padding: 0 }}>
        <div style={{ padding: '1rem 1.25rem', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.75rem' }}>
          <strong style={{ fontSize: '1.05rem' }}>Market Synchronization Checkpoints & Gap Integrity</strong>
          <button className="btn btn-secondary" onClick={loadStatus} disabled={loading} style={{ padding: '0.4rem 0.85rem', fontSize: '0.8rem' }}>
            <RefreshCw size={13} className={loading ? 'spinner' : ''} />
            <span>Refresh Diagnostics</span>
          </button>
        </div>

        {loading ? (
          <div className="loading-box">
            <div className="spinner"></div>
            <span>Checking checkpoints & database state...</span>
          </div>
        ) : status && status.checkpoints.length > 0 ? (
          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Asset Symbol</th>
                  <th>Interval</th>
                  <th>Total Candles</th>
                  <th>Latest Synced Candle</th>
                  <th>Sync Status</th>
                  <th>Detected Gaps</th>
                  <th>Last Sync Update</th>
                </tr>
              </thead>
              <tbody>
                {status.checkpoints.map((cp) => (
                  <tr key={`${cp.symbol}-${cp.timeframe}`}>
                    <td><strong style={{ color: '#fff' }}>{cp.symbol}</strong></td>
                    <td>{cp.timeframe}</td>
                    <td>{formatNumber(cp.total_candles, 0)}</td>
                    <td>{cp.last_close_time ? formatDateTime(cp.last_close_time) : '—'}</td>
                    <td>
                      <span className={`badge ${cp.last_sync_status === 'SUCCESS' ? 'badge-success' : 'badge-warning'}`}>
                        {cp.last_sync_status}
                      </span>
                    </td>
                    <td>
                      {cp.detected_gaps_count === 0 ? (
                        <span className="badge badge-success">0 gaps (Clean)</span>
                      ) : (
                        <span className="badge badge-danger">{cp.detected_gaps_count} gaps detected</span>
                      )}
                    </td>
                    <td style={{ color: 'var(--text-muted)' }}>
                      {formatDateTime(cp.updated_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="loading-box">
            <p>No synchronization checkpoints found yet. Checkpoints are automatically generated when triggering Binance market sync.</p>
          </div>
        )}
      </div>
    </div>
  );
};
