import React, { useState, useEffect } from 'react';
import { Sparkles, TrendingUp, TrendingDown, ShieldCheck, Zap, AlertCircle } from 'lucide-react';
import { api } from '../services/api';
import { ForecastRecord, SymbolInfo } from '../types';
import {
  formatCurrency,
  formatPercent,
  formatDateTime
} from '../utils/formatters';

export const PredictionStudio: React.FC = () => {
  const [symbols, setSymbols] = useState<SymbolInfo[]>([]);
  const [symbol, setSymbol] = useState<string>('BTCUSDT');
  const [timeframe, setTimeframe] = useState<string>('1h');
  const [horizon, setHorizon] = useState<number>(6);
  const [generating, setGenerating] = useState<boolean>(false);
  const [forecast, setForecast] = useState<ForecastRecord | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getSymbols().then(setSymbols).catch(() => {});
  }, []);

  const handleGenerate = async () => {
    try {
      setGenerating(true);
      setError(null);
      const res = await api.generateForecast(symbol, timeframe, horizon);
      setForecast(res);
    } catch (err: any) {
      setError(err.message || 'Failed to generate forecast.');
    } finally {
      setGenerating(false);
    }
  };

  const isUp = forecast?.predicted_direction === 'UP';
  const isDown = forecast?.predicted_direction === 'DOWN';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', maxWidth: '1200px', margin: '0 auto', width: '100%' }}>
      {/* Configuration Header Card */}
      <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem', padding: '1.5rem' }}>
        <div>
          <h2 style={{ fontSize: '1.3rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
            <Sparkles size={20} color="var(--accent-cyan)" />
            Prediction Studio
          </h2>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            Multi-horizon time-series machine learning inference with calibrated directional probability and empirical confidence bounds.
          </p>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '1rem', alignItems: 'flex-end' }}>
          <div className="form-group">
            <label className="form-label" htmlFor="pred-symbol-select">Asset Pair</label>
            <select
              id="pred-symbol-select"
              className="form-select"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
            >
              {(symbols.length > 0 ? symbols : [
                { symbol: 'BTCUSDT', base_asset: 'BTC', quote_asset: 'USDT' },
                { symbol: 'ETHUSDT', base_asset: 'ETH', quote_asset: 'USDT' },
                { symbol: 'SOLUSDT', base_asset: 'SOL', quote_asset: 'USDT' },
                { symbol: 'BNBUSDT', base_asset: 'BNB', quote_asset: 'USDT' }
              ]).map((s) => (
                <option key={s.symbol} value={s.symbol}>
                  {s.base_asset} / {s.quote_asset}
                </option>
              ))}
            </select>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="pred-timeframe-select">Candle Interval</label>
            <select
              id="pred-timeframe-select"
              className="form-select"
              value={timeframe}
              onChange={(e) => setTimeframe(e.target.value)}
            >
              <option value="1m">1 Minute</option>
              <option value="5m">5 Minutes</option>
              <option value="15m">15 Minutes</option>
              <option value="1h">1 Hour</option>
              <option value="4h">4 Hours</option>
              <option value="1d">1 Day</option>
            </select>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="pred-horizon-select">Forecast Horizon</label>
            <select
              id="pred-horizon-select"
              className="form-select"
              value={horizon}
              onChange={(e) => setHorizon(Number(e.target.value))}
            >
              <option value={1}>1 step ahead</option>
              <option value={3}>3 steps ahead</option>
              <option value={6}>6 steps ahead</option>
              <option value={12}>12 steps ahead</option>
              <option value={24}>24 steps ahead</option>
            </select>
          </div>

          <button
            id="generate-forecast-btn"
            className="btn btn-primary"
            onClick={handleGenerate}
            disabled={generating}
            style={{ height: '42px' }}
          >
            <Zap size={16} />
            <span>{generating ? 'Running Inference...' : 'Generate Prediction'}</span>
          </button>
        </div>

        {error && (
          <div style={{
            padding: '0.85rem 1rem',
            background: 'rgba(244, 63, 94, 0.12)',
            border: '1px solid rgba(244, 63, 94, 0.3)',
            color: 'var(--accent-red)',
            borderRadius: 'var(--radius-md)',
            fontSize: '0.85rem',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem'
          }}>
            <AlertCircle size={16} />
            <span>{error}</span>
          </div>
        )}
      </div>

      {/* Prediction Output Results */}
      {forecast && (
        <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', border: '1px solid var(--border-glow)', padding: '1.5rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem', borderBottom: '1px solid var(--border-color)', paddingBottom: '1rem' }}>
            <div>
              <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontFamily: 'var(--font-mono)' }}>
                Forecast Horizon: {forecast.horizon_steps} candles ahead ({forecast.timeframe})
              </span>
              <h3 style={{ fontSize: '1.4rem', fontWeight: 700 }}>{forecast.symbol} Target Projection</h3>
            </div>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              padding: '0.45rem 1rem',
              borderRadius: 'var(--radius-md)',
              background: isUp ? 'rgba(16, 185, 129, 0.15)' : isDown ? 'rgba(244, 63, 94, 0.15)' : 'rgba(148, 163, 184, 0.15)',
              color: isUp ? 'var(--accent-green)' : isDown ? 'var(--accent-red)' : 'var(--text-secondary)',
              fontWeight: 700,
              fontFamily: 'var(--font-mono)'
            }}>
              {isUp ? <TrendingUp size={18} /> : isDown ? <TrendingDown size={18} /> : null}
              <span>PREDICTED DIRECTION: {forecast.predicted_direction}</span>
            </div>
          </div>

          {/* Key Metrics Grid */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1.25rem' }}>
            {/* Target Price */}
            <div style={{ background: 'rgba(255, 255, 255, 0.02)', padding: '1.25rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)' }}>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Projected Target Price</div>
              <div style={{ fontSize: '1.8rem', fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--accent-cyan)', margin: '0.25rem 0' }}>
                {formatCurrency(forecast.predicted_price)}
              </div>
              <div style={{ fontSize: '0.85rem', color: isUp ? 'var(--accent-green)' : 'var(--accent-red)', fontFamily: 'var(--font-mono)' }}>
                {formatPercent(forecast.predicted_return_pct)} expected return
              </div>
            </div>

            {/* Reference Price */}
            <div style={{ background: 'rgba(255, 255, 255, 0.02)', padding: '1.25rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)' }}>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Cutoff Reference Price</div>
              <div style={{ fontSize: '1.8rem', fontWeight: 700, fontFamily: 'var(--font-mono)', margin: '0.25rem 0' }}>
                {formatCurrency(forecast.current_price)}
              </div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                Cutoff: {formatDateTime(forecast.data_cutoff_time)}
              </div>
            </div>

            {/* Direction Probability */}
            <div style={{ background: 'rgba(255, 255, 255, 0.02)', padding: '1.25rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)' }}>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Directional Probability P(Up)</div>
              <div style={{ fontSize: '1.8rem', fontWeight: 700, fontFamily: 'var(--font-mono)', margin: '0.25rem 0' }}>
                {(forecast.direction_probability * 100).toFixed(1)}%
              </div>
              {/* Visual meter */}
              <div style={{ width: '100%', height: '6px', background: 'rgba(244, 63, 94, 0.3)', borderRadius: '3px', marginTop: '0.5rem', overflow: 'hidden' }}>
                <div style={{ width: `${Math.min(100, Math.max(0, forecast.direction_probability * 100))}%`, height: '100%', background: 'var(--accent-green)', borderRadius: '3px' }} />
              </div>
            </div>

            {/* 95% Confidence Interval */}
            <div style={{ background: 'rgba(255, 255, 255, 0.02)', padding: '1.25rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-color)' }}>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Empirical 95% Confidence Bounds</div>
              <div style={{ fontSize: '1.1rem', fontWeight: 600, fontFamily: 'var(--font-mono)', margin: '0.35rem 0' }}>
                {formatCurrency(forecast.lower_bound_price)} — {formatCurrency(forecast.upper_bound_price)}
              </div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '0.3rem', marginTop: '0.4rem' }}>
                <ShieldCheck size={14} color="var(--accent-green)" />
                Calibrated walk-forward residual bounds
              </div>
            </div>
          </div>

          {/* Audit & Timing Footer */}
          <div style={{
            display: 'flex',
            flexWrap: 'wrap',
            justifyContent: 'space-between',
            alignItems: 'center',
            background: 'rgba(0, 0, 0, 0.3)',
            padding: '0.85rem 1.25rem',
            borderRadius: 'var(--radius-md)',
            fontSize: '0.8rem',
            fontFamily: 'var(--font-mono)',
            color: 'var(--text-secondary)',
            gap: '0.75rem'
          }}>
            <span>Model: <strong style={{ color: '#fff' }}>{forecast.model_id} (v{forecast.model_version})</strong></span>
            <span>Generated: <strong>{formatDateTime(forecast.forecast_timestamp)}</strong></span>
            <span>Target Execution: <strong style={{ color: 'var(--accent-cyan)' }}>{formatDateTime(forecast.target_time)}</strong></span>
            <span>Status: <span className="badge badge-warning">{forecast.status}</span></span>
          </div>
        </div>
      )}
    </div>
  );
};
