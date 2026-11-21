import React, { useState, useEffect } from 'react';
import {
  Activity,
  Database,
  Server,
  CheckCircle2,
  Shield,
  RefreshCw,
  Cpu,
  HardDrive,
  Radio,
  Trash2,
  AlertTriangle
} from 'lucide-react';
import { api } from '../services/api';
import { SystemStatus, SystemResourcesResponse } from '../types';
import { formatNumber, formatDateTime } from '../utils/formatters';

export const SystemStatusView: React.FC = () => {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [resources, setResources] = useState<SystemResourcesResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [runningAction, setRunningAction] = useState<boolean>(false);

  const loadStatus = async () => {
    try {
      setLoading(true);
      setError(null);
      const [statRes, resRes] = await Promise.all([
        api.getSystemStatus(),
        api.getSystemResources()
      ]);
      setStatus(statRes);
      setResources(resRes);
    } catch (err: any) {
      setError(err?.message || 'Failed to load system diagnostics.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStatus();
    const timer = setInterval(loadStatus, 10000);
    return () => clearInterval(timer);
  }, []);

  const handleFlush = async () => {
    try {
      setRunningAction(true);
      const res = await api.flushStreamingBuffer();
      setActionMsg(`Flushed ${res.flushed} queued broker messages (${res.bronze_records || 0} Bronze, ${res.silver_klines || 0} Silver).`);
      await loadStatus();
    } catch (err: any) {
      setActionMsg(`Flush failed: ${err.message}`);
    } finally {
      setRunningAction(false);
    }
  };

  const handleRetention = async () => {
    try {
      setRunningAction(true);
      const res = await api.runRetentionCleanup();
      setActionMsg(`Retention complete: removed ${res.deleted_files} files (${res.freed_bytes} bytes freed).`);
      await loadStatus();
    } catch (err: any) {
      setActionMsg(`Retention failed: ${err.message}`);
    } finally {
      setRunningAction(false);
    }
  };

  return (
    <div className="view-container">
      <div className="view-header">
        <div>
          <div className="view-tag">RESOURCE BUDGET • BROKER LAG • STORAGE TELEMETRY</div>
          <h1 className="view-title">System Health & Resource Observatory</h1>
          <p className="view-subtitle">
            Measured single-node RSS memory, CPU utilization, NATS JetStream lag, Medallion storage sizes, and sync checkpoints.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.6rem', flexWrap: 'wrap' }}>
          <button className="btn btn-secondary btn-sm" onClick={handleFlush} disabled={runningAction}>
            <Radio size={13} />
            <span>Flush Buffer</span>
          </button>
          <button className="btn btn-secondary btn-sm" onClick={handleRetention} disabled={runningAction}>
            <Trash2 size={13} />
            <span>Run Retention</span>
          </button>
          <button className="btn btn-primary btn-sm" onClick={loadStatus} disabled={loading}>
            <RefreshCw size={13} className={loading ? 'spin' : ''} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {actionMsg && (
        <div className="alert-banner info" style={{ marginBottom: '1rem' }}>
          <Activity size={15} />
          <span>{actionMsg}</span>
        </div>
      )}

      {error && (
        <div className="alert-banner error" style={{ marginBottom: '1rem' }}>
          <AlertTriangle size={15} />
          <span>{error}</span>
        </div>
      )}

      {/* Main Status Grid */}
      <div className="kpi-grid">
        <div className="kpi-card">
          <div className="kpi-header">
            <span className="kpi-label">Operational Profile</span>
            <Server size={16} color="var(--accent-cyan)" />
          </div>
          <div className="kpi-value" style={{ color: status?.status === 'OPERATIONAL' ? 'var(--semantic-green)' : 'var(--semantic-red)' }}>
            {status?.status || 'UNKNOWN'}
          </div>
          <div className="kpi-subtext">
            Profile: <strong>{resources?.profile?.toUpperCase() || '—'}</strong> • v{status?.version}
          </div>
        </div>

        <div className="kpi-card">
          <div className="kpi-header">
            <span className="kpi-label">Process RSS / Budget</span>
            <Cpu size={16} color="var(--accent-cyan)" />
          </div>
          <div className="kpi-value">
            {resources ? `${resources.measured.process_rss_mb} MB` : '—'}
          </div>
          <div className="kpi-subtext">
            {resources
              ? `${resources.measured.budget_utilization_pct}% of ${resources.limits.total_memory_mb} MB cap • CPU ${resources.measured.process_cpu_percent}%`
              : 'Measuring...'}
          </div>
        </div>

        <div className="kpi-card">
          <div className="kpi-header">
            <span className="kpi-label">Host RAM & Disk Free</span>
            <HardDrive size={16} color="var(--accent-cyan)" />
          </div>
          <div className="kpi-value">
            {resources ? `${resources.measured.host_ram_available_mb} MB` : '—'}
          </div>
          <div className="kpi-subtext">
            {resources
              ? `of ${resources.measured.host_ram_total_mb} MB RAM • ${resources.measured.disk_free_gb} GB disk free`
              : '—'}
          </div>
        </div>

        <div className="kpi-card">
          <div className="kpi-header">
            <span className="kpi-label">Stored Candles & Models</span>
            <Database size={16} color="var(--accent-cyan)" />
          </div>
          <div className="kpi-value">
            {formatNumber(status?.total_candles_stored || 0, 0)}
          </div>
          <div className="kpi-subtext">
            {status?.active_models_count || 0} active models • {status?.total_reconciled_forecasts || 0}/{status?.total_forecasts_generated || 0} forecasts reconciled
          </div>
        </div>
      </div>

      {/* Streaming Broker & Storage Breakdown */}
      {resources && (
        <div className="grid-2-cols" style={{ marginTop: '1.25rem' }}>
          <div className="panel">
            <div className="panel-header">
              <div className="panel-title">
                <Radio size={17} color="var(--accent-cyan)" />
                <span>NATS JetStream & Bounded Queue Telemetry</span>
              </div>
              <span className={`badge ${resources.streaming.broker_connected ? 'badge-success' : 'badge-warning'}`}>
                {resources.streaming.broker_connected ? 'BROKER ONLINE' : 'BROKER OFFLINE'}
              </span>
            </div>
            <div className="grid-3-cols">
              <div className="mini-card">
                <div className="mini-card-label">Broker Stream Msgs</div>
                <div className="mini-card-value">{formatNumber(resources.streaming.broker_messages, 0)}</div>
              </div>
              <div className="mini-card">
                <div className="mini-card-label">Consumer Lag</div>
                <div className="mini-card-value">{resources.streaming.total_consumer_lag}</div>
              </div>
              <div className="mini-card">
                <div className="mini-card-label">Queue Depth</div>
                <div className="mini-card-value">
                  {resources.streaming.queue_depth} / {resources.limits.stream_queue_maxsize}
                </div>
              </div>
              <div className="mini-card">
                <div className="mini-card-label">WS Received</div>
                <div className="mini-card-value">{formatNumber(resources.streaming.events_received, 0)}</div>
              </div>
              <div className="mini-card">
                <div className="mini-card-label">Consumed</div>
                <div className="mini-card-value">{formatNumber(resources.streaming.events_consumed, 0)}</div>
              </div>
              <div className="mini-card">
                <div className="mini-card-label">DLQ Quarantined</div>
                <div className="mini-card-value" style={{ color: resources.streaming.dlq_count > 0 ? 'var(--semantic-red)' : undefined }}>
                  {resources.streaming.dlq_count}
                </div>
              </div>
            </div>
          </div>

          <div className="panel">
            <div className="panel-header">
              <div className="panel-title">
                <Shield size={17} color="var(--accent-cyan)" />
                <span>Medallion Storage Usage & Engine Limits</span>
              </div>
              <span className="badge badge-neutral">DuckDB {resources.limits.duckdb_memory_limit}</span>
            </div>
            <div className="grid-3-cols">
              <div className="mini-card">
                <div className="mini-card-label">Bronze (zstd JSONL)</div>
                <div className="mini-card-value">{resources.measured.storage_mb.bronze} MB</div>
              </div>
              <div className="mini-card">
                <div className="mini-card-label">Silver (Parquet)</div>
                <div className="mini-card-value">{resources.measured.storage_mb.silver} MB</div>
              </div>
              <div className="mini-card">
                <div className="mini-card-label">Gold (Parquet)</div>
                <div className="mini-card-value">{resources.measured.storage_mb.gold} MB</div>
              </div>
              <div className="mini-card">
                <div className="mini-card-label">NATS Store</div>
                <div className="mini-card-value">{resources.measured.storage_mb.nats} MB</div>
              </div>
              <div className="mini-card">
                <div className="mini-card-label">Metadata DB</div>
                <div className="mini-card-value">{resources.measured.storage_mb.metadata_db} MB</div>
              </div>
              <div className="mini-card">
                <div className="mini-card-label">Batch / Flush</div>
                <div className="mini-card-value" style={{ fontSize: '0.9rem' }}>
                  {resources.limits.bronze_flush_max_records} / {resources.limits.microbatch_flush_max_age_sec}s
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Sync Checkpoints Table */}
      <div className="panel" style={{ marginTop: '1.25rem' }}>
        <div className="panel-header">
          <div className="panel-title">
            <CheckCircle2 size={17} color="var(--accent-cyan)" />
            <span>Market Synchronization Checkpoints & Gap Integrity</span>
          </div>
        </div>

        {loading && !status ? (
          <div className="loading-state">
            <RefreshCw size={22} className="spin" />
            <span>Checking checkpoints & database state...</span>
          </div>
        ) : status && status.checkpoints.length > 0 ? (
          <div className="table-wrapper">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Asset Symbol</th>
                  <th>Interval</th>
                  <th className="num">Total Candles</th>
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
                    <td style={{ fontFamily: 'var(--font-mono)' }}>{cp.timeframe}</td>
                    <td className="num">{formatNumber(cp.total_candles, 0)}</td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem' }}>
                      {cp.last_close_time ? formatDateTime(cp.last_close_time) : '—'}
                    </td>
                    <td>
                      <span className={`badge ${cp.last_sync_status === 'SUCCESS' ? 'badge-success' : 'badge-warning'}`}>
                        {cp.last_sync_status}
                      </span>
                    </td>
                    <td>
                      {cp.detected_gaps_count === 0 ? (
                        <span className="badge badge-success">0 gaps (Clean)</span>
                      ) : (
                        <span className="badge badge-danger">{cp.detected_gaps_count} gaps</span>
                      )}
                    </td>
                    <td style={{ color: 'var(--text-muted)', fontSize: '0.78rem' }}>
                      {formatDateTime(cp.updated_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty-state-container">
            <Database size={32} className="empty-state-icon" />
            <div className="empty-state-title">No Synchronization Checkpoints Yet</div>
            <div className="empty-state-message">
              Checkpoints are created automatically when REST market sync or Medallion pipelines execute.
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
