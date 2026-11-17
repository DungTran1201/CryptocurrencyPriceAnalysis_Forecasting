# Data Plane System Specification Pack (`docs/data-plane/`)

**Project:** Resource-Efficient Real-Time Financial Data Intelligence Platform (`CryptocurrencyPriceAnalysis_Forecasting`)  
**Spec Version:** `1.0.0-draft` (Phase 1 Architecture & Design Baseline)  
**Baseline Git Commit:** `95496ac` (`feat/realtime-data-platform`)  
**Scope:** End-to-end production upgrade of the Data Plane (ingestion, NATS JetStream broker, stream processing, Medallion Data Lake, persistent DuckDB Data Warehouse, hot state/cache, durable workflow orchestration, cross-process Serving Gateway Bridge, governance, observability, security, testing, and operations).

---

## 1. Purpose & Non-Destructive Governance Policy

1. This directory holds the canonical **Data Plane Production Upgrade Specification Pack**.
2. Existing repository documentation under `docs/10-audit/`, `docs/20-requirements/`, `docs/30-architecture/`, `docs/40-adr/`, `docs/architecture/`, `docs/audit/`, and `docs/design/` is **preserved untouched** as historical v2.0.0/v3.0.0 project records. Supersessions are explicitly recorded in [`00-spec-management/document-control.md`](00-spec-management/document-control.md) and [`50-architecture-decisions/ADR-INDEX.md`](50-architecture-decisions/ADR-INDEX.md).
3. All claims in this specification pack carry explicit epistemic labels:
   - **`OBSERVED`**: Directly verified in repository source files, configs, schemas, or on-disk data.
   - **`MEASURED`**: Directly executed and recorded via benchmark, hardware probe, or test command on the target host.
   - **`INFERRED`**: Logically derived from observed code or measured runtime behavior.
   - **`PROPOSED`**: Target-state architecture, contract, or work package to be implemented in Phase 2.
   - **`UNVERIFIED`**: Not yet executed or proven in the current environment.

---

## 2. Folder Taxonomy & Quick Navigation

| Folder | Role | Entry Point |
|---|---|---|
| [`00-spec-management/`](00-spec-management/README.md) | Master index, governance, glossary, principles, hardware audit, gap analysis, traceability, WI board, changelog | [`document-index.md`](00-spec-management/document-index.md) |
| [`10-requirements/`](10-requirements/README.md) | Formal Data Plane requirements (`REQ-DP-*`) and performance/resource targets | [`data-plane-srs.md`](10-requirements/data-plane-srs.md) |
| [`20-architecture/`](20-architecture/README.md) | Target 3-plane decoupled architecture, process topology, and C4/deployment diagrams | [`system-architecture-specification.md`](20-architecture/system-architecture-specification.md) |
| [`30-detailed-design/`](30-detailed-design/README.md) | Component-level designs for ingestion, durability, lake, warehouse, hot state, DQ, and orchestration | [`README.md`](30-detailed-design/README.md) |
| [`40-interfaces-and-contracts/`](40-interfaces-and-contracts/README.md) | Canonical schemas, NATS subjects/KV contracts, DDL/Parquet contracts, APIs, and configuration specs | [`README.md`](40-interfaces-and-contracts/README.md) |
| [`50-architecture-decisions/`](50-architecture-decisions/README.md) | Architectural Decision Records (`ADR-DP-001` through `ADR-DP-007`) | [`ADR-INDEX.md`](50-architecture-decisions/ADR-INDEX.md) |
| [`60-security-and-governance/`](60-security-and-governance/README.md) | Threat model, auth/error sanitization, test isolation, catalog, lineage, and manifest-safe retention | [`README.md`](60-security-and-governance/README.md) |
| [`70-testing/`](70-testing/README.md) | Risk-based test strategy, `TC-DP-*` catalog, fault injection (`S1..S14`), and performance specs | [`README.md`](70-testing/README.md) |
| [`80-operations/`](80-operations/README.md) | Deployment runbooks, monitoring/alerting, backup/restore, rollback, and readiness checklist | [`README.md`](80-operations/README.md) |

---

## 3. Authoritative Host & Baseline Summary (`MEASURED` / `OBSERVED`)

- **Host CPU & OS (`MEASURED`):** Windows 10 Enterprise (`10.0.19045`), Intel Core i5-10600KF (6 cores / 12 threads, 4.10 GHz).
- **Host RAM & Disk (`MEASURED`):** `31.89 GB` total physical RAM, **`2.64 GB` currently available** (`91.7%` used by concurrent host workloads); `78.19 GB` free on `C:\` SSD (`118.52 GB` total).
- **Host Toolchain (`MEASURED`):** `.venv` Python `3.14.10` (`fastapi 0.163.1`, `duckdb 2.0.0`, `pyarrow 26.0.1`, `SQLAlchemy 2.1.9`, `nats-py 2.16.0`), `.bin/nats-server.exe v2.15.3` (running, `63.25 MB` WS), Node `v26.13.1` / npm `11.20.0`, Git `2.56.1`. **Docker, WSL2, Redis, and PostgreSQL are absent on host.**
- **Baseline Tests (`MEASURED`):** `.venv\Scripts\python.exe -m pytest -v` passes **`43 passed in 12.86s`**, with critical gaps in process isolation, streaming durability (`BoundedDedupCache` pre-commit skip), SQL/Silver divergence, and test `data/` isolation (`tests/test_api_and_security.py:68-73` retention against live `./data/`).
