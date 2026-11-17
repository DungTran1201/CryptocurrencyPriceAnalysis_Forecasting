# 30-detailed-design — Detailed Component & Storage Design

## 1. Purpose

This folder stores the **component-level engineering designs** for the upgraded Cryptocurrency Market Data Plane (`COMP-DP-01` through `COMP-DP-13`). Each document translates the system architecture (`../20-architecture/`) and architecture decision records (`../50-architecture-decisions/`) into concrete module designs, invariants, state machines, storage layouts, concurrency models, and failure-handling sequences ready for Phase 2 implementation (`WI-DP-02` through `WI-DP-13`).

## 2. Document Types Stored

- **Subsystem Detailed Designs** (`*-design.md`): Deep-dive behavioral, concurrency, storage, and recovery specifications per subsystem.
- **Technical Diagrams** (`diagrams-*.md`): Labeled Mermaid flowcharts, sequence diagrams, state machines, ERDs, and star-schema diagrams (`[AS-IS]` vs `[TO-BE]`).

Current index:

| File | Owner Role | Covered Components & IDs |
|---|---|---|
| `data-lake-design.md` | Data Engineering | `COMP-DP-04`, `ADR-DP-003`, `REQ-DP-LAKE-01..06`, `REQ-DP-KLN-01`, `WI-DP-04`, `WI-DP-05` |
| `data-warehouse-design.md` | Data Engineering | `COMP-DP-06`, `ADR-DP-004`, `REQ-DP-DW-01..03`, `WI-DP-06` |
| `data-quality-design.md` | Data Engineering | `COMP-DP-10`, `REQ-DP-DEL-04`, `REQ-DP-LAKE-06`, `WI-DP-02`, `WI-DP-09` |
| `diagrams-storage-and-warehouse.md` | Data Engineering | Visual `[AS-IS]` / `[TO-BE]` Medallion flow, Metadata ERD, Star Schema, Snapshot Swap, Retention Lifecycle |
| `ingestion-and-streaming-design.md` | Streaming & Orchestration | `COMP-DP-01`, `COMP-DP-02`, `REQ-DP-ING-01..04`, `WI-DP-03` |
| `reliability-and-recovery-design.md` | Streaming & Orchestration | `COMP-DP-03`, `COMP-DP-13`, `ADR-DP-002`, `REQ-DP-DEL-01..06`, `WI-DP-02` |
| `hot-state-and-cache-design.md` | Streaming & Orchestration | `COMP-DP-07`, `COMP-DP-08`, `ADR-DP-005`, `ADR-DP-007`, `REQ-DP-HOT-01`, `REQ-DP-SRV-01`, `WI-DP-08` |
| `orchestration-design.md` | Streaming & Orchestration | `COMP-DP-09`, `ADR-DP-006`, `REQ-DP-ORC-01..04`, `WI-DP-07` |
| `diagrams-streaming-and-orchestration.md` | Streaming & Orchestration | Visual `[AS-IS]` / `[TO-BE]` Ingestion, Bridge, Micro-Batch State Machine, Workflow DAG & Lease Diagrams |

## 3. Naming Rules

- Lowercase kebab-case Markdown files (`<domain>-design.md` or `diagrams-<scope>.md`).
- Diagram files must prefix every Mermaid diagram title/heading with `[AS-IS]`, `[TO-BE]`, or `[TRANSITION]`.
- Every engineering claim must carry an evidence tag: `OBSERVED`, `MEASURED`, `INFERRED`, `PROPOSED`, `UNVERIFIED`, or `TARGET_TO_BE_ESTABLISHED`.

## 4. Document Structure

Each `*-design.md` document follows a consistent layout:
1. **Scope, Requirements & Components** (referencing `REQ-DP-*`, `COMP-DP-*`, `ADR-DP-*`, `IFC-DP-*`, `WI-DP-*`).
2. **AS-IS Defects & Evidence** (exact `file:line` citations and runtime measurements).
3. **TO-BE Design & Invariants** (algorithms, state transitions, schemas, concurrency/locking rules).
4. **Failure Modes & Edge Cases** (error handling, partial failure recovery, profile constraints).
5. **Implementation & Verification Mapping** (`WI-DP-*` file boundaries and test requirements).

## 5. Cross-Folder Relationships

- **Upstream**:
  - `../10-requirements/` defines mandatory `REQ-DP-*` requirements and resource budgets.
  - `../20-architecture/` defines container and process boundaries.
  - `../50-architecture-decisions/` records binding choices (`ADR-DP-001..007`).
- **Lateral**:
  - `../40-interfaces-and-contracts/` captures exact SQL DDLs, Arrow schemas, NATS subjects, KV buckets, and REST/Config contracts (`IFC-DP-001..011`).
  - `../60-security-and-governance/` captures catalog, lineage, retention, and security controls.
- **Downstream**:
  - `../70-testing/` and `../80-operations/` derive fault-injection tests, runbooks, and alerts from the invariants defined here.

## 6. Agent Rules for Creating and Updating

1. Reference canonical IDs from `../00-spec-management/` rather than inventing ad-hoc names.
2. Never duplicate exact wire schemas or SQL DDL verbatim when `../40-interfaces-and-contracts/` is the normative contract; cross-reference `IFC-DP-*` and focus here on behavior, algorithms, and concurrency invariants.
3. Preserve strict non-overlapping ownership between Data Engineering files and Streaming/Orchestration files.
4. Keep Mermaid labels quoted when containing special characters (`()`, `[]`, `:`, `/`) and avoid raw HTML tags.

## 7. Exclusions (What Does NOT Belong Here)

- High-level C4 context/container architecture (`../20-architecture/`).
- ADR rationale and rejected alternatives (`../50-architecture-decisions/`).
- Full test cases, pytest fixtures, or operational runbooks (`../70-testing/`, `../80-operations/`).
- Unverified hardware claims or speculative performance targets (`TARGET_TO_BE_ESTABLISHED` must be preserved).
