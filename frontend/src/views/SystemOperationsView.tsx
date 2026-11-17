import React, { useState } from 'react';
import { ShieldCheck, Database, Activity, Server } from 'lucide-react';
import { DataQualityLineage } from './DataQualityLineage';
import { DataExplorer } from './DataExplorer';
import { PipelineObservatory } from './PipelineObservatory';
import { SystemStatusView } from './SystemStatusView';

export type OperationsTab = 'quality' | 'explorer' | 'pipelines' | 'system';

interface SystemOperationsViewProps {
  initialTab?: OperationsTab;
}

export const SystemOperationsView: React.FC<SystemOperationsViewProps> = ({ initialTab = 'quality' }) => {
  const [activeTab, setActiveTab] = useState<OperationsTab>(initialTab);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: '#0B0E11', overflow: 'hidden' }}>
      {/* Top Operations Secondary Navigation Bar */}
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
            System & Operations Hub
          </span>
          <span style={{ color: '#222B35' }}>|</span>
          <div style={{ display: 'flex', gap: '4px' }}>
            <button
              onClick={() => setActiveTab('quality')}
              style={{
                background: activeTab === 'quality' ? '#222B35' : 'none',
                border: 'none',
                borderRadius: '4px',
                padding: '6px 12px',
                fontSize: '12px',
                fontWeight: 600,
                color: activeTab === 'quality' ? '#00D8FF' : '#848E9C',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '6px'
              }}
            >
              <ShieldCheck size={14} />
              <span>Quality & Lineage</span>
            </button>
            <button
              onClick={() => setActiveTab('explorer')}
              style={{
                background: activeTab === 'explorer' ? '#222B35' : 'none',
                border: 'none',
                borderRadius: '4px',
                padding: '6px 12px',
                fontSize: '12px',
                fontWeight: 600,
                color: activeTab === 'explorer' ? '#00D8FF' : '#848E9C',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '6px'
              }}
            >
              <Database size={14} />
              <span>Data Explorer</span>
            </button>
            <button
              onClick={() => setActiveTab('pipelines')}
              style={{
                background: activeTab === 'pipelines' ? '#222B35' : 'none',
                border: 'none',
                borderRadius: '4px',
                padding: '6px 12px',
                fontSize: '12px',
                fontWeight: 600,
                color: activeTab === 'pipelines' ? '#00D8FF' : '#848E9C',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '6px'
              }}
            >
              <Activity size={14} />
              <span>Pipeline Observatory</span>
            </button>
            <button
              onClick={() => setActiveTab('system')}
              style={{
                background: activeTab === 'system' ? '#222B35' : 'none',
                border: 'none',
                borderRadius: '4px',
                padding: '6px 12px',
                fontSize: '12px',
                fontWeight: 600,
                color: activeTab === 'system' ? '#00D8FF' : '#848E9C',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '6px'
              }}
            >
              <Server size={14} />
              <span>System Health & Storage</span>
            </button>
          </div>
        </div>

        <div style={{ fontSize: '11px', color: '#848E9C', fontFamily: 'monospace' }}>
          Runtime: <span style={{ color: '#0ECB81' }}>OPERATIONAL</span>
        </div>
      </div>

      {/* Main Operations View Content */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {activeTab === 'quality' && <DataQualityLineage />}
        {activeTab === 'explorer' && <DataExplorer />}
        {activeTab === 'pipelines' && <PipelineObservatory />}
        {activeTab === 'system' && <SystemStatusView />}
      </div>
    </div>
  );
};
