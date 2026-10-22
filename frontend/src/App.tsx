import React, { useState, useEffect } from 'react';
import {
  TrendingUp,
  LineChart,
  Sparkles,
  History,
  Cpu,
  Activity,
  Menu,
  X,
  Layers,
  ShieldCheck,
  Database,
  Server
} from 'lucide-react';
import { DataOpsOverview } from './views/DataOpsOverview';
import { PipelineObservatory } from './views/PipelineObservatory';
import { DataQualityLineage } from './views/DataQualityLineage';
import { DataExplorer } from './views/DataExplorer';
import { MarketAnalytics } from './views/MarketAnalytics';
import { PredictionStudio } from './views/PredictionStudio';
import { ForecastHistory } from './views/ForecastHistory';
import { ModelLab } from './views/ModelLab';
import { SystemStatusView } from './views/SystemStatusView';
import { api } from './services/api';
import { SystemStatus } from './types';

type TabType =
  | 'overview'
  | 'pipelines'
  | 'quality'
  | 'explorer'
  | 'analytics'
  | 'studio'
  | 'history'
  | 'models'
  | 'system';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabType>('overview');
  const [mobileMenuOpen, setMobileMenuOpen] = useState<boolean>(false);
  const [systemState, setSystemState] = useState<{
    status: 'ONLINE' | 'AWAITING_DATA' | 'OFFLINE';
    label: string;
    details: string;
  }>({
    status: 'ONLINE',
    label: 'CHECKING SYSTEM',
    details: 'Verifying database & backend connection...'
  });

  const checkStatus = async () => {
    try {
      const res: SystemStatus = await api.getSystemStatus();
      if (res.database_connected && res.status === 'OPERATIONAL') {
        if (res.total_candles_stored > 0) {
          setSystemState({
            status: 'ONLINE',
            label: 'ENGINE ONLINE',
            details: `${res.total_candles_stored.toLocaleString()} candles • ${res.active_models_count} active models`
          });
        } else {
          setSystemState({
            status: 'AWAITING_DATA',
            label: 'NO STORED CANDLES',
            details: 'Database connected. Click Sync Medallion to seed market data.'
          });
        }
      } else {
        setSystemState({
          status: 'OFFLINE',
          label: 'DEGRADED',
          details: 'Backend is operating in degraded state.'
        });
      }
    } catch {
      setSystemState({
        status: 'OFFLINE',
        label: 'DISCONNECTED',
        details: 'Cannot reach backend API.'
      });
    }
  };

  useEffect(() => {
    checkStatus();
    const interval = setInterval(checkStatus, 30000);
    return () => clearInterval(interval);
  }, []);

  const navItems: { id: TabType; label: string; icon: React.ReactNode }[] = [
    { id: 'overview', label: 'Data Operations', icon: <Layers size={15} /> },
    { id: 'pipelines', label: 'Pipelines', icon: <Activity size={15} /> },
    { id: 'quality', label: 'Quality & Lineage', icon: <ShieldCheck size={15} /> },
    { id: 'explorer', label: 'Data Explorer', icon: <Database size={15} /> },
    { id: 'analytics', label: 'Market Analytics', icon: <LineChart size={15} /> },
    { id: 'studio', label: 'Prediction Studio', icon: <Sparkles size={15} /> },
    { id: 'history', label: 'Forecast History', icon: <History size={15} /> },
    { id: 'models', label: 'Model Lab', icon: <Cpu size={15} /> },
    { id: 'system', label: 'System Health', icon: <Server size={15} /> },
  ];

  const handleTabSelect = (tab: TabType) => {
    setActiveTab(tab);
    setMobileMenuOpen(false);
  };

  return (
    <div className="app-container">
      {/* Global Navbar */}
      <nav className="navbar" role="navigation" aria-label="Main Navigation">
        <div className="nav-brand" onClick={() => handleTabSelect('overview')} style={{ cursor: 'pointer' }}>
          <div className="brand-icon">
            <TrendingUp size={20} color="#07090e" strokeWidth={2.5} />
          </div>
          <div>
            <div style={{ color: '#fff', fontSize: '1.05rem', fontWeight: 700, letterSpacing: '-0.02em' }}>
              CRYPTO DATA PLATFORM
            </div>
            <div style={{ fontSize: '0.65rem', color: 'var(--accent-cyan)', letterSpacing: '0.08em', fontFamily: 'var(--font-mono)' }}>
              DATA ENG • ANALYTICS • FORECAST LAB
            </div>
          </div>
        </div>

        {/* Desktop Navigation Tabs */}
        <div className="nav-tabs desktop-only">
          {navItems.map((item) => (
            <button
              key={item.id}
              id={`tab-${item.id}`}
              className={`nav-tab ${activeTab === item.id ? 'active' : ''}`}
              onClick={() => handleTabSelect(item.id)}
            >
              {item.icon}
              <span>{item.label}</span>
            </button>
          ))}
        </div>

        {/* Operational Status Pill (Driven by real backend data) */}
        <div className="nav-status">
          <div
            className={`status-badge ${
              systemState.status === 'ONLINE'
                ? 'status-online'
                : systemState.status === 'AWAITING_DATA'
                ? 'status-warning'
                : 'status-offline'
            }`}
            title={systemState.details}
          >
            <div className="pulse-dot"></div>
            <span>{systemState.label}</span>
          </div>

          {/* Mobile hamburger toggle */}
          <button
            className="mobile-menu-btn mobile-only"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            aria-label="Toggle navigation menu"
          >
            {mobileMenuOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
        </div>
      </nav>

      {/* Mobile Navigation Dropdown */}
      {mobileMenuOpen && (
        <div className="mobile-nav-menu mobile-only">
          {navItems.map((item) => (
            <button
              key={item.id}
              className={`mobile-nav-item ${activeTab === item.id ? 'active' : ''}`}
              onClick={() => handleTabSelect(item.id)}
            >
              {item.icon}
              <span>{item.label}</span>
            </button>
          ))}
        </div>
      )}

      {/* Main Viewport Content */}
      <main className="main-viewport">
        {activeTab === 'overview' && <DataOpsOverview onNavigateTab={(tab) => handleTabSelect(tab as TabType)} />}
        {activeTab === 'pipelines' && <PipelineObservatory />}
        {activeTab === 'quality' && <DataQualityLineage />}
        {activeTab === 'explorer' && <DataExplorer />}
        {activeTab === 'analytics' && <MarketAnalytics />}
        {activeTab === 'studio' && <PredictionStudio />}
        {activeTab === 'history' && <ForecastHistory />}
        {activeTab === 'models' && <ModelLab />}
        {activeTab === 'system' && <SystemStatusView />}
      </main>

      {/* Global Footer */}
      <footer className="app-footer">
        <div>
          Binance Predict Value & Trend • Enterprise Crypto Data & Analytics Platform
        </div>
        <div style={{ fontFamily: 'var(--font-mono)' }}>
          Medallion Architecture • Data Quality SLAs • Walk-Forward Walk CV • Realtime REST Telemetry
        </div>
      </footer>
    </div>
  );
};

export default App;
