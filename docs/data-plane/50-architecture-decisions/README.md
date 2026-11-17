# `50-architecture-decisions/` — Architecture Decision Records (`ADR-DP-*`)

## 1. Purpose
This folder records binding architectural decisions (`ADR-DP-001` through `ADR-DP-007`) governing runtime process topology, streaming durability semantics, immutable Lakehouse manifests, persistent DuckDB snapshots, hot-state caching vs Redis, durable workflow orchestration, and the cross-process Serving Gateway Bridge.

## 2. Document Types Stored
- ADR Registry Index & Supersession Map (`ADR-INDEX.md`)
- Individual Decision Records (`ADR-DP-<NNN>-<short-kebab-slug>.md`)

## 3. Naming Rules
- `ADR-INDEX.md` (uppercase prefix) for the registry.
- `ADR-DP-<NNN>-<kebab-title>.md` for individual records (e.g., `ADR-DP-004-persistent-duckdb-warehouse-and-snapshots.md`).

## 4. Document Structure
Every ADR contains: Metadata Header, Context & Observed/Measured Evidence, Options Evaluated, Decision, Positive/Negative Consequences, and Traceability Links.

## 5. Cross-Folder Relationships
- Informed by baseline findings in [`00-spec-management/`](../00-spec-management/README.md) and [`10-requirements/`](../10-requirements/README.md).
- Shapes [`20-architecture/`](../20-architecture/README.md) and constrains [`30-detailed-design/`](../30-detailed-design/README.md) and [`40-interfaces-and-contracts/`](../40-interfaces-and-contracts/README.md).

## 6. Agent Rules for Creating & Updating
- Never overwrite legacy ADRs in `docs/40-adr/`; mark supersession explicitly in `ADR-INDEX.md` and the individual ADR header.
- Any structural change to process boundaries, storage formats, or broker usage in Phase 2 requires updating the corresponding `ADR-DP-*` first.

## 7. What Does NOT Belong Here
- Full SQL DDL, column dictionaries, or API JSON schemas (belongs in `40-interfaces-and-contracts/`).
- Step-by-step operational checklists (belongs in `80-operations/`).
