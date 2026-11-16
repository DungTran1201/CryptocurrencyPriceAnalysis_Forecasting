"""Application configuration, adaptive execution profiles, and typed settings schema.

Centralizes environment variables, runtime profiles (LITE, STANDARD, EXTENDED),
resource budgets, streaming bounds, storage abstraction, and ML gating limits.
"""

from enum import Enum
import os
from pathlib import Path
from typing import Dict, List, Optional
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
        "max_python_procs": 2,
        "total_memory_mb": 450,
        "worker_concurrency": 2,
        "stream_queue_maxsize": 1000,
        "consumer_batch_size": 50,
        "bronze_flush_max_records": 250,
        "microbatch_flush_max_age_sec": 5.0,
        "bronze_buffer_max_mb": 16,
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
        "default_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"],
    },
}


class ResourceBudgetSettings(BaseModel):
    """Strict bounded memory, concurrency, batching, and retention controls."""
    max_python_procs: int = Field(default=2, ge=1, le=16)
    total_memory_mb: int = Field(default=450, ge=128, le=16384)
    worker_concurrency: int = Field(default=2, ge=1, le=16)
    stream_queue_maxsize: int = Field(default=1000, ge=50, le=50000)
    queue_high_watermark_ratio: float = Field(default=0.80, ge=0.5, le=0.95)
    consumer_batch_size: int = Field(default=50, ge=1, le=1000)
    bronze_flush_max_records: int = Field(default=250, ge=1, le=10000)
    microbatch_flush_max_age_sec: float = Field(default=5.0, ge=0.5, le=120.0)
    bronze_buffer_max_mb: int = Field(default=16, ge=1, le=512)
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


class Settings(BaseSettings):
    """Global system settings."""
    app_name: str = "Binance Real-Time Financial Intelligence Platform"
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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

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
        self.streaming.symbols = list(defaults["default_symbols"])
        self.streaming.embedded_in_api = (profile == PlatformProfile.LITE)

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "Settings":
        """Load settings from optional config.yaml, profile defaults, and environment."""
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

        # Resolve profile (env PLATFORM_PROFILE takes precedence over yaml app.profile)
        raw_profile = os.getenv("PLATFORM_PROFILE") or (
            yaml_overrides.get("app", {}).get("profile")
            if isinstance(yaml_overrides.get("app"), dict)
            else None
        )
        if raw_profile:
            try:
                selected_profile = PlatformProfile(str(raw_profile).strip().lower())
            except ValueError:
                selected_profile = PlatformProfile.LITE
        else:
            selected_profile = instance.profile

        instance.apply_profile_defaults(selected_profile)

        # Merge yaml data config if present
        data_cfg = yaml_overrides.get("data")
        if isinstance(data_cfg, dict):
            if isinstance(data_cfg.get("symbols"), list) and data_cfg["symbols"]:
                yaml_syms = [str(s).upper() for s in data_cfg["symbols"] if s]
                instance.sync.symbols = yaml_syms
                if selected_profile != PlatformProfile.LITE:
                    instance.streaming.symbols = yaml_syms
            time_cfg = data_cfg.get("time")
            if isinstance(time_cfg, dict) and time_cfg.get("default_frame"):
                instance.sync.default_timeframe = str(time_cfg["default_frame"])

        # Explicit environment overrides for streaming & storage
        if os.getenv("STREAM_SYMBOLS"):
            instance.streaming.symbols = [
                s.strip().upper() for s in os.environ["STREAM_SYMBOLS"].split(",") if s.strip()
            ]
        if os.getenv("STREAM_ENABLED"):
            instance.streaming.enabled = os.environ["STREAM_ENABLED"].strip().lower() in {"1", "true", "yes"}
        if os.getenv("STREAM_EMBEDDED_IN_API"):
            instance.streaming.embedded_in_api = os.environ["STREAM_EMBEDDED_IN_API"].strip().lower() in {"1", "true", "yes"}
        if os.getenv("BROKER_BACKEND"):
            instance.streaming.broker_backend = os.environ["BROKER_BACKEND"].strip().lower()
        if os.getenv("NATS_URL"):
            instance.streaming.nats_url = os.environ["NATS_URL"].strip()
        if os.getenv("STORAGE_BACKEND"):
            instance.storage.backend = os.environ["STORAGE_BACKEND"].strip().lower()
        if os.getenv("DATA_DIR"):
            instance.storage.data_dir = os.environ["DATA_DIR"].strip()
        if os.getenv("S3_ENDPOINT_URL"):
            instance.storage.s3_endpoint_url = os.environ["S3_ENDPOINT_URL"].strip()
        if os.getenv("S3_BUCKET"):
            instance.storage.s3_bucket = os.environ["S3_BUCKET"].strip()
        if os.getenv("S3_ACCESS_KEY"):
            instance.storage.s3_access_key = os.environ["S3_ACCESS_KEY"].strip()
        if os.getenv("S3_SECRET_KEY"):
            instance.storage.s3_secret_key = os.environ["S3_SECRET_KEY"].strip()
        if os.getenv("MLFLOW_TRACKING_URI"):
            instance.mlflow_tracking_uri = os.environ["MLFLOW_TRACKING_URI"].strip()
        if os.getenv("ADMIN_API_TOKEN"):
            instance.admin_api_token = os.environ["ADMIN_API_TOKEN"].strip()
        if os.getenv("LOG_FORMAT"):
            instance.log_format = os.environ["LOG_FORMAT"].strip().lower()

        # Database env override
        env_db = os.getenv("DATABASE_URL")
        if env_db:
            instance.database_url = env_db
            if env_db.startswith("postgresql://"):
                instance.database_url = env_db.replace("postgresql://", "postgresql+asyncpg://", 1)
                instance.sync_database_url = env_db
            elif env_db.startswith("postgresql+asyncpg://"):
                instance.sync_database_url = env_db.replace("postgresql+asyncpg://", "postgresql://", 1)
        if os.getenv("SYNC_DATABASE_URL"):
            instance.sync_database_url = os.environ["SYNC_DATABASE_URL"].strip()

        return instance


settings = Settings.load()
