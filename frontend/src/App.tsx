import React, { useState, useEffect } from 'react';
import {
  TrendingUp,
  LineChart,
  Sparkles,
  History,
  Cpu,
  Activity,
  Menu,
  X
} from 'lucide-react';
import { MarketOverview } from './views/MarketOverview';
import { PredictionStudio } from './views/PredictionStudio';
import { ForecastHistory } from './views/ForecastHistory';
import { ModelLab } from './views/ModelLab';
import { SystemStatusView } from './views/SystemStatusView';
import { api } from './services/api';
import { SystemStatus } from './types';

type TabType = 'market' | 'studio' | 'history' | 'models' | 'system';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabType>('market');
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
            details: 'Database connected. Click Sync Binance to seed market data.'
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
    { id: 'market', label: 'Market Overview', icon: <LineChart size={16} /> },
    { id: 'studio', label: 'Prediction Studio', icon: <Sparkles size={16} /> },
    { id: 'history', label: 'Forecast History', icon: <History size={16} /> },
    { id: 'models', label: 'Model Lab', icon: <Cpu size={16} /> },
    { id: 'system', label: 'System Status', icon: <Activity size={16} /> },
  ];

  const handleTabSelect = (tab: TabType) => {
    setActiveTab(tab);
    setMobileMenuOpen(false);
  };

  return (
    <div className="app-container">
      {/* Global Navbar */}
      <nav className="navbar" role="navigation" aria-label="Main Navigation">
        <div className="nav-brand">
          <div className="brand-icon">
            <TrendingUp size={20} color="#07090e" strokeWidth={2.5} />
          </div>
          <div>
            <div style={{ color: '#fff', fontSize: '1.15rem', fontWeight: 700, letterSpacing: '-0.02em' }}>
              CRYPTO INTELLIGENCE
            </div>
            <div style={{ fontSize: '0.68rem', color: 'var(--accent-cyan)', letterSpacing: '0.08em', fontFamily: 'var(--font-mono)' }}>
              FORECASTING & EVALUATION ENGINE
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
        {activeTab === 'market' && <MarketOverview />}
        {activeTab === 'studio' && <PredictionStudio />}
        {activeTab === 'history' && <ForecastHistory />}
        {activeTab === 'models' && <ModelLab />}
        {activeTab === 'system' && <SystemStatusView />}
      </main>

      {/* Global Footer */}
      <footer className="app-footer">
        <div>
          Binance Predict Value & Trend • Enterprise Crypto Market Forecasting Architecture
        </div>
        <div style={{ fontFamily: 'var(--font-mono)' }}>
          FastAPI Backend • React TypeScript Frontend • Walk-Forward Cross Validation
        </div>
      </footer>
    </div>
  );
};

export default App;
