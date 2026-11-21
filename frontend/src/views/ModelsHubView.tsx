import React, { useState } from 'react';
import { Cpu, History } from 'lucide-react';
import { ModelLab } from './ModelLab';
import { ForecastHistory } from './ForecastHistory';

export const ModelsHubView: React.FC = () => {
  const [activeSubTab, setActiveSubTab] = useState<'registry' | 'history'>('registry');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: '#0B0E11', overflow: 'hidden' }}>
      {/* Top Models Sub-Navigation Bar */}
      <div
        style={{
          background: '#12161A',
          borderBottom: '1px solid #222B35',
          padding: '8px 24px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '11px', fontFamily: 'monospace', color: '#848E9C', fontWeight: 700, textTransform: 'uppercase' }}>
            Machine Learning Intelligence Plane
          </span>
          <span style={{ color: '#222B35' }}>|</span>
          <div style={{ display: 'flex', gap: '4px' }}>
            <button
              onClick={() => setActiveSubTab('registry')}
              style={{
                background: activeSubTab === 'registry' ? '#222B35' : 'none',
                border: 'none',
                borderRadius: '4px',
                padding: '6px 12px',
                fontSize: '12px',
                fontWeight: 600,
                color: activeSubTab === 'registry' ? '#FCD535' : '#848E9C',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '6px'
              }}
            >
              <Cpu size={14} />
              <span>Model Registry & Training Lab</span>
            </button>
            <button
              onClick={() => setActiveSubTab('history')}
              style={{
                background: activeSubTab === 'history' ? '#222B35' : 'none',
                border: 'none',
                borderRadius: '4px',
                padding: '6px 12px',
                fontSize: '12px',
                fontWeight: 600,
                color: activeSubTab === 'history' ? '#FCD535' : '#848E9C',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '6px'
              }}
            >
              <History size={14} />
              <span>Forecast History & Audit Ledger</span>
            </button>
          </div>
        </div>

        <div style={{ fontSize: '11px', color: '#848E9C', fontFamily: 'monospace' }}>
          Promotion Gate: <span style={{ color: '#00D8FF' }}>&ge;1% Naive Gain</span>
        </div>
      </div>

      {/* Main View Content */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {activeSubTab === 'registry' && <ModelLab />}
        {activeSubTab === 'history' && <ForecastHistory />}
      </div>
    </div>
  );
};
