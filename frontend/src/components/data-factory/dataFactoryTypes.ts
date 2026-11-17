export interface StationInfo {
  id: string;
  code: string;
  name: string;
  subtitle: string;
  category: 'INGEST' | 'BROKER' | 'PROCESSING' | 'STORAGE' | 'INTELLIGENCE' | 'WAREHOUSE' | 'SERVING';
  position: [number, number, number];
  size: [number, number, number];
  color: string;
  accentColor: string;
  role: string;
  description: string;
  inputContract: string;
  outputContract: string;
  pathType: 'streaming' | 'batch';
}

export const FACTORY_STATIONS: StationInfo[] = [
  {
    id: 'st_01_sources',
    code: 'ST-01',
    name: 'Data Sources Gateway',
    subtitle: 'Binance Public WS & REST Connectors',
    category: 'INGEST',
    position: [-14, 0, -8],
    size: [3.2, 2.0, 3.2],
    color: '#00D8FF',
    accentColor: '#00B4D8',
    role: 'External market connectivity and raw event stream ingress',
    description: 'Establishes persistent duplex WebSocket connections to Binance Vision for real-time aggTrade and kline_1m feeds, alongside idempotent REST backfill connectors.',
    inputContract: 'Public Binance WS (wss://stream.binance.com) & REST API',
    outputContract: 'Raw JSON frames { e: "aggTrade" | "kline", s: symbol, p, q, T }',
    pathType: 'streaming'
  },
  {
    id: 'st_02_normalize',
    code: 'ST-02',
    name: 'Ingestion & Normalizer',
    subtitle: 'Schema Validation & Canonical Parsing',
    category: 'INGEST',
    position: [-7, 0, -8],
    size: [3.0, 1.8, 3.0],
    color: '#00B4D8',
    accentColor: '#0077B6',
    role: 'De-serialization and canonical typed event creation',
    description: 'Parses incoming raw exchange payloads into strongly typed CanonicalTradeEvent and CanonicalKlineEvent Pydantic models with UTC normalization.',
    inputContract: 'Raw exchange JSON frames',
    outputContract: 'CanonicalTradeEvent & CanonicalKlineEvent (Schema v3)',
    pathType: 'streaming'
  },
  {
    id: 'st_03_broker',
    code: 'ST-03',
    name: 'Message Broker Hub',
    subtitle: 'NATS JetStream & Bounded Buffer',
    category: 'BROKER',
    position: [0, 0, -8],
    size: [3.8, 2.6, 3.8],
    color: '#FCD535',
    accentColor: '#FFA000',
    role: 'Durable event buffering, flow control & backpressure management',
    description: 'Single-node NATS JetStream 2.15 broker managing MARKET_EVENTS durable stream and MARKET_DLQ with high-watermark producer flow control.',
    inputContract: 'Canonical events from producer bounded queue',
    outputContract: 'NATS JetStream subject market.{type}.{symbol}',
    pathType: 'streaming'
  },
  {
    id: 'st_04_stream_processing',
    code: 'ST-04',
    name: 'Stream Processing Unit',
    subtitle: 'Micro-Batch Consumer & SQL Flusher',
    category: 'PROCESSING',
    position: [7, 0, -8],
    size: [3.2, 2.0, 3.2],
    color: '#0ECB81',
    accentColor: '#00A86B',
    role: 'Durable pull consumption, deduplication and storage dispatch',
    description: 'Pulls message batches via durable consumer, dedupes bars on (symbol, timeframe, open_time), and micro-batches records for database and lakehouse flush.',
    inputContract: 'JetStream durable pull batches (ack_wait=5s)',
    outputContract: 'Flushed SQLite klines & staged Bronze/Silver partitions',
    pathType: 'streaming'
  },
  {
    id: 'st_05_medallion',
    code: 'ST-05',
    name: 'Medallion Lakehouse',
    subtitle: 'Bronze (zstd) • Silver (Parquet)',
    category: 'STORAGE',
    position: [14, 0, -4],
    size: [3.6, 3.2, 4.0],
    color: '#6366F1',
    accentColor: '#4F46E5',
    role: 'Multi-temperature immutable data lakehouse',
    description: 'Bronze layer stores raw zstd-compressed JSONL micro-batches (~25x ratio). Silver layer maintains partitioned columnar Parquet files audited by 10 Data Quality SLA rules.',
    inputContract: 'Deduplicated event batches & validated OHLCV bars',
    outputContract: 'data/bronze/**/*.jsonl.zst & data/silver/**/*.parquet',
    pathType: 'streaming'
  },
  {
    id: 'st_06_intelligence',
    code: 'ST-06',
    name: 'Intelligence & Analytics Engine',
    subtitle: 'Incremental O(1) Stream & Risk Suite',
    category: 'INTELLIGENCE',
    position: [7, 0, 4],
    size: [3.4, 2.4, 3.4],
    color: '#10B981',
    accentColor: '#059669',
    role: 'Real-time indicators, volatility, risk & ML feature vectors',
    description: 'Computes O(1) rolling state for RSI, EMA, SMA, VWAP, ATR14, VaR/CVaR 95%, and extracts zero-lookahead feature vectors for machine learning inference.',
    inputContract: 'Closed kline bars & continuous trade ticks',
    outputContract: 'Incremental analytics snapshots & gold_feature_sets',
    pathType: 'streaming'
  },
  {
    id: 'st_07_warehouse',
    code: 'ST-07',
    name: 'DuckDB Analytical Marts',
    subtitle: 'Asynchronous Columnar Warehouse ETL',
    category: 'WAREHOUSE',
    position: [-2, 0, 4],
    size: [3.4, 2.2, 3.4],
    color: '#F59E0B',
    accentColor: '#D97706',
    role: 'Batch analytical materialization & Star Schema marts',
    description: 'Asynchronous pipeline worker building gold_analytics_marts Parquet files queried via in-process memory-bounded DuckDB sessions (128MB under lite profile).',
    inputContract: 'Silver Parquet partitions & historical SQLite klines',
    outputContract: 'Curated Gold Marts: returns, drawdowns, correlation matrix',
    pathType: 'batch'
  },
  {
    id: 'st_08_serving',
    code: 'ST-08',
    name: 'Hot State & Serving Gateway',
    subtitle: 'FastAPI REST & Coalesced WebSocket Hub',
    category: 'SERVING',
    position: [-11, 0, 4],
    size: [3.4, 2.4, 3.4],
    color: '#EC4899',
    accentColor: '#DB2777',
    role: 'High-density client distribution & API serving plane',
    description: 'Coalesces streaming price ticks, technical indicators, and telemetry into 100ms frames dispatched to browser terminals, accompanied by 38 REST endpoints.',
    inputContract: 'Incremental state snapshots & DuckDB query results',
    outputContract: 'Coalesced WebSocket /ws/market & OpenAPI REST schemas',
    pathType: 'streaming'
  }
];

