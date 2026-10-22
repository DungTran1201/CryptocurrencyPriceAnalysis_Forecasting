import React, { useState } from 'react';
import { Sparkles, TrendingUp, TrendingDown, ShieldCheck, Zap } from 'lucide-react';
import { api } from '../services/api';
import { ForecastRecord } from '../types';

export const PredictionStudio: React.FC = () => {
  const [symbol, setSymbol] = useState<string>('BTCUSDT');
  const [timeframe, setTimeframe] = useState<string>('1h');
  const [horizon, setHorizon] = useState<number>(6);
  const [generating, setGenerating] = useState<boolean>(false);
  const [forecast, setForecast] = useState<ForecastRecord | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleGenerate = async () => {
    try {
      setGenerating(true);
      setError(null);
      const res = await api.generateForecast(symbol, timeframe, horizon);
      setForecast(res);
    } catch (err: any) {
      setError(err.message || 'Failed to generate forecast');
    } finally {
      setGenerating(false);
    }
  };

  const isUp = forecast?.predicted_direction === 'UP';
  const isDown = forecast?.predicted_direction === 'DOWN';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', maxWidth: '1200px', margin: '0 auto' }}>
      {/* Configuration Header Card */}
      <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
        <div>
          <h2 style={{ fontSize: '1.3rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Sparkles size={20} color="var(--accent-cyan)" />
            Prediction Studio
          </h2>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
            Multi-horizon time-series machine learning inference with calibrated probability and empirical confidence bounds.
          </p>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '1rem', alignItems: 'flex-end' }}>
          <div className="form-group">
            <label className="form-label">Asset Pair</label>
            <select
              id="pred-symbol-select"
              className="form-select"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
            >
              <option value="BTCUSDT">BTC / USDT</option>
              <option value="ETHUSDT">ETH / USDT</option>
              <option value="SOLUSDT">SOL / USDT</option>
              <option value="BNBUSDT">BNB / USDT</option>
            </select>
          </div>

          <div className="form-group">
            <label className="form-label">Candle Interval</label>
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
            <label className="form-label">Forecast Horizon</label>
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
          <div style={{ padding: '0.75rem 1rem', background: 'rgba(244, 63, 94, 0.15)', color: 'var(--accent-red)', borderRadius: 'var(--radius-md)' }}>
            {error}
          </div>
        )}
      </div>

      {/* Prediction Output Results */}
      {forecast && (
        <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', border: '1px solid var(--border-glow)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--border-color)', paddingBottom: '1rem' }}>
            <div>
              <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontFamily: 'var(--font-mono)' }}>
                Forecast Horizon: {forecast.horizon_steps} candles ahead ({forecast.timeframe})
              </span>
              <h3 style={{ fontSize: '1.4rem', fontWeight: 700 }}>{forecast.symbol} Price Target</h3>
            </div>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              padding: '0.4rem 1rem',
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

          {/* Key Metrics Columns */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1.25rem' }}>
            {/* Target Price */}
            <div style={{ background: 'rgba(255, 255, 255, 0.02)', padding: '1rem', borderRadius: 'var(--radius-md)' }}>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Target Price</div>
              <div style={{ fontSize: '1.8rem', fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--accent-cyan)' }}>
                ${forecast.predicted_price.toLocaleString(undefined, { minimumFractionDigits: 2 })}
              </div>
              <div style={{ fontSize: '0.85rem', color: isUp ? 'var(--accent-green)' : 'var(--accent-red)', fontFamily: 'var(--font-mono)' }}>
                {isUp ? '+' : ''}{forecast.predicted_return_pct.toFixed(2)}% expected return
              </div>
            </div>

            {/* Current Reference Price */}
            <div style={{ background: 'rgba(255, 255, 255, 0.02)', padding: '1rem', borderRadius: 'var(--radius-md)' }}>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Reference (Cutoff) Price</div>
              <div style={{ fontSize: '1.8rem', fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
                ${forecast.current_price.toLocaleString(undefined, { minimumFractionDigits: 2 })}
              </div>
              <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                Cutoff: {forecast.data_cutoff_time.slice(0, 16).replace('T', ' ')}
              </div>
            </div>

            {/* Direction Probability */}
            <div style={{ background: 'rgba(255, 255, 255, 0.02)', padding: '1rem', borderRadius: 'var(--radius-md)' }}>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Directional Probability P(Up)</div>
              <div style={{ fontSize: '1.8rem', fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
                {(forecast.direction_probability * 100).toFixed(1)}%
              </div>
              {/* Visual meter */}
              <div style={{ width: '100%', height: '6px', background: 'rgba(244, 63, 94, 0.3)', borderRadius: '3px', marginTop: '0.5rem', overflow: 'hidden' }}>
                <div style={{ width: `${forecast.direction_probability * 100}%`, height: '100%', background: 'var(--accent-green)', borderRadius: '3px' }} />
              </div>
            </div>

            {/* 95% Confidence Interval */}
            <div style={{ background: 'rgba(255, 255, 255, 0.02)', padding: '1rem', borderRadius: 'var(--radius-md)' }}>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Empirical 95% Bounds</div>
              <div style={{ fontSize: '1.1rem', fontWeight: 600, fontFamily: 'var(--font-mono)', marginTop: '0.35rem' }}>
                ${forecast.lower_bound_price?.toFixed(2)} - ${forecast.upper_bound_price?.toFixed(2)}
              </div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: '0.3rem', marginTop: '0.4rem' }}>
                <ShieldCheck size={14} color="var(--accent-green)" />
                Residual std empirical interval
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
            padding: '0.75rem 1rem',
            borderRadius: 'var(--radius-md)',
            fontSize: '0.8rem',
            fontFamily: 'var(--font-mono)',
            color: 'var(--text-muted)'
          }}>
            <span>Model: <strong style={{ color: '#fff' }}>{forecast.model_id} (v{forecast.model_version})</strong></span>
            <span>Created: <strong>{forecast.forecast_timestamp.slice(0, 19).replace('T', ' ')}</strong></span>
            <span>Target Execution: <strong style={{ color: 'var(--accent-cyan)' }}>{forecast.target_time.slice(0, 19).replace('T', ' ')}</strong></span>
            <span>Status: <span className="badge badge-warning">{forecast.status}</span></span>
          </div>
        </div>
      )}
    </div>
  );
};
