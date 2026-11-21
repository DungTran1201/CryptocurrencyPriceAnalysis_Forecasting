import React from 'react';
import { Radio, RefreshCw } from 'lucide-react';
import { SymbolInfo } from '../../types';
import { formatCurrency, formatPercent, formatVolume, formatNumber } from '../../utils/formatters';

interface MarketHeaderProps {
  symbols: SymbolInfo[];
  selectedSymbol: string;
  onSelectSymbol: (symbol: string) => void;
  timeframe: string;
  onSelectTimeframe: (tf: string) => void;
  livePrice?: number | null;
  tickerInfo?: SymbolInfo | null;
  wsState: 'CONNECTING' | 'CONNECTED' | 'RECONNECTING' | 'DISCONNECTED';
  crosshairBar?: { open: number; high: number; low: number; close: number; volume: number; time: string } | null;
  activeOverlays: {
    sma: boolean;
    ema: boolean;
    boll: boolean;
    vwap: boolean;
  };
  onToggleOverlay: (key: 'sma' | 'ema' | 'boll' | 'vwap') => void;
  onQuickSync: () => void;
  syncing: boolean;
}

const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d'];

export const MarketHeader: React.FC<MarketHeaderProps> = ({
  symbols,
  selectedSymbol,
  onSelectSymbol,
  timeframe,
  onSelectTimeframe,
  livePrice,
  tickerInfo,
  wsState,
  crosshairBar,
  activeOverlays,
  onToggleOverlay,
  onQuickSync,
  syncing
}) => {
  const currentPrice = livePrice || tickerInfo?.current_price;
  const change24h = tickerInfo?.change_24h || 0;
  const isUp = change24h >= 0;

  return (
    <div
      style={{
        background: '#12161A',
        borderBottom: '1px solid #222B35',
        padding: '12px 18px',
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '14px'
      }}
    >
      {/* Left: Symbol & Price Ticker */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        {/* Symbol Select */}
        <select
          value={selectedSymbol}
          onChange={(e) => onSelectSymbol(e.target.value)}
          style={{
            background: '#161E27',
            border: '1px solid #222B35',
            color: '#EAECEF',
            borderRadius: '4px',
            padding: '6px 12px',
            fontSize: '14px',
            fontWeight: 700,
            cursor: 'pointer',
            fontFamily: 'monospace',
            outline: 'none'
          }}
        >
          {symbols.length > 0 ? (
            symbols.map((s) => (
              <option key={s.symbol} value={s.symbol}>
                {s.symbol} ({s.base_asset}/{s.quote_asset})
              </option>
            ))
          ) : (
            <>
              <option value="BTCUSDT">BTCUSDT</option>
              <option value="ETHUSDT">ETHUSDT</option>
              <option value="SOLUSDT">SOLUSDT</option>
              <option value="BNBUSDT">BNBUSDT</option>
            </>
          )}
        </select>

        {/* Real-Time Price */}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
          <span
            style={{
              fontSize: '22px',
              fontWeight: 800,
              fontFamily: 'monospace',
              color: isUp ? '#0ECB81' : '#F6465D',
              transition: 'color 0.2s ease'
            }}
          >
            {currentPrice ? formatCurrency(currentPrice) : '—'}
          </span>
          <span
            style={{
              fontSize: '12px',
              fontFamily: 'monospace',
              fontWeight: 700,
              color: isUp ? '#0ECB81' : '#F6465D'
            }}
          >
            {formatPercent(change24h)}
          </span>
        </div>

        {/* 24h Summary */}
        <div style={{ display: 'flex', gap: '14px', fontSize: '11px', color: '#848E9C', borderLeft: '1px solid #222B35', paddingLeft: '14px' }}>
          <div>
            <span style={{ color: '#5E6673' }}>24h High: </span>
            <span style={{ color: '#EAECEF', fontFamily: 'monospace' }}>
              {tickerInfo?.high_24h ? formatCurrency(tickerInfo.high_24h) : '—'}
            </span>
          </div>
          <div>
            <span style={{ color: '#5E6673' }}>24h Low: </span>
            <span style={{ color: '#EAECEF', fontFamily: 'monospace' }}>
              {tickerInfo?.low_24h ? formatCurrency(tickerInfo.low_24h) : '—'}
            </span>
          </div>
          <div>
            <span style={{ color: '#5E6673' }}>24h Vol: </span>
            <span style={{ color: '#EAECEF', fontFamily: 'monospace' }}>
              {tickerInfo?.volume_24h ? formatVolume(tickerInfo.volume_24h) : '—'}
            </span>
          </div>
        </div>
      </div>

      {/* Middle: Crosshair Hover Bar Details (if user hovering chart) */}
      {crosshairBar ? (
        <div
          style={{
            display: 'flex',
            gap: '10px',
            fontSize: '11px',
            fontFamily: 'monospace',
            background: '#161E27',
            padding: '4px 10px',
            borderRadius: '4px',
            border: '1px solid #222B35'
          }}
        >
          <span style={{ color: '#848E9C' }}>O: <b style={{ color: '#EAECEF' }}>{crosshairBar.open.toFixed(2)}</b></span>
          <span style={{ color: '#848E9C' }}>H: <b style={{ color: '#0ECB81' }}>{crosshairBar.high.toFixed(2)}</b></span>
          <span style={{ color: '#848E9C' }}>L: <b style={{ color: '#F6465D' }}>{crosshairBar.low.toFixed(2)}</b></span>
          <span style={{ color: '#848E9C' }}>C: <b style={{ color: crosshairBar.close >= crosshairBar.open ? '#0ECB81' : '#F6465D' }}>{crosshairBar.close.toFixed(2)}</b></span>
          <span style={{ color: '#848E9C' }}>V: <b style={{ color: '#FCD535' }}>{formatNumber(crosshairBar.volume, 1)}</b></span>
        </div>
      ) : null}

      {/* Right: Timeframe Pills & Indicators Toolbar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        {/* Timeframe Selector */}
        <div style={{ display: 'flex', background: '#161E27', borderRadius: '4px', padding: '2px', border: '1px solid #222B35' }}>
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              onClick={() => onSelectTimeframe(tf)}
              style={{
                background: timeframe === tf ? '#222B35' : 'none',
                border: 'none',
                borderRadius: '3px',
                color: timeframe === tf ? '#FCD535' : '#848E9C',
                fontSize: '11px',
                fontFamily: 'monospace',
                fontWeight: 700,
                padding: '4px 8px',
                cursor: 'pointer'
              }}
            >
              {tf}
            </button>
          ))}
        </div>

        {/* Overlay Indicator Toggles */}
        <div style={{ display: 'flex', gap: '4px', background: '#161E27', padding: '2px', borderRadius: '4px', border: '1px solid #222B35' }}>
          <button
            onClick={() => onToggleOverlay('sma')}
            style={{
              background: activeOverlays.sma ? 'rgba(252, 213, 53, 0.2)' : 'none',
              border: `1px solid ${activeOverlays.sma ? '#FCD535' : 'transparent'}`,
              borderRadius: '3px',
              color: activeOverlays.sma ? '#FCD535' : '#848E9C',
              fontSize: '10px',
              fontFamily: 'monospace',
              fontWeight: 700,
              padding: '3px 6px',
              cursor: 'pointer'
            }}
          >
            SMA
          </button>
          <button
            onClick={() => onToggleOverlay('ema')}
            style={{
              background: activeOverlays.ema ? 'rgba(0, 216, 255, 0.2)' : 'none',
              border: `1px solid ${activeOverlays.ema ? '#00D8FF' : 'transparent'}`,
              borderRadius: '3px',
              color: activeOverlays.ema ? '#00D8FF' : '#848E9C',
              fontSize: '10px',
              fontFamily: 'monospace',
              fontWeight: 700,
              padding: '3px 6px',
              cursor: 'pointer'
            }}
          >
            EMA
          </button>
          <button
            onClick={() => onToggleOverlay('boll')}
            style={{
              background: activeOverlays.boll ? 'rgba(234, 236, 239, 0.2)' : 'none',
              border: `1px solid ${activeOverlays.boll ? '#EAECEF' : 'transparent'}`,
              borderRadius: '3px',
              color: activeOverlays.boll ? '#EAECEF' : '#848E9C',
              fontSize: '10px',
              fontFamily: 'monospace',
              fontWeight: 700,
              padding: '3px 6px',
              cursor: 'pointer'
            }}
          >
            BOLL
          </button>
          <button
            onClick={() => onToggleOverlay('vwap')}
            style={{
              background: activeOverlays.vwap ? 'rgba(168, 85, 247, 0.2)' : 'none',
              border: `1px solid ${activeOverlays.vwap ? '#A855F7' : 'transparent'}`,
              borderRadius: '3px',
              color: activeOverlays.vwap ? '#A855F7' : '#848E9C',
              fontSize: '10px',
              fontFamily: 'monospace',
              fontWeight: 700,
              padding: '3px 6px',
              cursor: 'pointer'
            }}
          >
            VWAP
          </button>
        </div>

        {/* WebSocket Status Indicator */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '5px',
            fontSize: '11px',
            fontFamily: 'monospace',
            color: wsState === 'CONNECTED' ? '#0ECB81' : '#F6465D',
            background: wsState === 'CONNECTED' ? 'rgba(14, 203, 129, 0.1)' : 'rgba(246, 70, 93, 0.1)',
            padding: '4px 8px',
            borderRadius: '4px',
            border: `1px solid ${wsState === 'CONNECTED' ? 'rgba(14, 203, 129, 0.3)' : 'rgba(246, 70, 93, 0.3)'}`
          }}
        >
          <Radio size={12} className={wsState === 'CONNECTED' ? 'pulse' : ''} />
          <span>{wsState === 'CONNECTED' ? 'LIVE WS' : wsState}</span>
        </div>

        {/* Quick Sync Button */}
        <button
          onClick={onQuickSync}
          disabled={syncing}
          style={{
            padding: '6px 10px',
            background: '#161E27',
            border: '1px solid #222B35',
            borderRadius: '4px',
            color: '#EAECEF',
            fontSize: '11px',
            cursor: syncing ? 'not-allowed' : 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '5px'
          }}
        >
          <RefreshCw size={12} className={syncing ? 'spin' : ''} />
          <span>{syncing ? 'Syncing...' : 'Sync'}</span>
        </button>
      </div>
    </div>
  );
};
