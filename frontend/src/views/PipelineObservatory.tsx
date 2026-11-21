import React, { useState, useEffect } from 'react';
import {
  Layers,
  Play,
  CheckCircle2,
  AlertTriangle,
  FileText,
  Filter,
  X,
  RefreshCw
} from 'lucide-react';
import { api } from '../services/api';
import { PipelineRunItem, PipelineRunDetail, SymbolInfo, StreamingStatusResponse } from '../types';
import { formatRelativeTime } from '../utils/formatters';
import { RealtimePipelineFlow } from '../components/RealtimePipelineFlow';
import { useMarketStream } from '../hooks/useMarketStream';

export const PipelineObservatory: React.FC = () => {
  const [runs, setRuns] = useState<PipelineRunItem[]>([]);
  const [symbols, setSymbols] = useState<SymbolInfo[]>([]);
  const [streamingMeta, setStreamingMeta] = useState<StreamingStatusResponse | null>(null);
  const { wsState, streamStatus } = useMarketStream(true);
  const livePipelineFlow = streamStatus?.pipeline_flow || streamingMeta?.pipeline_flow || null;
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [filterSymbol, setFilterSymbol] = useState<string>('');
  const [filterStatus, setFilterStatus] = useState<string>('');

  // Manual Trigger State
  const [triggerModalOpen, setTriggerModalOpen] = useState<boolean>(false);
  const [triggerSymbol, setTriggerSymbol] = useState<string>('BTCUSDT');
  const [triggerTimeframe, setTriggerTimeframe] = useState<string>('1h');
  const [triggerLookback, setTriggerLookback] = useState<number>(30);
  const [skipNetworkIngest, setSkipNetworkIngest] = useState<boolean>(false);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [triggerSuccess, setTriggerSuccess] = useState<string | null>(null);

  // Detail Drawer State
  const [selectedRun, setSelectedRun] = useState<PipelineRunDetail | null>(null);

  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);
      const [runsRes, symsRes, streamStat] = await Promise.all([
        api.getPipelineRuns(filterSymbol || undefined, filterStatus || undefined, 50),
        api.getSymbols(),
        api.getStreamingStatus().catch(() => null)
      ]);
      setRuns(runsRes);
      setSymbols(symsRes);
      if (streamStat) setStreamingMeta(streamStat);
    } catch (err: any) {
      setError(err?.message || 'Failed to load pipeline runs.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 15000);
    return () => clearInterval(interval);
  }, [filterSymbol, filterStatus]);

  const handleOpenDetail = async (runId: string) => {
    try {
      const detail = await api.getPipelineRunDetails(runId);
      setSelectedRun(detail);
    } catch (err: any) {
      setError(`Failed to fetch run details: ${err.message}`);
    }
  };

  const handleTriggerPipeline = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setIsSubmitting(true);
      setTriggerSuccess(null);
      const res: any = await api.triggerPipeline(
        triggerSymbol,
        triggerTimeframe,
        triggerLookback,
        true,
        skipNetworkIngest
      );
      setTriggerSuccess(`Pipeline executed successfully! Added ${res.rows_inserted || 0} rows in ${res.duration_seconds?.toFixed(2) || '0.00'}s.`);
      await loadData();
      setTimeout(() => {
        setTriggerModalOpen(false);
        setTriggerSuccess(null);
      }, 2500);
    } catch (err: any) {
      setError(`Pipeline trigger error: ${err.message}`);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="view-container">
      {/* Header */}
      <div className="view-header">
        <div>
          <div className="view-tag">PIPELINE OBSERVABILITY & ORCHESTRATION</div>
          <h1 className="view-title">Pipeline Observatory</h1>
          <p className="view-subtitle">
            Audit historical batch runs, monitor task status transitions, and inspect execution logs.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <button
            className="btn btn-primary"
            onClick={() => setTriggerModalOpen(true)}
            id="btn-open-trigger-modal"
          >
            <Play size={14} />
            <span>Trigger Pipeline</span>
          </button>
          <button className="btn btn-secondary" onClick={loadData} title="Refresh runs">
            <RefreshCw size={14} />
          </button>
        </div>
      </div>

      {error && (
        <div className="alert-banner error" style={{ marginBottom: '1.25rem' }}>
          <AlertTriangle size={16} />
          <span>{error}</span>
        </div>
      )}

      {/* Real-Time Streaming Pipeline Visualizer & Latency Breakdown */}
      <RealtimePipelineFlow
        flow={livePipelineFlow}
        wsConnected={wsState === 'CONNECTED'}
        onAfterFlush={loadData}
      />

      {/* Filter Toolbar */}
      <div className="filter-toolbar">
        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
          <Filter size={15} color="var(--text-muted)" />
          <select
            className="filter-select"
            value={filterSymbol}
            onChange={(e) => setFilterSymbol(e.target.value)}
            aria-label="Filter by Symbol"
          >
            <option value="">All Symbols</option>
            {symbols.map((s) => (
              <option key={s.symbol} value={s.symbol}>
                {s.symbol}
              </option>
            ))}
          </select>

          <select
            className="filter-select"
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value)}
            aria-label="Filter by Status"
          >
            <option value="">All Statuses</option>
            <option value="SUCCESS">SUCCESS</option>
            <option value="FAILED">FAILED</option>
            <option value="RUNNING">RUNNING</option>
          </select>

          {(filterSymbol || filterStatus) && (
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => {
                setFilterSymbol('');
                setFilterStatus('');
              }}
            >
              Reset Filters
            </button>
          )}
        </div>

        <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
          Showing {runs.length} recorded runs
        </div>
      </div>

      {/* Runs Table */}
      <div className="panel" style={{ marginTop: '1rem' }}>
        {loading && runs.length === 0 ? (
          <div className="loading-state">
            <RefreshCw size={24} className="spin" />
            <span>Loading pipeline audit trail...</span>
          </div>
        ) : runs.length === 0 ? (
          <div className="empty-state">
            <Layers size={36} color="var(--text-muted)" />
            <h3>No Pipeline Runs Found</h3>
            <p>Trigger a new Medallion pipeline run to begin ingesting and transforming data.</p>
            <button className="btn btn-primary btn-sm" onClick={() => setTriggerModalOpen(true)}>
              Trigger Run
            </button>
          </div>
        ) : (
          <div className="table-responsive">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Pipeline</th>
                  <th>Symbol</th>
                  <th>Timeframe</th>
                  <th>Trigger</th>
                  <th>Rows Ingested</th>
                  <th>Duration</th>
                  <th>Execution Window</th>
                  <th>Watermark Range</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id}>
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
                    <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{r.pipeline_name}</td>
                    <td>
                      <span className="badge badge-neutral">{r.symbol}</span>
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)' }}>{r.timeframe}</td>
                    <td>
                      <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>{r.trigger_type}</span>
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)' }}>+{r.rows_inserted}</td>
                    <td style={{ fontFamily: 'var(--font-mono)' }}>
                      {r.duration_seconds != null ? `${r.duration_seconds.toFixed(2)}s` : '—'}
                    </td>
                    <td style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                      {formatRelativeTime(r.created_at)}
                    </td>
                    <td style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                      {r.start_watermark && r.end_watermark ? (
                        `${r.start_watermark.slice(0, 10)} → ${r.end_watermark.slice(0, 10)}`
                      ) : (
                        '—'
                      )}
                    </td>
                    <td>
                      <button
                        className="btn btn-secondary btn-sm"
                        onClick={() => handleOpenDetail(r.id)}
                        title="View Task Details and Logs"
                      >
                        <FileText size={12} />
                        <span>Logs</span>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Task Details Drawer Modal */}
      {selectedRun && (
        <div className="modal-overlay" onClick={() => setSelectedRun(null)}>
          <div className="modal-content large" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div>
                <div style={{ fontSize: '0.75rem', color: 'var(--accent-cyan)', fontFamily: 'var(--font-mono)' }}>
                  RUN ID: {selectedRun.id}
                </div>
                <h2 style={{ fontSize: '1.2rem', color: '#fff', margin: '0.2rem 0' }}>
                  {selectedRun.pipeline_name} • {selectedRun.symbol} ({selectedRun.timeframe})
                </h2>
              </div>
              <button className="btn-close" onClick={() => setSelectedRun(null)} aria-label="Close details">
                <X size={18} />
              </button>
            </div>

            <div className="modal-body">
              {/* High-level run metadata */}
              <div className="grid-4-cols" style={{ marginBottom: '1.25rem' }}>
                <div className="mini-card">
                  <div className="mini-card-label">Status</div>
                  <div className="mini-card-value">{selectedRun.status}</div>
                </div>
                <div className="mini-card">
                  <div className="mini-card-label">Total Duration</div>
                  <div className="mini-card-value">
                    {selectedRun.duration_seconds ? `${selectedRun.duration_seconds.toFixed(2)}s` : '—'}
                  </div>
                </div>
                <div className="mini-card">
                  <div className="mini-card-label">Rows Processed</div>
                  <div className="mini-card-value">+{selectedRun.rows_inserted}</div>
                </div>
                <div className="mini-card">
                  <div className="mini-card-label">Gaps Detected</div>
                  <div className="mini-card-value">{selectedRun.gaps_detected}</div>
                </div>
              </div>

              {selectedRun.error_message && (
                <div className="alert-banner error" style={{ marginBottom: '1rem' }}>
                  <AlertTriangle size={16} />
                  <span>Error: {selectedRun.error_message}</span>
                </div>
              )}

              {/* Task Stages breakdown */}
              <h3 style={{ fontSize: '0.95rem', color: '#fff', marginBottom: '0.75rem' }}>
                Stage Execution Sequence
              </h3>

              <div className="task-list">
                {selectedRun.tasks.map((task) => (
                  <div key={task.id} className="task-card">
                    <div className="task-header">
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span className="task-seq">#{task.sequence_order}</span>
                        <span className="task-name">{task.task_name}</span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                        <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                          {task.duration_seconds ? `${task.duration_seconds.toFixed(2)}s` : '—'}
                        </span>
                        <span
                          className={`badge ${
                            task.status === 'SUCCESS'
                              ? 'badge-success'
                              : task.status === 'FAILED'
                              ? 'badge-danger'
                              : 'badge-neutral'
                          }`}
                        >
                          {task.status}
                        </span>
                      </div>
                    </div>
                    {task.logs && (
                      <div className="task-logs">
                        <pre>{task.logs}</pre>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>

            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setSelectedRun(null)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Manual Trigger Modal */}
      {triggerModalOpen && (
        <div className="modal-overlay" onClick={() => setTriggerModalOpen(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2 style={{ fontSize: '1.2rem', color: '#fff' }}>Trigger Medallion Pipeline</h2>
              <button className="btn-close" onClick={() => setTriggerModalOpen(false)}>
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleTriggerPipeline}>
              <div className="modal-body">
                <p style={{ color: 'var(--text-muted)', fontSize: '0.88rem', marginBottom: '1.25rem' }}>
                  Executes the 4-stage pipeline (Bronze REST Ingestion → Silver Quality Validation → Gold Mart Aggregations → Feature Extraction).
                </p>

                {triggerSuccess && (
                  <div className="alert-banner info" style={{ marginBottom: '1rem' }}>
                    <CheckCircle2 size={16} />
                    <span>{triggerSuccess}</span>
                  </div>
                )}

                <div className="form-group">
                  <label className="form-label">Asset Symbol</label>
                  <select
                    className="form-control"
                    value={triggerSymbol}
                    onChange={(e) => setTriggerSymbol(e.target.value)}
                  >
                    {symbols.map((s) => (
                      <option key={s.symbol} value={s.symbol}>
                        {s.symbol} ({s.base_asset}/{s.quote_asset})
                      </option>
                    ))}
                  </select>
                </div>

                <div className="form-group">
                  <label className="form-label">Candlestick Timeframe</label>
                  <select
                    className="form-control"
                    value={triggerTimeframe}
                    onChange={(e) => setTriggerTimeframe(e.target.value)}
                  >
                    <option value="15m">15m (15 Minutes)</option>
                    <option value="1h">1h (1 Hour - Recommended)</option>
                    <option value="4h">4h (4 Hours)</option>
                    <option value="1d">1d (1 Day)</option>
                  </select>
                </div>

                <div className="form-group">
                  <label className="form-label">Lookback Window (Days if seeding initial candles)</label>
                  <input
                    type="number"
                    min="1"
                    max="180"
                    className="form-control"
                    value={triggerLookback}
                    onChange={(e) => setTriggerLookback(parseInt(e.target.value) || 30)}
                  />
                </div>

                <div className="form-group">
                  <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontSize: '0.84rem' }}>
                    <input
                      type="checkbox"
                      checked={skipNetworkIngest}
                      onChange={(e) => setSkipNetworkIngest(e.target.checked)}
                    />
                    <span>Historical Recomputation Only (Silver → Gold/Features without REST sync)</span>
                  </label>
                </div>
              </div>

              <div className="modal-footer">
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => setTriggerModalOpen(false)}
                  disabled={isSubmitting}
                >
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={isSubmitting}>
                  {isSubmitting ? <RefreshCw size={14} className="spin" /> : <Play size={14} />}
                  <span>{isSubmitting ? 'Executing Pipeline...' : 'Run Pipeline'}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
