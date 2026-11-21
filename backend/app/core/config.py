"""Application configuration, adaptive execution profiles, and typed settings schema.

Centralizes environment variables, runtime profiles (LITE, STANDARD, EXTENDED),
resource budgets, streaming bounds, storage abstraction, warehouse/hot-state/workflow
settings, and ML gating limits (IFC-DP-011).
"""

from enum import Enum
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PlatformProfile(str, Enum):
    """Single-node adaptive execution profiles."""
    LITE = "lite"
    STANDARD = "standard"
    EXTENDED = "extended"


PROFILE_RESOURCE_DEFAULTS: Dict[PlatformProfile, Dict[str, object]] = {
    PlatformProfile.LITE: {
        "max_python_procs": 1,
        "total_memory_mb": 450,
        "worker_concurrency": 2,
        "stream_queue_maxsize": 1000,
        "consumer_batch_size": 50,
        "bronze_flush_max_records": 250,
        "microbatch_flush_max_age_sec": 5.0,
        "bronze_buffer_max_mb": 16,
        "producer_spool_max_mb": 16,
        "db_pool_size": 5,
        "db_max_overflow": 5,
        "duckdb_memory_limit": "128MB",
        "duckdb_threads": 2,
        "online_window_max_bars": 300,
        "ml_max_train_rows": 2000,
        "retention_bronze_days": 3,
        "retention_bronze_max_mb": 256,
        "retention_silver_days": 14,
        "retention_silver_max_mb": 256,
        "retention_gold_days": 30,
        "retention_gold_max_mb": 256,
        "ws_coalesce_interval_ms": 500,
        "ui_stream_buffer_max": 200,
        "nats_max_mem_mb": 64,
        "nats_max_file_mb": 128,
        "aggtrade_backfill_max_batches": 5,
        "workflow_max_concurrent_jobs": 1,
        "warehouse_retain_snapshots": 3,
        "hot_state_kv_max_bytes_mb": 8,
        "heartbeat_max_bytes_mb": 1,
        "l1_cache_maxsize": 512,
        "default_symbols": ["BTCUSDT", "ETHUSDT"],
    },
    PlatformProfile.STANDARD: {
        "max_python_procs": 3,
        "total_memory_mb": 950,
        "worker_concurrency": 4,
        "stream_queue_maxsize": 5000,
        "consumer_batch_size": 200,
        "bronze_flush_max_records": 1000,
        "microbatch_flush_max_age_sec": 5.0,
        "bronze_buffer_max_mb": 32,
        "producer_spool_max_mb": 32,
        "db_pool_size": 5,
        "db_max_overflow": 10,
        "duckdb_memory_limit": "256MB",
        "duckdb_threads": 4,
        "online_window_max_bars": 500,
        "ml_max_train_rows": 5000,
        "retention_bronze_days": 7,
        "retention_bronze_max_mb": 1024,
        "retention_silver_days": 30,
        "retention_silver_max_mb": 1024,
        "retention_gold_days": 90,
        "retention_gold_max_mb": 1024,
        "ws_coalesce_interval_ms": 250,
        "ui_stream_buffer_max": 300,
        "nats_max_mem_mb": 128,
        "nats_max_file_mb": 512,
        "aggtrade_backfill_max_batches": 10,
        "workflow_max_concurrent_jobs": 2,
        "warehouse_retain_snapshots": 3,
        "hot_state_kv_max_bytes_mb": 16,
        "heartbeat_max_bytes_mb": 2,
        "l1_cache_maxsize": 1024,
        "default_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"],
    },
    PlatformProfile.EXTENDED: {
        "max_python_procs": 4,
        "total_memory_mb": 2048,
        "worker_concurrency": 6,
        "stream_queue_maxsize": 10000,
        "consumer_batch_size": 500,
        "bronze_flush_max_records": 2000,
        "microbatch_flush_max_age_sec": 10.0,
        "bronze_buffer_max_mb": 64,
        "producer_spool_max_mb": 64,
        "db_pool_size": 10,
        "db_max_overflow": 15,
        "duckdb_memory_limit": "512MB",
        "duckdb_threads": 4,
        "online_window_max_bars": 1000,
        "ml_max_train_rows": 20000,
        "retention_bronze_days": 30,
        "retention_bronze_max_mb": 4096,
        "retention_silver_days": 90,
        "retention_silver_max_mb": 4096,
        "retention_gold_days": 180,
        "retention_gold_max_mb": 4096,
        "ws_coalesce_interval_ms": 250,
        "ui_stream_buffer_max": 500,
        "nats_max_mem_mb": 256,
        "nats_max_file_mb": 1024,
        "aggtrade_backfill_max_batches": 20,
        "workflow_max_concurrent_jobs": 3,
        "warehouse_retain_snapshots": 5,
        "hot_state_kv_max_bytes_mb": 32,
        "heartbeat_max_bytes_mb": 4,
        "l1_cache_maxsize": 2048,
        "default_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"],
    },
}


