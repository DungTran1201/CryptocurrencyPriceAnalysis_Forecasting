import React, { useState, useEffect, useRef } from 'react';
import {
  RefreshCw,
  TrendingUp,
  TrendingDown,
  Layers,
  BarChart2,
  Clock,
  AlertCircle,
  Database,
  Radio,
  Activity
} from 'lucide-react';
import { api } from '../services/api';
import { SymbolInfo, MarketDataResponse, StreamingStatusResponse } from '../types';
import { CandlestickChart } from '../components/CandlestickChart';
import { useMarketStream } from '../hooks/useMarketStream';
import {
  formatCurrency,
  formatPercent,
  formatVolume,
  formatNumber,
  formatRelativeTime
} from '../utils/formatters';

export const MarketOverview: React.FC = () => {
  const [symbols, setSymbols] = useState<SymbolInfo[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState<string>('BTCUSDT');
  const [timeframe, setTimeframe] = useState<string>('1m');
  const [marketData, setMarketData] = useState<MarketDataResponse | null>(null);
  const [streamingMeta, setStreamingMeta] = useState<StreamingStatusResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [loadingError, setLoadingError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState<boolean>(false);
  const [syncMessage, setSyncMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const [indicators, setIndicators] = useState({
    sma: true,
    ema: false,
    boll: true,
    rsi: true
  });

  const { wsState, liveSymbols, recentFeed, lastMessageAt } = useMarketStream(true);
  const timeframes = ['1m', '5m', '15m', '1h', '4h', '1d'];
  const activeReqRef = useRef<number>(0);

  const loadData = async () => {
    const reqId = ++activeReqRef.current;
    try {
      setLoading(true);
      setLoadingError(null);

      const [syms, klines, streamStat] = await Promise.all([
        api.getSymbols(),
        api.getKlines(selectedSymbol, timeframe, 200),
        api.getStreamingStatus().catch(() => null)
      ]);

      if (reqId === activeReqRef.current) {
        setSymbols(syms);
        setMarketData(klines);
        if (streamStat) setStreamingMeta(streamStat);
      }
    } catch (err: any) {
      if (reqId === activeReqRef.current) {
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

  // Periodically coalesce candle refresh from DB when closed 1m bar updates via WS
  const liveSelected = liveSymbols[selectedSymbol];
  const lastClosedOpenTime = liveSelected?.kline_1m?.is_closed ? liveSelected.kline_1m.open_time : null;
  useEffect(() => {
    if (!lastClosedOpenTime || timeframe !== '1m') return;
    api.getKlines(selectedSymbol, timeframe, 200)
      .then((res) => setMarketData(res))
      .catch(() => {});
  }, [lastClosedOpenTime, selectedSymbol, timeframe]);

  const handleSync = async () => {
    try {
      setSyncing(true);
      setSyncMessage(null);
      const res = await api.syncMarket(selectedSymbol, timeframe, 7);
      setSyncMessage({ type: 'success', text: res.message });

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
  const incSnap =
    liveSelected?.analytics ||
    streamingMeta?.incremental_symbols?.find((s) => s.symbol === selectedSymbol);

  return (
    <div className="view-container">
      {/* Header */}
      <div className="view-header">
        <div>
          <div className="view-tag">REAL-TIME STREAMING & COALESCED MARKET MONITOR</div>
          <h1 className="view-title">Live Market Monitor</h1>
          <p className="view-subtitle">
            Binance WebSocket → NATS JetStream → Incremental O(1) Analytics → Coalesced Gateway ({wsState}).
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.6rem', alignItems: 'center', flexWrap: 'wrap' }}>
          <span
            className={`status-badge ${
              wsState === 'CONNECTED' ? 'badge-success' : wsState === 'RECONNECTING' ? 'badge-warning' : 'badge-danger'
            }`}
          >
            <span className="pulse-dot"></span>
            <Radio size={12} />
            <span>WS {wsState}</span>
          </span>
          {lastMessageAt && (
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
              Tick: {lastMessageAt.slice(11, 19)} UTC
            </span>
          )}
        </div>
      </div>

      {/* 1. Market Ticker Cards Grid (Live WS overlaid truthfully onto stored 24h context) */}
      <div className="grid-4-cols" style={{ marginBottom: '1.25rem' }}>
        {symbols.map((s) => {
          const isSelected = s.symbol === selectedSymbol;
          const wsTick = liveSymbols[s.symbol];
          const displayPrice = wsTick?.live_price ?? s.current_price;
          const hasData = displayPrice !== null && displayPrice !== undefined;
          const isLive = wsTick?.live_price !== undefined && wsTick?.live_price !== null;
          const isUp = (s.change_24h ?? 0) >= 0;

          return (
            <div
              key={s.symbol}
              className={`kpi-card ${isSelected ? 'active' : ''}`}
              style={{
                cursor: 'pointer',
                borderColor: isSelected ? 'var(--accent-yellow)' : undefined
              }}
              onClick={() => setSelectedSymbol(s.symbol)}
              id={`ticker-card-${s.symbol}`}
              tabIndex={0}
              role="button"
              aria-label={`Select ${s.symbol} market data`}
            >
              <div className="kpi-header">
                <span style={{ fontWeight: 700, color: '#fff' }}>{s.symbol}</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                  {isLive ? (
                    <span className="badge badge-success">LIVE WS</span>
                  ) : s.data_status === 'UNAVAILABLE' ? (
                    <span className="badge badge-neutral">No data</span>
                  ) : s.data_status === 'PARTIAL' ? (
                    <span className="badge badge-warning">Partial ({s.candle_count_24h}h)</span>
                  ) : s.data_status === 'STALE' ? (
                    <span className="badge badge-warning">Stale</span>
                  ) : (
                    <span className="badge badge-success">Synced</span>
                  )}
                </div>
              </div>

              <div className="kpi-value" style={{ color: hasData ? '#fff' : 'var(--text-muted)' }}>
                {formatCurrency(displayPrice)}
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '0.35rem' }}>
                {s.change_24h !== null && s.change_24h !== undefined ? (
                  <div className={`change-tag ${isUp ? 'up' : 'down'}`}>
                    {isUp ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
                    <span>{formatPercent(s.change_24h)}</span>
                  </div>
                ) : (
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                    {isLive ? 'Stream active' : 'Pending sync'}
                  </span>
                )}

                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                  {wsTick?.live_trades_count ? `${wsTick.live_trades_count} ticks` : `Vol: ${formatVolume(s.volume_24h)}`}
                </span>
              </div>

              <div className="kpi-subtext" style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', marginTop: '0.35rem' }}>
                <Clock size={11} />
                <span>{wsTick?.live_trade_time ? `Live ${wsTick.live_trade_time.slice(11, 19)} UTC` : formatRelativeTime(s.last_synced_at)}</span>
              </div>
            </div>
          );
        })}
      </div>

      {/* 2. Incremental Live Analytics Strip */}
      {incSnap && (
        <div className="panel" style={{ marginBottom: '1.25rem' }}>
          <div className="panel-header">
            <div className="panel-title">
              <Activity size={16} color="var(--accent-cyan)" />
              <span>Incremental Rolling Analytics State ({selectedSymbol})</span>
            </div>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
              O(1) State • {incSnap.bar_count} closed bars • VWAP {formatCurrency(liveSelected?.live_vwap ?? incSnap.vwap)}
            </span>
          </div>
          <div className="grid-4-cols">
            <div className="mini-card">
              <div className="mini-card-label">RSI (14)</div>
              <div className="mini-card-value">{incSnap.rsi_14 != null ? formatNumber(incSnap.rsi_14, 2) : 'Warming up'}</div>
            </div>
            <div className="mini-card">
              <div className="mini-card-label">ATR (14)</div>
              <div className="mini-card-value">{incSnap.atr_14 != null ? formatNumber(incSnap.atr_14, 4) : 'Warming up'}</div>
            </div>
            <div className="mini-card">
              <div className="mini-card-label">VaR 95% / CVaR 95%</div>
              <div className="mini-card-value" style={{ fontSize: '0.95rem' }}>
                {incSnap.var_95_pct != null
                  ? `${incSnap.var_95_pct.toFixed(2)}% / ${incSnap.cvar_95_pct?.toFixed(2) ?? '—'}%`
                  : 'Need 20+ bars'}
              </div>
            </div>
            <div className="mini-card">
              <div className="mini-card-label">Max Drawdown</div>
              <div className="mini-card-value" style={{ color: incSnap.max_drawdown_pct < -2 ? 'var(--semantic-red)' : undefined }}>
                {incSnap.max_drawdown_pct.toFixed(2)}%
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 3. Main Candlestick Chart + Coalesced Stream Tape */}
      <div className="grid-3-cols-uneven">
        <div className="panel" style={{ gridColumn: 'span 2' }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: '0.75rem', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '0.9rem', marginBottom: '1rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
              <BarChart2 size={18} color="var(--accent-yellow)" />
              <strong style={{ fontSize: '1.1rem' }}>{selectedSymbol}</strong>
              <span className="badge badge-neutral">{timeframe.toUpperCase()}</span>
              <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                {marketData ? `${marketData.count} bars` : '—'}
              </span>
              {currentSymbolInfo && currentSymbolInfo.high_24h != null && currentSymbolInfo.low_24h != null && (
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                  24h H/L: {formatCurrency(currentSymbolInfo.high_24h)} / {formatCurrency(currentSymbolInfo.low_24h)}
                </span>
              )}
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
              <div className="tab-pill-group">
                {timeframes.map((tf) => (
                  <button
                    key={tf}
                    id={`tf-btn-${tf}`}
                    className={`tab-pill ${timeframe === tf ? 'active' : ''}`}
                    style={{ padding: '0.3rem 0.6rem', fontSize: '0.75rem' }}
                    onClick={() => setTimeframe(tf)}
                  >
                    {tf}
                  </button>
                ))}
              </div>

              <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', fontSize: '0.75rem' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.2rem', cursor: 'pointer' }}>
                  <input type="checkbox" checked={indicators.sma} onChange={(e) => setIndicators({ ...indicators, sma: e.target.checked })} />
                  <span>SMA</span>
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.2rem', cursor: 'pointer' }}>
                  <input type="checkbox" checked={indicators.ema} onChange={(e) => setIndicators({ ...indicators, ema: e.target.checked })} />
                  <span>EMA</span>
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.2rem', cursor: 'pointer' }}>
                  <input type="checkbox" checked={indicators.boll} onChange={(e) => setIndicators({ ...indicators, boll: e.target.checked })} />
                  <span>BOLL</span>
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: '0.2rem', cursor: 'pointer' }}>
                  <input type="checkbox" checked={indicators.rsi} onChange={(e) => setIndicators({ ...indicators, rsi: e.target.checked })} />
                  <span>RSI</span>
                </label>
              </div>

              <button id="sync-market-btn" className="btn btn-primary btn-sm" onClick={handleSync} disabled={syncing}>
                <RefreshCw size={13} className={syncing ? 'spin' : ''} />
                <span>{syncing ? 'Syncing...' : 'Sync REST'}</span>
              </button>
            </div>
          </div>

          {syncMessage && (
            <div className={`alert-banner ${syncMessage.type === 'error' ? 'error' : 'success'}`} style={{ marginBottom: '0.9rem' }}>
              <AlertCircle size={15} />
              <span>{syncMessage.text}</span>
            </div>
          )}

          {loadingError && (
            <div className="alert-banner error" style={{ marginBottom: '0.9rem', justifyContent: 'space-between' }}>
              <span>{loadingError}</span>
              <button className="btn btn-secondary btn-sm" onClick={loadData}>Retry</button>
            </div>
          )}

          {loading ? (
            <div className="loading-state" style={{ minHeight: '400px' }}>
              <RefreshCw size={24} className="spin" />
              <span>Loading {selectedSymbol} ({timeframe}) candles...</span>
            </div>
          ) : marketData && marketData.candles.length > 0 ? (
            <CandlestickChart
              candles={marketData.candles}
              indicators={marketData.indicators}
              visibleIndicators={indicators}
            />
          ) : (
            <div className="empty-state-container">
              <Database size={36} className="empty-state-icon" />
              <div className="empty-state-title">No Stored Candles for {selectedSymbol} ({timeframe})</div>
              <div className="empty-state-message">
                Click Sync REST to backfill historical candles from Binance Vision API, or wait for closed 1m stream bars.
              </div>
              <button className="btn btn-primary btn-sm" onClick={handleSync} disabled={syncing}>
                <RefreshCw size={14} className={syncing ? 'spin' : ''} />
                <span>{syncing ? 'Syncing...' : `Sync ${selectedSymbol}`}</span>
              </button>
            </div>
          )}
        </div>

        {/* Bounded Live Stream Feed */}
        <div className="panel">
          <div className="panel-header">
            <div className="panel-title">
              <Layers size={16} color="var(--accent-cyan)" />
              <span>Coalesced Stream Feed</span>
            </div>
            <span className="badge badge-neutral">Max {recentFeed.length}/60</span>
          </div>
          {recentFeed.length === 0 ? (
            <div className="empty-state-container" style={{ padding: '2rem 1rem' }}>
              <Radio size={26} className="empty-state-icon" />
              <div className="empty-state-title">Awaiting Stream Ticks</div>
              <div className="empty-state-message">
                Connects via NATS JetStream → /api/v1/ws/market. Ensure NATS is running for live ticks.
              </div>
            </div>
          ) : (
            <div className="table-wrapper" style={{ maxHeight: '420px', overflowY: 'auto' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th className="num">Price</th>
                    <th className="num">VWAP</th>
                    <th>UTC</th>
                  </tr>
                </thead>
                <tbody>
                  {recentFeed.slice(0, 20).map((item, idx) => (
                    <tr key={`${item.id}-${idx}`}>
                      <td><strong>{item.symbol}</strong></td>
                      <td className="num">{formatCurrency(item.price)}</td>
                      <td className="num" style={{ color: 'var(--text-muted)' }}>{formatCurrency(item.vwap)}</td>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                        {item.time.slice(11, 19)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
