import React, { useState, useEffect } from 'react';
import {
  TrendingUp,
  Box,
  BarChart2,
  Cpu,
  Settings,
  Menu,
  X,
  ChevronRight,
  ExternalLink,
  RefreshCw,
  Radio
} from 'lucide-react';
import { MarketStreamProvider } from './context/MarketStreamContext';
import { DataFactoryView } from './views/DataFactoryView';
import { MarketTerminalView } from './views/MarketTerminalView';
import { ModelsHubView } from './views/ModelsHubView';
import { SystemOperationsView, OperationsTab } from './views/SystemOperationsView';
import { api } from './services/api';
import { SystemStatus } from './types';
import { StatusBadge } from './components/StatusBadge';

export type PrimaryTabType = 'factory' | 'terminal' | 'models' | 'operations';

interface RouteState {
  primary: PrimaryTabType;
  operationsTab?: OperationsTab;
}

const parseHash = (): RouteState => {
  if (typeof window === 'undefined') return { primary: 'factory' };
  const raw = window.location.hash.replace(/^#\/?/, '').trim().toLowerCase();

  // Backward compatibility mappings
  if (raw === 'overview' || raw === 'factory' || !raw) return { primary: 'factory' };
  if (raw === 'live' || raw === 'terminal' || raw === 'analytics') return { primary: 'terminal' };
  if (raw === 'models' || raw === 'studio' || raw === 'history') return { primary: 'models' };
  if (raw === 'quality' || raw === 'explorer' || raw === 'pipelines' || raw === 'system' || raw === 'operations') {
    const opTab = (['quality', 'explorer', 'pipelines', 'system'].includes(raw) ? raw : 'quality') as OperationsTab;
    return { primary: 'operations', operationsTab: opTab };
  }
  return { primary: 'factory' };
};

export const AppContent: React.FC = () => {
  const [route, setRoute] = useState<RouteState>(parseHash);
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
      setRoute(parseHash());
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

  const handleNavigate = (tab: PrimaryTabType, opTab?: OperationsTab) => {
    if (tab === 'operations' && opTab) {
      window.location.hash = opTab;
    } else {
      window.location.hash = tab;
    }
    setRoute({ primary: tab, operationsTab: opTab });
    setMobileMenuOpen(false);
  };

  const navItems = [
    {
      groupTitle: 'Core Workspaces',
      items: [
        {
          id: 'factory' as PrimaryTabType,
          label: 'Data Factory',
          subtitle: '3D Real-Time Platform',
          icon: <Box size={18} />
        },
        {
          id: 'terminal' as PrimaryTabType,
          label: 'Market Terminal',
          subtitle: 'TradingView & ML Overlay',
          icon: <BarChart2 size={18} />
        },
        {
          id: 'models' as PrimaryTabType,
          label: 'Models & Inference',
          subtitle: 'Training Lab & Ledger',
          icon: <Cpu size={18} />
        }
      ]
    },
    {
      groupTitle: 'Operations & Governance',
      items: [
        {
          id: 'operations' as PrimaryTabType,
          label: 'System & Operations',
          subtitle: 'DQ, Explorer, Pipelines, Health',
          icon: <Settings size={18} />
        }
      ]
    }
  ];

  const getBreadcrumbLabel = () => {
    switch (route.primary) {
      case 'factory':
        return 'Data Factory (3D Real-Time Platform)';
      case 'terminal':
        return 'Market Terminal (TradingView & ML Inference)';
      case 'models':
        return 'Models & Experiments (Walk-Forward Lab)';
      case 'operations':
        return `System & Operations (${route.operationsTab || 'Quality & Lineage'})`;
      default:
        return 'Platform';
    }
  };

  return (
    <div className="app-layout">
      {/* 1. Left Persistent Sidebar */}
      <aside className={`app-sidebar ${mobileMenuOpen ? 'mobile-open' : ''}`} role="navigation" aria-label="Main Navigation">
        {/* Brand Header */}
        <div className="sidebar-brand" onClick={() => handleNavigate('factory')} role="button" tabIndex={0}>
          <div className="brand-icon">
            <TrendingUp size={18} color="#12161C" strokeWidth={2.6} />
          </div>
          <div>
            <div className="brand-title">MARKETSTREAM</div>
            <div className="brand-tagline">REAL-TIME DATA INTELLIGENCE</div>
          </div>
        </div>

        {/* Navigation Categories */}
        <nav className="sidebar-nav">
          {navItems.map((group) => (
            <div key={group.groupTitle} className="nav-group">
              <div className="nav-group-label">{group.groupTitle}</div>
              {group.items.map((item) => {
                const isActive = route.primary === item.id;
                return (
                  <button
                    key={item.id}
                    id={`nav-item-${item.id}`}
                    className={`nav-item ${isActive ? 'active' : ''}`}
                    onClick={() => handleNavigate(item.id)}
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'flex-start',
                      padding: '10px 14px',
                      gap: '2px',
                      marginBottom: '4px'
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', width: '100%' }}>
                      <span style={{ color: isActive ? '#00D8FF' : '#848E9C' }}>{item.icon}</span>
                      <span style={{ fontWeight: isActive ? 700 : 500, color: isActive ? '#EAECEF' : '#CBD5E1', fontSize: '13px' }}>
                        {item.label}
                      </span>
                    </div>
                    <span style={{ fontSize: '10px', color: '#848E9C', paddingLeft: '28px' }}>
                      {item.subtitle}
                    </span>
                  </button>
                );
              })}
            </div>
          ))}
        </nav>

        {/* Sidebar Footer */}
        <div className="sidebar-footer">
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px', fontSize: '11px', color: '#0ECB81' }}>
            <Radio size={12} className="pulse" />
            <span>Single WebSocket Hub</span>
          </div>
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
            <span className="active">{getBreadcrumbLabel()}</span>
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
        <main className="main-viewport" role="main" style={{ padding: 0, display: 'flex', flexDirection: 'column' }}>
          {route.primary === 'factory' && <DataFactoryView />}
          {route.primary === 'terminal' && <MarketTerminalView />}
          {route.primary === 'models' && <ModelsHubView />}
          {route.primary === 'operations' && <SystemOperationsView initialTab={route.operationsTab} />}
        </main>

        {/* Institutional Footer */}
        <footer className="app-footer">
          <div>
            MarketStream — Real-Time Financial Data Intelligence Platform • Industrial Data Factory & Financial Terminal
          </div>
          <div style={{ fontFamily: 'var(--font-mono)' }}>
            Medallion Lakehouse • TradingView Engine • Zero-Lookahead Walk-Forward ML
          </div>
        </footer>
      </div>
    </div>
  );
};

export const App: React.FC = () => {
  return (
    <MarketStreamProvider>
      <AppContent />
    </MarketStreamProvider>
  );
};

export default App;