class DatabaseSettings(BaseModel):
    """Database URL normalization utilities for SQLite WAL & PostgreSQL (psycopg v3)."""
    async_url: str = Field(default="sqlite+aiosqlite:///./data/crypto_market.db")
    sync_url: str = Field(default="sqlite:///./data/crypto_market.db")

    @staticmethod
    def normalize_urls(
        database_url: str,
        sync_database_url: Optional[str] = None,
    ) -> Tuple[str, str]:
        """Derive consistent async (asyncpg/aiosqlite) and sync (psycopg/sqlite) URLs."""
        db_url = database_url.strip()
        explicit_sync = sync_database_url.strip() if sync_database_url else None

        if db_url.startswith("postgresql://"):
            async_u = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
            default_sync = db_url.replace("postgresql://", "postgresql+psycopg://", 1)
        elif db_url.startswith("postgresql+asyncpg://"):
            async_u = db_url
            default_sync = db_url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
        elif db_url.startswith("postgresql+psycopg://") or db_url.startswith("postgresql+psycopg2://"):
            async_u = "postgresql+asyncpg://" + db_url.split("://", 1)[1]
            default_sync = "postgresql+psycopg://" + db_url.split("://", 1)[1]
        elif db_url.startswith("sqlite+aiosqlite://"):
            async_u = db_url
            default_sync = db_url.replace("sqlite+aiosqlite://", "sqlite://", 1)
        elif db_url.startswith("sqlite://"):
            async_u = db_url.replace("sqlite://", "sqlite+aiosqlite://", 1)
            default_sync = db_url
        else:
            async_u = db_url
            default_sync = db_url

        if explicit_sync:
            if explicit_sync.startswith("postgresql://"):
                sync_u = explicit_sync.replace("postgresql://", "postgresql+psycopg://", 1)
            elif explicit_sync.startswith("postgresql+asyncpg://"):
                sync_u = explicit_sync.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
            elif explicit_sync.startswith("postgresql+psycopg2://"):
                sync_u = explicit_sync.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)
            elif explicit_sync.startswith("sqlite+aiosqlite://"):
                sync_u = explicit_sync.replace("sqlite+aiosqlite://", "sqlite://", 1)
            else:
                sync_u = explicit_sync
        else:
            sync_u = default_sync

        return async_u, sync_u


class ResourceBudgetSettings(BaseModel):
    """Strict bounded memory, concurrency, batching, and retention controls."""
    max_python_procs: int = Field(default=1, ge=1, le=16)
    total_memory_mb: int = Field(default=450, ge=128, le=16384)
    worker_concurrency: int = Field(default=2, ge=1, le=16)
    stream_queue_maxsize: int = Field(default=1000, ge=50, le=50000)
    queue_high_watermark_ratio: float = Field(default=0.80, ge=0.5, le=0.95)
    consumer_batch_size: int = Field(default=50, ge=1, le=1000)
    bronze_flush_max_records: int = Field(default=250, ge=1, le=10000)
    microbatch_flush_max_age_sec: float = Field(default=5.0, ge=0.5, le=120.0)
    bronze_buffer_max_mb: int = Field(default=16, ge=1, le=512)
    producer_spool_max_mb: int = Field(default=16, ge=1, le=512)
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=5, ge=0, le=50)
    duckdb_memory_limit: str = Field(default="128MB")
    duckdb_threads: int = Field(default=2, ge=1, le=16)
    online_window_max_bars: int = Field(default=300, ge=50, le=5000)
    ml_max_train_rows: int = Field(default=2000, ge=100, le=100000)
    retention_bronze_days: int = Field(default=3, ge=1, le=365)
    retention_bronze_max_mb: int = Field(default=256, ge=16, le=65536)
    retention_silver_days: int = Field(default=14, ge=1, le=365)
    retention_silver_max_mb: int = Field(default=256, ge=16, le=65536)
    retention_gold_days: int = Field(default=30, ge=1, le=730)
    retention_gold_max_mb: int = Field(default=256, ge=16, le=65536)
    ws_coalesce_interval_ms: int = Field(default=500, ge=50, le=5000)
    ui_stream_buffer_max: int = Field(default=200, ge=20, le=2000)


