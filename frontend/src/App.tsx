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
  Server,
  RefreshCw,
  ChevronRight,
  ExternalLink,
  Radio
} from 'lucide-react';
import { DataOpsOverview } from './views/DataOpsOverview';
import { MarketOverview } from './views/MarketOverview';
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
import { StatusBadge } from './components/StatusBadge';

export type TabType =
  | 'overview'
  | 'live'
  | 'pipelines'
  | 'quality'
  | 'explorer'
  | 'analytics'
  | 'studio'
  | 'history'
  | 'models'
  | 'system';

const VALID_TABS: TabType[] = [
  'overview',
  'live',
  'pipelines',
  'quality',
  'explorer',
  'analytics',
  'studio',
  'history',
  'models',
  'system'
];

const getTabFromHash = (): TabType => {
  if (typeof window === 'undefined') return 'overview';
  const hash = window.location.hash.replace(/^#\/?/, '').trim();
  return VALID_TABS.includes(hash as TabType) ? (hash as TabType) : 'overview';
};

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabType>(getTabFromHash);
  const [mobileMenuOpen, setMobileMenuOpen] = useState<boolean>(false);
  const [syncingQuick, setSyncingQuick] = useState<boolean>(false);
  const [systemState, setSystemState] = useState<{
    status: 'ONLINE' | 'AWAITING_DATA' | 'OFFLINE';
    label: string;
    details: string;
    candleCount: number;
    modelsCount: number;
  }>({
    status: 'ONLINE',
    label: 'CHECKING SYSTEM',
    details: 'Verifying database & backend connection...',
    candleCount: 0,
    modelsCount: 0
  });

  const checkStatus = async () => {
    try {
      const res: SystemStatus = await api.getSystemStatus();
      if (res.database_connected && res.status === 'OPERATIONAL') {
        if (res.total_candles_stored > 0) {
          setSystemState({
            status: 'ONLINE',
            label: 'ENGINE ONLINE',
            details: `${res.total_candles_stored.toLocaleString()} candles • ${res.active_models_count} active models`,
            candleCount: res.total_candles_stored,
            modelsCount: res.active_models_count
          });
        } else {
          setSystemState({
            status: 'AWAITING_DATA',
            label: 'NO STORED CANDLES',
            details: 'Database connected. Click Quick Sync to seed market data.',
            candleCount: 0,
            modelsCount: res.active_models_count
          });
        }
      } else {
        setSystemState({
          status: 'OFFLINE',
          label: 'DEGRADED',
          details: 'Backend is operating in degraded state.',
          candleCount: 0,
          modelsCount: 0
        });
      }
    } catch {
      setSystemState({
        status: 'OFFLINE',
        label: 'DISCONNECTED',
        details: 'Cannot reach backend API.',
        candleCount: 0,
        modelsCount: 0
      });
    }
  };

  useEffect(() => {
    checkStatus();
    const interval = setInterval(checkStatus, 30000);
    const onHashChange = () => {
      setActiveTab(getTabFromHash());
    };
    window.addEventListener('hashchange', onHashChange);
    return () => {
      clearInterval(interval);
      window.removeEventListener('hashchange', onHashChange);
    };
  }, []);

  const handleQuickSync = async () => {
    try {
      setSyncingQuick(true);
      await api.syncMarket('BTCUSDT', '1h', 30);
      await checkStatus();
    } catch (err: any) {
      console.error('Quick sync failed:', err);
    } finally {
      setSyncingQuick(false);
    }
  };

  const navGroups: {
    groupTitle: string;
    items: { id: TabType; label: string; icon: React.ReactNode; badge?: string }[];
  }[] = [
    {
      groupTitle: 'Core Operations',
      items: [
        { id: 'overview', label: 'Data Operations', icon: <Layers size={16} /> },
        { id: 'live', label: 'Live Market', icon: <Radio size={16} /> },
        { id: 'pipelines', label: 'Pipelines', icon: <Activity size={16} /> },
        { id: 'quality', label: 'Quality & Lineage', icon: <ShieldCheck size={16} /> },
        { id: 'explorer', label: 'Data Explorer', icon: <Database size={16} /> }
      ]
    },
    {
      groupTitle: 'Quantitative Lab',
      items: [
        { id: 'analytics', label: 'Market Analytics', icon: <LineChart size={16} /> },
        { id: 'studio', label: 'Prediction Studio', icon: <Sparkles size={16} /> },
        { id: 'history', label: 'Forecast History', icon: <History size={16} /> },
        { id: 'models', label: 'Model Lab', icon: <Cpu size={16} /> }
      ]
    },
    {
      groupTitle: 'Infrastructure',
      items: [
        { id: 'system', label: 'System Health', icon: <Server size={16} /> }
      ]
    }
  ];

  const handleTabSelect = (tab: TabType) => {
    window.location.hash = tab;
    setActiveTab(tab);
    setMobileMenuOpen(false);
  };

  // Find active label for breadcrumb
  let activeLabel = 'Data Operations';
  for (const g of navGroups) {
    const found = g.items.find((i) => i.id === activeTab);
    if (found) {
      activeLabel = found.label;
      break;
    }
  }

  return (
    <div className="app-layout">
      {/* 1. Left Persistent Sidebar */}
      <aside className={`app-sidebar ${mobileMenuOpen ? 'mobile-open' : ''}`} role="navigation" aria-label="Main Navigation">
        {/* Brand Header */}
        <div className="sidebar-brand" onClick={() => handleTabSelect('overview')} role="button" tabIndex={0}>
          <div className="brand-icon">
            <TrendingUp size={18} color="#12161C" strokeWidth={2.6} />
          </div>
          <div>
            <div className="brand-title">CRYPTO PLATFORM</div>
            <div className="brand-tagline">DATA ENG • ANALYTICS • ML</div>
          </div>
        </div>

        {/* Navigation Categories */}
        <nav className="sidebar-nav">
          {navGroups.map((group) => (
            <div key={group.groupTitle} className="nav-group">
              <div className="nav-group-label">{group.groupTitle}</div>
              {group.items.map((item) => (
                <button
                  key={item.id}
                  id={`nav-item-${item.id}`}
                  className={`nav-item ${activeTab === item.id ? 'active' : ''}`}
                  onClick={() => handleTabSelect(item.id)}
                >
                  {item.icon}
                  <span>{item.label}</span>
                </button>
              ))}
            </div>
          ))}
        </nav>

        {/* Sidebar Footer */}
        <div className="sidebar-footer">
          <div style={{ marginBottom: '0.35rem' }}>Real-Time Intelligence v3.0</div>
          <div className="engine-spec-pill">
            <span>NATS • DUCKDB • FASTAPI</span>
          </div>
        </div>
      </aside>

      {/* 2. Main Area: TopBar + Viewport + Footer */}
      <div className="app-main">
        {/* TopBar Header */}
        <header className="topbar" role="banner">
          <div className="topbar-breadcrumbs">
            <button
              className="mobile-toggle-btn"
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              aria-label="Toggle navigation menu"
            >
              {mobileMenuOpen ? <X size={18} /> : <Menu size={18} />}
            </button>
            <span>Platform</span>
            <ChevronRight size={14} />
            <span className="active">{activeLabel}</span>
          </div>

          <div className="topbar-actions">
            {/* Quick Sync Action */}
            <button
              className="btn btn-secondary btn-sm"
              onClick={handleQuickSync}
              disabled={syncingQuick}
              title="Trigger incremental 30-day sync for BTCUSDT"
            >
              <RefreshCw size={12} className={syncingQuick ? 'spin' : ''} />
              <span>{syncingQuick ? 'Syncing...' : 'Quick Sync BTC'}</span>
            </button>

            {/* Operational Engine Status Pill */}
            <StatusBadge
              status={systemState.status}
              label={systemState.label}
              pulse={systemState.status === 'ONLINE'}
              title={systemState.details}
            />

            {/* API Docs Link */}
            <a
              href="/docs"
              target="_blank"
              rel="noreferrer"
              className="btn btn-secondary btn-sm"
              title="Open FastAPI Swagger Interactive Documentation"
            >
              <ExternalLink size={12} />
              <span>Swagger</span>
            </a>
          </div>
        </header>

        {/* Main Viewport */}
        <main className="main-viewport" role="main">
          {activeTab === 'overview' && <DataOpsOverview onNavigateTab={(tab) => handleTabSelect(tab as TabType)} />}
          {activeTab === 'live' && <MarketOverview />}
          {activeTab === 'pipelines' && <PipelineObservatory />}
          {activeTab === 'quality' && <DataQualityLineage />}
          {activeTab === 'explorer' && <DataExplorer />}
          {activeTab === 'analytics' && <MarketAnalytics />}
          {activeTab === 'studio' && <PredictionStudio />}
          {activeTab === 'history' && <ForecastHistory />}
          {activeTab === 'models' && <ModelLab />}
          {activeTab === 'system' && <SystemStatusView />}
        </main>

        {/* Institutional Footer */}
        <footer className="app-footer">
          <div>
            Crypto Data Engineering, Analytics & Forecasting Platform • Binance Reference Language
          </div>
          <div style={{ fontFamily: 'var(--font-mono)' }}>
            Medallion Architecture (Bronze/Silver/Gold) • Walk-Forward Expanding CV • Strict Integrity SLAs
          </div>
        </footer>
      </div>
    </div>
  );
};

export default App;
