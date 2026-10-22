import React, { useState, useEffect } from 'react';
import { Activity, Database, Server, CheckCircle2, Shield } from 'lucide-react';
import { api } from '../services/api';
import { SystemStatus } from '../types';

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
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      <div>
        <h2 style={{ fontSize: '1.3rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Activity size={20} color="var(--accent-cyan)" />
          System Health, Freshness & Sync Diagnostics
        </h2>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
          Real-time diagnostics covering database health, Kline candle synchronization checkpoints, gap detection, and model serving.
        </p>
      </div>

      {/* Main Status Grid */}
      <div className="grid-4">
        <div className="card">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
            <Server size={16} />
            <span>Operational State</span>
          </div>
          <div style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--accent-green)', fontFamily: 'var(--font-mono)' }}>
            {status?.status || 'UNKNOWN'}
          </div>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
            v{status?.version} [{status?.environment}]
          </span>
        </div>

        <div className="card">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
            <Database size={16} />
            <span>Total Stored Candles</span>
          </div>
          <div style={{ fontSize: '1.5rem', fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--accent-cyan)' }}>
            {status?.total_candles_stored.toLocaleString() || 0}
          </div>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
            Normalized UTC Candlesticks
          </span>
        </div>

        <div className="card">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
            <CheckCircle2 size={16} />
            <span>Audited Forecasts</span>
          </div>
          <div style={{ fontSize: '1.5rem', fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
            {status?.total_reconciled_forecasts} / {status?.total_forecasts_generated}
          </div>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
            Reconciled vs Total Generated
          </span>
        </div>

        <div className="card">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
            <Shield size={16} />
            <span>Active Production Models</span>
          </div>
          <div style={{ fontSize: '1.5rem', fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
            {status?.active_models_count || 0}
          </div>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
            Serving Live Predictions
          </span>
        </div>
      </div>

      {/* Sync Checkpoints Table */}
      <div className="card" style={{ padding: 0 }}>
        <div style={{ padding: '1rem 1.25rem', borderBottom: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <strong style={{ fontSize: '1.05rem' }}>Market Synchronization Checkpoints & Gap Integrity</strong>
          <button className="btn btn-secondary" onClick={loadStatus} style={{ padding: '0.35rem 0.8rem', fontSize: '0.8rem' }}>
            Refresh Status
          </button>
        </div>

        {loading ? (
          <div className="loading-box">
            <div className="spinner"></div>
            <span>Checking checkpoints...</span>
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
                    <td>{cp.total_candles.toLocaleString()}</td>
                    <td>{cp.last_close_time ? cp.last_close_time.slice(0, 19).replace('T', ' ') : 'N/A'}</td>
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
                      {cp.updated_at.slice(0, 19).replace('T', ' ')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="loading-box">
            <p>No synchronization checkpoints found yet. Checkpoints are automatically updated during market sync cycles.</p>
          </div>
        )}
      </div>
    </div>
  );
};
