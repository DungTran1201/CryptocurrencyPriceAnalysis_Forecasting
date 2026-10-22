"""Application configuration and typed settings schema.

Centralizes environment variables and config.yaml settings with strict
Pydantic validation, eliminating hardcoded machine paths.
"""

from pathlib import Path
from typing import List, Optional
import os
import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DataSyncSettings(BaseModel):
    """Configuration for Binance data collection and synchronization."""
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
    save_raw_csv: bool = Field(default=True)
    save_parquet: bool = Field(default=True)


class MLSettings(BaseModel):
    """Configuration for ML models, feature engineering, and evaluation gates."""
    model_storage_dir: str = Field(default="./data/models")
    default_horizon_steps: int = Field(default=6, description="Default forecast horizon in steps (e.g. 6 hours)")
    supported_horizons: List[int] = Field(default=[1, 3, 6, 12, 24])
    min_training_samples: int = Field(default=300, description="Minimum rows required to train")
    walk_forward_folds: int = Field(default=5, ge=2, le=20)
    test_split_ratio: float = Field(default=0.2, ge=0.05, le=0.4)
    # Gating requirement: Model MAE must beat Naive Baseline by at least 1% to be promoted
    activation_margin_threshold: float = Field(default=0.01)
    min_direction_accuracy: float = Field(default=0.51, ge=0.50, description="Minimum directional hit rate %")


class Settings(BaseSettings):
    """Global system settings."""
    app_name: str = "Binance Crypto Intelligence & Forecasting System"
    app_version: str = "2.0.0"
    app_env: str = Field(default="development", description="development, production, testing")
    debug: bool = Field(default=False)
    
    # Base directory dynamically computed relative to repository root
    base_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parents[3])
    
    # Database
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/crypto_market.db",
        description="Database connection string (SQLite for local, PostgreSQL for prod)"
    )
    sync_database_url: str = Field(
        default="sqlite:///./data/crypto_market.db",
        description="Synchronous database URL for migration and worker tasks"
    )
    
    # CORS
    cors_origins: List[str] = Field(
        default=["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:5173"]
    )
    
    # Sub-configs
    sync: DataSyncSettings = Field(default_factory=DataSyncSettings)
    ml: MLSettings = Field(default_factory=MLSettings)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "Settings":
        """Load settings from optional config.yaml, overlaying with environment."""
        resolved_path = None
        if config_path:
            p = Path(config_path)
            if p.exists():
                resolved_path = p
        else:
            default_p = Path(__file__).resolve().parents[3] / "config.yaml"
            if default_p.exists():
                resolved_path = default_p

        yaml_overrides = {}
        if resolved_path and resolved_path.exists():
            try:
                with open(resolved_path, "r", encoding="utf-8") as f:
                    loaded = yaml.safe_load(f)
                    if isinstance(loaded, dict):
                        yaml_overrides = loaded
            except Exception:
                pass

        # Build instance
        instance = cls()
        
        # Merge yaml data if present
        if "data" in yaml_overrides:
            data_cfg = yaml_overrides["data"]
            if "symbol" in data_cfg and data_cfg["symbol"]:
                sym = data_cfg["symbol"]
                if sym not in instance.sync.symbols:
                    instance.sync.symbols.insert(0, sym)
            if "time" in data_cfg and "frame" in data_cfg["time"]:
                instance.sync.default_timeframe = data_cfg["time"]["frame"]
        
        # Override with environment variable if specified
        env_db = os.getenv("DATABASE_URL")
        if env_db:
            instance.database_url = env_db
            if env_db.startswith("postgresql://"):
                instance.database_url = env_db.replace("postgresql://", "postgresql+asyncpg://")
                instance.sync_database_url = env_db

        return instance


# Global cached settings instance
settings = Settings.load()
