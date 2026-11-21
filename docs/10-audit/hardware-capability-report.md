# Hardware Capability Report

**Audit Timestamp:** 2026-11-16T22:16:32+07:00  
**Host:** `DESKTOP-J7FA4CN`  
**Operating System:** Microsoft Windows 10 Pro (64-bit, Version `10.0.19045`, Build `19045`)

---

## 1. Measured Hardware Inventory

| Subsystem | Observed Specification | Operational Constraint & Implication |
|---|---|---|
| **CPU** | 12th Gen Intel(R) Core(TM) i5-12400F | 6 Physical Cores / 12 Logical Processors, 2500 MHz base clock, L2: 7680 KB, L3: 18432 KB. Plenty of CPU compute for incremental analytics, DuckDB, and CPU-friendly scikit-learn models. |
| **System RAM** | **8,035.1 MB** (~7.85 GiB) total physical | **CRITICAL CONSTRAINT:** Only **1,418.1 MB (~1.38 GiB)** free physical RAM observed during active development (Windows OS + IDE + Chrome). Virtual commit limit: 22,883.1 MB total / 12,259.5 MB free. |
| **GPU** | NVIDIA GeForce GTX 1650 (4,096 MiB VRAM, 3,274 MiB free, Driver `591.74`) | Not required and deliberately excluded from platform critical path per resource-efficiency mandate. |
| **Disk (`C:`)** | 237.86 GB total / **17.09 GB free** | **CRITICAL CONSTRAINT:** Workspace resides on `C:`. Avoid large Docker images/volumes and unbounded logs/datasets on `C:`; enforce strict data retention and compact dependencies. |
| **Disk (`E:`)** | 465.76 GB total / 271.82 GB free | Available secondary volume if extended historical benchmarks are ever relocated off `C:`. |

---

## 2. Installed Runtimes & Services

| Component | Observed State | Notes |
|---|---|---|
| **Python** | `3.12.9` (`py -3.12`), `3.9`, `3.8.10` (`python` default on PATH) | Default `python` resolves to `3.8.10`; all backend/platform scripts must target Python `3.12` (`.venv\Scripts\python.exe`). No `.venv` existed at audit time. |
| **Node.js / npm** | Node `v24.18.0`, npm `11.16.0` | `frontend/node_modules` not installed at baseline. |
| **Docker / WSL2** | Docker CLI `28.5.1`, Compose `v2.40.0-desktop.1` | `com.docker.service` is **Stopped**; WSL2 distros (`Ubuntu`, `docker-desktop`) are **Stopped**; `%USERPROFILE%\.wslconfig` is **absent**. |
| **Native Broker / DB** | `nats-server` not in PATH; `psql` not in PATH | Can install lightweight native `nats-server.exe` (~15-20 MB binary, ~20 MB RAM) without starting WSL2 VM. |
| **Running Heavy Processes** | `chrome` (~1,034 MB WS top 2 procs), `Antigravity IDE` (~1,055 MB top processes), `agy` (~504 MB), `MsMpEng` (~270 MB) | Explains why only ~1.4-1.6 GiB physical RAM remains free during development. |

---

## 3. External Connectivity Verification

All probes executed from the host via Python `httpx` and `websockets` at audit time:

| Target | Protocol | Result |
|---|---|---|
| `https://data-api.binance.vision/api/v3/ping` | HTTPS REST | HTTP `200` |
| `wss://data-stream.binance.vision:9443/ws/btcusdt@aggTrade` | WebSocket (TLS) | Connected and received live event (`aggTrade BTCUSDT`) |
| `https://api.github.com/repos/nats-io/nats-server/releases/latest` | HTTPS REST | HTTP `200` |
| `https://pypi.org/simple/nats-py/` | HTTPS REST | HTTP `200` |
| `https://registry.npmjs.org/typescript` | HTTPS REST | HTTP `200` |

---

## 4. Architectural Implications Derived from Hardware

1. **Docker Desktop / WSL2 cannot be mandatory for Profile A (LITE) or local dev/demo:** With ~1.4 GiB free physical RAM and no `.wslconfig` memory cap, starting WSL2 + Docker Desktop would immediately trigger severe pagefile thrashing and consume scarce `C:` disk space.
2. **Native Single-Node Lightweight Execution First:**
   - Use **native `nats-server.exe` with JetStream** (~20 MB RSS) instead of Kafka/ZooKeeper or Dockerized brokers for local single-node execution.
   - Use **SQLite WAL** (LITE) and optional **PostgreSQL** (STANDARD Docker profile with explicit memory limits) via SQLAlchemy 2.0 + Alembic.
   - Use **DuckDB** (in-process OLAP with `memory_limit='256MB'`) + **PyArrow Parquet** + **Zstandard JSONL** instead of separate analytical clusters.
   - Use **CPU-only Scikit-learn** (`Ridge`, `LogisticRegression`, `HistGradientBoosting`) with capped sample windows and `n_jobs` limits.
3. **Disk & Memory Guardrails:** Strict bounded queues, micro-batch Parquet/JSONL flushes, and automated disk retention policies are mandatory to protect the **17.09 GB free on `C:`** and **1.38 GiB free physical RAM**.

