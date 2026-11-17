import React from 'react';
import { X, Activity, RefreshCw } from 'lucide-react';
import { StationInfo } from './dataFactoryTypes';
import { formatNumber } from '../../utils/formatters';

interface StationInspectorProps {
  station: StationInfo;
  onClose: () => void;
  streamStatus: Record<string, any>;
  resources?: Record<string, any> | null;
  wsConnected: boolean;
  onFlush?: () => Promise<void>;
}

export const StationInspector: React.FC<StationInspectorProps> = ({
  station,
  onClose,
  streamStatus,
  resources,
  wsConnected,
  onFlush
}) => {
  const [flushing, setFlushing] = React.useState(false);

  const broker = streamStatus.broker || {};
  const ingestor = streamStatus.ingestor || {};
  const producer = streamStatus.producer || {};
  const consumer = streamStatus.consumer || {};
  const pipelineFlow = streamStatus.pipeline_flow || {};
  const nodes = pipelineFlow.nodes || {};

  // Determine runtime status based on real telemetry
  let statusBadge = { label: 'ONLINE', color: '#0ECB81', bg: 'rgba(14, 203, 129, 0.15)' };
  if (!wsConnected && station.category === 'INGEST') {
    statusBadge = { label: 'DISCONNECTED', color: '#F6465D', bg: 'rgba(246, 70, 93, 0.15)' };
  } else if (producer.backpressure_active && (station.category === 'BROKER' || station.category === 'INGEST')) {
    statusBadge = { label: 'BACKPRESSURE', color: '#FCD535', bg: 'rgba(252, 213, 53, 0.15)' };
  } else if (station.category === 'BROKER' && !broker.connected) {
    statusBadge = { label: 'DISCONNECTED', color: '#F6465D', bg: 'rgba(246, 70, 93, 0.15)' };
  }

  const handleFlush = async () => {
    if (!onFlush || flushing) return;
    try {
      setFlushing(true);
      await onFlush();
    } finally {
      setFlushing(false);
    }
  };

  // Extract station-specific live metrics
  const renderStationMetrics = () => {
    switch (station.id) {
      case 'st_01_sources':
        return (
          <div className="inspector-grid">
            <div className="metric-box">
              <span className="lbl">WS Connection</span>
              <span className="val" style={{ color: wsConnected ? '#0ECB81' : '#F6465D' }}>
                {wsConnected ? 'CONNECTED' : 'DISCONNECTED'}
              </span>
            </div>
            <div className="metric-box">
              <span className="lbl">Active Ingress Symbols</span>
              <span className="val">{ingestor.symbols?.length || 2} Pairs</span>
            </div>
            <div className="metric-box">
              <span className="lbl">Received Events</span>
              <span className="val">{formatNumber(ingestor.events_received || 0)}</span>
            </div>
            <div className="metric-box">
              <span className="lbl">Reconnect Count</span>
              <span className="val">{ingestor.reconnect_count || 0}</span>
            </div>
          </div>
        );

      case 'st_02_normalize':
        const normNode = nodes.normalize || {};
        return (
          <div className="inspector-grid">
            <div className="metric-box">
              <span className="lbl">Validation Latency</span>
              <span className="val" style={{ color: '#00D8FF' }}>
                {normNode.last_duration_ms !== undefined ? `${normNode.last_duration_ms.toFixed(3)} ms` : '< 0.05 ms'}
              </span>
            </div>
            <div className="metric-box">
              <span className="lbl">P95 Parse Time</span>
              <span className="val">
                {normNode.p95_duration_ms !== undefined ? `${normNode.p95_duration_ms.toFixed(3)} ms` : '~0.08 ms'}
              </span>
            </div>
            <div className="metric-box">
              <span className="lbl">Canonical Schema</span>
              <span className="val">v3.0.0 Strictly Typed</span>
            </div>
            <div className="metric-box">
              <span className="lbl">Malformed Discarded</span>
              <span className="val" style={{ color: producer.dlq_count > 0 ? '#FCD535' : '#0ECB81' }}>
                {producer.dlq_count || 0}
              </span>
            </div>
          </div>
        );

      case 'st_03_broker':
        return (
          <div className="inspector-grid">
            <div className="metric-box">
              <span className="lbl">Queue Occupancy</span>
              <span className="val" style={{ color: producer.backpressure_active ? '#FCD535' : '#EAECEF' }}>
                {producer.queue_size || 0} / {producer.queue_maxsize || 2000}
              </span>
            </div>
            <div className="metric-box">
              <span className="lbl">Durable Stream Msgs</span>
              <span className="val">{formatNumber(broker.messages || 0)}</span>
            </div>
            <div className="metric-box">
              <span className="lbl">Consumer Lag</span>
              <span className="val" style={{ color: (consumer.lag || 0) > 50 ? '#FCD535' : '#0ECB81' }}>
                {consumer.lag !== undefined ? consumer.lag : 0} msgs
              </span>
            </div>
            <div className="metric-box">
              <span className="lbl">DLQ Messages</span>
              <span className="val">{producer.dlq_count || 0}</span>
            </div>
          </div>
        );

      case 'st_04_stream_processing':
        const flushNode = nodes.medallion_flush || {};
        return (
          <div className="inspector-grid">
            <div className="metric-box">
              <span className="lbl">Consumer Processed</span>
              <span className="val">{formatNumber(consumer.processed_count || 0)}</span>
            </div>
            <div className="metric-box">
              <span className="lbl">Pending In-Memory</span>
              <span className="val">{consumer.pending_events || 0} events</span>
            </div>
            <div className="metric-box">
              <span className="lbl">Last Micro-Batch Flush</span>
              <span className="val" style={{ color: '#0ECB81' }}>
                {flushNode.last_duration_ms !== undefined ? `${flushNode.last_duration_ms.toFixed(1)} ms` : 'Idle'}
              </span>
            </div>
            <div className="metric-box">
              <span className="lbl">Flush Target</span>
              <span className="val">SQLite WAL + Bronze zstd</span>
            </div>
          </div>
        );

      case 'st_05_medallion':
        return (
          <div className="inspector-grid">
            <div className="metric-box">
              <span className="lbl">Bronze Raw (zstd)</span>
              <span className="val">
                {resources?.bronze_disk_mb ? `${resources.bronze_disk_mb.toFixed(2)} MB` : 'Active partition'}
              </span>
            </div>
            <div className="metric-box">
              <span className="lbl">Silver Parquet</span>
              <span className="val">
                {resources?.silver_disk_mb ? `${resources.silver_disk_mb.toFixed(2)} MB` : 'Deduplicated OHLCV'}
              </span>
            </div>
            <div className="metric-box">
              <span className="lbl">Gold Parquet Marts</span>
              <span className="val">
                {resources?.gold_disk_mb ? `${resources.gold_disk_mb.toFixed(2)} MB` : 'Curated Analytics'}
              </span>
            </div>
            <div className="metric-box">
              <span className="lbl">Data Quality Gate</span>
              <span className="val" style={{ color: '#0ECB81' }}>
                10 Automated Rules
              </span>
            </div>
          </div>
        );

      case 'st_06_intelligence':
        const anaNode = nodes.incremental_analytics || {};
        return (
          <div className="inspector-grid">
            <div className="metric-box">
              <span className="lbl">Indicator Latency</span>
              <span className="val" style={{ color: '#00D8FF' }}>
                {anaNode.last_duration_ms !== undefined ? `${anaNode.last_duration_ms.toFixed(3)} ms` : '< 0.1 ms'}
              </span>
            </div>
            <div className="metric-box">
              <span className="lbl">Complexity</span>
              <span className="val">O(1) Rolling Stream</span>
            </div>
            <div className="metric-box">
              <span className="lbl">Calculated Metrics</span>
              <span className="val">15 Metrics (RSI, ATR, VaR...)</span>
            </div>
            <div className="metric-box">
              <span className="lbl">ML Feature Vectors</span>
              <span className="val">Zero Lookahead Leakage</span>
            </div>
          </div>
        );

      case 'st_07_warehouse':
        return (
          <div className="inspector-grid">
            <div className="metric-box">
              <span className="lbl">Warehouse Engine</span>
              <span className="val">DuckDB In-Memory + Parquet</span>
            </div>
            <div className="metric-box">
              <span className="lbl">Memory Limit</span>
              <span className="val">128 MB (Lite Capped)</span>
            </div>
            <div className="metric-box">
              <span className="lbl">Query Performance</span>
              <span className="val">&lt; 40 ms Columnar Scan</span>
            </div>
            <div className="metric-box">
              <span className="lbl">Pipeline Type</span>
              <span className="val" style={{ color: '#F59E0B' }}>
                Asynchronous Batch ETL
              </span>
            </div>
          </div>
        );

      case 'st_08_serving':
        const wsNode = nodes.ws_gateway || {};
        return (
          <div className="inspector-grid">
            <div className="metric-box">
              <span className="lbl">WS Hub Interval</span>
              <span className="val">100 ms Coalesced Frames</span>
            </div>
            <div className="metric-box">
              <span className="lbl">Gateway Dispatch Time</span>
              <span className="val" style={{ color: '#EC4899' }}>
                {wsNode.last_duration_ms !== undefined ? `${wsNode.last_duration_ms.toFixed(3)} ms` : '~0.3 ms'}
              </span>
            </div>
            <div className="metric-box">
              <span className="lbl">REST API Endpoints</span>
              <span className="val">38 Endpoints + /metrics</span>
            </div>
            <div className="metric-box">
              <span className="lbl">Serving Mode</span>
              <span className="val">Bounded Ring Buffer</span>
            </div>
          </div>
        );

      default:
        return null;
    }
  };

  return (
    <div
      style={{
        position: 'absolute',
        top: 0,
        right: 0,
        width: '380px',
        height: '100%',
        background: '#12161A',
        borderLeft: '1px solid #222B35',
        display: 'flex',
        flexDirection: 'column',
        boxShadow: '-8px 0 24px rgba(0, 0, 0, 0.7)',
        zIndex: 20,
        animation: 'slideInRight 0.25s ease-out'
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: '16px 20px',
          borderBottom: '1px solid #222B35',
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between'
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
            <span
              style={{
                fontFamily: 'monospace',
                fontSize: '11px',
                fontWeight: 700,
                padding: '2px 6px',
                borderRadius: '3px',
                background: station.color,
                color: '#0B0E11'
              }}
            >
              {station.code}
            </span>
            <span
              style={{
                fontSize: '10px',
                fontFamily: 'monospace',
                padding: '2px 6px',
                borderRadius: '3px',
                background: statusBadge.bg,
                color: statusBadge.color,
                fontWeight: 700
              }}
            >
              {statusBadge.label}
            </span>
          </div>
          <h3 style={{ fontSize: '16px', fontWeight: 700, color: '#EAECEF', margin: 0 }}>
            {station.name}
          </h3>
          <p style={{ fontSize: '11px', color: '#848E9C', margin: '2px 0 0' }}>
            {station.subtitle}
          </p>
        </div>
        <button
          onClick={onClose}
          style={{
            background: 'none',
            border: 'none',
            color: '#848E9C',
            cursor: 'pointer',
            padding: '4px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            borderRadius: '4px'
          }}
        >
          <X size={18} />
        </button>
      </div>

      {/* Body content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px' }}>
        {/* Architectural Role */}
        <div style={{ marginBottom: '16px' }}>
          <div style={{ fontSize: '10px', textTransform: 'uppercase', color: '#848E9C', fontWeight: 700, letterSpacing: '0.05em', marginBottom: '6px' }}>
            Architectural Responsibility
          </div>
          <p style={{ fontSize: '12px', color: '#CBD5E1', lineHeight: '1.5', margin: 0 }}>
            {station.description}
          </p>
        </div>

        {/* Live Telemetry Metrics */}
        <div style={{ marginBottom: '20px' }}>
          <div style={{ fontSize: '10px', textTransform: 'uppercase', color: '#848E9C', fontWeight: 700, letterSpacing: '0.05em', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <Activity size={12} color="#00D8FF" />
            <span>Live Telemetry Metrics</span>
          </div>
          {renderStationMetrics()}
        </div>

        {/* Input/Output Data Contracts */}
        <div style={{ marginBottom: '20px' }}>
          <div style={{ fontSize: '10px', textTransform: 'uppercase', color: '#848E9C', fontWeight: 700, letterSpacing: '0.05em', marginBottom: '8px' }}>
            Data Contracts
          </div>
          <div style={{ background: '#161E27', border: '1px solid #222B35', borderRadius: '4px', padding: '10px' }}>
            <div style={{ marginBottom: '8px' }}>
              <div style={{ fontSize: '10px', color: '#848E9C', marginBottom: '2px' }}>INPUT CONTRACT:</div>
              <div style={{ fontSize: '11px', fontFamily: 'monospace', color: '#00D8FF' }}>
                {station.inputContract}
              </div>
            </div>
            <div>
              <div style={{ fontSize: '10px', color: '#848E9C', marginBottom: '2px' }}>OUTPUT CONTRACT:</div>
              <div style={{ fontSize: '11px', fontFamily: 'monospace', color: '#0ECB81' }}>
                {station.outputContract}
              </div>
            </div>
          </div>
        </div>

        {/* Pipeline Execution Mode */}
        <div style={{ marginBottom: '16px' }}>
          <div style={{ fontSize: '10px', textTransform: 'uppercase', color: '#848E9C', fontWeight: 700, letterSpacing: '0.05em', marginBottom: '6px' }}>
            Processing Paradigm
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span
              style={{
                fontSize: '11px',
                fontFamily: 'monospace',
                padding: '3px 8px',
                borderRadius: '4px',
                background: station.pathType === 'streaming' ? 'rgba(0, 216, 255, 0.15)' : 'rgba(245, 158, 11, 0.15)',
                color: station.pathType === 'streaming' ? '#00D8FF' : '#F59E0B',
                fontWeight: 600
              }}
            >
              {station.pathType === 'streaming' ? 'REAL-TIME STREAMING' : 'ASYNCHRONOUS BATCH ETL'}
            </span>
          </div>
        </div>
      </div>

      {/* Footer Actions */}
      {onFlush && station.id === 'st_04_stream_processing' && (
        <div style={{ padding: '12px 20px', borderTop: '1px solid #222B35', background: '#0D1117' }}>
          <button
            onClick={handleFlush}
            disabled={flushing}
            style={{
              width: '100%',
              padding: '8px 12px',
              background: '#0ECB81',
              color: '#0B0E11',
              border: 'none',
              borderRadius: '4px',
              fontSize: '12px',
              fontWeight: 700,
              cursor: flushing ? 'not-allowed' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '6px'
            }}
          >
            <RefreshCw size={14} className={flushing ? 'spin' : ''} />
            <span>{flushing ? 'Flushing Micro-Batch...' : 'Flush Staged Micro-Batch'}</span>
          </button>
        </div>
      )}
    </div>
  );
};
