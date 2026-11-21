# ADR-001: Single-Node Adaptive Execution Profiles & Resource Budget

- **Status:** Accepted
- **Date:** 2026-11-16
- **Context:** Hardware audit on `DESKTOP-J7FA4CN` measured 8,035 MB total RAM with only **1,418 MB (~1.38 GiB) free physical RAM** during active IDE + browser use, and **17.09 GB free disk on `C:`** while Docker Desktop/WSL2 is stopped with no `.wslconfig` cap.
- **Decision:** Implement three deterministic runtime profiles (`LITE`, `STANDARD`, `EXTENDED`) controlled via `PLATFORM_PROFILE` in `Settings` and Compose profiles. `LITE` runs natively with minimal processes (<= 450 MB RAM, SQLite WAL + native `nats-server.exe` + DuckDB + Parquet). `STANDARD` enables full 4-symbol streams, PostgreSQL/Docker support, and broader windows. `EXTENDED` activates optional MinIO, Prometheus, and Grafana without requiring them for core operation.
- **Consequences:** All profiles share identical financial formulas, DQ rules, and ML validation gates; only resource bounds, concurrency, retention, and optional external exporters change.

