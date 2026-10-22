export interface SymbolInfo {
  symbol: string;
  base_asset: string;
  quote_asset: string;
  current_price: number;
  change_24h: number;
  high_24h: number;
  low_24h: number;
  volume_24h: number;
  last_synced_at?: string;
}

export interface KlineCandle {
  open_time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  close_time: string;
  is_closed: boolean;
}

export interface MarketDataResponse {
  symbol: string;
  timeframe: string;
  count: number;
  candles: KlineCandle[];
  indicators: Record<string, (number | null)[]>;
}

export interface ForecastRecord {
  id: string;
  model_id: string;
  model_version: string;
  symbol: string;
  timeframe: string;
  horizon_steps: number;
  data_cutoff_time: string;
  forecast_timestamp: string;
  target_time: string;
  current_price: number;
  predicted_price: number;
  predicted_return_pct: number;
  predicted_direction: 'UP' | 'DOWN' | 'FLAT';
  direction_probability: number;
  lower_bound_price?: number;
  upper_bound_price?: number;
  confidence_level: number;
  status: 'PENDING' | 'RECONCILED' | 'EXPIRED';
  realized_price?: number;
  realized_direction?: 'UP' | 'DOWN' | 'FLAT';
  absolute_error?: number;
  percentage_error?: number;
  direction_correct?: boolean;
  reconciled_at?: string;
}

export interface ForecastHistoryResponse {
  total_count: number;
  reconciled_count: number;
  direction_hit_rate_pct: number;
  mean_percentage_error: number;
  records: ForecastRecord[];
}

export interface ModelMetric {
  mae: number;
  rmse: number;
  mape: number;
  directional_accuracy: number;
  brier_score?: number;
  naive_mae?: number;
  mae_improvement_pct?: number;
  beats_naive_baseline: boolean;
}

export interface ModelCard {
  model_id: string;
  name: string;
  version: string;
  model_type: string;
  symbol: string;
  timeframe: string;
  horizon_steps: number;
  train_start_time: string;
  train_end_time: string;
  train_sample_count: number;
  is_active: boolean;
  created_at: string;
  metrics?: ModelMetric;
}

export interface CheckpointSummary {
  symbol: string;
  timeframe: string;
  total_candles: number;
  last_close_time?: string;
  last_sync_status: string;
  detected_gaps_count: number;
  updated_at: string;
}

export interface SystemStatus {
  status: string;
  version: string;
  environment: string;
  current_time: string;
  database_connected: boolean;
  total_candles_stored: number;
  total_forecasts_generated: number;
  total_reconciled_forecasts: number;
  active_models_count: number;
  checkpoints: CheckpointSummary[];
}
