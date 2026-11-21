import React from 'react';
import { StreamEventFeedItem } from '../../context/MarketStreamContext';
import { formatCurrency, formatNumber } from '../../utils/formatters';

interface FactoryEventFeedProps {
  events: StreamEventFeedItem[];
  wsConnected: boolean;
}

export const FactoryEventFeed: React.FC<FactoryEventFeedProps> = ({ events, wsConnected }) => {
  return (
    <div
      style={{
        background: '#12161A',
        border: '1px solid #222B35',
        borderRadius: '6px',
        padding: '12px 16px',
        marginTop: '16px'
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '11px', textTransform: 'uppercase', color: '#848E9C', fontWeight: 700, letterSpacing: '0.05em' }}>
            Live Stream Ingress Activity
          </span>
          <span
            style={{
              fontSize: '10px',
              fontFamily: 'monospace',
              padding: '1px 6px',
              borderRadius: '3px',
              background: wsConnected ? 'rgba(14, 203, 129, 0.15)' : 'rgba(246, 70, 93, 0.15)',
              color: wsConnected ? '#0ECB81' : '#F6465D',
              fontWeight: 600
            }}
          >
            {wsConnected ? 'BUFFER ACTIVE' : 'STREAM OFFLINE'}
          </span>
        </div>
        <span style={{ fontSize: '11px', color: '#848E9C', fontFamily: 'monospace' }}>
          Showing latest {events.length} / 60 events
        </span>
      </div>

      {events.length === 0 ? (
        <div style={{ padding: '16px', textAlign: 'center', color: '#848E9C', fontSize: '12px' }}>
          Awaiting real-time WebSocket tick frames...
        </div>
      ) : (
        <div
          style={{
            display: 'flex',
            gap: '8px',
            overflowX: 'auto',
            paddingBottom: '4px'
          }}
        >
          {events.slice(0, 15).map((evt) => (
            <div
              key={evt.id}
              style={{
                flexShrink: 0,
                background: '#161E27',
                border: '1px solid #222B35',
                borderRadius: '4px',
                padding: '6px 10px',
                display: 'flex',
                flexDirection: 'column',
                gap: '2px',
                minWidth: '140px'
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '11px', fontWeight: 700, color: '#EAECEF' }}>{evt.symbol}</span>
                <span style={{ fontSize: '9px', color: '#848E9C', fontFamily: 'monospace' }}>
                  {evt.time.split('T')[1]?.slice(0, 8) || ''}
                </span>
              </div>
              <div style={{ fontSize: '13px', fontWeight: 700, color: '#00D8FF', fontFamily: 'monospace' }}>
                {formatCurrency(evt.price)}
              </div>
              <div style={{ fontSize: '10px', color: '#848E9C', display: 'flex', justifyContent: 'space-between' }}>
                <span>Qty: {evt.qty ? formatNumber(evt.qty, 3) : '—'}</span>
                <span>VWAP: {evt.vwap ? `$${evt.vwap.toFixed(1)}` : '—'}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
