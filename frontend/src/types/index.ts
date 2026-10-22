export interface SymbolInfo {
  symbol: string;
  base_asset: string;
  quote_asset: string;
  current_price?: number | null;
  change_24h?: number | null;
  high_24h?: number | null;
  low_24h?: number | null;
  volume_24h?: number | null;
  candle_count_24h?: number;
  has_full_24h?: boolean;
  data_status?: 'SYNCHRONIZED' | 'PARTIAL' | 'UNAVAILABLE' | 'STALE' | string;
  last_synced_at?: string | null;
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

export interface PipelineOverview {
  total_runs: number;
  succeeded_runs: number;
  failed_runs: number;
  running_runs: number;
  success_rate_pct: number;
  total_rows_read: number;
  total_rows_inserted: number;
  avg_duration_seconds: number;
  latest_successful_run_at?: string | null;
  latest_error_message?: string | null;
}

export interface PipelineRunItem {
  id: string;
  pipeline_name: string;
  symbol: string;
  timeframe: string;
  status: 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED' | 'CANCELLED' | string;
  trigger_type: string;
  started_at?: string | null;
  completed_at?: string | null;
  duration_seconds?: number | null;
  rows_read: number;
  rows_inserted: number;
  rows_updated: number;
  rows_rejected: number;
  gaps_detected: number;
  start_watermark?: string | null;
  end_watermark?: string | null;
  error_message?: string | null;
  created_at: string;
}

export interface PipelineTaskItem {
  id: string;
  task_name: string;
  sequence_order: number;
  status: string;
  started_at?: string | null;
  completed_at?: string | null;
  duration_seconds?: number | null;
  records_processed: number;
  error_message?: string | null;
  logs?: string | null;
}

export interface PipelineRunDetail extends PipelineRunItem {
  tasks: PipelineTaskItem[];
}

export interface DataQualityOverview {
  total_active_suites: number;
  total_rules_evaluated: number;
  passed_rules: number;
  failed_rules: number;
  pass_rate_pct: number;
  healthy_suites_count: number;
  warning_suites_count: number;
  failed_suites_count: number;
}

export interface DataQualityRunItem {
  id: string;
  dataset_name: string;
  symbol: string;
  timeframe: string;
  run_timestamp: string;
  status: 'PASSED' | 'WARNING' | 'FAILED' | string;
  total_rules_evaluated: number;
  rules_passed: number;
  rules_failed: number;
  evaluated_row_count: number;
  duration_ms: number;
}

export interface DataQualityResultItem {
  id: string;
  rule_id: string;
  rule_name: string;
  category: 'SCHEMA' | 'COMPLETENESS' | 'INTEGRITY' | 'CONSISTENCY' | 'ANOMALY' | string;
  severity: 'CRITICAL' | 'ERROR' | 'WARNING' | 'INFO' | string;
  status: 'PASS' | 'FAIL' | string;
  failed_records_count: number;
  sample_failures?: string | null;
  message: string;
}

export interface LineageNode {
  id: string;
  label: string;
  layer: string;
  type: string;
  status: string;
  details: string;
  records: number;
  freshness: string;
}

export interface LineageEdge {
  source: string;
  target: string;
  contract: string;
}

export interface LineageGraphResponse {
  nodes: LineageNode[];
  edges: LineageEdge[];
  last_updated: string;
}

export interface DatasetColumn {
  name: string;
  type: string;
  nullable: boolean;
  description: string;
}

export interface DatasetMetadata {
  id: string;
  name: string;
  layer: string;
  description: string;
  primary_keys: string[];
  columns: DatasetColumn[];
}

export interface DatasetPreviewResponse {
  dataset: string;
  metadata?: DatasetMetadata;
  page: number;
  page_size: number;
  total_rows: number;
  total_pages: number;
  profile: {
    total_records: number;
    sample_size: number;
    columns_count: number;
    min_open_time?: string;
    max_open_time?: string;
  };
  rows: Record<string, any>[];
}

export interface ReturnsDistributionResponse {
  symbol: string;
  timeframe: string;
  count: number;
  has_sufficient_data: boolean;
  message?: string;
  start_time?: string;
  end_time?: string;
  metrics?: {
    mean_pct: number;
    median_pct: number;
    std_pct: number;
    variance_pct: number;
    skewness: number;
    kurtosis: number;
    min_pct: number;
    max_pct: number;
    p25_pct: number;
    p75_pct: number;
    var_95_pct: number;
    var_99_pct: number;
  };
  histogram?: {
    bin_start: number;
    bin_end: number;
    bin_center: number;
    count: number;
  }[];
}

export interface RollingVolatilityResponse {
  symbol: string;
  timeframe: string;
  has_sufficient_data: boolean;
  windows?: number[];
  current_annualized_vol?: Record<string, any>;
  series: {
    timestamp: string;
    vol_7?: number;
    vol_14?: number;
    vol_30?: number;
  }[];
}

export interface DrawdownsResponse {
  symbol: string;
  timeframe: string;
  has_sufficient_data: boolean;
  max_drawdown_pct?: number;
  max_drawdown_peak_date?: string;
  max_drawdown_trough_date?: string;
  current_drawdown_pct?: number;
  series: {
    timestamp: string;
    price: number;
    peak: number;
    drawdown_pct: number;
  }[];
}

export interface CorrelationMatrixResponse {
  symbols: string[];
  available_symbols?: string[];
  timeframe?: string;
  observations_count?: number;
  has_sufficient_data: boolean;
  message?: string;
  matrix: Record<string, any>[];
}

export interface MLflowTrackingStatus {
  is_connected: boolean;
  tracking_uri: string;
  server_status: 'CONNECTED' | 'UNAVAILABLE' | 'NOT_CONFIGURED' | string;
  adapter_mode: string;
  message: string;
}

export interface ExperimentRunItem {
  run_id: string;
  model_name: string;
  version: string;
  model_type: string;
  symbol: string;
  timeframe: string;
  horizon_steps: number;
  is_active: boolean;
  train_sample_count: number;
  train_start_time?: string;
  train_end_time?: string;
  created_at?: string;
  hyperparameters: Record<string, any>;
  metrics?: {
    mae?: number;
    rmse?: number;
    mape?: number;
    directional_accuracy_pct?: number;
    naive_mae?: number;
    mae_improvement_pct?: number;
    beats_naive_baseline: boolean;
  };
  gating_status: string;
  promotion_criteria: string;
}

