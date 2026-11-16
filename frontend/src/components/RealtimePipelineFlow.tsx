import React, { useState, useEffect } from 'react';
import {
  ArrowRight,
  Cpu,
  Clock,
  Zap,
  AlertTriangle,
  Database,
  CheckCircle2,
  Activity
} from 'lucide-react';
import { api } from '../services/api';
import { PipelineFlowSnapshot, PipelineNodeTelemetry } from '../types';
import { formatNumber, formatRelativeTime } from '../utils/formatters';

interface Props {
  flow?: PipelineFlowSnapshot | null;
  wsConnected?: boolean;
  onAfterFlush?: () => void;
  compact?: boolean;
}

const formatMs = (val: number | null | undefined, digits = 3): string => {
  if (val === null || val === undefined || Number.isNaN(val)) return '—';
  return `${val.toFixed(digits)} ms`;
};

const statusBadgeClass = (status: string): string => {
  switch (status) {
    case 'ACTIVE':
      return 'badge-success';
    case 'BACKPRESSURE':
      return 'badge-warning';
    case 'DEGRADED':
      return 'badge-danger';
    default:
      return 'badge-neutral';
  }
};

export const RealtimePipelineFlow: React.FC<Props> = ({
  flow,
  wsConnected = false,
  onAfterFlush,
  compact = false
}) => {
  const [selectedNodeId, setSelectedNodeId] = useState<string>('ws_ingest');
  const [flushing, setFlushing] = useState<boolean>(false);
  const [flushNote, setFlushNote] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const nodes = flow?.nodes || [];
  const totals = flow?.totals;

  useEffect(() => {
    if (nodes.length > 0 && !nodes.some((n) => n.node_id === selectedNodeId)) {
      setSelectedNodeId(nodes[0].node_id);
    }
  }, [nodes, selectedNodeId]);

  const selectedNode: PipelineNodeTelemetry | undefined =
    nodes.find((n) => n.node_id === selectedNodeId) || nodes[0];

  const handleFlush = async () => {
    try {
      setFlushing(true);
      setFlushNote(null);
      const res = await api.flushStreamingBuffer();
      const msText = res.flush_duration_ms != null ? ` in ${res.flush_duration_ms.toFixed(2)} ms` : '';
      setFlushNote({
        type: 'success',
        text: `Flushed ${res.flushed} queued messages (Bronze: ${res.bronze_records ?? 0}, Silver klines: ${res.silver_klines ?? 0})${msText}.`
      });
      if (onAfterFlush) onAfterFlush();
    } catch (err: any) {
      setFlushNote({
        type: 'error',
        text: err?.message || 'Unable to flush micro-batch buffer.'
      });
    } finally {
      setFlushing(false);
    }
  };

  if (!flow || nodes.length === 0) {
    return (
      <div className="panel">
        <div className="panel-header">
          <div className="panel-title">
            <Activity size={17} color="var(--accent-cyan)" />
            <span>Real-Time Streaming Pipeline & Node Latency</span>
          </div>
          <span className="badge badge-neutral">WAITING FOR TELEMETRY</span>
        </div>
        <div className="empty-state" style={{ padding: '1.5rem' }}>
          <Clock size={26} color="var(--text-muted)" />
          <p style={{ margin: 0, fontSize: '0.84rem' }}>
            Real-time pipeline telemetry is not available yet. Ensure streaming runtime is active.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <div className="panel-title">
          <Zap size={17} color="var(--accent-yellow)" />
          <span>Real-Time Data Flow Pipeline & Processing Time</span>
          <span className={`badge ${wsConnected ? 'badge-success' : 'badge-neutral'}`}>
            {wsConnected ? 'LIVE STREAM TELEMETRY' : 'REST SNAPSHOT'}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.74rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            Measured: {flow.measured_at ? formatRelativeTime(flow.measured_at) : '—'}
          </span>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={handleFlush}
            disabled={flushing}
            title="Flush pending Bronze/Silver micro-batch buffer and measure storage commit latency"
          >
            <Database size={13} className={flushing ? 'spin' : ''} />
            <span>{flushing ? 'Flushing...' : 'Flush Micro-Batch'}</span>
          </button>
        </div>
      </div>

      {flushNote && (
        <div
          className={`alert-banner ${flushNote.type === 'error' ? 'error' : 'success'}`}
          style={{ marginBottom: '0.85rem' }}
        >
          {flushNote.type === 'error' ? <AlertTriangle size={14} /> : <CheckCircle2 size={14} />}
          <span>{flushNote.text}</span>
        </div>
      )}

      {/* Total Pipeline Processing Time Summary */}
      <div className="rt-pipeline-summary-grid">
        <div className="mini-card">
          <div className="mini-card-label">Total Inline Processing (Sum Nodes 1-7)</div>
          <div className="mini-card-value" style={{ color: '#06b6d4', fontFamily: 'var(--font-mono)', fontSize: '1.1rem' }}>
            {formatMs(totals?.total_inline_avg_ms)}
          </div>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            Last tick: {formatMs(totals?.total_inline_last_ms)} ({totals?.active_inline_nodes ?? 0}/{totals?.inline_nodes_count ?? 7} active)
          </div>
        </div>

        <div className="mini-card">
          <div className="mini-card-label">Total With Async Batch Flush (Nodes 1-8)</div>
          <div className="mini-card-value" style={{ color: 'var(--accent-yellow)', fontFamily: 'var(--font-mono)', fontSize: '1.1rem' }}>
            {formatMs(totals?.total_with_flush_avg_ms)}
          </div>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            Batch flush avg: {formatMs(totals?.medallion_flush_avg_ms, 2)}
          </div>
        </div>

        <div className="mini-card">
          <div className="mini-card-label">End-to-End Event Latency (Receipt -&gt; Analytics)</div>
          <div className="mini-card-value" style={{ color: 'var(--color-success)', fontFamily: 'var(--font-mono)', fontSize: '1.1rem' }}>
            {formatMs(totals?.e2e_wall_avg_ms, 2)}
          </div>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            Last: {formatMs(totals?.e2e_wall_last_ms, 2)} | P95: {formatMs(totals?.e2e_wall_p95_ms, 2)}
          </div>
        </div>

        <div className="mini-card">
          <div className="mini-card-label">Primary Inline Bottleneck Stage</div>
          <div className="mini-card-value" style={{ fontSize: '0.96rem', color: '#fff' }}>
            {totals?.bottleneck_node_name || '—'}
          </div>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            Avg latency: {formatMs(totals?.bottleneck_avg_ms)}
          </div>
        </div>
      </div>

      {/* Horizontal Interactive Pipeline Flow Diagram */}
      <div className="rt-pipeline-track" role="list" aria-label="Real-time data pipeline nodes">
        {nodes.map((node, idx) => {
          const isSelected = selectedNode?.node_id === node.node_id;
          const isBatch = node.execution_mode === 'async_batch';
          const statusCls =
            node.status === 'BACKPRESSURE'
              ? 'status-backpressure'
              : node.status === 'DEGRADED'
              ? 'status-degraded'
              : '';
          const sharePct = node.share_of_inline_pct ?? 0;

          return (
            <React.Fragment key={node.node_id}>
              {idx > 0 && (
                <div className={`rt-connector ${node.status === 'ACTIVE' && wsConnected ? 'flowing' : ''}`} aria-hidden="true">
                  <ArrowRight size={16} />
                  {!compact && isBatch && (
                    <span style={{ fontSize: '0.58rem', fontFamily: 'var(--font-mono)', marginTop: '0.15rem' }}>
                      BATCH
                    </span>
                  )}
                </div>
              )}

              <button
                type="button"
                role="listitem"
                onClick={() => setSelectedNodeId(node.node_id)}
                className={`rt-node-card ${isSelected ? 'selected' : ''} ${isBatch ? 'async-batch' : ''} ${statusCls}`}
              >
                <div className="rt-node-head">
                  <span className="rt-node-step">
                    N{node.step} · {node.layer}
                  </span>
                  <span className={`badge ${statusBadgeClass(node.status)}`} style={{ fontSize: '0.6rem', padding: '0.1rem 0.4rem' }}>
                    {node.status}
                  </span>
                </div>

                <div className="rt-node-title">{node.name}</div>

                <div className="rt-node-timing">
                  <span className="rt-node-ms">{formatMs(node.avg_ms, node.avg_ms && node.avg_ms >= 10 ? 2 : 3)}</span>
                  <span style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>
                    {isBatch ? 'async/batch' : node.share_of_inline_pct != null ? `${node.share_of_inline_pct.toFixed(1)}%` : '—'}
                  </span>
                </div>

                <div className="rt-node-share-track" title="Share of total inline processing time">
                  <div
                    className="rt-node-share-fill"
                    style={{
                      width: `${isBatch ? (node.avg_ms != null ? 100 : 0) : Math.min(100, Math.max(node.avg_ms != null ? 4 : 0, sharePct))}%`,
                      opacity: node.avg_ms != null ? 1 : 0.2,
                      background: isBatch ? 'linear-gradient(90deg, #3b82f6, #06b6d4)' : undefined
                    }}
                  />
                </div>

                <div className="rt-node-foot">
                  <span>Last: {formatMs(node.last_ms, node.last_ms && node.last_ms >= 10 ? 1 : 3)}</span>
                  <span>#{formatNumber(node.processed_count, 0)}</span>
                </div>
              </button>
            </React.Fragment>
          );
        })}
      </div>

      {/* Selected Node Detailed Telemetry Inspector */}
      {selectedNode && (
        <div className="rt-inspector-panel">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '0.65rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
              <Cpu size={15} color="var(--accent-yellow)" />
              <strong style={{ color: '#fff', fontSize: '0.9rem' }}>
                Node {selectedNode.step}: {selectedNode.name}
              </strong>
              <span className={`badge ${statusBadgeClass(selectedNode.status)}`}>{selectedNode.status}</span>
              <span className="badge badge-neutral">
                {selectedNode.execution_mode === 'async_batch' ? 'ASYNC MICRO-BATCH' : 'INLINE REAL-TIME PATH'}
              </span>
            </div>
            <span style={{ fontSize: '0.74rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
              Window: {selectedNode.sample_count}/64 recent samples
            </span>
          </div>

          <p style={{ margin: '0 0 0.75rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
            {selectedNode.description}
          </p>

          <div className="grid-4-cols" style={{ gap: '0.75rem' }}>
            <div className="mini-card">
              <div className="mini-card-label">Last / Avg Time</div>
              <div className="mini-card-value" style={{ fontFamily: 'var(--font-mono)', color: '#06b6d4' }}>
                {formatMs(selectedNode.last_ms)} / {formatMs(selectedNode.avg_ms)}
              </div>
            </div>
            <div className="mini-card">
              <div className="mini-card-label">P95 / Max Time</div>
              <div className="mini-card-value" style={{ fontFamily: 'var(--font-mono)' }}>
                {formatMs(selectedNode.p95_ms)} / {formatMs(selectedNode.max_ms)}
              </div>
            </div>
            <div className="mini-card">
              <div className="mini-card-label">Processed / Errors</div>
              <div className="mini-card-value" style={{ fontFamily: 'var(--font-mono)' }}>
                {formatNumber(selectedNode.processed_count, 0)} /{' '}
                <span style={{ color: selectedNode.error_count > 0 ? 'var(--color-danger)' : 'var(--color-success)' }}>
                  {selectedNode.error_count}
                </span>
              </div>
            </div>
            <div className="mini-card">
              <div className="mini-card-label">Stage Telemetry</div>
              <div className="mini-card-value" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem' }}>
                {Object.entries(selectedNode.meta || {})
                  .slice(0, 3)
                  .map(([k, v]) => `${k}: ${v === null || v === undefined ? '—' : String(v)}`)
                  .join(' · ') || '—'}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default RealtimePipelineFlow;
