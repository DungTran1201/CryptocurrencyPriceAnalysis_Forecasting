import React, { useState, useEffect } from 'react';
import { RefreshCw, TrendingUp, TrendingDown, Layers, BarChart2 } from 'lucide-react';
import { api } from '../services/api';
import { SymbolInfo, MarketDataResponse } from '../types';
import { CandlestickChart } from '../components/CandlestickChart';

export const MarketOverview: React.FC = () => {
  const [symbols, setSymbols] = useState<SymbolInfo[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState<string>('BTCUSDT');
  const [timeframe, setTimeframe] = useState<string>('1h');
  const [marketData, setMarketData] = useState<MarketDataResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [syncing, setSyncing] = useState<boolean>(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);

  // Indicators toggle
  const [indicators, setIndicators] = useState({
    sma: true,
    ema: false,
    boll: true,
    rsi: true
  });

  const timeframes = ['1m', '5m', '15m', '1h', '4h', '1d'];

  const loadData = async () => {
    try {
      setLoading(true);
      const [syms, klines] = await Promise.all([
        api.getSymbols(),
        api.getKlines(selectedSymbol, timeframe, 180)
      ]);
      setSymbols(syms);
      setMarketData(klines);
    } catch (err: any) {
      console.error('Failed to load market data:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [selectedSymbol, timeframe]);

  const handleSync = async () => {
    try {
      setSyncing(true);
      setSyncMessage(null);
      const res = await api.syncMarket(selectedSymbol, timeframe, 30);
      setSyncMessage(res.message);
      // Reload candles
      const freshKlines = await api.getKlines(selectedSymbol, timeframe, 180);
      setMarketData(freshKlines);
    } catch (err: any) {
      setSyncMessage(`Sync failed: ${err.message}`);
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* 1. Ticker Cards Grid */}
      <div className="grid-4">
        {symbols.map((s) => {
          const isUp = s.change_24h >= 0;
          const isSelected = s.symbol === selectedSymbol;
          return (
            <div
              key={s.symbol}
              className={`card stat-card ${isSelected ? 'active' : ''}`}
              onClick={() => setSelectedSymbol(s.symbol)}
              id={`ticker-card-${s.symbol}`}
            >
              <div className="stat-header">
                <span className="symbol-name">{s.symbol}</span>
                <span className="asset-badge">{s.base_asset} / {s.quote_asset}</span>
              </div>
              <div className="price-main">${s.current_price.toLocaleString(undefined, { minimumFractionDigits: 2 })}</div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div className={`change-tag ${isUp ? 'up' : 'down'}`}>
                  {isUp ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
                  <span>{isUp ? '+' : ''}{s.change_24h.toFixed(2)}%</span>
                </div>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                  Vol: {s.volume_24h > 1000 ? `${(s.volume_24h / 1000).toFixed(1)}k` : s.volume_24h.toFixed(1)}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* 2. Main Chart Card with Toolbar */}
      <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        {/* Controls Bar */}
        <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: '1rem' }}>
          {/* Left: Symbol & Timeframe */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <BarChart2 size={18} color="var(--accent-cyan)" />
              <strong style={{ fontSize: '1.1rem' }}>{selectedSymbol}</strong>
            </div>

            {/* Timeframe Buttons */}
            <div style={{ display: 'flex', background: 'rgba(255, 255, 255, 0.04)', padding: '0.2rem', borderRadius: 'var(--radius-md)', gap: '0.2rem' }}>
              {timeframes.map((tf) => (
                <button
                  key={tf}
                  id={`tf-btn-${tf}`}
                  onClick={() => setTimeframe(tf)}
                  style={{
                    background: timeframe === tf ? 'var(--accent-cyan)' : 'transparent',
                    color: timeframe === tf ? '#07090e' : 'var(--text-secondary)',
                    border: 'none',
                    borderRadius: 'var(--radius-sm)',
                    padding: '0.3rem 0.65rem',
                    fontSize: '0.8rem',
                    fontWeight: 600,
                    cursor: 'pointer',
                    fontFamily: 'var(--font-mono)'
                  }}
                >
                  {tf}
                </button>
              ))}
            </div>
          </div>

          {/* Right: Technical Indicator Toggles & Sync */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', background: 'rgba(255,255,255,0.03)', padding: '0.3rem 0.6rem', borderRadius: 'var(--radius-md)' }}>
              <Layers size={15} color="var(--text-muted)" />
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.8rem', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={indicators.sma}
                  onChange={(e) => setIndicators({ ...indicators, sma: e.target.checked })}
                />
                <span style={{ color: '#f59e0b' }}>SMA</span>
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.8rem', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={indicators.boll}
                  onChange={(e) => setIndicators({ ...indicators, boll: e.target.checked })}
                />
                <span style={{ color: '#00f2fe' }}>BOLL</span>
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.8rem', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={indicators.rsi}
                  onChange={(e) => setIndicators({ ...indicators, rsi: e.target.checked })}
                />
                <span style={{ color: '#ec4899' }}>RSI</span>
              </label>
            </div>

            <button
              id="sync-market-btn"
              className="btn btn-secondary"
              onClick={handleSync}
              disabled={syncing}
              style={{ fontSize: '0.8rem', padding: '0.45rem 0.9rem' }}
            >
              <RefreshCw size={14} className={syncing ? 'spinner' : ''} />
              <span>{syncing ? 'Syncing...' : 'Sync Binance'}</span>
            </button>
          </div>
        </div>

        {/* Sync notification message */}
        {syncMessage && (
          <div style={{
            padding: '0.6rem 1rem',
            borderRadius: 'var(--radius-md)',
            background: syncMessage.includes('failed') ? 'rgba(244, 63, 94, 0.15)' : 'rgba(16, 185, 129, 0.15)',
            color: syncMessage.includes('failed') ? 'var(--accent-red)' : 'var(--accent-green)',
            fontSize: '0.85rem'
          }}>
            {syncMessage}
          </div>
        )}

        {/* Candlestick & Indicator Chart */}
        {loading ? (
          <div className="loading-box">
            <div className="spinner"></div>
            <span>Loading {selectedSymbol} market candles...</span>
          </div>
        ) : marketData && marketData.candles.length > 0 ? (
          <CandlestickChart
            candles={marketData.candles}
            indicators={marketData.indicators}
            visibleIndicators={indicators}
          />
        ) : (
          <div className="loading-box">
            <p>No candle history found. Click "Sync Binance" to seed market data.</p>
          </div>
        )}
      </div>
    </div>
  );
};
