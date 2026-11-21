# Specification Pack Change Log

**Document ID:** `DOC-DP-00-CHANGELOG`  
**Version:** `1.0.1`

---

| Version | Date (UTC) | Author / Role | Summary of Changes |
|---|---|---|---|
| `0.1.0` | `2026-11-17` | `@architect`, `@data-eng`, `@stream-orch`, `@sre-qa` | Phase 1 Step 1 read-only codebase audit, hardware/toolchain/pytest baseline (`#6`–`#9`), and target architecture design proposals (`#7`). |
| `0.2.0` | `2026-11-17` | `@architect`, `@data-eng`, `@stream-orch`, `@sre-qa` | Phase 1 Step 1B empirical host probes (`#14` disk/DuckDB Parquet latency; `#15` DuckDB 2.0.0 Windows lock & `1.43 ms` snapshot copy; `#16` NATS JetStream KV `StorageType.MEMORY` vs `StorageType.FILE` probe) and unified ID registry (`#17`). |
| `1.0.0` | `2026-11-17` | `@architect`, `@data-eng`, `@stream-orch`, `@sre-qa` | Phase 1 Step 2 initial release of complete Data Plane System Specification Pack (`docs/data-plane/00-spec-management` through `80-operations`). All legacy `docs/` preserved untouched. |
| `1.0.1` | `2026-11-17` | `@architect`, `@data-eng`, `@stream-orch`, `@sre-qa` | Phase 1 Gate reconciliation (`#28`–`#31`): standardized `psycopg[binary]>=3.2.0,<4.0` + `postgresql+psycopg://`, `serving.market.<SYMBOL>`, `worker.<role>.<worker_id>` KV keys (`1/2/4 MB` MEMORY caps), `data/warehouse/staging/dw_staging.duckdb`, `warehouse_snapshots.status`, `WarehouseSettings.retain_snapshots` (`3/3/5`, `reader_grace_ttl_sec >= 60`), canonical `workflow_*` SQL schema (`workflow_type`, `lease_token`, `RETENTION_ENFORCE`), `HotStateCache` (`IFC-DP-009`) methods, disjoint `work-item-board.md` ownership (`backend/app/schemas/*`, `.github/workflows/ci.yml`), `TC-DP-*` ranges, and Mermaid diagram fixes. |