class StreamingSettings(BaseModel):
    """Real-time WebSocket ingestion and NATS JetStream configuration."""
    enabled: bool = Field(default=True)
    embedded_in_api: bool = Field(default=True, description="Run lightweight ingestor+consumers inside API process in LITE mode")
    symbols: List[str] = Field(default=["BTCUSDT", "ETHUSDT"])
    streams: List[str] = Field(default=["aggTrade", "kline_1m"])
    binance_ws_base_url: str = Field(default="wss://data-stream.binance.vision:9443")
    binance_ws_fallback_url: str = Field(default="wss://stream.binance.com:9443")
    broker_backend: str = Field(default="nats", description="'nats' or 'memory' (tests only)")
    nats_url: str = Field(default="nats://127.0.0.1:4222")
    nats_stream_name: str = Field(default="MARKET_EVENTS")
    nats_dlq_stream_name: str = Field(default="MARKET_DLQ")
    nats_max_mem_mb: int = Field(default=64, ge=8, le=2048)
    nats_max_file_mb: int = Field(default=128, ge=16, le=16384)
    nats_ack_wait_sec: int = Field(default=30, ge=5, le=300)
    nats_max_deliver: int = Field(default=5, ge=1, le=20)
    nats_dedup_window_sec: int = Field(default=120, ge=10, le=3600)
    reconnect_min_sec: float = Field(default=1.0, ge=0.2)
    reconnect_max_sec: float = Field(default=30.0, ge=1.0)
    aggtrade_backfill_max_batches: int = Field(default=5, ge=1, le=100)
    ml_inference_trigger: str = Field(default="closed_candle", description="closed_candle | api_only")


class StorageSettings(BaseModel):
    """Medallion storage backend and paths."""
    backend: str = Field(default="local", description="'local' or 's3'")
    data_dir: str = Field(default="./data")
    bronze_subdir: str = Field(default="bronze")
    silver_subdir: str = Field(default="silver")
    gold_subdir: str = Field(default="gold")
    checkpoint_subdir: str = Field(default="checkpoints")
    dlq_subdir: str = Field(default="dlq")
    s3_endpoint_url: Optional[str] = Field(default=None)
    s3_bucket: str = Field(default="crypto-lakehouse")
    s3_access_key: Optional[str] = Field(default=None)
    s3_secret_key: Optional[str] = Field(default=None)
    s3_region: str = Field(default="us-east-1")


class DataSyncSettings(BaseModel):
    """Configuration for Binance REST data collection and synchronization."""
    symbols: List[str] = Field(
        default=["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"],
        description="Active crypto pairs tracked by system"
    )
    default_timeframe: str = Field(default="1h", description="Default operational timeframe")
    supported_timeframes: List[str] = Field(
        default=["1m", "5m", "15m", "1h", "4h", "1d"],
        description="Supported Kline intervals"
    )
    binance_api_url: str = Field(
        default="https://data-api.binance.vision/api/v3/klines",
        description="Primary Binance Public API endpoint"
    )
    binance_fallback_url: str = Field(
        default="https://api.binance.com/api/v3/klines",
        description="Secondary fallback API endpoint"
    )
    batch_limit: int = Field(default=1000, ge=10, le=1000)
    max_retries: int = Field(default=5, ge=1, le=10)
    retry_backoff_base: float = Field(default=1.5, ge=1.0)
    request_timeout_seconds: float = Field(default=15.0, ge=3.0)
    save_raw_csv: bool = Field(default=False)
    save_parquet: bool = Field(default=True)


