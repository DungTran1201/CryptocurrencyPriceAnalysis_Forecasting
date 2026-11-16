# ADR-003: Hybrid Storage — Zstd JSONL Bronze, Partitioned Parquet Silver, DuckDB Gold, SQLite/PostgreSQL Metadata

- **Status:** Accepted
- **Date:** 2026-11-16
- **Context:** Storing every `aggTrade` tick as an individual SQL row in SQLite or PostgreSQL causes write amplification and lock contention. Conversely, running ClickHouse/Spark/Presto exceeds single-node RAM limits.
- **Decision:**
  - **Bronze:** Micro-batched immutable raw event logs compressed with `zstd` (`*.jsonl.zst`) via a clean `StorageBackend` interface (`LocalStorageBackend` default, `S3StorageBackend` for optional MinIO).
  - **Silver:** Validated, deduplicated Apache Parquet files partitioned by `event_type/dt=YYYY-MM-DD/symbol=...` using PyArrow, plus upserted OHLCV klines in SQLite/PostgreSQL for backward-compatible low-latency REST endpoints.
  - **Gold:** Materialized Parquet marts queried in-process by **DuckDB** (`memory_limit` capped per profile) for fast analytical scans without a separate OLAP server.
  - **Operational Metadata:** SQLAlchemy 2.0 + **Alembic** supporting SQLite WAL (`LITE`) and PostgreSQL 16 (`STANDARD`/`EXTENDED`) for pipelines, checkpoints, DQ runs, catalog, lineage, DLQ, model registry, and forecasts.
- **Consequences:** Columnar scans use minimal RAM and disk while maintaining transactional ACID metadata and zero-migration-drift via Alembic.

