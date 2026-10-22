# Standalone Developer Installation & Environment Setup Guide

**Platform**: Binance Predict Value & Trend  
**Target Environment**: Windows PowerShell (Verified) & macOS/Linux (Bash)  
**Python Runtime**: 3.12+ (Tested on Python 3.12.9)  
**Node.js Runtime**: Node 18+ (Tested on Node v24.18.0, npm 11.7.0)  

This guide provides end-to-end instructions to clone, configure, initialize, sync, run, test, and troubleshoot the application on a clean development machine.

---

## 1. Prerequisites Installation

Ensure the following tools are installed on your workstation:
- **Git**: [git-scm.com](https://git-scm.com/)
- **Python 3.12+**: [python.org](https://www.python.org/downloads/) (Check **"Add python.exe to PATH"** during Windows setup)
- **Node.js 18+ & npm**: [nodejs.org](https://nodejs.org/)

Verify installations in a fresh PowerShell terminal:
```powershell
python --version
node --version
npm --version
git --version
```

---

## 2. Clone Repository & Directory Navigation

```powershell
git clone https://github.com/DungTran1201/CryptocurrencyPriceAnalysis_Forecasting.git binance-platform
cd binance-platform
```

---

## 3. Python Virtual Environment & Backend Dependencies

Create an isolated Python virtual environment inside the repository root (`.venv`):

```powershell
# Create virtual environment
python -m venv .venv

# Activate environment (Windows PowerShell)
.venv\Scripts\Activate.ps1

# (Optional: If PowerShell execution policy restricts scripts, run:
# Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process)

# Upgrade pip and install pinned backend dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt
```

*For Linux/macOS users:*
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 4. Frontend Dependencies & Production Build

Navigate to the `frontend/` directory and install dependencies using `npm`:

```powershell
cd frontend
npm install

# Verify unit tests
npm test

# Compile TypeScript and build production bundle
npm run build
cd ..
```

---

## 5. Local Environment Configuration

Copy `.env.example` to `.env` if custom overrides are needed. The platform defaults to safe zero-config local defaults using SQLite:

```powershell
# Optional: create a local .env file
# APP_ENV=development
# DATABASE_URL=sqlite+aiosqlite:///./data/crypto_platform.db
# CORS_ORIGINS=["http://localhost:3000","http://localhost:5173","http://localhost:8000"]
# BINANCE_API_KEY="" # Optional: Public endpoints require no API key
```

---

## 6. Database Initialization & Initial Seed Data

Initialize database tables (SQLite by default, stored at `data/crypto_platform.db`) and seed default market trading pairs (`BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`):

```powershell
# Set PYTHONPATH so the backend package resolves correctly
$env:PYTHONPATH = "."

# Run table and seed initialization
.venv\Scripts\python -c "import asyncio; from backend.app.core.database import init_db; from backend.app.main import seed_initial_symbols; asyncio.run(init_db()); asyncio.run(seed_initial_symbols())"
```

---

## 7. Data Synchronization & Market Seeding

To immediately populate historical candlestick data for analytics and modeling without manual clicks:

```powershell
$env:PYTHONPATH = "."
.venv\Scripts\python -c "import asyncio; from backend.app.services.market_service import MarketService; asyncio.run(MarketService.sync_candles('BTCUSDT', '1h', lookback_days=30))"
```

---

## 8. Starting Backend and Frontend Servers

### Option A: Unified Server (FastAPI serving production frontend build)
FastAPI automatically serves the compiled `frontend/dist` bundle at the root URL:

```powershell
# In repository root with .venv active:
$env:PYTHONPATH = "."
.venv\Scripts\uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```
Open **[http://localhost:8000/](http://localhost:8000/)** in your browser.

### Option B: Separate Development Servers (with Vite HMR)
Open two separate PowerShell terminals:

**Terminal 1 (Backend API)**:
```powershell
cd c:\Users\PC\Project\Binance-Predict-Value-And-Trend
.venv\Scripts\activate
$env:PYTHONPATH = "."
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```

**Terminal 2 (Frontend Dev Server)**:
```powershell
cd c:\Users\PC\Project\Binance-Predict-Value-And-Trend\frontend
npm run dev
```
Vite will start at **[http://localhost:5173/](http://localhost:5173/)** with automatic proxying to backend on port 8000.

---

## 9. Verification & Health Probes

Test service responsiveness using PowerShell:

```powershell
# Health check probe
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/health"

# Operational telemetry and candle count
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/system/status"

# Interactive Swagger OpenAPI documentation
# Open http://localhost:8000/docs
```

---

## 10. Running Test Suites

```powershell
# 1. Run all backend tests (API contracts, DQ engine, Marts, ML Pipeline)
$env:PYTHONPATH = "."
.venv\Scripts\python -m pytest -q

# 2. Run frontend unit tests
cd frontend
npm test

# 3. Check TypeScript types and build
npm run build
cd ..
```

---

## 11. Clean Shutdown

- Press `Ctrl + C` in each terminal window to cleanly terminate `uvicorn` and `vite`.
- SQLite database transactions commit atomically; no locks persist after process termination.
