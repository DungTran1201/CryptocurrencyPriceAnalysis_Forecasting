import React from 'react';
import { Activity, Zap, Database, Server } from 'lucide-react';
import { formatNumber } from '../../utils/formatters';

interface FactoryKPIStripProps {
  streamStatus: Record<string, any>;
  wsConnected: boolean;
  lastMessageAt?: string | null;
  profile?: string;
}

export const FactoryKPIStrip: React.FC<FactoryKPIStripProps> = ({
  streamStatus,
  wsConnected,
  profile = 'lite'
}) => {
  const ingestor = streamStatus.ingestor || {};
  const producer = streamStatus.producer || {};
  const consumer = streamStatus.consumer || {};
  const pipelineFlow = streamStatus.pipeline_flow || {};

  const inlineMs = pipelineFlow.inline_processing_ms || 0;
  const bottleneck = pipelineFlow.primary_bottleneck_node || 'None';
  const queueSize = producer.queue_size || 0;
  const queueMax = producer.queue_maxsize || 2000;
  const queuePct = Math.round((queueSize / queueMax) * 100);
  const consumerLag = consumer.lag || 0;

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
        gap: '12px',
        marginBottom: '16px'
      }}
    >
      {/* 1. Global Pipeline Status */}
      <div
        style={{
          background: '#12161A',
          border: '1px solid #222B35',
          borderRadius: '6px',
          padding: '12px 14px',
          display: 'flex',
          flexDirection: 'column',
          gap: '4px'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: '11px', color: '#848E9C', textTransform: 'uppercase', fontWeight: 600 }}>
            Pipeline Health
          </span>
          <span
            style={{
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              background: wsConnected ? '#0ECB81' : '#F6465D',
              boxShadow: wsConnected ? '0 0 8px #0ECB81' : 'none'
            }}
          />
        </div>
        <div style={{ fontSize: '18px', fontWeight: 700, color: wsConnected ? '#0ECB81' : '#F6465D', fontFamily: 'monospace' }}>
          {wsConnected ? 'OPERATIONAL' : 'DISCONNECTED'}
        </div>
        <div style={{ fontSize: '11px', color: '#848E9C' }}>
          Profile: <span style={{ color: '#FCD535', fontWeight: 600, textTransform: 'uppercase' }}>{profile}</span> • Single-Node
        </div>
      </div>

      {/* 2. Ingestion Throughput */}
      <div
        style={{
          background: '#12161A',
          border: '1px solid #222B35',
          borderRadius: '6px',
          padding: '12px 14px',
          display: 'flex',
          flexDirection: 'column',
          gap: '4px'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: '11px', color: '#848E9C', textTransform: 'uppercase', fontWeight: 600 }}>
            Ingress Events
          </span>
          <Zap size={14} color="#00D8FF" />
        </div>
        <div style={{ fontSize: '18px', fontWeight: 700, color: '#EAECEF', fontFamily: 'monospace' }}>
          {formatNumber(ingestor.events_received || 0)}
        </div>
        <div style={{ fontSize: '11px', color: '#848E9C' }}>
          Active Symbols: <span style={{ color: '#00D8FF', fontWeight: 600 }}>{ingestor.symbols?.length || 2} pairs</span>
        </div>
      </div>

      {/* 3. Bounded Queue Occupancy */}
      <div
        style={{
          background: '#12161A',
          border: '1px solid #222B35',
          borderRadius: '6px',
          padding: '12px 14px',
          display: 'flex',
          flexDirection: 'column',
          gap: '4px'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: '11px', color: '#848E9C', textTransform: 'uppercase', fontWeight: 600 }}>
            Buffer Occupancy
          </span>
          <Database size={14} color="#FCD535" />
        </div>
        <div style={{ fontSize: '18px', fontWeight: 700, color: producer.backpressure_active ? '#FCD535' : '#EAECEF', fontFamily: 'monospace' }}>
          {queueSize} <span style={{ fontSize: '12px', color: '#848E9C' }}>/ {queueMax} ({queuePct}%)</span>
        </div>
        <div style={{ fontSize: '11px', color: producer.backpressure_active ? '#FCD535' : '#848E9C' }}>
          {producer.backpressure_active ? 'Backpressure Active' : 'Normal Flow Rate'}
        </div>
      </div>

      {/* 4. Consumer Lag */}
      <div
        style={{
          background: '#12161A',
          border: '1px solid #222B35',
          borderRadius: '6px',
          padding: '12px 14px',
          display: 'flex',
          flexDirection: 'column',
          gap: '4px'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: '11px', color: '#848E9C', textTransform: 'uppercase', fontWeight: 600 }}>
            JetStream Lag
          </span>
          <Server size={14} color="#0ECB81" />
        </div>
        <div style={{ fontSize: '18px', fontWeight: 700, color: consumerLag > 50 ? '#FCD535' : '#0ECB81', fontFamily: 'monospace' }}>
          {consumerLag} <span style={{ fontSize: '12px', color: '#848E9C' }}>msgs</span>
        </div>
        <div style={{ fontSize: '11px', color: '#848E9C' }}>
          Committed: <span style={{ color: '#EAECEF' }}>{formatNumber(consumer.committed_count || 0)}</span>
        </div>
      </div>

      {/* 5. End-to-End Processing Latency */}
      <div
        style={{
          background: '#12161A',
          border: '1px solid #222B35',
          borderRadius: '6px',
          padding: '12px 14px',
          display: 'flex',
          flexDirection: 'column',
          gap: '4px'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: '11px', color: '#848E9C', textTransform: 'uppercase', fontWeight: 600 }}>
            Inline Latency (N1-N7)
          </span>
          <Activity size={14} color="#00D8FF" />
        </div>
        <div style={{ fontSize: '18px', fontWeight: 700, color: '#00D8FF', fontFamily: 'monospace' }}>
          {inlineMs > 0 ? `${inlineMs.toFixed(2)} ms` : '< 2.5 ms'}
        </div>
        <div style={{ fontSize: '11px', color: '#848E9C' }}>
          Bottleneck: <span style={{ color: '#FCD535', fontWeight: 600 }}>{bottleneck}</span>
        </div>
      </div>
    </div>
  );
};
