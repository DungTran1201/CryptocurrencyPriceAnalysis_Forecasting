import React, { useState, useEffect } from 'react';
import {
  Activity,
  Layers,
  Database,
  ShieldCheck,
  AlertTriangle,
  Play,
  Clock,
  ArrowRight,
  TrendingUp,
  Cpu,
  RefreshCw,
  ChevronRight
} from 'lucide-react';
import { api } from '../services/api';
import {
  PipelineOverview,
  PipelineRunItem,
  DataQualityOverview,
  SymbolInfo,
  LineageGraphResponse
} from '../types';
import { formatNumber, formatRelativeTime } from '../utils/formatters';

interface DataOpsOverviewProps {
  onNavigateTab: (tabId: string) => void;
}

export const DataOpsOverview: React.FC<DataOpsOverviewProps> = ({ onNavigateTab }) => {
  const [pipelineStats, setPipelineStats] = useState<PipelineOverview | null>(null);
  const [dqStats, setDqStats] = useState<DataQualityOverview | null>(null);
  const [recentRuns, setRecentRuns] = useState<PipelineRunItem[]>([]);
  const [symbols, setSymbols] = useState<SymbolInfo[]>([]);
  const [lineage, setLineage] = useState<LineageGraphResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedSymbol, setSelectedSymbol] = useState<string>('BTCUSDT');
  const [triggering, setTriggering] = useState<boolean>(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);
      const [pipeRes, dqRes, runsRes, symRes, linRes] = await Promise.all([
        api.getPipelineOverview(),
        api.getDataQualityOverview(),
        api.getPipelineRuns(undefined, undefined, 5),
        api.getSymbols(),
        api.getDataLineage()
      ]);
      setPipelineStats(pipeRes);
      setDqStats(dqRes);
      setRecentRuns(runsRes);
      setSymbols(symRes);
      setLineage(linRes);
    } catch (err: any) {
      setError(err?.message || 'Failed to load operational metrics.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 30000);
    return () => clearInterval(interval);
  }, []);

  const handleTriggerQuickSync = async () => {
    try {
      setTriggering(true);
      setActionMessage(null);
      await api.triggerPipeline(selectedSymbol, '1h', 14, false);
      setActionMessage(`Pipeline job dispatched for ${selectedSymbol} (1h). Refreshing in 3s...`);
      setTimeout(() => {
        loadData();
        setActionMessage(null);
      }, 3500);
    } catch (err: any) {
      setActionMessage(`Dispatch failed: ${err.message}`);
    } finally {
      setTriggering(false);
    }
  };

  const selectedSymInfo = symbols.find((s) => s.symbol === selectedSymbol);

  return (
    <div className="view-container">
      {/* Header & Quick Action Bar */}
      <div className="view-header">
        <div>
          <div className="view-tag">CONTROL PLANE • OBSERVABILITY & PIPELINES</div>
          <h1 className="view-title">Data Operations Overview</h1>
          <p className="view-subtitle">
            Real-time telemetry across the Medallion lifecycle: Ingestion → Validation → Marts → Features → Models.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <select
            className="filter-select"
            value={selectedSymbol}
            onChange={(e) => setSelectedSymbol(e.target.value)}
            aria-label="Target Symbol Selector"
          >
            {symbols.map((s) => (
              <option key={s.symbol} value={s.symbol}>
                {s.symbol} ({s.base_asset})
              </option>
            ))}
          </select>
          <button
            className="btn btn-primary"
            onClick={handleTriggerQuickSync}
            disabled={triggering}
            id="btn-quick-sync"
          >
            {triggering ? <RefreshCw size={14} className="spin" /> : <Play size={14} />}
            <span>{triggering ? 'Triggering...' : 'Sync Medallion'}</span>
          </button>
          <button
            className="btn btn-secondary"
            onClick={loadData}
            title="Refresh Metrics"
            aria-label="Refresh operational metrics"
          >
            <RefreshCw size={14} className={loading ? 'spin' : ''} />
          </button>
        </div>
      </div>

      {actionMessage && (
        <div className="alert-banner info" style={{ marginBottom: '1.25rem' }}>
          <Activity size={16} />
          <span>{actionMessage}</span>
        </div>
      )}

      {error && (
        <div className="alert-banner error" style={{ marginBottom: '1.25rem' }}>
          <AlertTriangle size={16} />
          <span>{error}</span>
        </div>
      )}

      {/* KPI Cards Grid */}
      <div className="kpi-grid">
        {/* Pipeline Runs */}
        <div className="kpi-card" onClick={() => onNavigateTab('pipelines')} style={{ cursor: 'pointer' }}>
          <div className="kpi-header">
            <span className="kpi-label">Pipeline Runs & State</span>
            <Layers size={16} color="var(--accent-cyan)" />
          </div>
          <div className="kpi-value">
            {pipelineStats ? (
              <>
                {pipelineStats.total_runs}{' '}
                <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)', fontWeight: 400 }}>
                  ({pipelineStats.success_rate_pct}% success)
                </span>
              </>
            ) : (
              '—'
            )}
          </div>
          <div className="kpi-subtext" style={{ display: 'flex', gap: '0.6rem' }}>
            <span style={{ color: 'var(--semantic-green)' }}>
              ✓ {pipelineStats?.succeeded_runs ?? 0} ok
            </span>
            <span style={{ color: 'var(--semantic-red)' }}>
              ✗ {pipelineStats?.failed_runs ?? 0} fail
            </span>
            <span style={{ color: 'var(--accent-cyan)' }}>
              ⚡ {pipelineStats?.running_runs ?? 0} active
            </span>
          </div>
        </div>

        {/* Data Quality Scorecard */}
        <div className="kpi-card" onClick={() => onNavigateTab('quality')} style={{ cursor: 'pointer' }}>
          <div className="kpi-header">
            <span className="kpi-label">Data Quality Adherence</span>
            <ShieldCheck size={16} color="var(--accent-cyan)" />
          </div>
          <div className="kpi-value">
            {dqStats && dqStats.total_rules_evaluated > 0 ? (
              <>
                {dqStats.passed_rules} / {dqStats.total_rules_evaluated}{' '}
                <span style={{ fontSize: '0.85rem', color: 'var(--semantic-green)', fontWeight: 400 }}>
                  ({dqStats.pass_rate_pct}%)
                </span>
              </>
            ) : (
              'Pending Check'
            )}
          </div>
          <div className="kpi-subtext">
            {dqStats ? `${dqStats.healthy_suites_count} healthy suites • ${dqStats.warning_suites_count} warnings` : 'Run check to score'}
          </div>
        </div>

        {/* Data Freshness */}
        <div className="kpi-card">
          <div className="kpi-header">
            <span className="kpi-label">Candle Freshness SLA</span>
            <Clock size={16} color="var(--accent-cyan)" />
          </div>
          <div className="kpi-value">
            {selectedSymInfo?.last_synced_at ? (
              formatRelativeTime(selectedSymInfo.last_synced_at)
            ) : (
              <span style={{ color: 'var(--text-muted)' }}>No sync</span>
            )}
          </div>
          <div className="kpi-subtext">
            Status:{' '}
            <span
              style={{
                color:
                  selectedSymInfo?.data_status === 'SYNCHRONIZED'
                    ? 'var(--semantic-green)'
                    : 'var(--semantic-amber)'
              }}
            >
              {selectedSymInfo?.data_status || 'UNKNOWN'}
            </span>{' '}
            • {selectedSymbol}
          </div>
        </div>

        {/* Processed Row Volume */}
        <div className="kpi-card" onClick={() => onNavigateTab('explorer')} style={{ cursor: 'pointer' }}>
          <div className="kpi-header">
            <span className="kpi-label">Total Volume Processed</span>
            <Database size={16} color="var(--accent-cyan)" />
          </div>
          <div className="kpi-value">
            {pipelineStats ? formatNumber(pipelineStats.total_rows_inserted) : '0'}
          </div>
          <div className="kpi-subtext">
            {pipelineStats?.avg_duration_seconds ? `Avg execution: ${pipelineStats.avg_duration_seconds}s` : 'Zero-copy pipeline'}
          </div>
        </div>
      </div>

      {/* Medallion Pipeline Flow Graph */}
      <div className="panel" style={{ marginTop: '1.5rem' }}>
        <div className="panel-header">
          <div className="panel-title">
            <Layers size={18} color="var(--accent-cyan)" />
            <span>Medallion Architecture & Stage Status</span>
          </div>
          <button className="btn btn-secondary btn-sm" onClick={() => onNavigateTab('quality')}>
            <span>View Full Lineage</span>
            <ArrowRight size={13} />
          </button>
        </div>

        <div className="medallion-pipeline-container">
          {lineage?.nodes.map((node, idx) => (
            <React.Fragment key={node.id}>
              <div className="medallion-node">
                <div className="node-layer-badge">{node.layer}</div>
                <div className="node-label">{node.label}</div>
                <div className="node-meta">
                  <div className="node-status">
                    <span className={`status-dot ${node.status === 'HEALTHY' ? 'online' : 'warning'}`}></span>
                    <span>{node.status}</span>
                  </div>
                  <div className="node-records">{formatNumber(node.records)} rows</div>
                </div>
                <div className="node-details">{node.details}</div>
              </div>

              {idx < lineage.nodes.length - 1 && (
                <div className="medallion-connector">
                  <ChevronRight size={18} color="var(--text-muted)" />
                </div>
              )}
            </React.Fragment>
          ))}
        </div>
      </div>

      {/* Grid: Recent Pipeline Runs & Quick Exploration */}
      <div className="grid-2-cols" style={{ marginTop: '1.5rem' }}>
        {/* Recent Runs Table */}
        <div className="panel">
          <div className="panel-header">
            <div className="panel-title">
              <Activity size={18} color="var(--accent-cyan)" />
              <span>Recent Orchestrator Runs</span>
            </div>
            <button className="btn btn-secondary btn-sm" onClick={() => onNavigateTab('pipelines')}>
              <span>All Runs</span>
              <ChevronRight size={13} />
            </button>
          </div>

          {recentRuns.length === 0 ? (
            <div className="empty-state">
              <Activity size={32} />
              <p>No recorded pipeline runs yet.</p>
              <button className="btn btn-primary btn-sm" onClick={handleTriggerQuickSync}>
                Trigger Initial Medallion Run
              </button>
            </div>
          ) : (
            <div className="table-responsive">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Pipeline</th>
                    <th>Symbol</th>
                    <th>Status</th>
                    <th>Rows Ingested</th>
                    <th>Duration</th>
                    <th>Executed</th>
                  </tr>
                </thead>
                <tbody>
                  {recentRuns.map((r) => (
                    <tr key={r.id}>
                      <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{r.pipeline_name}</td>
                      <td>
                        <span className="badge badge-neutral">{r.symbol}</span>
                      </td>
                      <td>
                        <span
                          className={`badge ${
                            r.status === 'SUCCESS'
                              ? 'badge-success'
                              : r.status === 'FAILED'
                              ? 'badge-danger'
                              : 'badge-info'
                          }`}
                        >
                          {r.status}
                        </span>
                      </td>
                      <td style={{ fontFamily: 'var(--font-mono)' }}>+{r.rows_inserted}</td>
                      <td style={{ fontFamily: 'var(--font-mono)' }}>
                        {r.duration_seconds != null ? `${r.duration_seconds.toFixed(2)}s` : '—'}
                      </td>
                      <td style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                        {formatRelativeTime(r.created_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Quick Analytical Workbench Links */}
        <div className="panel">
          <div className="panel-header">
            <div className="panel-title">
              <Cpu size={18} color="var(--accent-cyan)" />
              <span>Platform Workbenches</span>
            </div>
          </div>

          <div className="workbench-links-list">
            <div className="workbench-card" onClick={() => onNavigateTab('quality')}>
              <div className="workbench-icon">
                <ShieldCheck size={20} color="var(--accent-cyan)" />
              </div>
              <div className="workbench-info">
                <div className="workbench-name">Data Quality & Anomaly Suite</div>
                <div className="workbench-desc">10 automated integrity rules: schema, OHLC geometry, missing gaps, and price spikes.</div>
              </div>
              <ChevronRight size={16} color="var(--text-muted)" />
            </div>

            <div className="workbench-card" onClick={() => onNavigateTab('explorer')}>
              <div className="workbench-icon">
                <Database size={20} color="var(--accent-cyan)" />
              </div>
              <div className="workbench-info">
                <div className="workbench-name">Data Explorer & Catalog</div>
                <div className="workbench-desc">Inspect Silver/Gold records, analyze column distributions, and download CSV extracts.</div>
              </div>
              <ChevronRight size={16} color="var(--text-muted)" />
            </div>

            <div className="workbench-card" onClick={() => onNavigateTab('analytics')}>
              <div className="workbench-icon">
                <TrendingUp size={20} color="var(--accent-cyan)" />
              </div>
              <div className="workbench-info">
                <div className="workbench-name">Market & Exploratory Analytics</div>
                <div className="workbench-desc">Return moments (skewness/kurtosis), rolling realized volatility, drawdowns, and cross-asset correlation.</div>
              </div>
              <ChevronRight size={16} color="var(--text-muted)" />
            </div>

            <div className="workbench-card" onClick={() => onNavigateTab('models')}>
              <div className="workbench-icon">
                <Cpu size={20} color="var(--accent-cyan)" />
              </div>
              <div className="workbench-info">
                <div className="workbench-name">Model Lab & MLflow Observability</div>
                <div className="workbench-desc">Walk-forward evaluation against naive baselines and external MLflow tracking connection status.</div>
              </div>
              <ChevronRight size={16} color="var(--text-muted)" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
