import React from 'react';
import { FACTORY_STATIONS, StationInfo } from './dataFactoryTypes';

interface DataFactory2DFallbackProps {
  selectedStationId: string | null;
  onSelectStation: (station: StationInfo) => void;
  wsConnected: boolean;
}

export const DataFactory2DFallback: React.FC<DataFactory2DFallbackProps> = ({
  selectedStationId,
  onSelectStation,
  wsConnected
}) => {
  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        background: '#0B0E11',
        padding: '24px',
        overflow: 'auto',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        alignItems: 'center'
      }}
    >
      <div style={{ maxWidth: '960px', width: '100%' }}>
        <div style={{ textAlign: 'center', marginBottom: '20px' }}>
          <span style={{ fontSize: '11px', fontFamily: 'monospace', color: '#848E9C', textTransform: 'uppercase' }}>
            2D Schematic Architecture Mode
          </span>
          <h2 style={{ fontSize: '18px', fontWeight: 700, color: '#EAECEF', margin: '4px 0 0' }}>
            Data Platform Pipeline Topology
          </h2>
        </div>

        {/* Streaming Ingress & Processing Row */}
        <div style={{ marginBottom: '16px' }}>
          <div style={{ fontSize: '10px', color: '#00D8FF', fontWeight: 700, letterSpacing: '0.05em', marginBottom: '8px' }}>
            ▲ REAL-TIME STREAMING & LAKEHOUSE INGESTION PATH
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px' }}>
            {FACTORY_STATIONS.slice(0, 4).map((st) => {
              const isSelected = st.id === selectedStationId;
              return (
                <div
                  key={st.id}
                  onClick={() => onSelectStation(st)}
                  style={{
                    background: isSelected ? 'rgba(0, 216, 255, 0.12)' : '#12161A',
                    border: `1px solid ${isSelected ? st.color : '#222B35'}`,
                    borderRadius: '6px',
                    padding: '14px',
                    cursor: 'pointer',
                    transition: 'all 0.2s ease',
                    boxShadow: isSelected ? `0 0 16px ${st.color}33` : 'none'
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                    <span style={{ fontSize: '10px', fontFamily: 'monospace', fontWeight: 700, color: st.color }}>
                      {st.code}
                    </span>
                    <span
                      style={{
                        width: '6px',
                        height: '6px',
                        borderRadius: '50%',
                        background: wsConnected ? '#0ECB81' : '#F6465D'
                      }}
                    />
                  </div>
                  <div style={{ fontSize: '13px', fontWeight: 700, color: '#EAECEF', marginBottom: '2px' }}>
                    {st.name}
                  </div>
                  <div style={{ fontSize: '10px', color: '#848E9C', lineHeight: '1.4' }}>
                    {st.subtitle}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Downstream Storage, Intelligence, Warehouse & Serving Row */}
        <div>
          <div style={{ fontSize: '10px', color: '#10B981', fontWeight: 700, letterSpacing: '0.05em', marginBottom: '8px' }}>
            ▼ STORAGE, ANALYTICS & SERVING PLANE
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px' }}>
            {FACTORY_STATIONS.slice(4, 8).map((st) => {
              const isSelected = st.id === selectedStationId;
              return (
                <div
                  key={st.id}
                  onClick={() => onSelectStation(st)}
                  style={{
                    background: isSelected ? `${st.color}15` : '#12161A',
                    border: `1px solid ${isSelected ? st.color : '#222B35'}`,
                    borderRadius: '6px',
                    padding: '14px',
                    cursor: 'pointer',
                    transition: 'all 0.2s ease',
                    boxShadow: isSelected ? `0 0 16px ${st.color}33` : 'none'
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                    <span style={{ fontSize: '10px', fontFamily: 'monospace', fontWeight: 700, color: st.color }}>
                      {st.code}
                    </span>
                    <span style={{ fontSize: '9px', fontFamily: 'monospace', color: st.pathType === 'batch' ? '#F59E0B' : '#00D8FF' }}>
                      {st.pathType.toUpperCase()}
                    </span>
                  </div>
                  <div style={{ fontSize: '13px', fontWeight: 700, color: '#EAECEF', marginBottom: '2px' }}>
                    {st.name}
                  </div>
                  <div style={{ fontSize: '10px', color: '#848E9C', lineHeight: '1.4' }}>
                    {st.subtitle}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
};
