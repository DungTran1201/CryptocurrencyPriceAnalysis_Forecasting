import React, { useState, useEffect } from 'react';
import { Layers, Box, RefreshCw } from 'lucide-react';
import { useMarketStream } from '../context/MarketStreamContext';
import { DataFactory3D } from '../components/data-factory/DataFactory3D';
import { DataFactory2DFallback } from '../components/data-factory/DataFactory2DFallback';
import { StationInspector } from '../components/data-factory/StationInspector';
import { FactoryKPIStrip } from '../components/data-factory/FactoryKPIStrip';
import { FactoryEventFeed } from '../components/data-factory/FactoryEventFeed';
import { FACTORY_STATIONS, StationInfo } from '../components/data-factory/dataFactoryTypes';
import { api } from '../services/api';

export const DataFactoryView: React.FC = () => {
  const { wsState, streamStatus, recentFeed, lastMessageAt } = useMarketStream();
  const [selectedStation, setSelectedStation] = useState<StationInfo | null>(FACTORY_STATIONS[2]); // Default to Broker Hub
  const [viewMode, setViewMode] = useState<'3d' | '2d'>('3d');
  const [reducedMotion] = useState(false);
  const [resources, setResources] = useState<Record<string, any> | null>(null);
  const [syncing, setSyncing] = useState(false);

  // Load backend resource statistics
  const loadResources = async () => {
    try {
      const res = await api.getSystemResources();
      setResources(res);
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    loadResources();
    const interval = setInterval(loadResources, 10000);
    return () => clearInterval(interval);
  }, []);

  const handleFlush = async () => {
    try {
      await api.flushStreamingBuffer();
      await loadResources();
    } catch (err) {
      console.error('Flush failed:', err);
    }
  };

  const handleQuickSync = async () => {
    try {
      setSyncing(true);
      await api.syncMarket('BTCUSDT', '1h', 30);
      await loadResources();
    } catch (err) {
      console.error('Quick sync failed:', err);
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div style={{ padding: '20px 24px', display: 'flex', flexDirection: 'column', height: '100%', boxSizing: 'border-box' }}>
      {/* Top Page Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ fontSize: '11px', fontFamily: 'monospace', color: '#00D8FF', fontWeight: 700, letterSpacing: '0.05em' }}>
              REAL-TIME ARCHITECTURE OBSERVATORY
            </span>
            <span
              style={{
                fontSize: '10px',
                fontFamily: 'monospace',
                padding: '2px 6px',
                borderRadius: '3px',
                background: wsState === 'CONNECTED' ? 'rgba(14, 203, 129, 0.15)' : 'rgba(246, 70, 93, 0.15)',
                color: wsState === 'CONNECTED' ? '#0ECB81' : '#F6465D',
                fontWeight: 700
              }}
            >
              {wsState === 'CONNECTED' ? 'STREAM CONNECTED' : 'STREAM OFFLINE'}
            </span>
          </div>
          <h1 style={{ fontSize: '22px', fontWeight: 800, color: '#EAECEF', margin: '4px 0 0' }}>
            Data Factory & Pipeline Flow
          </h1>
        </div>

        {/* Action Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <button
            onClick={handleQuickSync}
            disabled={syncing}
            style={{
              padding: '6px 12px',
              background: '#161E27',
              border: '1px solid #222B35',
              borderRadius: '4px',
              color: '#EAECEF',
              fontSize: '11px',
              fontWeight: 600,
              cursor: syncing ? 'not-allowed' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}
          >
            <RefreshCw size={13} className={syncing ? 'spin' : ''} />
            <span>{syncing ? 'Syncing BTC...' : 'Sync BTC'}</span>
          </button>

          {/* 3D vs 2D Mode Switcher */}
          <div style={{ background: '#12161A', border: '1px solid #222B35', borderRadius: '4px', display: 'flex', padding: '2px' }}>
            <button
              onClick={() => setViewMode('3d')}
              style={{
                background: viewMode === '3d' ? '#222B35' : 'none',
                border: 'none',
                borderRadius: '3px',
                padding: '4px 10px',
                fontSize: '11px',
                fontWeight: 600,
                color: viewMode === '3d' ? '#00D8FF' : '#848E9C',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '4px'
              }}
            >
              <Box size={13} />
              <span>3D Factory</span>
            </button>
            <button
              onClick={() => setViewMode('2d')}
              style={{
                background: viewMode === '2d' ? '#222B35' : 'none',
                border: 'none',
                borderRadius: '3px',
                padding: '4px 10px',
                fontSize: '11px',
                fontWeight: 600,
                color: viewMode === '2d' ? '#00D8FF' : '#848E9C',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '4px'
              }}
            >
              <Layers size={13} />
              <span>2D Topology</span>
            </button>
          </div>
        </div>
      </div>

      {/* KPI Strip */}
      <FactoryKPIStrip
        streamStatus={streamStatus}
        wsConnected={wsState === 'CONNECTED'}
        lastMessageAt={lastMessageAt}
        profile={streamStatus.profile}
      />

      {/* Main Factory Canvas Area */}
      <div
        style={{
          flex: 1,
          minHeight: '480px',
          background: '#0B0E11',
          border: '1px solid #222B35',
          borderRadius: '8px',
          position: 'relative',
          overflow: 'hidden'
        }}
      >
        {viewMode === '3d' ? (
          <DataFactory3D
            selectedStationId={selectedStation?.id || null}
            onSelectStation={(st) => setSelectedStation(st)}
            streamStatus={streamStatus}
            wsConnected={wsState === 'CONNECTED'}
            reducedMotion={reducedMotion}
          />
        ) : (
          <DataFactory2DFallback
            selectedStationId={selectedStation?.id || null}
            onSelectStation={(st) => setSelectedStation(st)}
            wsConnected={wsState === 'CONNECTED'}
          />
        )}

        {/* Side Inspector */}
        {selectedStation && (
          <StationInspector
            station={selectedStation}
            onClose={() => setSelectedStation(null)}
            streamStatus={streamStatus}
            resources={resources}
            wsConnected={wsState === 'CONNECTED'}
            onFlush={handleFlush}
          />
        )}
      </div>

      {/* Bottom Real-Time Event Feed */}
      <FactoryEventFeed
        events={recentFeed}
        wsConnected={wsState === 'CONNECTED'}
      />
    </div>
  );
};
