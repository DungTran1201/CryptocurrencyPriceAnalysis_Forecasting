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

export interface SystemResourcesResponse {
  profile: string;
  limits: {
    total_memory_mb: number;
    worker_concurrency: number;
    stream_queue_maxsize: number;
    consumer_batch_size: number;
    bronze_flush_max_records: number;
    microbatch_flush_max_age_sec: number;
    duckdb_memory_limit: string;
    duckdb_threads: number;
    ml_max_train_rows: number;
    ws_coalesce_interval_ms: number;
  };
  measured: {
    process_pid: number;
    process_rss_mb: number;
    memory_budget_mb: number;
    budget_utilization_pct: number;
    process_cpu_percent: number;
    host_ram_total_mb: number;
    host_ram_available_mb: number;
    host_ram_used_pct: number;
    disk_free_gb: number;
    storage_mb: {
      bronze: number;
      silver: number;
      gold: number;
      nats: number;
      metadata_db: number;
    };
  };
  streaming: {
    broker_connected: boolean;
    broker_backend?: string;
    broker_messages: number;
    total_consumer_lag: number;
    ws_connected: boolean;
    events_received: number;
    events_published: number;
    events_consumed: number;
    queue_depth: number;
    backpressure_active: boolean;
    dlq_count: number;
  };
}

export interface IncrementalAnalyticsSnapshot {
  symbol: string;
  timeframe: string;
  bar_count: number;
  last_open_time?: string | null;
  last_close?: number | null;
  live_price?: number | null;
  live_trade_time?: string | null;
  live_trades_count: number;
  simple_return?: number | null;
  log_return?: number | null;
  sma_7?: number | null;
  sma_25?: number | null;
  ema_12?: number | null;
  ema_26?: number | null;
  rsi_14?: number | null;
  macd_line?: number | null;
  macd_signal?: number | null;
  macd_hist?: number | null;
  boll_mid?: number | null;
  boll_upper?: number | null;
  boll_lower?: number | null;
  atr_14?: number | null;
  vwap?: number | null;
  vol_7_ann_pct?: number | null;
  vol_14_ann_pct?: number | null;
  vol_30_ann_pct?: number | null;
  var_95_pct?: number | null;
  cvar_95_pct?: number | null;
  var_99_pct?: number | null;
  cvar_99_pct?: number | null;
  running_peak?: number | null;
  current_drawdown_pct: number;
  max_drawdown_pct: number;
}

export interface StreamingStatusResponse {
  profile: string;
  streaming_enabled: boolean;
  embedded_in_api: boolean;
  broker: {
    connected: boolean;
    backend?: string;
    url?: string;
    stream?: string;
    messages?: number;
    bytes?: number;
    first_seq?: number;
    last_seq?: number;
    dlq_messages?: number;
    total_consumer_lag?: number;
    consumers?: { name: string; num_pending: number; num_ack_pending: number; lag: number }[];
  };
  ingestor: {
    connected: boolean;
    endpoint?: string | null;
    symbols: string[];
    streams: string[];
    received_count: number;
    malformed_count: number;
    reconnect_count: number;
    last_event_time?: string | null;
    last_error?: string | null;
  };
  producer: {
    queue_depth: number;
    queue_maxsize: number;
    occupancy_pct: number;
    backpressure_active: boolean;
    backpressure_events: number;
    published_count: number;
    publish_errors: number;
  };
  consumer: {
    durable_name: string;
    consumed_count: number;
    dedup_skipped_count: number;
    flushed_batches_count: number;
    dlq_count: number;
    last_seq: number;
    pending_buffer_records: number;
    last_flush_at?: string | null;
  };
  ws_clients: number;
  last_triggered_inference?: Record<string, any> | null;
  incremental_symbols: IncrementalAnalyticsSnapshot[];
}

export interface DataCatalogItem {
  dataset_id: string;
  dataset_name: string;
  layer: string;
  description: string;
  schema: { name: string; type: string; nullable: boolean; description: string }[];
  data_type: string;
  source: string;
  partition_spec?: string;
  row_count: number;
  size_bytes: number;
  storage_location: string;
  owner: string;
  retention_policy: string;
  version: string;
  created_at: string;
  updated_at: string;
}

export interface DLQEventItem {
  id: string;
  subject: string;
  stream_type: string;
  symbol: string;
  event_id?: string | null;
  error_reason: string;
  delivery_count: number;
  status: string;
  created_at: string;
  replayed_at?: string | null;
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
  workflow_version?: string;
  symbol: string;
  timeframe: string;
  status: 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED' | 'CANCELLED' | string;
  trigger_type: string;
  retry_count?: number;
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
  depends_on?: string | null;
  status: string;
  retry_count?: number;
  started_at?: string | null;
  completed_at?: string | null;
  duration_seconds?: number | null;
  records_processed: number;
  input_dataset?: string | null;
  output_dataset?: string | null;
  error_message?: string | null;
  logs?: string | null;
}

export interface PipelineRunDetail extends PipelineRunItem {
  input_datasets?: string[];
  output_datasets?: string[];
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
  check_mode?: string;
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

export interface LineageRecordedRun {
  id: string;
  run_id?: string | null;
  source_dataset: string;
  target_dataset: string;
  transformation: string;
  records_in: number;
  records_out: number;
  status: string;
  recorded_at: string;
}

export interface LineageGraphResponse {
  nodes: LineageNode[];
  edges: LineageEdge[];
  recorded_runs?: LineageRecordedRun[];
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
  row_count?: number;
  size_bytes?: number;
  retention_policy?: string;
  storage_location?: string;
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
    log_mean_pct?: number;
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
    cvar_95_pct?: number;
    var_99_pct: number;
    cvar_99_pct?: number;
    atr_14?: number | null;
    vwap?: number | null;
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
  covariance_matrix?: Record<string, any>[];
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
