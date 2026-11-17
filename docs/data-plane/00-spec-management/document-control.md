# Document Control & Supersession Policy

**Document ID:** `DOC-DP-00-CONTROL`  
**Version:** `1.0.0`  
**Status:** `APPROVED_PHASE_1_BASELINE`

---

## 1. Versioning & Lifecycle States

- **Semantic Versioning (`MAJOR.MINOR.PATCH`)**:
  - `MAJOR`: Incompatible contract or architectural change (`IFC-DP-*`, `ADR-DP-*`).
  - `MINOR`: Backward-compatible addition of requirements, schemas, or work items.
  - `PATCH`: Typo fix, line-reference update, or verification status update.
- **Document Status Lifecycle**: `DRAFT` -> `PHASE_1_BASELINE` -> `IMPLEMENTED_VERIFIED` (updated only after Phase 2/3 code and tests pass) -> `SUPERSEDED` (never deleted).

---

## 2. Mandatory Epistemic Evidence Tags

Every factual, diagnostic, or design statement MUST carry one of the following tags:

| Tag | Meaning | Permitted Use |
|---|---|---|
| `OBSERVED` | Directly verified in existing files, DB schemas, or on-disk artifacts | AS-IS behavior, bugs, config drift |
| `MEASURED` | Executed via command, benchmark, hardware probe, or pytest with exact output | Hardware specs, latencies, memory RSS, test counts |
| `INFERRED` | Reasoned deduction from `OBSERVED` / `MEASURED` evidence | Concurrency hazards, failure cascades not yet triggered live |
| `PROPOSED` | Target design, requirement, contract, or implementation plan | TO-BE architecture, schemas, work items |
| `UNVERIFIED` | Claim or runtime mode not executed on the current host | Docker Compose runtime, PostgreSQL live server, S3/MinIO, scaling beyond tested sizes |

---

## 3. Legacy Documentation Preservation & Supersession Map

Per repository preservation rules, **zero existing files under `docs/` are deleted or overwritten** during Phase 1–2. Where existing v2.0.0/v3.0.0 documents conflict with verified AS-IS reality or the upgraded TO-BE architecture, the `docs/data-plane/` documents take precedence:

| Legacy Document | Conflicting Claim (`OBSERVED`) | Authoritative Replacement in `docs/data-plane/` |
|---|---|---|
| `docs/10-audit/hardware-capability-report.md`, `docs/30-architecture/system-architecture.md:4`, `README.md:340-344` | Contradictory hardware specs (`i5-12400F` / `8 GB` RAM / `Python 3.12.9` vs `i5-11400H` / `16 GB` RAM) | [`repository-and-hardware-audit.md`](repository-and-hardware-audit.md) (`i5-10600KF`, `31.89 GB` RAM / `2.64 GB` free, `Python 3.14.10`, no Docker/Redis/PG) |
| `docs/40-adr/ADR-001-runtime-profiles-and-single-node-budget.md` | Assumes `LITE` single-process embedded runtime is sufficient without cross-process IPC bridge | [`ADR-DP-001`](../50-architecture-decisions/ADR-DP-001-runtime-profiles-and-process-topology.md) & [`ADR-DP-007`](../50-architecture-decisions/ADR-DP-007-serving-gateway-bridge-over-nats.md) |
| `docs/40-adr/ADR-003-hybrid-medallion-storage-parquet-duckdb-sqlite-postgres.md` | Claims in-process `:memory:` DuckDB over mutable daily Parquet is sufficient; omits manifests & persistent warehouse | [`ADR-DP-003`](../50-architecture-decisions/ADR-DP-003-immutable-data-lake-and-sql-manifests.md) & [`ADR-DP-004`](../50-architecture-decisions/ADR-DP-004-persistent-duckdb-warehouse-and-snapshots.md) |
| `docs/40-adr/ADR-004-incremental-streaming-and-microbatch-semantics.md` | Omits post-commit `BoundedDedupCache` gate, flush mutex, and SQL-first commit invariants | [`ADR-DP-002`](../50-architecture-decisions/ADR-DP-002-microbatch-durability-and-post-commit-ack.md) |
| `docs/architecture/data-flow.md:15-52,97` | References obsolete v2.0.0 table names (`raw_market_klines`, etc.) and `FastAPI.BackgroundTasks` | [`system-architecture-specification.md`](../20-architecture/system-architecture-specification.md) & [`ADR-DP-006`](../50-architecture-decisions/ADR-DP-006-durable-sql-workflow-orchestrator.md) |
| `docs/30-architecture/system-architecture.md:79,88` | Depicts nonexistent `ServingGatewayBridge` (`C3`) | [`ADR-DP-007`](../50-architecture-decisions/ADR-DP-007-serving-gateway-bridge-over-nats.md) (now designed & specified for implementation) |

> **Note (`WI-DP-15`, Phase 3):** After Phase 2 implementation and verification complete, `README.md`, `README_INSTALL.md`, `docs/audit/codebase-audit.md` (append-only reconciliation section), and `.agent/execution/MASTER_EXECUTION_STATE.md` will be updated per `AGENTS.md` Definition of Done.
