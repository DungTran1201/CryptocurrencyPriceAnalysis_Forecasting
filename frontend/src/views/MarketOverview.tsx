import React, { useState, useEffect, useRef } from 'react';
import {
  RefreshCw,
  TrendingUp,
  TrendingDown,
  Layers,
  BarChart2,
  Clock,
  AlertCircle,
  Database
} from 'lucide-react';
import { api } from '../services/api';
import { SymbolInfo, MarketDataResponse } from '../types';
import { CandlestickChart } from '../components/CandlestickChart';
import {
  formatCurrency,
  formatPercent,
  formatVolume,
  formatRelativeTime
} from '../utils/formatters';

export const MarketOverview: React.FC = () => {
  const [symbols, setSymbols] = useState<SymbolInfo[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState<string>('BTCUSDT');
  const [timeframe, setTimeframe] = useState<string>('1h');
  const [marketData, setMarketData] = useState<MarketDataResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [loadingError, setLoadingError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState<boolean>(false);
  const [syncMessage, setSyncMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // Indicators toggle
  const [indicators, setIndicators] = useState({
    sma: true,
    ema: false,
    boll: true,
    rsi: true
  });

  const timeframes = ['1m', '5m', '15m', '1h', '4h', '1d'];
  const activeReqRef = useRef<number>(0);

  const loadData = async () => {
    const reqId = ++activeReqRef.current;
    try {
      setLoading(true);
      setLoadingError(null);

      const [syms, klines] = await Promise.all([
        api.getSymbols(),
        api.getKlines(selectedSymbol, timeframe, 200)
      ]);

      if (reqId === activeReqRef.current) {
        setSymbols(syms);
        setMarketData(klines);
      }
    } catch (err: any) {
      if (reqId === activeReqRef.current) {
        console.error('Failed to load market data:', err);
        setLoadingError(err.message || 'Unable to connect to market service.');
      }
    } finally {
      if (reqId === activeReqRef.current) {
        setLoading(false);
      }
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
      setSyncMessage({ type: 'success', text: res.message });

      // Reload candles and symbols
      const [freshSyms, freshKlines] = await Promise.all([
        api.getSymbols(),
        api.getKlines(selectedSymbol, timeframe, 200)
      ]);
      setSymbols(freshSyms);
      setMarketData(freshKlines);
    } catch (err: any) {
      setSyncMessage({ type: 'error', text: `Sync failed: ${err.message}` });
    } finally {
      setSyncing(false);
    }
  };

  const currentSymbolInfo = symbols.find((s) => s.symbol === selectedSymbol);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', width: '100%' }}>
      {/* 1. Market Ticker Cards Grid */}
      <div className="grid-4">
        {symbols.map((s) => {
          const isSelected = s.symbol === selectedSymbol;
          const hasData = s.current_price !== null && s.current_price !== undefined;
          const isUp = (s.change_24h ?? 0) >= 0;

          return (
            <div
              key={s.symbol}
              className={`card stat-card ${isSelected ? 'active' : ''}`}
              onClick={() => setSelectedSymbol(s.symbol)}
              id={`ticker-card-${s.symbol}`}
              tabIndex={0}
              role="button"
              aria-label={`Select ${s.symbol} market data`}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  setSelectedSymbol(s.symbol);
                }
              }}
            >
              <div className="stat-header">
                <span className="symbol-name">{s.symbol}</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                  <span className="asset-badge">{s.base_asset}/{s.quote_asset}</span>
                  {s.data_status === 'UNAVAILABLE' && (
                    <span className="badge badge-neutral" style={{ fontSize: '0.65rem', padding: '0.1rem 0.4rem' }}>
                      No data
                    </span>
                  )}
                  {s.data_status === 'PARTIAL' && (
                    <span className="badge badge-warning" style={{ fontSize: '0.65rem', padding: '0.1rem 0.4rem' }}>
                      Partial ({s.candle_count_24h}h)
                    </span>
                  )}
                  {s.data_status === 'SYNCHRONIZED' && (
                    <span className="badge badge-success" style={{ fontSize: '0.65rem', padding: '0.1rem 0.4rem' }}>
                      Synced
                    </span>
                  )}
                  {s.data_status === 'STALE' && (
                    <span className="badge badge-warning" style={{ fontSize: '0.65rem', padding: '0.1rem 0.4rem' }}>
                      Stale
                    </span>
                  )}
                </div>
              </div>

              {/* Price display - never show false zero */}
              <div className="price-main" style={{ color: hasData ? 'var(--text-primary)' : 'var(--text-muted)' }}>
                {formatCurrency(s.current_price)}
              </div>

              {/* 24h Change & Volume */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                {hasData && s.change_24h !== null && s.change_24h !== undefined ? (
                  <div className={`change-tag ${isUp ? 'up' : 'down'}`}>
                    {isUp ? <TrendingUp size={13} /> : <TrendingDown size={13} />}
                    <span>{formatPercent(s.change_24h)}</span>
                  </div>
                ) : (
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                    {s.data_status === 'UNAVAILABLE' ? 'Pending sync' : '—'}
                  </span>
                )}

                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                  Vol: {formatVolume(s.volume_24h)}
                </span>
              </div>

              {/* Sync Timestamp Footer */}
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.3rem',
                fontSize: '0.7rem',
                color: 'var(--text-muted)',
                marginTop: '0.2rem',
                borderTop: '1px solid rgba(255, 255, 255, 0.04)',
                paddingTop: '0.35rem'
              }}>
                <Clock size={11} />
                <span>{formatRelativeTime(s.last_synced_at)}</span>
              </div>
            </div>
          );
        })}
      </div>

      {/* 2. Main Market Analytics Panel */}
      <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem', padding: '1.5rem' }}>
        {/* Top Controls & Asset Overview Bar */}
        <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: '1rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '1rem' }}>
          {/* Left: Selected Symbol Info & Quick Stats */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '1.25rem', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
              <div style={{
                width: '32px',
                height: '32px',
                borderRadius: 'var(--radius-md)',
                background: 'rgba(0, 242, 254, 0.1)',
                border: '1px solid rgba(0, 242, 254, 0.3)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center'
              }}>
                <BarChart2 size={18} color="var(--accent-cyan)" />
              </div>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <strong style={{ fontSize: '1.2rem', letterSpacing: '-0.01em' }}>{selectedSymbol}</strong>
                  <span className="badge badge-neutral" style={{ fontSize: '0.7rem' }}>
                    {timeframe.toUpperCase()}
                  </span>
                </div>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                  {marketData ? `${marketData.count} candles loaded` : 'Connecting...'}
                </div>
              </div>
            </div>

            {/* Quick Metrics Strip */}
            {currentSymbolInfo && currentSymbolInfo.current_price !== null && (
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: '1.25rem',
                background: 'rgba(255, 255, 255, 0.03)',
                padding: '0.4rem 0.85rem',
                borderRadius: 'var(--radius-md)',
                fontSize: '0.82rem',
                fontFamily: 'var(--font-mono)'
              }}>
                <div>
                  <span style={{ color: 'var(--text-muted)', marginRight: '0.4rem' }}>Price:</span>
                  <strong style={{ color: '#fff' }}>{formatCurrency(currentSymbolInfo.current_price)}</strong>
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)', marginRight: '0.4rem' }}>24h:</span>
                  <strong style={{ color: (currentSymbolInfo.change_24h ?? 0) >= 0 ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                    {formatPercent(currentSymbolInfo.change_24h)}
                  </strong>
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)', marginRight: '0.4rem' }}>High:</span>
                  <span>{formatCurrency(currentSymbolInfo.high_24h)}</span>
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)', marginRight: '0.4rem' }}>Low:</span>
                  <span>{formatCurrency(currentSymbolInfo.low_24h)}</span>
                </div>
              </div>
            )}
          </div>

          {/* Right: Timeframe Switcher, Indicators & Sync Button */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            {/* Timeframe selector */}
            <div style={{
              display: 'flex',
              background: 'rgba(255, 255, 255, 0.04)',
              padding: '0.2rem',
              borderRadius: 'var(--radius-md)',
              border: '1px solid var(--border-color)',
              gap: '0.15rem'
            }}>
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
                    padding: '0.35rem 0.75rem',
                    fontSize: '0.8rem',
                    fontWeight: 700,
                    cursor: 'pointer',
                    fontFamily: 'var(--font-mono)',
                    transition: 'all 0.15s ease'
                  }}
                >
                  {tf}
                </button>
              ))}
            </div>

            {/* Technical indicator toggles */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.6rem',
              background: 'rgba(255, 255, 255, 0.03)',
              padding: '0.35rem 0.75rem',
              borderRadius: 'var(--radius-md)',
              border: '1px solid var(--border-color)'
            }}>
              <Layers size={14} color="var(--text-muted)" />
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.8rem', cursor: 'pointer', userSelect: 'none' }}>
                <input
                  type="checkbox"
                  checked={indicators.sma}
                  onChange={(e) => setIndicators({ ...indicators, sma: e.target.checked })}
                />
                <span style={{ color: '#f59e0b', fontWeight: 600 }}>SMA</span>
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.8rem', cursor: 'pointer', userSelect: 'none' }}>
                <input
                  type="checkbox"
                  checked={indicators.ema}
                  onChange={(e) => setIndicators({ ...indicators, ema: e.target.checked })}
                />
                <span style={{ color: '#ec4899', fontWeight: 600 }}>EMA</span>
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.8rem', cursor: 'pointer', userSelect: 'none' }}>
                <input
                  type="checkbox"
                  checked={indicators.boll}
                  onChange={(e) => setIndicators({ ...indicators, boll: e.target.checked })}
                />
                <span style={{ color: 'var(--accent-cyan)', fontWeight: 600 }}>BOLL</span>
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.8rem', cursor: 'pointer', userSelect: 'none' }}>
                <input
                  type="checkbox"
                  checked={indicators.rsi}
                  onChange={(e) => setIndicators({ ...indicators, rsi: e.target.checked })}
                />
                <span style={{ color: '#10b981', fontWeight: 600 }}>RSI</span>
              </label>
            </div>

            {/* Sync Binance Action Button */}
            <button
              id="sync-market-btn"
              className="btn btn-secondary"
              onClick={handleSync}
              disabled={syncing}
              style={{ fontSize: '0.82rem', padding: '0.45rem 0.9rem' }}
            >
              <RefreshCw size={14} className={syncing ? 'spinner' : ''} />
              <span>{syncing ? 'Syncing...' : 'Sync Binance'}</span>
            </button>
          </div>
        </div>

        {/* Sync notification message */}
        {syncMessage && (
          <div style={{
            padding: '0.75rem 1rem',
            borderRadius: 'var(--radius-md)',
            background: syncMessage.type === 'error' ? 'rgba(244, 63, 94, 0.12)' : 'rgba(16, 185, 129, 0.12)',
            color: syncMessage.type === 'error' ? 'var(--accent-red)' : 'var(--accent-green)',
            border: `1px solid ${syncMessage.type === 'error' ? 'rgba(244, 63, 94, 0.3)' : 'rgba(16, 185, 129, 0.3)'}`,
            fontSize: '0.85rem',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem'
          }}>
            {syncMessage.type === 'error' ? <AlertCircle size={16} /> : <RefreshCw size={16} />}
            <span>{syncMessage.text}</span>
          </div>
        )}

        {/* Error notification */}
        {loadingError && (
          <div style={{
            padding: '1rem',
            borderRadius: 'var(--radius-md)',
            background: 'rgba(244, 63, 94, 0.12)',
            border: '1px solid rgba(244, 63, 94, 0.3)',
            color: 'var(--accent-red)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <AlertCircle size={18} />
              <span>{loadingError}</span>
            </div>
            <button className="btn btn-secondary" onClick={loadData} style={{ padding: '0.3rem 0.8rem', fontSize: '0.8rem' }}>
              Retry
            </button>
          </div>
        )}

        {/* Candlestick & Technical Indicators Visualization */}
        {loading ? (
          <div className="loading-box" style={{ minHeight: '440px' }}>
            <div className="spinner"></div>
            <span style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
              Loading {selectedSymbol} {timeframe} market candles & indicators...
            </span>
          </div>
        ) : marketData && marketData.candles.length > 0 ? (
          <CandlestickChart
            candles={marketData.candles}
            indicators={marketData.indicators}
            visibleIndicators={indicators}
          />
        ) : (
          <div className="loading-box" style={{
            minHeight: '420px',
            background: 'rgba(7, 10, 18, 0.4)',
            borderRadius: 'var(--radius-md)',
            border: '1px dashed var(--border-color)',
            textAlign: 'center',
            gap: '1rem'
          }}>
            <div style={{
              width: '56px',
              height: '56px',
              borderRadius: '50%',
              background: 'rgba(0, 242, 254, 0.08)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--accent-cyan)'
            }}>
              <Database size={28} />
            </div>
            <div>
              <h3 style={{ fontSize: '1.15rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.35rem' }}>
                No Candle History for {selectedSymbol} ({timeframe})
              </h3>
              <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', maxWidth: '460px', margin: '0 auto' }}>
                The database has 0 stored candlesticks for this pair and timeframe. Trigger market synchronization to pull raw exchange data and compute indicators.
              </p>
            </div>
            <button
              className="btn btn-primary"
              onClick={handleSync}
              disabled={syncing}
              style={{ marginTop: '0.5rem' }}
            >
              <RefreshCw size={15} className={syncing ? 'spinner' : ''} />
              <span>{syncing ? 'Synchronizing from Binance...' : `Sync ${selectedSymbol} from Binance`}</span>
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
