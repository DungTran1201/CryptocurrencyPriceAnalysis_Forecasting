# Backup, Restore, and Recovery Runbook

**Document ID:** `DP-SPEC-803`  
**Status:** `PROPOSED_PHASE_1_SPEC`  
**Owner:** `@sre-qa` (`WI-DP-01`)  
**Applies To:** Operational SQLite/PostgreSQL, Medallion Lake (`bronze`/`silver`/`gold`), DuckDB Warehouse (`dw-v{N}.duckdb`), Checkpoints, and NATS JetStream

---

## 1. Recovery Objectives & Backup Inventory

| Store / Artifact | Path / Source | Backup Strategy | Restore / Rehydrate Source |
|---|---|---|---|
| **Operational SQL DB (SQLite WAL)** | `data/crypto_market.db` (+ `-wal`, `-shm`) | **Online consistent snapshot via Python `sqlite3.Connection.backup()`** (never raw `Copy-Item` while writers are active). | Restore `.db` backup file while API & workers are stopped; run `alembic upgrade head`. |
| **Operational SQL DB (PostgreSQL)** | External container / host | `pg_dump --format=custom` (`NOT_APPLICABLE` on current host lacking PG). | `pg_restore` + `alembic upgrade head`. |
| **Medallion Data Lake + Manifests** | `data/bronze/`, `data/silver/`, `data/gold/` | Archive Bronze `.jsonl.zst` + immutable Silver/Gold Parquet referenced by `ACTIVE` `lake_snapshots` + `lake_manifest_files`. | Restore object tree matching `ACTIVE` SQL snapshot; or rehydrate Silver/Gold from Bronze + SQL `klines`. |
| **DuckDB Warehouse** | `data/warehouse/snapshots/dw-v{N}.duckdb` | Copy immutable published `dw-v{N}.duckdb` + `LATEST` pointer (never touch `data/warehouse/staging/dw_staging.duckdb` while writer runs). | Copy back `dw-v{N}.duckdb` OR trigger `WorkflowWorker` `warehouse_build` rebuild from SQL `klines` + Silver Parquet. |
| **Incremental Analytics Checkpoints** | `data/checkpoints/analytics_*.json` | Backed up alongside `data/`; atomic `.tmp + os.replace` writes. | Recompute deterministically from last `300–1000` closed `klines` in SQL/Silver. |
| **NATS JetStream** | `data/nats/jetstream/` | Bounded transient replay buffer (`3d` / `128–512 MB`); not primary long-term archive. | Replay via `/api/v1/streaming/replay` or re-sync missing bars from Binance REST. |

---

## 2. Online Consistent Backup Procedure (SQLite + Lake + Warehouse)

Do **not** copy `data/crypto_market.db` with Windows `Copy-Item` while `uvicorn` or workers hold WAL transactions open, as copying `.db` without synchronized `-wal` causes corruption.

```powershell
# Safe online backup of SQLite WAL + immutable Warehouse snapshot + Lake
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$dest = "backups\$ts"
New-Item -ItemType Directory -Force $dest | Out-Null

# 1. Online consistent SQLite backup (safe under live WAL readers/writers)
.\.venv\Scripts\python.exe -c "
import sqlite3, pathlib
dst = pathlib.Path('$dest') / 'crypto_market.db'
src_conn = sqlite3.connect('data/crypto_market.db', timeout=30.0)
dst_conn = sqlite3.connect(str(dst))
with dst_conn:
    src_conn.backup(dst_conn)
dst_conn.close()
src_conn.close()
print('SQLite online backup OK:', dst, dst.stat().st_size)
"

# 2. Copy Lake, Checkpoints, and immutable Warehouse snapshots (skip staging/dw_staging.duckdb)
robocopy data\bronze "$dest\bronze" /E /NFL /NDL /NJH /NJS
robocopy data\silver "$dest\silver" /E /NFL /NDL /NJH /NJS
robocopy data\gold   "$dest\gold"   /E /NFL /NDL /NJH /NJS
robocopy data\checkpoints "$dest\checkpoints" /E /NFL /NDL /NJH /NJS
if (Test-Path data\warehouse\snapshots) {
    robocopy data\warehouse\snapshots "$dest\warehouse\snapshots" /E /NFL /NDL /NJH /NJS
}
```

---

## 3. Restore Procedures

### 3.1 Full Workspace Restore (Cold Recovery)
1. **Stop all running platform processes** (`uvicorn`, `stream_worker`, `workflow_worker`, and gracefully quit NATS if restoring broker state).
2. Remove stale `-wal` / `-shm` / `dw_staging.duckdb` files (`data/crypto_market.db-wal`, `data/crypto_market.db-shm`, `data/warehouse/staging/`).
3. Restore `crypto_market.db` and Lake/Warehouse folders from `$dest`.
4. Verify schema revision and integrity:
   ```powershell
   $env:PYTHONPATH = "."
   .\.venv\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect('data/crypto_market.db'); print(c.execute('PRAGMA integrity_check;').fetchone())"
   .\.venv\Scripts\alembic.exe current
   ```
5. Start NATS and platform processes (`DP-SPEC-801`), then trigger a gap-heal check (`Section 4.2`).

### 3.2 DuckDB Warehouse Rebuild (From SQL / Lake Without Backup)
Because the DuckDB Warehouse (`dw-v{N}.duckdb`) is a derived analytical projection of SQL `klines` + Silver Parquet:
1. Delete corrupt staging (`data/warehouse/staging/dw_staging.duckdb`) if writer crashed.
2. Enqueue or run `warehouse_build` (`WorkflowWorker` / `WarehouseService` rebuild), which populates `dim_*`, `fact_kline_bar`, and `fact_risk_daily` cleanly from authoritative Silver/SQL data and publishes a fresh `dw-v{N}.duckdb` snapshot.

---

## 4. Stream Replay, DLQ Recovery, and Gap Backfill

### 4.1 Replaying NATS JetStream Messages & Auditing DLQ
1. Inspect stream & consumer status: `GET http://127.0.0.1:8000/api/v1/streaming/status` and `http://127.0.0.1:8222/jsz?streams=true&consumers=true`.
2. Inspect quarantined events: `GET http://127.0.0.1:8000/api/v1/streaming/dlq?limit=100`.
3. Replay historical messages by sequence (requires `X-Admin-Token` if configured):
   ```powershell
   Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/streaming/replay" `
     -Headers @{ "X-Admin-Token" = $env:ADMIN_API_TOKEN; "Content-Type" = "application/json" } `
     -Body '{"subject":"market.>","start_seq":1,"max_msgs":200}'
   ```

### 4.2 Backfilling Data Gaps (`klines` and `aggTrades`)
- **Automatic Recovery:** On Binance WS reconnect or worker startup, single-flight gap healing reconciles missed `1m` klines and `/aggTrades?fromId`.
- **Manual Recovery (`scripts/recover_platform.ps1`):**
  ```powershell
  .\scripts\recover_platform.ps1 -Symbol BTCUSDT -Timeframe 1h -FillGaps -RecomputeGold
  .\scripts\recover_platform.ps1 -Symbol ETHUSDT -Timeframe 1m -FillGaps
  ```
- **Verify Post-Recovery Completeness:** Run `POST /api/v1/data-quality/evaluate` (`X-Admin-Token` once `WI-DP-09`/`WI-DP-13` land) and confirm `DQ-GAP-01`, `DQ-TRD-01`, and `DQ-FRE-01` return `PASS`.
