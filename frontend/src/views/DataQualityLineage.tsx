import React, { useState, useEffect } from 'react';
import {
  ShieldCheck,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Layers,
  RefreshCw,
  Info,
  Clock,
  Database
} from 'lucide-react';
import { api } from '../services/api';
import {
  DataQualityOverview,
  DataQualityRunItem,
  DataQualityResultItem,
  LineageGraphResponse,
  SymbolInfo
} from '../types';
import { formatNumber, formatRelativeTime } from '../utils/formatters';

export const DataQualityLineage: React.FC = () => {
  const [overview, setOverview] = useState<DataQualityOverview | null>(null);
  const [runs, setRuns] = useState<DataQualityRunItem[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [runResults, setRunResults] = useState<DataQualityResultItem[]>([]);
  const [lineage, setLineage] = useState<LineageGraphResponse | null>(null);
  const [symbols, setSymbols] = useState<SymbolInfo[]>([]);

  const [auditSymbol, setAuditSymbol] = useState<string>('BTCUSDT');
  const [auditTimeframe, setAuditTimeframe] = useState<string>('1h');
  const [isAuditing, setIsAuditing] = useState<boolean>(false);
  const [auditMessage, setAuditMessage] = useState<string | null>(null);

  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);
      const [overviewRes, runsRes, lineageRes, symRes] = await Promise.all([
        api.getDataQualityOverview(),
        api.getDataQualityRuns(undefined, undefined, 20),
        api.getDataLineage(),
        api.getSymbols()
      ]);
      setOverview(overviewRes);
      setRuns(runsRes);
      setLineage(lineageRes);
      setSymbols(symRes);

      if (runsRes.length > 0 && !selectedRunId) {
        setSelectedRunId(runsRes[0].id);
        const detail = await api.getDataQualityRunDetails(runsRes[0].id);
        setRunResults(detail.results);
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to load data quality telemetry.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleSelectRun = async (runId: string) => {
    try {
      setSelectedRunId(runId);
      const detail = await api.getDataQualityRunDetails(runId);
      setRunResults(detail.results);
    } catch (err: any) {
      setError(`Failed to fetch run details: ${err.message}`);
    }
  };

  const handleTriggerAudit = async () => {
    try {
      setIsAuditing(true);
      setAuditMessage(null);
      const res: any = await api.evaluateDataQuality(auditSymbol, auditTimeframe, 1000);
      setAuditMessage(
        `Audit finished for ${res.symbol} (${res.timeframe}): ${res.rules_passed}/${res.total_rules} rules passed (${res.status}).`
      );
      await loadData();
      if (res.run_id) {
        handleSelectRun(res.run_id);
      }
    } catch (err: any) {
      setAuditMessage(`Audit error: ${err.message}`);
    } finally {
      setIsAuditing(false);
    }
  };

  return (
    <div className="view-container">
      {/* Header */}
      <div className="view-header">
        <div>
          <div className="view-tag">DATA INTEGRITY & MEDALLION LINEAGE</div>
          <h1 className="view-title">Data Quality & Lineage</h1>
          <p className="view-subtitle">
            Automated schema, geometry, monotonicity, and anomaly rule audits across the data lifecycle.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <select
            className="filter-select"
            value={auditSymbol}
            onChange={(e) => setAuditSymbol(e.target.value)}
          >
            {symbols.map((s) => (
              <option key={s.symbol} value={s.symbol}>
                {s.symbol}
              </option>
            ))}
          </select>
          <select
            className="filter-select"
            value={auditTimeframe}
            onChange={(e) => setAuditTimeframe(e.target.value)}
          >
            <option value="15m">15m</option>
            <option value="1h">1h</option>
            <option value="4h">4h</option>
            <option value="1d">1d</option>
          </select>
          <button
            className="btn btn-primary"
            onClick={handleTriggerAudit}
            disabled={isAuditing}
            id="btn-run-dq-audit"
          >
            {isAuditing ? <RefreshCw size={14} className="spin" /> : <ShieldCheck size={14} />}
            <span>{isAuditing ? 'Auditing...' : 'Run Audit'}</span>
          </button>
          <button className="btn btn-secondary" onClick={loadData} title="Refresh telemetry">
            <RefreshCw size={14} className={loading ? 'spin' : ''} />
          </button>
        </div>
      </div>

      {auditMessage && (
        <div className="alert-banner info" style={{ marginBottom: '1.25rem' }}>
          <Info size={16} />
          <span>{auditMessage}</span>
        </div>
      )}

      {error && (
        <div className="alert-banner error" style={{ marginBottom: '1.25rem' }}>
          <AlertTriangle size={16} />
          <span>{error}</span>
        </div>
      )}

      {/* KPI Cards */}
      <div className="kpi-grid">
        <div className="kpi-card">
          <div className="kpi-header">
            <span className="kpi-label">Pass Rate Score</span>
            <ShieldCheck size={16} color="var(--accent-cyan)" />
          </div>
          <div className="kpi-value">
            {overview && overview.total_rules_evaluated > 0 ? (
              <>
                {overview.pass_rate_pct}%{' '}
                <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)', fontWeight: 400 }}>
                  ({overview.passed_rules} / {overview.total_rules_evaluated})
                </span>
              </>
            ) : (
              'Pending'
            )}
          </div>
          <div className="kpi-subtext">Across all monitored asset suites</div>
        </div>

        <div className="kpi-card">
          <div className="kpi-header">
            <span className="kpi-label">Healthy Suites</span>
            <CheckCircle2 size={16} color="var(--semantic-green)" />
          </div>
          <div className="kpi-value" style={{ color: 'var(--semantic-green)' }}>
            {overview?.healthy_suites_count ?? 0}
          </div>
          <div className="kpi-subtext">Zero critical integrity failures</div>
        </div>

        <div className="kpi-card">
          <div className="kpi-header">
            <span className="kpi-label">Warning / Degraded Suites</span>
            <AlertTriangle size={16} color="var(--semantic-amber)" />
          </div>
          <div className="kpi-value" style={{ color: 'var(--semantic-amber)' }}>
            {overview?.warning_suites_count ?? 0}
          </div>
          <div className="kpi-subtext">Continuity gap or stale candle notices</div>
        </div>

        <div className="kpi-card">
          <div className="kpi-header">
            <span className="kpi-label">Failed Suites</span>
            <XCircle size={16} color="var(--semantic-red)" />
          </div>
          <div className="kpi-value" style={{ color: 'var(--semantic-red)' }}>
            {overview?.failed_suites_count ?? 0}
          </div>
          <div className="kpi-subtext">Critical schema or OHLC geometry violation</div>
        </div>
      </div>

      {/* End-to-End Medallion Lineage Architecture */}
      <div className="panel" style={{ marginTop: '1.5rem' }}>
        <div className="panel-header">
          <div className="panel-title">
            <Layers size={18} color="var(--accent-cyan)" />
            <span>Medallion Data Lineage Graph</span>
          </div>
          <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            CONTRACTS TRACED • UPDATED {lineage?.last_updated || 'RECENTLY'}
          </span>
        </div>

        <div className="lineage-graph-wrapper">
          {lineage?.nodes.map((node) => (
            <div key={node.id} className="lineage-node-card">
              <div className="lineage-node-top">
                <span className="lineage-layer-tag">{node.layer}</span>
                <span
                  className={`status-pill ${
                    node.status === 'HEALTHY'
                      ? 'pill-success'
                      : node.status === 'WARNING'
                      ? 'pill-warning'
                      : 'pill-neutral'
                  }`}
                >
                  {node.status}
                </span>
              </div>
              <div className="lineage-node-title">{node.label}</div>
              <div className="lineage-node-records">
                <Database size={13} />
                <span>{formatNumber(node.records)} rows</span>
              </div>
              <div className="lineage-node-desc">{node.details}</div>
              <div className="lineage-node-freshness">
                <Clock size={11} />
                <span>{node.freshness}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Rule Results & Evaluation Audit Breakdown */}
      <div className="grid-3-cols-uneven" style={{ marginTop: '1.5rem' }}>
        {/* Runs Selector Sidebar */}
        <div className="panel">
          <div className="panel-header">
            <div className="panel-title">
              <Clock size={16} color="var(--accent-cyan)" />
              <span>Audit Executions</span>
            </div>
          </div>

          {runs.length === 0 ? (
            <div className="empty-state">
              <p>No audits executed yet.</p>
              <button className="btn btn-primary btn-sm" onClick={handleTriggerAudit}>
                Run Audit
              </button>
            </div>
          ) : (
            <div className="runs-vertical-list">
              {runs.map((r) => (
                <div
                  key={r.id}
                  className={`run-list-item ${selectedRunId === r.id ? 'active' : ''}`}
                  onClick={() => handleSelectRun(r.id)}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontWeight: 600, color: '#fff' }}>
                      {r.symbol} • {r.timeframe}
                    </span>
                    <span
                      className={`badge ${
                        r.status === 'PASSED'
                          ? 'badge-success'
                          : r.status === 'WARNING'
                          ? 'badge-warning'
                          : 'badge-danger'
                      }`}
                    >
                      {r.status}
                    </span>
                  </div>
                  <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '0.2rem' }}>
                    {r.rules_passed}/{r.total_rules_evaluated} rules passed • {r.evaluated_row_count} rows
                  </div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                    {formatRelativeTime(r.run_timestamp)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Detailed Rules Table */}
        <div className="panel" style={{ gridColumn: 'span 2' }}>
          <div className="panel-header">
            <div className="panel-title">
              <ShieldCheck size={18} color="var(--accent-cyan)" />
              <span>Rule Evaluation Scorecard</span>
            </div>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
              10 Programmatic Integrity Rules
            </span>
          </div>

          {runResults.length === 0 ? (
            <div className="empty-state">
              <p>Select an audit execution on the left or click 'Run Audit'.</p>
            </div>
          ) : (
            <div className="table-responsive">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Rule ID</th>
                    <th>Rule Description</th>
                    <th>Category</th>
                    <th>Severity</th>
                    <th>Status</th>
                    <th>Violations</th>
                    <th>Message & Findings</th>
                  </tr>
                </thead>
                <tbody>
                  {runResults.map((rule) => (
                    <tr key={rule.id}>
                      <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '0.82rem' }}>
                        {rule.rule_id}
                      </td>
                      <td style={{ fontWeight: 500, color: '#fff' }}>{rule.rule_name}</td>
                      <td>
                        <span className="badge badge-neutral">{rule.category}</span>
                      </td>
                      <td>
                        <span
                          className={`badge ${
                            rule.severity === 'CRITICAL'
                              ? 'badge-danger'
                              : rule.severity === 'ERROR'
                              ? 'badge-danger'
                              : 'badge-warning'
                          }`}
                        >
                          {rule.severity}
                        </span>
                      </td>
                      <td>
                        <span
                          className={`badge ${rule.status === 'PASS' ? 'badge-success' : 'badge-danger'}`}
                        >
                          {rule.status}
                        </span>
                      </td>
                      <td style={{ fontFamily: 'var(--font-mono)' }}>{rule.failed_records_count}</td>
                      <td style={{ fontSize: '0.82rem', color: 'var(--text-muted)', maxWidth: '350px' }}>
                        <div>{rule.message}</div>
                        {rule.sample_failures && (
                          <details style={{ marginTop: '0.25rem' }}>
                            <summary style={{ cursor: 'pointer', color: 'var(--accent-cyan)', fontSize: '0.75rem' }}>
                              View Violation Samples
                            </summary>
                            <pre style={{ fontSize: '0.7rem', padding: '0.3rem', background: 'rgba(0,0,0,0.4)', borderRadius: '4px' }}>
                              {rule.sample_failures}
                            </pre>
                          </details>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
