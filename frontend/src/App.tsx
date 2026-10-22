import React, { useState } from 'react';
import {
  TrendingUp,
  LineChart,
  Sparkles,
  History,
  Cpu,
  Activity
} from 'lucide-react';
import { MarketOverview } from './views/MarketOverview';
import { PredictionStudio } from './views/PredictionStudio';
import { ForecastHistory } from './views/ForecastHistory';
import { ModelLab } from './views/ModelLab';
import { SystemStatusView } from './views/SystemStatusView';

type TabType = 'market' | 'studio' | 'history' | 'models' | 'system';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabType>('market');

  return (
    <div className="app-container">
      {/* Global Navbar */}
      <nav className="navbar">
        <div className="nav-brand">
          <div className="brand-icon">
            <TrendingUp size={20} color="#07090e" strokeWidth={2.5} />
          </div>
          <div>
            <div style={{ color: '#fff', fontSize: '1.15rem' }}>CRYPTO INTELLIGENCE</div>
            <div style={{ fontSize: '0.68rem', color: 'var(--accent-cyan)', letterSpacing: '0.08em', fontFamily: 'var(--font-mono)' }}>
              FORECASTING & EVALUATION ENGINE
            </div>
          </div>
        </div>

        {/* Navigation Tabs */}
        <div className="nav-tabs">
          <button
            id="tab-market"
            className={`nav-tab ${activeTab === 'market' ? 'active' : ''}`}
            onClick={() => setActiveTab('market')}
          >
            <LineChart size={16} />
            <span>Market Overview</span>
          </button>

          <button
            id="tab-studio"
            className={`nav-tab ${activeTab === 'studio' ? 'active' : ''}`}
            onClick={() => setActiveTab('studio')}
          >
            <Sparkles size={16} />
            <span>Prediction Studio</span>
          </button>

          <button
            id="tab-history"
            className={`nav-tab ${activeTab === 'history' ? 'active' : ''}`}
            onClick={() => setActiveTab('history')}
          >
            <History size={16} />
            <span>Forecast History</span>
          </button>

          <button
            id="tab-models"
            className={`nav-tab ${activeTab === 'models' ? 'active' : ''}`}
            onClick={() => setActiveTab('models')}
          >
            <Cpu size={16} />
            <span>Model Lab</span>
          </button>

          <button
            id="tab-system"
            className={`nav-tab ${activeTab === 'system' ? 'active' : ''}`}
            onClick={() => setActiveTab('system')}
          >
            <Activity size={16} />
            <span>System Status</span>
          </button>
        </div>

        {/* Operational Status Pill */}
        <div className="nav-status">
          <div className="status-badge">
            <div className="pulse-dot"></div>
            <span>BINANCE LIVE</span>
          </div>
        </div>
      </nav>

      {/* Main Viewport Content */}
      <main className="main-viewport">
        {activeTab === 'market' && <MarketOverview />}
        {activeTab === 'studio' && <PredictionStudio />}
        {activeTab === 'history' && <ForecastHistory />}
        {activeTab === 'models' && <ModelLab />}
        {activeTab === 'system' && <SystemStatusView />}
      </main>

      {/* Footer */}
      <footer style={{
        marginTop: 'auto',
        borderTop: '1px solid var(--border-color)',
        padding: '1.25rem 2rem',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: '1rem',
        fontSize: '0.8rem',
        color: 'var(--text-muted)'
      }}>
        <div>
          Binance Predict Value & Trend • Enterprise Crypto Market Forecasting Architecture
        </div>
        <div style={{ fontFamily: 'var(--font-mono)' }}>
          FastAPI Backend • React TypeScript Frontend • Walk-Forward Evaluation
        </div>
      </footer>
    </div>
  );
};
export default App;
