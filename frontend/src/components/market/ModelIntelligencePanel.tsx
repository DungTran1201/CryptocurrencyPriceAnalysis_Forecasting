import React, { useState } from 'react';
import { Sparkles, Cpu, RefreshCw, TrendingUp, TrendingDown, Target, ShieldCheck } from 'lucide-react';
import { ForecastRecord, ModelCard } from '../../types';
import { formatCurrency, formatPercent } from '../../utils/formatters';

interface ModelIntelligencePanelProps {
  symbol: string;
  timeframe: string;
  activeModel?: ModelCard | null;
  latestForecast?: ForecastRecord | null;
  onGenerateForecast: (horizonSteps: number) => Promise<void>;
  onReconcile: () => Promise<void>;
  generating: boolean;
  reconciling: boolean;
}

export const ModelIntelligencePanel: React.FC<ModelIntelligencePanelProps> = ({
  symbol,
  timeframe,
  activeModel,
  latestForecast,
  onGenerateForecast,
  onReconcile,
  generating,
  reconciling
}) => {
  const [horizon, setHorizon] = useState<number>(6);

  const isUp = latestForecast?.predicted_direction === 'UP';
  const hasForecast = Boolean(latestForecast);
  const isReconciled = latestForecast?.status === 'RECONCILED';

  return (
    <div
      style={{
        width: '320px',
        background: '#12161A',
        borderLeft: '1px solid #222B35',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        boxSizing: 'border-box'
      }}
    >
      {/* Panel Header */}
      <div
        style={{
          padding: '12px 16px',
          borderBottom: '1px solid #222B35',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Sparkles size={16} color="#FCD535" />
          <span style={{ fontSize: '13px', fontWeight: 700, color: '#EAECEF' }}>
            AI & Model Intelligence
          </span>
        </div>
        <span
          style={{
            fontSize: '10px',
            fontFamily: 'monospace',
            padding: '2px 6px',
            borderRadius: '3px',
            background: activeModel ? 'rgba(14, 203, 129, 0.15)' : 'rgba(252, 213, 53, 0.15)',
            color: activeModel ? '#0ECB81' : '#FCD535',
            fontWeight: 700
          }}
        >
          {activeModel ? 'MODEL SERVING' : 'BASELINE GATE'}
        </span>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '14px 16px' }}>
        {/* 1. Active Model Card */}
        <div style={{ background: '#161E27', border: '1px solid #222B35', borderRadius: '6px', padding: '12px', marginBottom: '14px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
            <span style={{ fontSize: '11px', color: '#848E9C', fontWeight: 600 }}>ACTIVE MODEL REGISTRY</span>
            <Cpu size={14} color="#00D8FF" />
          </div>
          <div style={{ fontSize: '14px', fontWeight: 700, color: '#EAECEF', fontFamily: 'monospace' }}>
            {activeModel?.model_id || 'baseline_sma_14'}
          </div>
          <div style={{ fontSize: '11px', color: '#848E9C', marginTop: '2px' }}>
            Version: <span style={{ color: '#00D8FF' }}>{activeModel?.version || '1.0.0'}</span> • {symbol} ({timeframe})
          </div>

          <div style={{ marginTop: '10px', paddingTop: '10px', borderTop: '1px solid #222B35', display: 'flex', justifyContent: 'space-between', fontSize: '11px' }}>
            <div>
              <span style={{ color: '#5E6673' }}>Status: </span>
              <span style={{ color: activeModel?.is_active ? '#0ECB81' : '#FCD535', fontWeight: 600 }}>
                {activeModel?.is_active ? 'PRODUCTION' : 'BASELINE FALLBACK'}
              </span>
            </div>
            <div>
              <span style={{ color: '#5E6673' }}>Gate: </span>
              <span style={{ color: '#00D8FF', fontWeight: 600 }}>&ge;1% Naive Gain</span>
            </div>
          </div>
        </div>

        {/* 2. Real-Time Inference Card */}
        <div style={{ background: '#161E27', border: '1px solid #222B35', borderRadius: '6px', padding: '12px', marginBottom: '14px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <span style={{ fontSize: '11px', color: '#848E9C', fontWeight: 600 }}>LATEST ML PREDICTION</span>
            <Target size={14} color="#FCD535" />
          </div>

          {hasForecast && latestForecast ? (
            <div>
              {/* Predicted Price & Direction */}
              <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: '4px' }}>
                <span style={{ fontSize: '20px', fontWeight: 800, fontFamily: 'monospace', color: isUp ? '#0ECB81' : '#F6465D' }}>
                  {formatCurrency(latestForecast.predicted_price)}
                </span>
                <span
                  style={{
                    fontSize: '12px',
                    fontWeight: 700,
                    fontFamily: 'monospace',
                    color: isUp ? '#0ECB81' : '#F6465D',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '2px'
                  }}
                >
                  {isUp ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
                  <span>{formatPercent(latestForecast.predicted_return_pct)}</span>
                </span>
              </div>

              {/* Direction Probability & Confidence */}
              <div style={{ fontSize: '11px', color: '#848E9C', marginBottom: '8px' }}>
                Calibrated Direction Prob: <b style={{ color: '#EAECEF' }}>{(latestForecast.direction_probability * 100).toFixed(1)}%</b>
              </div>

              {/* Confidence Interval Bounds */}
              {latestForecast.lower_bound_price && latestForecast.upper_bound_price && (
                <div style={{ background: '#12161A', borderRadius: '4px', padding: '6px 8px', fontSize: '10px', fontFamily: 'monospace', color: '#848E9C', marginBottom: '8px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span>95% Lower:</span>
                    <span style={{ color: '#EAECEF' }}>${latestForecast.lower_bound_price.toFixed(2)}</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '2px' }}>
                    <span>95% Upper:</span>
                    <span style={{ color: '#EAECEF' }}>${latestForecast.upper_bound_price.toFixed(2)}</span>
                  </div>
                </div>
              )}

              {/* Target Horizon Time */}
              <div style={{ fontSize: '10px', color: '#5E6673' }}>
                Target: {new Date(latestForecast.target_time).toLocaleString()} ({latestForecast.horizon_steps} steps ahead)
              </div>
            </div>
          ) : (
            <div style={{ padding: '12px 0', textAlign: 'center', color: '#848E9C', fontSize: '12px' }}>
              No prediction generated yet for {symbol} ({timeframe}).
            </div>
          )}

          {/* Trigger Inference Controls */}
          <div style={{ marginTop: '12px', paddingTop: '10px', borderTop: '1px solid #222B35' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
              <span style={{ fontSize: '11px', color: '#848E9C' }}>Forecast Horizon:</span>
              <select
                value={horizon}
                onChange={(e) => setHorizon(Number(e.target.value))}
                style={{
                  background: '#12161A',
                  border: '1px solid #222B35',
                  color: '#EAECEF',
                  borderRadius: '3px',
                  padding: '2px 6px',
                  fontSize: '11px',
                  fontFamily: 'monospace'
                }}
              >
                <option value={1}>1 step ({timeframe})</option>
                <option value={3}>3 steps</option>
                <option value={6}>6 steps (Recommended)</option>
                <option value={12}>12 steps</option>
                <option value={24}>24 steps</option>
              </select>
            </div>

            <button
              onClick={() => onGenerateForecast(horizon)}
              disabled={generating}
              style={{
                width: '100%',
                padding: '7px 12px',
                background: '#FCD535',
                color: '#0B0E11',
                border: 'none',
                borderRadius: '4px',
                fontSize: '12px',
                fontWeight: 700,
                cursor: generating ? 'not-allowed' : 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '6px'
              }}
            >
              <Sparkles size={14} className={generating ? 'spin' : ''} />
              <span>{generating ? 'Running Model Inference...' : 'Generate Prediction'}</span>
            </button>
          </div>
        </div>

        {/* 3. Forecast Reconciliation Card */}
        <div style={{ background: '#161E27', border: '1px solid #222B35', borderRadius: '6px', padding: '12px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <span style={{ fontSize: '11px', color: '#848E9C', fontWeight: 600 }}>RECONCILIATION AUDIT</span>
            <ShieldCheck size={14} color="#0ECB81" />
          </div>

          {hasForecast && latestForecast ? (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', marginBottom: '4px' }}>
                <span style={{ color: '#848E9C' }}>Status:</span>
                <span
                  style={{
                    fontFamily: 'monospace',
                    fontWeight: 700,
                    color: isReconciled ? '#0ECB81' : '#FCD535'
                  }}
                >
                  {latestForecast.status}
                </span>
              </div>

              {isReconciled ? (
                <>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', marginBottom: '4px' }}>
                    <span style={{ color: '#848E9C' }}>Realized Price:</span>
                    <span style={{ fontFamily: 'monospace', color: '#EAECEF' }}>
                      {latestForecast.realized_price ? formatCurrency(latestForecast.realized_price) : '—'}
                    </span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', marginBottom: '4px' }}>
                    <span style={{ color: '#848E9C' }}>Realized Error:</span>
                    <span style={{ fontFamily: 'monospace', color: '#00D8FF' }}>
                      {latestForecast.percentage_error !== undefined && latestForecast.percentage_error !== null
                        ? `${latestForecast.percentage_error.toFixed(2)}%`
                        : '—'}
                    </span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', marginBottom: '4px' }}>
                    <span style={{ color: '#848E9C' }}>Direction Hit:</span>
                    <span
                      style={{
                        fontFamily: 'monospace',
                        fontWeight: 700,
                        color: latestForecast.direction_correct ? '#0ECB81' : '#F6465D'
                      }}
                    >
                      {latestForecast.direction_correct ? 'HIT ✓' : 'MISS ✗'}
                    </span>
                  </div>
                </>
              ) : (
                <div style={{ fontSize: '11px', color: '#848E9C', marginTop: '4px' }}>
                  Target candle has not matured yet. Click below once candle closes.
                </div>
              )}
            </div>
          ) : (
            <div style={{ fontSize: '11px', color: '#848E9C' }}>No pending records.</div>
          )}

          <button
            onClick={onReconcile}
            disabled={reconciling}
            style={{
              width: '100%',
              marginTop: '10px',
              padding: '6px 10px',
              background: '#12161A',
              border: '1px solid #222B35',
              color: '#EAECEF',
              borderRadius: '4px',
              fontSize: '11px',
              fontWeight: 600,
              cursor: reconciling ? 'not-allowed' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '5px'
            }}
          >
            <RefreshCw size={12} className={reconciling ? 'spin' : ''} />
            <span>{reconciling ? 'Reconciling...' : 'Reconcile Closed Forecasts'}</span>
          </button>
        </div>
      </div>
    </div>
  );
};
