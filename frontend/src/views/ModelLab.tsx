import React, { useState, useEffect } from 'react';
import { Cpu, Play, Award, AlertCircle, CheckCircle2 } from 'lucide-react';
import { api } from '../services/api';
import { ModelCard } from '../types';
import { formatNumber, formatPercent } from '../utils/formatters';

export const ModelLab: React.FC = () => {
  const [models, setModels] = useState<ModelCard[]>([]);
  const [loading, setLoading] = useState<boolean>(true);

  // Training form state
  const [trainSymbol, setTrainSymbol] = useState<string>('BTCUSDT');
  const [trainTf, setTrainTf] = useState<string>('1h');
  const [trainHorizon, setTrainHorizon] = useState<number>(6);
  const [trainModelType, setTrainModelType] = useState<string>('gradient_boosting');
  const [trainFolds, setTrainFolds] = useState<number>(4);
  const [training, setTraining] = useState<boolean>(false);
  const [trainResult, setTrainResult] = useState<any | null>(null);
  const [trainError, setTrainError] = useState<string | null>(null);

  const loadModels = async () => {
    try {
      setLoading(true);
      const res = await api.getModels();
      setModels(res);
    } catch (err: any) {
      console.error('Failed to load models:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadModels();
  }, []);

  const handleTrain = async () => {
    try {
      setTraining(true);
      setTrainResult(null);
      setTrainError(null);
      const res = await api.trainModel(
        trainSymbol,
        trainTf,
        trainHorizon,
        trainModelType,
        trainFolds
      );
      setTrainResult(res);
      await loadModels();
    } catch (err: any) {
      setTrainError(err.message || 'Training pipeline failed.');
    } finally {
      setTraining(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', width: '100%' }}>
      {/* Title */}
      <div>
        <h2 style={{ fontSize: '1.3rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
          <Cpu size={20} color="var(--accent-cyan)" />
          Model Lab & Walk-Forward Leaderboard
        </h2>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
          Evaluate time-series forecasters under rigorous chronological walk-forward cross validation. Models must strictly outperform naive persistence baselines before promotion to active serving.
        </p>
      </div>

      {/* Training Studio Card */}
      <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem', border: '1px solid rgba(0, 242, 254, 0.2)', padding: '1.5rem' }}>
        <h3 style={{ fontSize: '1.1rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Play size={16} color="var(--accent-green)" />
          Train Time-Series Forecaster
        </h3>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '1rem', alignItems: 'flex-end' }}>
          <div className="form-group">
            <label className="form-label" htmlFor="train-symbol">Asset</label>
            <select id="train-symbol" className="form-select" value={trainSymbol} onChange={(e) => setTrainSymbol(e.target.value)}>
              <option value="BTCUSDT">BTCUSDT</option>
              <option value="ETHUSDT">ETHUSDT</option>
              <option value="SOLUSDT">SOLUSDT</option>
              <option value="BNBUSDT">BNBUSDT</option>
            </select>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="train-tf">Timeframe</label>
            <select id="train-tf" className="form-select" value={trainTf} onChange={(e) => setTrainTf(e.target.value)}>
              <option value="15m">15m</option>
              <option value="1h">1h</option>
              <option value="4h">4h</option>
              <option value="1d">1d</option>
            </select>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="train-horizon">Horizon</label>
            <select id="train-horizon" className="form-select" value={trainHorizon} onChange={(e) => setTrainHorizon(Number(e.target.value))}>
              <option value={1}>1 step ahead</option>
              <option value={3}>3 steps ahead</option>
              <option value={6}>6 steps ahead</option>
              <option value={12}>12 steps ahead</option>
            </select>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="train-model-type">Architecture</label>
            <select id="train-model-type" className="form-select" value={trainModelType} onChange={(e) => setTrainModelType(e.target.value)}>
              <option value="gradient_boosting">Gradient Boosting (Histogram)</option>
              <option value="ridge">Regularized Ridge Regressor</option>
            </select>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="train-folds">Walk-Forward Folds</label>
            <select id="train-folds" className="form-select" value={trainFolds} onChange={(e) => setTrainFolds(Number(e.target.value))}>
              <option value={3}>3 Expanding Folds</option>
              <option value={4}>4 Expanding Folds</option>
              <option value={5}>5 Expanding Folds</option>
            </select>
          </div>

          <button
            id="start-training-btn"
            className="btn btn-primary"
            onClick={handleTrain}
            disabled={training}
            style={{ height: '42px' }}
          >
            <span>{training ? 'Evaluating Pipeline...' : 'Run Walk-Forward CV'}</span>
          </button>
        </div>

        {trainError && (
          <div style={{
            padding: '0.75rem 1rem',
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
            <span>{trainError}</span>
          </div>
        )}

        {trainResult && (
          <div style={{
            padding: '1.25rem',
            background: 'rgba(0, 242, 254, 0.05)',
            border: '1px solid rgba(0, 242, 254, 0.3)',
            borderRadius: 'var(--radius-md)',
            display: 'flex',
            flexDirection: 'column',
            gap: '0.75rem'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <CheckCircle2 size={18} color="var(--accent-cyan)" />
                <strong>Walk-Forward Evaluation Complete: {trainResult.model_id}</strong>
              </div>
              <span className={`badge ${trainResult.is_active ? 'badge-success' : 'badge-warning'}`}>
                {trainResult.is_active ? 'PASSED GATES → ACTIVE SERVING' : 'FAILED ACTIVATION GATES'}
              </span>
            </div>
            <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
              Folds evaluated: {trainResult.evaluation.folds_evaluated} | Samples: {trainResult.train_samples} | Features: {trainResult.feature_count}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '0.75rem', marginTop: '0.25rem', background: 'rgba(0,0,0,0.2)', padding: '0.75rem', borderRadius: 'var(--radius-sm)' }}>
              <div>Candidate MAE: <strong>{formatNumber(trainResult.evaluation.candidate.mae, 2)}</strong></div>
              <div>Naive Baseline MAE: <strong>{formatNumber(trainResult.evaluation.naive_baseline.mae, 2)}</strong></div>
              <div>Improvement: <strong style={{ color: 'var(--accent-green)' }}>{formatPercent(trainResult.evaluation.mae_improvement_pct)}</strong></div>
              <div>Directional Accuracy: <strong>{(trainResult.evaluation.candidate.directional_accuracy * 100).toFixed(1)}%</strong></div>
            </div>
          </div>
        )}
      </div>

      {/* Model Leaderboard */}
      <div className="card" style={{ padding: 0 }}>
        <div style={{ padding: '1rem 1.25rem', borderBottom: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Award size={18} color="var(--accent-gold)" />
          <strong style={{ fontSize: '1.05rem' }}>Registered Production Models & Benchmarks</strong>
        </div>

        {loading ? (
          <div className="loading-box">
            <div className="spinner"></div>
            <span>Loading model registry...</span>
          </div>
        ) : models.length > 0 ? (
          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Model / Version</th>
                  <th>Target Asset & Horizon</th>
                  <th>Serving State</th>
                  <th>MAE vs Baseline</th>
                  <th>MAE Gain %</th>
                  <th>Directional Accuracy</th>
                  <th>RMSE / MAPE</th>
                  <th>Trained Samples</th>
                </tr>
              </thead>
              <tbody>
                {models.map((m) => {
                  return (
                    <tr key={m.model_id}>
                      <td>
                        <div style={{ fontWeight: 600, color: '#fff' }}>{m.name}</div>
                        <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{m.model_type} (v{m.version})</div>
                      </td>
                      <td>{m.symbol} - {m.horizon_steps}h ({m.timeframe})</td>
                      <td>
                        <span className={`badge ${m.is_active ? 'badge-success' : 'badge-neutral'}`}>
                          {m.is_active ? 'ACTIVE (Serving)' : 'Archived'}
                        </span>
                      </td>
                      <td>
                        {m.metrics ? (
                          <span>
                            {formatNumber(m.metrics.mae, 2)} vs {m.metrics.naive_mae ? formatNumber(m.metrics.naive_mae, 2) : 'N/A'}
                          </span>
                        ) : 'Pending'}
                      </td>
                      <td>
                        {m.metrics?.mae_improvement_pct !== undefined && m.metrics.mae_improvement_pct !== null ? (
                          <span style={{ color: m.metrics.mae_improvement_pct > 0 ? 'var(--accent-green)' : 'var(--accent-red)', fontWeight: 600 }}>
                            {formatPercent(m.metrics.mae_improvement_pct)}
                          </span>
                        ) : '—'}
                      </td>
                      <td>
                        {m.metrics ? (
                          <strong style={{ color: m.metrics.directional_accuracy >= 0.5 ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                            {(m.metrics.directional_accuracy * 100).toFixed(1)}%
                          </strong>
                        ) : '—'}
                      </td>
                      <td>
                        {m.metrics ? `${formatNumber(m.metrics.rmse, 1)} / ${formatNumber(m.metrics.mape, 2)}%` : '—'}
                      </td>
                      <td>{formatNumber(m.train_sample_count, 0)} candles</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="loading-box">
            <p>No trained models registered yet. The system is serving the Rolling Mean Baseline. Use the trainer above to train and validate a model.</p>
          </div>
        )}
      </div>
    </div>
  );
};