class MLSettings(BaseModel):
    """Configuration for ML models, feature engineering, and evaluation gates."""
    model_storage_dir: str = Field(default="./data/models")
    default_horizon_steps: int = Field(default=6, description="Default forecast horizon in steps")
    supported_horizons: List[int] = Field(default=[1, 3, 6, 12, 24])
    min_training_samples: int = Field(default=300, description="Minimum rows required to train")
    walk_forward_folds: int = Field(default=5, ge=2, le=20)
    test_split_ratio: float = Field(default=0.2, ge=0.05, le=0.4)
    activation_margin_threshold: float = Field(default=0.01)
    min_direction_accuracy: float = Field(default=0.51, ge=0.50, description="Minimum directional hit rate %")


class WorkflowSettings(BaseModel):
    """Durable SQL workflow orchestrator settings (IFC-DP-011)."""
    poll_interval_sec: float = Field(default=2.0, ge=0.2, le=60.0)
    lease_ttl_sec: int = Field(default=60, ge=10, le=3600)
    heartbeat_interval_sec: int = Field(default=15, ge=2, le=300)
    reaper_interval_sec: int = Field(default=15, ge=5, le=300)
    max_concurrent_jobs: int = Field(default=1, ge=1, le=16)
    max_attempts_default: int = Field(default=3, ge=1, le=10)
    graceful_shutdown_sec: float = Field(default=15.0, ge=1.0, le=120.0)
    memory_throttle_pct: float = Field(default=90.0, ge=50.0, le=99.0)


class WarehouseSettings(BaseModel):
    """Persistent DuckDB Data Warehouse & snapshot lifecycle settings (IFC-DP-011)."""
    enabled: bool = Field(default=True)
    warehouse_dir: str = Field(default="./data/warehouse")
    staging_filename: str = Field(default="dw_staging.duckdb")
    retain_snapshots: int = Field(default=3, ge=1, le=20)
    reader_grace_ttl_sec: int = Field(default=60, ge=5, le=3600)
    query_timeout_ms: int = Field(default=5000, ge=200, le=60000)


class HotStateSettings(BaseModel):
    """Tiered HotStateCache (NATS JetStream Memory KV + in-process L1 TTLCache) settings."""
    backend: str = Field(default="nats_kv", description="'nats_kv', 'memory', or 'redis'")
    kv_bucket: str = Field(default="hot_state")
    heartbeat_bucket: str = Field(default="worker_heartbeats")
    kv_max_bytes_mb: int = Field(default=8, ge=1, le=256)
    heartbeat_max_bytes_mb: int = Field(default=1, ge=1, le=64)
    kv_ttl_sec: float = Field(default=300.0, ge=10.0, le=86400.0)
    heartbeat_ttl_sec: float = Field(default=15.0, ge=5.0, le=300.0)
    l1_cache_maxsize: int = Field(default=512, ge=32, le=50000)
    l1_cache_ttl_sec: float = Field(default=2.0, ge=0.1, le=60.0)


class ServingBridgeSettings(BaseModel):
    """Cross-process ServingGatewayBridge control and fanout settings."""
    control_timeout_sec: float = Field(default=5.0, ge=0.5, le=30.0)
    heartbeat_interval_sec: float = Field(default=2.0, ge=0.5, le=30.0)
    closed_bar_inference_queue_max: int = Field(default=32, ge=1, le=500)


def _apply_section_fields(target: BaseModel, section: Any, key_map: Optional[Dict[str, str]] = None) -> None:
    """Safely apply matching dictionary keys onto a Pydantic sub-model."""
    if not isinstance(section, dict):
        return
    mapping = key_map or {}
    for raw_k, val in section.items():
        if val is None:
            continue
        dest_k = mapping.get(raw_k, raw_k)
        if hasattr(target, dest_k):
            setattr(target, dest_k, val)


