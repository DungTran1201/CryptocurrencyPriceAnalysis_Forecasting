import React, { useState, useEffect } from 'react';
import {
  Play,
  Award,
  AlertCircle,
  CheckCircle2,
  RefreshCw,
  Server,
  Layers
} from 'lucide-react';
import { api } from '../services/api';
import { ModelCard, MLflowTrackingStatus, ExperimentRunItem } from '../types';
import { formatNumber, formatPercent } from '../utils/formatters';

export const ModelLab: React.FC = () => {
  const [models, setModels] = useState<ModelCard[]>([]);
  const [experiments, setExperiments] = useState<ExperimentRunItem[]>([]);
  const [trackingStatus, setTrackingStatus] = useState<MLflowTrackingStatus | null>(null);
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

  const loadData = async () => {
    try {
      setLoading(true);
      const [modelsRes, statusRes, expRes] = await Promise.all([
        api.getModels(),
        api.getTrackingStatus(),
        api.getExperiments()
      ]);
      setModels(modelsRes);
      setTrackingStatus(statusRes);
      setExperiments(expRes);
    } catch (err: any) {
      console.error('Failed to load models/tracking data:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
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
      await loadData();
    } catch (err: any) {
      setTrainError(err.message || 'Training pipeline failed.');
    } finally {
      setTraining(false);
    }
  };

  return (
    <div className="view-container">
      {/* Header */}
      <div className="view-header">
        <div>
          <div className="view-tag">EXPERIMENT TRACKING & MODEL REGISTRY</div>
          <h1 className="view-title">Model Lab & Observability</h1>
          <p className="view-subtitle">
            Walk-forward cross validation, hyperparameter tracking, and strict promotion gating against naive baselines.
          </p>
        </div>
        <button className="btn btn-secondary" onClick={loadData} title="Refresh Experiments">
          <RefreshCw size={14} />
        </button>
      </div>

      {/* MLflow Tracking Connection Card */}
      {trackingStatus && (
        <div className="panel" style={{ marginBottom: '1.25rem', borderLeft: '4px solid var(--accent-cyan)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.75rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
              <Server size={18} color="var(--accent-cyan)" />
              <div>
                <div style={{ fontWeight: 600, color: '#fff', fontSize: '0.95rem' }}>
                  MLflow Experiment Tracking Status: {trackingStatus.server_status}
                </div>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                  {trackingStatus.message}
                </div>
              </div>
            </div>
            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
              <span className={`badge ${trackingStatus.is_connected ? 'badge-success' : 'badge-neutral'}`}>
                {trackingStatus.adapter_mode}
              </span>
              <span style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
                {trackingStatus.tracking_uri}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Training Studio Card */}
      <div className="panel" style={{ marginBottom: '1.5rem' }}>
        <div className="panel-header">
          <div className="panel-title">
            <Play size={18} color="var(--semantic-green)" />
            <span>Train Chronological Time-Series Forecaster</span>
          </div>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
            Expanding Walk-Forward CV (No Look-Ahead Leakage)
          </span>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '1rem', alignItems: 'flex-end', marginTop: '0.75rem' }}>
          <div className="form-group">
            <label className="form-label" htmlFor="train-symbol">Asset</label>
            <select id="train-symbol" className="form-control" value={trainSymbol} onChange={(e) => setTrainSymbol(e.target.value)}>
              <option value="BTCUSDT">BTCUSDT</option>
              <option value="ETHUSDT">ETHUSDT</option>
              <option value="SOLUSDT">SOLUSDT</option>
              <option value="BNBUSDT">BNBUSDT</option>
            </select>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="train-tf">Timeframe</label>
            <select id="train-tf" className="form-control" value={trainTf} onChange={(e) => setTrainTf(e.target.value)}>
              <option value="15m">15m</option>
              <option value="1h">1h</option>
              <option value="4h">4h</option>
              <option value="1d">1d</option>
            </select>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="train-horizon">Horizon</label>
            <select id="train-horizon" className="form-control" value={trainHorizon} onChange={(e) => setTrainHorizon(Number(e.target.value))}>
              <option value={1}>1 step ahead</option>
              <option value={3}>3 steps ahead</option>
              <option value={6}>6 steps ahead</option>
              <option value={12}>12 steps ahead</option>
            </select>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="train-model-type">Architecture</label>
            <select id="train-model-type" className="form-control" value={trainModelType} onChange={(e) => setTrainModelType(e.target.value)}>
              <option value="gradient_boosting">Gradient Boosting (Histogram)</option>
              <option value="ridge">Regularized Ridge Regressor</option>
            </select>
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="train-folds">Walk-Forward Folds</label>
            <select id="train-folds" className="form-control" value={trainFolds} onChange={(e) => setTrainFolds(Number(e.target.value))}>
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
            style={{ height: '40px' }}
          >
            {training ? <RefreshCw size={14} className="spin" /> : <Play size={14} />}
            <span>{training ? 'Evaluating...' : 'Train Model'}</span>
          </button>
        </div>

        {trainError && (
          <div className="alert-banner error" style={{ marginTop: '1rem' }}>
            <AlertCircle size={16} />
            <span>{trainError}</span>
          </div>
        )}

        {trainResult && (
          <div style={{ marginTop: '1rem', padding: '1rem', background: 'rgba(0, 242, 254, 0.05)', border: '1px solid rgba(0, 242, 254, 0.3)', borderRadius: '6px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <CheckCircle2 size={18} color="var(--accent-cyan)" />
                <strong style={{ color: '#fff' }}>Walk-Forward CV Complete: {trainResult.model_id}</strong>
              </div>
              <span className={`badge ${trainResult.is_active ? 'badge-success' : 'badge-warning'}`}>
                {trainResult.is_active ? 'PROMOTED TO ACTIVE SERVING' : 'CANDIDATE (Gating Incomplete)'}
              </span>
            </div>
            <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginTop: '0.4rem' }}>
              Folds: {trainResult.evaluation.folds_evaluated} • Samples: {trainResult.train_samples} • Features: {trainResult.feature_count}
            </div>
            <div className="grid-4-cols" style={{ marginTop: '0.75rem' }}>
              <div className="mini-card">
                <div className="mini-card-label">Candidate MAE</div>
                <div className="mini-card-value">{formatNumber(trainResult.evaluation.candidate.mae, 2)}</div>
              </div>
              <div className="mini-card">
                <div className="mini-card-label">Naive Baseline MAE</div>
                <div className="mini-card-value">{formatNumber(trainResult.evaluation.naive_baseline.mae, 2)}</div>
              </div>
              <div className="mini-card">
                <div className="mini-card-label">Gain vs Baseline</div>
                <div className="mini-card-value" style={{ color: 'var(--semantic-green)' }}>
                  {formatPercent(trainResult.evaluation.mae_improvement_pct)}
                </div>
              </div>
              <div className="mini-card">
                <div className="mini-card-label">Directional Hit Rate</div>
                <div className="mini-card-value">
                  {(trainResult.evaluation.candidate.directional_accuracy * 100).toFixed(1)}%
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Model Leaderboard */}
      <div className="panel">
        <div className="panel-header">
          <div className="panel-title">
            <Award size={18} color="var(--accent-cyan)" />
            <span>Registered Model Versions & Benchmark Comparison</span>
          </div>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
            Gating Rule: Outperform Naive Baseline (MAE Gain &gt; 0%)
          </span>
        </div>

        {loading ? (
          <div className="loading-state">
            <RefreshCw size={24} className="spin" />
            <span>Loading registered models...</span>
          </div>
        ) : models.length > 0 ? (
          <div className="table-responsive">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Model / Version</th>
                  <th>Target Asset & Horizon</th>
                  <th>Serving State</th>
                  <th>Candidate MAE</th>
                  <th>Naive Baseline MAE</th>
                  <th>Gain % vs Naive</th>
                  <th>Directional Accuracy</th>
                  <th>Trained Samples</th>
                </tr>
              </thead>
              <tbody>
                {models.map((m) => (
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
                    <td style={{ fontFamily: 'var(--font-mono)' }}>
                      {m.metrics ? formatNumber(m.metrics.mae, 2) : '—'}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
                      {m.metrics?.naive_mae ? formatNumber(m.metrics.naive_mae, 2) : 'N/A'}
                    </td>
                    <td>
                      {m.metrics?.mae_improvement_pct != null ? (
                        <span style={{ color: m.metrics.mae_improvement_pct > 0 ? 'var(--semantic-green)' : 'var(--semantic-red)', fontWeight: 600 }}>
                          {formatPercent(m.metrics.mae_improvement_pct)}
                        </span>
                      ) : '—'}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', color: (m.metrics?.directional_accuracy || 0) >= 0.5 ? 'var(--semantic-green)' : 'var(--semantic-red)' }}>
                      {m.metrics ? `${(m.metrics.directional_accuracy * 100).toFixed(1)}%` : '—'}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)' }}>{formatNumber(m.train_sample_count, 0)} bars</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty-state">
            <p>No models registered yet. Use the training studio above to train and validate a model.</p>
          </div>
        )}
      </div>

      {/* MLflow Experiment Runs Log */}
      <div className="panel" style={{ marginTop: '1.5rem' }}>
        <div className="panel-header">
          <div className="panel-title">
            <Layers size={18} color="var(--accent-cyan)" />
            <span>MLflow Experiment Runs & Hyperparameter Audit</span>
          </div>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
            {experiments.length} tracked run entities
          </span>
        </div>

        {experiments.length === 0 ? (
          <div className="empty-state">
            <p>No experiment runs logged yet. Execute a walk-forward CV run above to record an experiment.</p>
          </div>
        ) : (
          <div className="table-responsive">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Run ID</th>
                  <th>Model Architecture</th>
                  <th>Symbol</th>
                  <th>Hyperparameters</th>
                  <th>Gating Status</th>
                  <th>Promotion Criteria</th>
                </tr>
              </thead>
              <tbody>
                {experiments.map((exp) => (
                  <tr key={exp.run_id}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', color: 'var(--accent-cyan)' }}>
                      {exp.run_id.slice(0, 16)}...
                    </td>
                    <td style={{ fontWeight: 600, color: '#fff' }}>
                      {exp.model_name} (v{exp.version})
                    </td>
                    <td>
                      <span className="badge badge-neutral">{exp.symbol}</span>
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      {JSON.stringify(exp.hyperparameters)}
                    </td>
                    <td>
                      <span className={`badge ${exp.gating_status === 'APPROVED' ? 'badge-success' : 'badge-neutral'}`}>
                        {exp.gating_status}
                      </span>
                    </td>
                    <td style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                      {exp.promotion_criteria}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
