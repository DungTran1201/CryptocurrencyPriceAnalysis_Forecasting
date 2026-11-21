# `10-requirements/` — Data Plane Requirements & Resource Targets

## 1. Purpose
This folder defines all formal functional requirements, reliability invariants, security/isolation requirements, and resource/performance targets for the Data Plane upgrade.

## 2. Document Types Stored
- Formal Functional & Non-Functional Data Plane SRS (`data-plane-srs.md`)
- Baseline Measurements, `TARGET_TO_BE_ESTABLISHED` Resource/Latency Targets & Prometheus Metrics Contract (`performance-and-resource-targets.md`)

## 3. Naming Rules
- Files use lowercase kebab-case `.md`.
- Every requirement MUST carry a canonical `REQ-DP-<AREA>-<NN>` identifier registered in [`00-spec-management/traceability-matrix.md`](../00-spec-management/traceability-matrix.md).
- Every metric or latency ceiling MUST state whether it is `MEASURED` or `TARGET_TO_BE_ESTABLISHED`.

## 4. Document Structure
Each requirement entry contains: `ID`, `Scope Tier` (`Mandatory` vs `Aspirational/Optional`), `Context & Evidence`, `Statement`, `Acceptance Criteria`, and `Verification Method`.

## 5. Cross-Folder Relationships
- Derived from findings in [`00-spec-management/`](../00-spec-management/README.md).
- Realized by [`20-architecture/`](../20-architecture/README.md), [`30-detailed-design/`](../30-detailed-design/README.md), and [`50-architecture-decisions/`](../50-architecture-decisions/README.md).
- Verified by [`70-testing/`](../70-testing/README.md).

## 6. Agent Rules for Creating & Updating
- Never invent unmeasured numeric SLO targets; mark unmeasured targets `TARGET_TO_BE_ESTABLISHED` until benchmarked in Phase 2/3.
- Preserve clear separation between **Mandatory** single-node requirements (`LITE` / `STANDARD` native) and **Aspirational / Optional** capabilities (`EXTENDED` Docker/Postgres/MinIO/Redis).

## 7. What Does NOT Belong Here
- Architectural trade-off rationale (belongs in `50-architecture-decisions/`).
- Detailed DDL, Parquet column layouts, or NATS payload schemas (belongs in `40-interfaces-and-contracts/`).
- Step-by-step operator recovery runbooks (belongs in `80-operations/`).