class Settings(BaseSettings):
    """Global system settings."""
    app_name: str = "MarketStream — Real-Time Financial Data Intelligence Platform"
    app_version: str = "3.0.0"
    app_env: str = Field(default="development", description="development, production, testing")
    profile: PlatformProfile = Field(default=PlatformProfile.LITE)
    debug: bool = Field(default=False)
    log_format: str = Field(default="text", description="'text' or 'json'")
    admin_api_token: Optional[str] = Field(default=None)
    mlflow_tracking_uri: Optional[str] = Field(default=None)

    # Base directory dynamically computed relative to repository root
    base_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parents[3])

    # Database
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/crypto_market.db",
        description="Database connection string (SQLite for LITE, PostgreSQL for STANDARD/EXTENDED)"
    )
    sync_database_url: str = Field(
        default="sqlite:///./data/crypto_market.db",
        description="Synchronous database URL for Alembic migration and worker tasks"
    )

    # CORS
    cors_origins: List[str] = Field(
        default=["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:5173", "http://127.0.0.1:8000"]
    )

    # Sub-configs
    resources: ResourceBudgetSettings = Field(default_factory=ResourceBudgetSettings)
    streaming: StreamingSettings = Field(default_factory=StreamingSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    sync: DataSyncSettings = Field(default_factory=DataSyncSettings)
    ml: MLSettings = Field(default_factory=MLSettings)
    workflow: WorkflowSettings = Field(default_factory=WorkflowSettings)
    warehouse: WarehouseSettings = Field(default_factory=WarehouseSettings)
    hot_state: HotStateSettings = Field(default_factory=HotStateSettings)
    serving: ServingBridgeSettings = Field(default_factory=ServingBridgeSettings)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def database(self) -> DatabaseSettings:
        """Return normalized DatabaseSettings view."""
        return DatabaseSettings(async_url=self.database_url, sync_url=self.sync_database_url)

    def apply_profile_defaults(self, profile: PlatformProfile) -> None:
        """Apply profile-specific defaults without overriding explicit env overrides."""
        defaults = PROFILE_RESOURCE_DEFAULTS[profile]
        self.profile = profile
        self.resources = ResourceBudgetSettings(
            max_python_procs=int(defaults["max_python_procs"]),
            total_memory_mb=int(defaults["total_memory_mb"]),
            worker_concurrency=int(defaults["worker_concurrency"]),
            stream_queue_maxsize=int(defaults["stream_queue_maxsize"]),
            consumer_batch_size=int(defaults["consumer_batch_size"]),
            bronze_flush_max_records=int(defaults["bronze_flush_max_records"]),
            microbatch_flush_max_age_sec=float(defaults["microbatch_flush_max_age_sec"]),
            bronze_buffer_max_mb=int(defaults["bronze_buffer_max_mb"]),
            producer_spool_max_mb=int(defaults["producer_spool_max_mb"]),
            db_pool_size=int(defaults["db_pool_size"]),
            db_max_overflow=int(defaults["db_max_overflow"]),
            duckdb_memory_limit=str(defaults["duckdb_memory_limit"]),
            duckdb_threads=int(defaults["duckdb_threads"]),
            online_window_max_bars=int(defaults["online_window_max_bars"]),
            ml_max_train_rows=int(defaults["ml_max_train_rows"]),
            retention_bronze_days=int(defaults["retention_bronze_days"]),
            retention_bronze_max_mb=int(defaults["retention_bronze_max_mb"]),
            retention_silver_days=int(defaults["retention_silver_days"]),
            retention_silver_max_mb=int(defaults["retention_silver_max_mb"]),
            retention_gold_days=int(defaults["retention_gold_days"]),
            retention_gold_max_mb=int(defaults["retention_gold_max_mb"]),
            ws_coalesce_interval_ms=int(defaults["ws_coalesce_interval_ms"]),
            ui_stream_buffer_max=int(defaults["ui_stream_buffer_max"]),
        )
        self.streaming.nats_max_mem_mb = int(defaults["nats_max_mem_mb"])
        self.streaming.nats_max_file_mb = int(defaults["nats_max_file_mb"])
        self.streaming.aggtrade_backfill_max_batches = int(defaults["aggtrade_backfill_max_batches"])
        self.streaming.symbols = list(defaults["default_symbols"])
        self.streaming.embedded_in_api = (profile == PlatformProfile.LITE)
        self.workflow.max_concurrent_jobs = int(defaults["workflow_max_concurrent_jobs"])
        self.warehouse.retain_snapshots = int(defaults["warehouse_retain_snapshots"])
        self.hot_state.kv_max_bytes_mb = int(defaults["hot_state_kv_max_bytes_mb"])
        self.hot_state.heartbeat_max_bytes_mb = int(defaults["heartbeat_max_bytes_mb"])
        self.hot_state.l1_cache_maxsize = int(defaults["l1_cache_maxsize"])

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "Settings":
        """Load settings with precedence: env/dotenv > config.yaml > profile defaults."""
        resolved_path = None
        if config_path:
            p = Path(config_path)
            if p.exists():
                resolved_path = p
        else:
            default_p = Path(__file__).resolve().parents[3] / "config.yaml"
            if default_p.exists():
                resolved_path = default_p

        yaml_overrides: Dict[str, object] = {}
        if resolved_path and resolved_path.exists():
            try:
                with open(resolved_path, "r", encoding="utf-8") as f:
                    loaded = yaml.safe_load(f)
                    if isinstance(loaded, dict):
                        yaml_overrides = loaded
            except Exception:
                pass

        instance = cls()

        # Resolve profile (OS env > .env > config.yaml app.profile > default)
        raw_env_profile = os.getenv("PLATFORM_PROFILE")
        yaml_app = yaml_overrides.get("app") if isinstance(yaml_overrides.get("app"), dict) else {}
        if raw_env_profile:
            try:
                selected_profile = PlatformProfile(str(raw_env_profile).strip().lower())
            except ValueError:
                selected_profile = PlatformProfile.LITE
        elif "profile" in instance.model_fields_set:
            selected_profile = instance.profile
        elif yaml_app.get("profile"):
            try:
                selected_profile = PlatformProfile(str(yaml_app["profile"]).strip().lower())
            except ValueError:
                selected_profile = PlatformProfile.LITE
        else:
            selected_profile = instance.profile

        instance.apply_profile_defaults(selected_profile)

        # Merge config.yaml app section (if not explicitly set in env/.env)
        if yaml_app:
            if yaml_app.get("name") and "app_name" not in instance.model_fields_set:
                instance.app_name = str(yaml_app["name"])
            if yaml_app.get("version") and "app_version" not in instance.model_fields_set:
                instance.app_version = str(yaml_app["version"])
            if yaml_app.get("env") and "app_env" not in instance.model_fields_set:
                instance.app_env = str(yaml_app["env"])

        # Merge config.yaml data section
        data_cfg = yaml_overrides.get("data")
        if isinstance(data_cfg, dict):
            if isinstance(data_cfg.get("symbols"), list) and data_cfg["symbols"]:
                yaml_syms = [str(s).upper() for s in data_cfg["symbols"] if s]
                instance.sync.symbols = yaml_syms
                if selected_profile != PlatformProfile.LITE:
                    instance.streaming.symbols = yaml_syms
            if isinstance(data_cfg.get("streams"), list) and data_cfg["streams"]:
                instance.streaming.streams = [str(s).strip() for s in data_cfg["streams"] if str(s).strip()]
            time_cfg = data_cfg.get("time")
            if isinstance(time_cfg, dict):
                if time_cfg.get("default_frame"):
                    instance.sync.default_timeframe = str(time_cfg["default_frame"])
                if isinstance(time_cfg.get("supported_frames"), list) and time_cfg["supported_frames"]:
                    instance.sync.supported_timeframes = [str(tf).lower() for tf in time_cfg["supported_frames"] if tf]
            api_cfg = data_cfg.get("api")
            _apply_section_fields(
                instance.sync,
                api_cfg,
                key_map={
                    "primary_url": "binance_api_url",
                    "fallback_url": "binance_fallback_url",
                    "timeout_seconds": "request_timeout_seconds",
                },
            )

        # Merge config.yaml ml, streaming, workflow, warehouse, hot_state, serving sections
        _apply_section_fields(
            instance.ml,
            yaml_overrides.get("ml"),
            key_map={"model_dir": "model_storage_dir"},
        )
        _apply_section_fields(instance.streaming, yaml_overrides.get("streaming"))
        _apply_section_fields(instance.workflow, yaml_overrides.get("workflow"))
        _apply_section_fields(instance.warehouse, yaml_overrides.get("warehouse"))
        _apply_section_fields(instance.hot_state, yaml_overrides.get("hot_state"))
        _apply_section_fields(instance.serving, yaml_overrides.get("serving"))

        # Explicit environment overrides (highest precedence)
        if os.getenv("STREAM_SYMBOLS"):
            instance.streaming.symbols = [
                s.strip().upper() for s in os.environ["STREAM_SYMBOLS"].split(",") if s.strip()
            ]
        if os.getenv("STREAM_STREAMS"):
            instance.streaming.streams = [
                s.strip() for s in os.environ["STREAM_STREAMS"].split(",") if s.strip()
            ]
        if os.getenv("STREAM_ENABLED"):
            instance.streaming.enabled = os.environ["STREAM_ENABLED"].strip().lower() in {"1", "true", "yes"}
        if os.getenv("STREAM_EMBEDDED_IN_API"):
            instance.streaming.embedded_in_api = os.environ["STREAM_EMBEDDED_IN_API"].strip().lower() in {"1", "true", "yes"}
        if os.getenv("BROKER_BACKEND"):
            instance.streaming.broker_backend = os.environ["BROKER_BACKEND"].strip().lower()
        if os.getenv("NATS_URL"):
            instance.streaming.nats_url = os.environ["NATS_URL"].strip()

        ws_base = os.getenv("BINANCE_WS_BASE_URL") or os.getenv("BINANCE_WS_URL")
        if ws_base:
            instance.streaming.binance_ws_base_url = ws_base.strip()
        if os.getenv("BINANCE_WS_FALLBACK_URL"):
            instance.streaming.binance_ws_fallback_url = os.environ["BINANCE_WS_FALLBACK_URL"].strip()

        if os.getenv("BINANCE_API_URL"):
            instance.sync.binance_api_url = os.environ["BINANCE_API_URL"].strip()
        if os.getenv("BINANCE_FALLBACK_URL"):
            instance.sync.binance_fallback_url = os.environ["BINANCE_FALLBACK_URL"].strip()

        if os.getenv("STORAGE_BACKEND"):
            instance.storage.backend = os.environ["STORAGE_BACKEND"].strip().lower()
        data_dir_env = os.getenv("DATA_DIR") or os.getenv("DATA_ROOT_DIR")
        if data_dir_env:
            instance.storage.data_dir = data_dir_env.strip()
        if os.getenv("S3_ENDPOINT_URL"):
            instance.storage.s3_endpoint_url = os.environ["S3_ENDPOINT_URL"].strip()
        if os.getenv("S3_BUCKET"):
            instance.storage.s3_bucket = os.environ["S3_BUCKET"].strip()
        if os.getenv("S3_ACCESS_KEY"):
            instance.storage.s3_access_key = os.environ["S3_ACCESS_KEY"].strip()
        if os.getenv("S3_SECRET_KEY"):
            instance.storage.s3_secret_key = os.environ["S3_SECRET_KEY"].strip()

        if os.getenv("HOT_STATE_BACKEND"):
            instance.hot_state.backend = os.environ["HOT_STATE_BACKEND"].strip().lower()
        if os.getenv("WAREHOUSE_ENABLED"):
            instance.warehouse.enabled = os.environ["WAREHOUSE_ENABLED"].strip().lower() in {"1", "true", "yes"}
        if os.getenv("WAREHOUSE_DIR"):
            instance.warehouse.warehouse_dir = os.environ["WAREHOUSE_DIR"].strip()
        if os.getenv("WORKFLOW_POLL_INTERVAL_SEC"):
            try:
                instance.workflow.poll_interval_sec = float(os.environ["WORKFLOW_POLL_INTERVAL_SEC"])
            except ValueError:
                pass

        if os.getenv("MLFLOW_TRACKING_URI"):
            instance.mlflow_tracking_uri = os.environ["MLFLOW_TRACKING_URI"].strip()
        if os.getenv("ADMIN_API_TOKEN"):
            instance.admin_api_token = os.environ["ADMIN_API_TOKEN"].strip()
        if os.getenv("LOG_FORMAT"):
            instance.log_format = os.environ["LOG_FORMAT"].strip().lower()

        # Normalize database_url and sync_database_url (from OS env, .env, or defaults)
        raw_db_url = os.getenv("DATABASE_URL") or instance.database_url
        raw_sync_db_url = os.getenv("SYNC_DATABASE_URL") or (
            instance.sync_database_url
            if "sync_database_url" in instance.model_fields_set and not os.getenv("DATABASE_URL")
            else None
        )
        instance.database_url, instance.sync_database_url = DatabaseSettings.normalize_urls(
            raw_db_url,
            raw_sync_db_url,
        )

        return instance


settings = Settings.load()
