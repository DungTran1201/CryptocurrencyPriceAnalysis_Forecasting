# Binance Crypto Data Engineering, Analytics & Forecasting Platform

[![CI Pipeline](https://github.com/DungTran1201/Binance-Predict-Value-And-Trend/actions/workflows/ci.yml/badge.svg)](https://github.com/DungTran1201/Binance-Predict-Value-And-Trend/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)
[![React 18](https://img.shields.io/badge/React-18-61dafb.svg)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.6-3178c6.svg)](https://www.typescriptlang.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

An institutional-grade, end-to-end **Data Engineering, Analytics Engineering, and ML Observability Platform** for cryptocurrency markets. The project models the complete data lifecycle:
$$\text{Ingest (Bronze)} \longrightarrow \text{Validate (Silver)} \longrightarrow \text{Marts (Gold)} \longrightarrow \text{Features} \longrightarrow \text{Serve Predictions} \longrightarrow \text{Audit Quality \& Drift}$$

Designed as a demonstrable technical workbench inspired by **Apache Superset, Metabase, MLflow Tracking, and Prefect**, featuring dark technical control-plane aesthetics, zero fabricated metrics, real database-backed pipeline runs, and comprehensive data quality rule scoring.

---

## Table of Contents
1. [Architecture & Medallion Data Flow](#architecture--medallion-data-flow)
2. [Target Product Modules](#target-product-modules)
3. [Data Quality & Integrity SLA Engine](#data-quality--integrity-sla-engine)
4. [Exploratory & Quantitative Analytics Methods](#exploratory--quantitative-analytics-methods)
5. [Pipeline Orchestration & Task Execution](#pipeline-orchestration--task-execution)
6. [MLflow Observability & Gating Criteria](#mlflow-observability--gating-criteria)
7. [Quick Start & Setup Instructions](#quick-start--setup-instructions)
8. [API Route Specifications (28 Endpoints)](#api-route-specifications)
9. [Testing & Verification Evidence](#testing--verification-evidence)

---

## Architecture & Medallion Data Flow

```mermaid
graph TD
    A[Binance REST API / Vision] -->|Batch Ingest with Checkpoints| B[Bronze Layer: Ingestion Buffer]
    B -->|Schema Adherence & Geometry Validation| C[Silver Layer: Validated OHLCV Klines]
    
    subgraph Data Quality & Lineage Engine
        C --> D1[Schema & Null Checks]
        C --> D2[OHLC Logical Geometry]
        C --> D3[Key Uniqueness & Monotonic Timestamps]
        C --> D4[Interval Continuity & Gaps]
        C --> D5[Single-Bar Spike Anomaly Detection]
        C --> D6[Freshness SLA Tracking]
        D1 & D2 & D3 & D4 & D5 & D6 --> D7[(data_quality_runs & results)]
    end

    subgraph Analytical Data Marts (Gold)
        C --> E1[Simple & Log Returns Distributions]
        C --> E2[Rolling Realized Volatility: 7d, 14d, 30d]
        C --> E3[Cumulative Drawdowns & Maximum DD]
        C --> E4[Cross-Asset Pearson Correlation Matrix]
    end

    subgraph Machine Learning & Observability
        C --> F1[Zero-Leakage Technical Features: SMA, EMA, RSI, BB, MACD]
        F1 --> F2[Walk-Forward Expanding Window CV Engine]
        F2 --> F3[Model Registry & Gating Gatekeeper]
        F3 --> F4[Forecast Immutable Audit Ledger]
        F3 --> F5[MLflow Experiment Tracking Adapter]
    end

    subgraph Serving & Frontend Workbenches
        D7 --> UI1[Data Operations Overview Control Plane]
        C & E1 & E2 & E3 & E4 --> UI2[Market & Exploratory Analytics]
        C & D7 --> UI3[Data Explorer & Schema Catalog]
        F4 & F5 --> UI4[Model Lab & Prediction Studio]
    end
```

---

## Target Product Modules

### 1. Data Operations Overview (`/overview`)
The primary technical control-plane landing page:
- **Telemetry KPIs**: Total pipeline runs, success rate %, rows ingested, data quality pass rate, and candle freshness SLA.
- **Medallion Flow Graph**: Live status, record volume, and freshness timestamps across Bronze, Silver, Gold, Features, and Serving.
- **Recent Orchestrator Runs**: Real status (`SUCCESS`, `FAILED`, `RUNNING`), ingested counts, durations, and quick links.
- **Platform Workbenches**: Direct routing to specialized sub-systems.

### 2. Pipeline Observatory (`/pipelines`)
Audit trail and task-level execution runner:
- Filter historical runs by symbol, timeframe, or execution status.
- **Task Stages Breakdown**: Inspect sequential execution (`ingest_bronze` → `validate_silver` → `build_gold_marts` → `extract_features`) with duration, record counts, and execution logs.
- **Manual Trigger Studio**: Dispatches synchronous or asynchronous pipeline jobs with customizable lookback windows.

### 3. Data Quality & Lineage (`/quality`)
Rigorous data verification suite:
- **10 Automated Integrity Rules**: Evaluated against historical bars with pass/fail counts, severities, and violation sample inspection.
- **Lineage DAG**: Interactive visualization tracing upstream exchange APIs down to model prediction serving.
- **On-Demand Audit Trigger**: Immediately re-evaluates the active dataset against all data contracts.

### 4. Data Explorer & Catalog (`/explorer`)
Safe, read-only dataset exploration without direct database access:
- **Partition Inspection**: Server-side bounded pagination across Silver Klines, DQ Audit Logs, and Forecast Realizations.
- **Schema Dictionary**: Full column data types, nullability contracts, and business descriptions.
- **Dataset Profiling**: Real-time record counts, time coverage start, and latest closed watermarks.
- **Bounded CSV Export**: One-click download of filtered dataset partitions.

### 5. Market & Exploratory Analytics (`/analytics`)
Quantitative research workbench:
- **Candlestick & Indicator Chart**: Dynamic canvas with moving averages, Bollinger Bands, and RSI/MACD sub-charts.
- **Return Distributions & Moments**: Empirical $\mu$, $\sigma$, Skewness, Kurtosis, Value-at-Risk ($VaR_{95\%}, VaR_{99\%}$), and binned return frequency histograms.
- **Rolling Realized Volatility**: Multi-window annualized volatility series ($7, 14, 30$ periods).
- **Drawdown Trajectory**: Peak progression, current drawdown %, and maximum drawdown (MDD) callouts.
- **Pairwise Correlation Matrix**: Pearson correlation coefficients across BTC, ETH, BNB, and SOL returns.

### 6. Forecast Lab & Prediction Studio (`/studio`, `/history`)
Research-oriented time-series forecasting:
- Multi-step ahead point-in-time predictions with frozen cutoff timestamps.
- Calibrated directional probabilities and empirical 95% confidence intervals.
- Immutable forecast ledger with realization tracking once actual prices close.

### 7. Model Lab & MLflow Observability (`/models`)
Walk-forward model training and registry:
- Chronological walk-forward CV without future look-ahead leakage.
- **Promotion Gating**: Strict enforcement requiring candidates to outperform naive persistence baselines before activation.
- **MLflow Tracking Adapter**: Connection status indicator (`REMOTE_MLFLOW` vs `LOCAL_REGISTRY_FALLBACK`) with hyperparameter logging.

### 8. System Health (`/system`)
Liveness and readiness monitoring:
- Database connectivity, stored candle counters, sync checkpoint trackers, and worker status.

---

## Data Quality & Integrity SLA Engine

Every market partition is evaluated by 10 programmatic rules:

| Rule ID | Rule Name | Category | Severity | Failure Condition |
| :--- | :--- | :--- | :--- | :--- |
| **DQ-SCH-01** | Schema & Type Adherence | SCHEMA | CRITICAL | Column types differ from float/int/datetime |
| **DQ-NUL-01** | Non-Null Price & Timestamps | COMPLETENESS | CRITICAL | Null or NaN values in OHLCV columns |
| **DQ-UNI-01** | Primary Key Uniqueness | INTEGRITY | CRITICAL | Duplicate `(symbol, timeframe, open_time)` |
| **DQ-ORD-01** | Monotonic Ordering | CONSISTENCY | ERROR | Out-of-order timestamp step ($t_i \le t_{i-1}$) |
| **DQ-GAP-01** | Interval Continuity | CONSISTENCY | WARNING | Gap exceeding $1.5\times$ expected interval delta |
| **DQ-REL-01** | OHLC Price Geometry | INTEGRITY | CRITICAL | $High < Low$ or extremes fail to bound $Open / Close$ |
| **DQ-VOL-01** | Non-Negative Volume | INTEGRITY | ERROR | Base or quote asset volume $< 0$ |
| **DQ-FUT-01** | Timestamp Temporal Validity | CONSISTENCY | CRITICAL | Candle open timestamp $> now\_utc$ |
| **DQ-OUT-01** | Extreme Price Spike Flag | ANOMALY | WARNING | Single-bar price change $> 35\%$ (flagged for review) |
| **DQ-FRE-01** | Freshness SLA Adherence | COMPLETENESS | WARNING | Latest closed candle exceeds allowable delay window |

---

## Exploratory & Quantitative Analytics Methods

### 1. Return Distributions & Higher Moments
Given closing prices $P_t$, simple returns $R_t = \frac{P_t - P_{t-1}}{P_{t-1}}$ and log returns $r_t = \ln(P_t / P_{t-1})$:
- **Sample Mean ($\mu$)**: $\frac{1}{N} \sum R_t$
- **Sample Variance ($\sigma^2$)**: $\frac{1}{N-1} \sum (R_t - \mu)^2$
- **Fisher-Pearson Skewness**:
  $$S = \frac{\frac{1}{N}\sum (R_t - \mu)^3}{\left(\frac{1}{N}\sum (R_t - \mu)^2\right)^{3/2}}$$
- **Excess Kurtosis**:
  $$K = \frac{\frac{1}{N}\sum (R_t - \mu)^4}{\left(\frac{1}{N}\sum (R_t - \mu)^2\right)^2} - 3$$
- **Value-at-Risk ($VaR_\alpha$)**: Empirical quantile $Q(\alpha)$ representing maximum loss at confidence $(1-\alpha)$.

### 2. Rolling Realized Volatility
Annualized rolling standard deviation over lookback window $W$:
$$\sigma_{annual} = \sigma_W(R_t) \times \sqrt{P_{year}}$$
where $P_{year} = 365 \times 24$ for hourly candles.

### 3. Drawdowns & Maximum Drawdown (MDD)
Cumulative running peak $Peak_t = \max_{s \le t} (P_s)$ and drawdown $DD_t = \frac{P_t - Peak_t}{Peak_t}$.
$$\text{MDD} = \min_{t} (DD_t)$$

### 4. Pairwise Cross-Asset Correlation Matrix
For aligned return series $X$ and $Y$:
$$\rho_{X, Y} = \frac{\sum (X_t - \bar{X})(Y_t - \bar{Y})}{\sqrt{\sum (X_t - \bar{X})^2 \sum (Y_t - \bar{Y})^2}}$$

---

## Quick Start & Setup Instructions

### Prerequisites
- Python 3.12+
- Node.js 18+ (tested on Node v24.18.0)
- SQLite (built-in) or PostgreSQL

### 1. Backend Setup
```bash
# Activate virtual environment
.venv\Scripts\activate   # Windows
# source .venv/bin/activate # Linux/macOS

# Install dependencies
pip install -r requirements.txt

# Run database table initialization
python -c "import asyncio; from backend.app.core.database import init_db; asyncio.run(init_db())"

# Start FastAPI server
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 2. Frontend Setup
```bash
cd frontend
npm install
npm run build    # Compiles to frontend/dist (auto-served by FastAPI at http://localhost:8000/)
# Or run Vite dev server:
npm run dev
```

### 3. Run Backend & Frontend Verification Tests
```bash
# Backend pytest suite (28 tests covering contracts, DQ engine, analytics, and pipelines)
python -m pytest -q

# Frontend unit tests
cd frontend
npm test

# Frontend TypeScript check and production build
npm run build
```

---

## API Route Specifications

| Method | Path | Summary | Tags |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/health` | Service liveness and version probe | System |
| `GET` | `/api/v1/system/status` | Operational status, DB connectivity, checkpoints | System |
| `GET` | `/api/v1/pipelines/overview` | Pipeline runs, success rate, throughput stats | Pipelines |
| `GET` | `/api/v1/pipelines/runs` | Historical runs with status/symbol filters | Pipelines |
| `GET` | `/api/v1/pipelines/runs/{id}` | Task stages breakdown, record counts, and logs | Pipelines |
| `POST` | `/api/v1/pipelines/trigger` | Trigger synchronous or asynchronous Medallion run | Pipelines |
| `GET` | `/api/v1/data-quality/overview`| Platform data quality pass rates and rule summary | Data Quality |
| `GET` | `/api/v1/data-quality/lineage` | Medallion data lineage DAG (nodes and edges) | Data Quality |
| `GET` | `/api/v1/data-quality/runs` | Historical quality evaluation runs | Data Quality |
| `GET` | `/api/v1/data-quality/runs/{id}`| Detailed rule results and violation samples | Data Quality |
| `POST` | `/api/v1/data-quality/evaluate`| Trigger on-demand quality audit on symbol/timeframe | Data Quality |
| `GET` | `/api/v1/data-explorer/datasets`| List queryable datasets and schema dictionaries | Data Explorer |
| `GET` | `/api/v1/data-explorer/preview` | Paginated dataset records and profile stats | Data Explorer |
| `GET` | `/api/v1/data-explorer/export` | Bounded downloadable CSV extract | Data Explorer |
| `GET` | `/api/v1/analytics/returns` | Return distributions, skewness, kurtosis, VaR | Analytics |
| `GET` | `/api/v1/analytics/volatility` | Rolling annualized volatility across 7, 14, 30 periods | Analytics |
| `GET` | `/api/v1/analytics/drawdowns` | Cumulative peak series, drawdown %, and MDD | Analytics |
| `GET` | `/api/v1/analytics/correlations`| Pairwise Pearson correlation matrix across assets | Analytics |
| `GET` | `/api/v1/market/symbols` | Registered asset symbols and sync status flags | Market |
| `GET` | `/api/v1/market/klines` | Validated OHLCV bars and technical indicators | Market |
| `POST` | `/api/v1/market/sync` | Incremental candle synchronization | Market |
| `GET` | `/api/v1/forecasts` | Paginated immutable forecast history | Forecasts |
| `POST` | `/api/v1/forecasts/generate` | Generate multi-horizon price & direction prediction | Forecasts |
| `POST` | `/api/v1/forecasts/reconcile`| Reconcile pending forecasts with actual outcomes | Forecasts |
| `GET` | `/api/v1/models` | Registered models and walk-forward metrics | Models |
| `GET` | `/api/v1/models/experiments` | MLflow experiment runs and hyperparameters | Models |
| `GET` | `/api/v1/models/tracking-status`| Probe remote MLflow server vs local registry fallback | Models |
| `POST` | `/api/v1/models/train` | Execute walk-forward cross validation with gating | Models |

---

## Testing & Verification Evidence

All test suites execute deterministically without external network dependencies:
- **Backend Test Suite**: `python -m pytest -q` passes **28/28 tests** in ~7.2s.
- **Frontend Test Suite**: `npm test` passes **5/5 unit tests** in ~0.2s.
- **Frontend Compilation**: `tsc && vite build` transforms 1584 modules and builds production bundles with **0 errors**.
- **Browser Subagent Live Verification**: Verified all 9 interactive views on `http://localhost:8000/`.

---

## License
MIT License. Free for educational and commercial crypto market analysis.