export interface ConnectionWire {
  fromId: string;
  toId: string;
  fromPos: [number, number, number];
  toPos: [number, number, number];
  pathType: 'streaming' | 'batch';
  color: string;
}

export const FACTORY_CONNECTIONS: ConnectionWire[] = [
  {
    fromId: 'st_01_sources',
    toId: 'st_02_normalize',
    fromPos: [-14, 0.5, -8],
    toPos: [-7, 0.5, -8],
    pathType: 'streaming',
    color: '#00D8FF'
  },
  {
    fromId: 'st_02_normalize',
    toId: 'st_03_broker',
    fromPos: [-7, 0.5, -8],
    toPos: [0, 0.5, -8],
    pathType: 'streaming',
    color: '#00B4D8'
  },
  {
    fromId: 'st_03_broker',
    toId: 'st_04_stream_processing',
    fromPos: [0, 0.5, -8],
    toPos: [7, 0.5, -8],
    pathType: 'streaming',
    color: '#FCD535'
  },
  {
    fromId: 'st_04_stream_processing',
    toId: 'st_05_medallion',
    fromPos: [7, 0.5, -8],
    toPos: [14, 0.5, -4],
    pathType: 'streaming',
    color: '#0ECB81'
  },
  {
    fromId: 'st_04_stream_processing',
    toId: 'st_06_intelligence',
    fromPos: [7, 0.5, -8],
    toPos: [7, 0.5, 4],
    pathType: 'streaming',
    color: '#0ECB81'
  },
  {
    fromId: 'st_05_medallion',
    toId: 'st_07_warehouse',
    fromPos: [14, 0.5, -4],
    toPos: [-2, 0.5, 4],
    pathType: 'batch',
    color: '#6366F1'
  },
  {
    fromId: 'st_06_intelligence',
    toId: 'st_08_serving',
    fromPos: [7, 0.5, 4],
    toPos: [-11, 0.5, 4],
    pathType: 'streaming',
    color: '#10B981'
  },
  {
    fromId: 'st_07_warehouse',
    toId: 'st_08_serving',
    fromPos: [-2, 0.5, 4],
    toPos: [-11, 0.5, 4],
    pathType: 'batch',
    color: '#F59E0B'
  }
];
