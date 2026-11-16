# Standalone Developer Installation & Environment Setup Guide

**Platform:** Resource-Efficient Real-Time Financial Data Intelligence Platform (`v3.0.0`)  
**Target Environment:** Windows PowerShell (Verified) & Docker Compose Profiles (`lite`, `standard`, `extended`)  
**Python Runtime:** 3.12+ (Tested on Python 3.12.9)  
**Node.js Runtime:** Node 24+ (Tested on Node v24.18.0, npm 11.16.0)

---

## 1. Prerequisites

- **Python 3.12+**: (`py -3.12 --version`)
- **Node.js 20+ & npm**: (`node --version`, `npm --version`)
- **Git**
- **Optional (Containerized Profiles):** Docker Desktop + Docker Compose v2

---

## 2. Create Virtual Environment & Install Backend Dependencies

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

---

## 3. Install Native Single-Node NATS JetStream Binary (Profile LITE)

For a lightweight native deployment (~22 MB RSS, no Docker VM required):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_nats.ps1
```

This downloads the official Windows `nats-server.exe` release into `.bin\nats-server.exe`.

---

## 4. Install Frontend Dependencies & Compile Production Static Bundle

```powershell
cd frontend
npm install
npm test
npm run build
cd ..
```

`npm run build` compiles the optimized React bundle into `frontend/dist/`, which FastAPI mounts automatically at `/`.

---

## 5. Database Migrations (Alembic)

Initialize or upgrade the SQLite (LITE) or PostgreSQL (STANDARD/EXTENDED) metadata schema:

```powershell
$env:PYTHONPATH = "."
.\.venv\Scripts\alembic.exe upgrade head
```

---

## 6. Start the Platform (Adaptive Execution Profiles)

### Option A — Native Profile LITE (Recommended on 8 GB Personal Computers)
Starts native `nats-server.exe` JetStream + Alembic upgrade + FastAPI + Embedded Binance WS Ingestor + Medallion Consumers + Static Frontend:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_lite.ps1
```

Open `http://127.0.0.1:8000/`.

### Option B — Native Profile STANDARD (Separate Stream Worker Process)
1. Terminal 1 (NATS JetStream):
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\start_nats.ps1 -MaxMemMb 128 -MaxFileMb 512
   ```
2. Terminal 2 (Standalone Stream Ingestion & Consumer Worker):
   ```powershell
   $env:PYTHONPATH = "."
   $env:PLATFORM_PROFILE = "standard"
   $env:STREAM_EMBEDDED_IN_API = "false"
   .\.venv\Scripts\python.exe -m backend.app.workers.stream_worker
   ```
3. Terminal 3 (API & Serving):
   ```powershell
   $env:PYTHONPATH = "."
   $env:PLATFORM_PROFILE = "standard"
   $env:STREAM_EMBEDDED_IN_API = "false"
   .\.venv\Scripts\uvicorn.exe backend.app.main:app --host 127.0.0.1 --port 8000
   ```

### Option C — Docker Compose Profiles (`lite`, `standard`, `extended`)

```powershell
# Profile LITE (NATS + Backend Lite)
docker compose -f docker\docker-compose.yml --profile lite up -d

# Profile STANDARD (+ PostgreSQL + Stream Worker + Nginx Frontend)
docker compose -f docker\docker-compose.yml --profile standard up -d

# Profile EXTENDED (+ MinIO S3 + Prometheus + Grafana)
docker compose -f docker\docker-compose.yml --profile extended up -d
```

---

## 7. Recovery, Replay & Maintenance Commands

```powershell
# Backfill gaps & recompute Gold Marts/Features from Silver
powershell -ExecutionPolicy Bypass -File .\scripts\recover_platform.ps1 -Symbol BTCUSDT -Timeframe 1h -FillGaps -RecomputeGold

# Enforce disk retention budgets
powershell -ExecutionPolicy Bypass -File .\scripts\recover_platform.ps1 -RunRetention
```

---

## 8. Run Automated Tests & Benchmarks

```powershell
# Backend & Streaming & ML & Financial Correctness Suite
$env:PYTHONPATH = "."
$env:APP_ENV = "testing"
.\.venv\Scripts\python.exe -m pytest tests/ -v

# Frontend Unit Tests & Build
cd frontend
npm test
npm run build
cd ..

# Resource & Throughput Benchmark
$env:PYTHONPATH = "."
.\.venv\Scripts\python.exe scripts\benchmark_platform.py
```
