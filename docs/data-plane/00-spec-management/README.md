# `00-spec-management/` — Specification Management & Governance

## 1. Purpose
This folder governs the structure, vocabulary, baseline evidence, architectural principles, gap analysis, end-to-end traceability, and Phase 2 work-item allocation for the `docs/data-plane/` specification pack.

## 2. Document Types Stored
- Master document index and navigation (`document-index.md`)
- Versioning, supersession, and review policy (`document-control.md`)
- Canonical technical glossary (`glossary.md`)
- Authoritative hardware, toolchain, and test baseline audit (`repository-and-hardware-audit.md`)
- Non-negotiable engineering and architectural principles (`architecture-principles.md`)
- AS-IS vs TO-BE gap matrix, KEEP/IMPROVE/REPLACE/ADD/REMOVE register, and risk register (`gap-analysis-and-upgrade-decisions.md`)
- Master traceability matrix (`traceability-matrix.md`)
- Phase 2/3 non-overlapping work-item board (`work-item-board.md`)
- Specification change log (`change-log.md`)

## 3. Naming Rules
- All filenames use lowercase kebab-case with `.md` extension (e.g., `architecture-principles.md`).
- Canonical IDs defined here MUST be referenced verbatim across all downstream folders:
  - Requirements: `REQ-DP-<AREA>-<NN>`
  - Components: `COMP-DP-<NN>`
  - ADRs: `ADR-DP-<NNN>`
  - Interfaces/Contracts: `IFC-DP-<NNN>`
  - Work Items: `WI-DP-<NN>`
  - Test Cases: `TC-DP-001..029` / `TC-DP-FI-01..14` / `TC-DP-PERF-01..05`

## 4. Document Structure
Every document in this folder starts with a metadata header (Document ID, Version, Status, Owner Role, Upstream Dependencies) followed by numbered sections, evidence-tagged tables (`OBSERVED`, `MEASURED`, `INFERRED`, `PROPOSED`, `UNVERIFIED`), and explicit cross-links.

## 5. Cross-Folder Relationships
- Feeds requirement IDs to [`10-requirements/`](../10-requirements/README.md).
- Maps component IDs to [`20-architecture/`](../20-architecture/README.md) and [`30-detailed-design/`](../30-detailed-design/README.md).
- Anchors decision authority in [`50-architecture-decisions/`](../50-architecture-decisions/README.md) and verification coverage in [`70-testing/`](../70-testing/README.md).

## 6. Agent Rules for Creating & Updating
- Never invent new IDs in `30-detailed-design/` through `80-operations/` without registering them in `traceability-matrix.md` and `work-item-board.md`.
- File ownership in `work-item-board.md` must remain strictly disjoint per implementation work item before Phase 2 starts.
- Do not modify `repository-and-hardware-audit.md` without re-executing read-only host/pytest probes.

## 7. What Does NOT Belong Here
- Formal functional/non-functional acceptance criteria (belongs in `10-requirements/`).
- Code-level state machines, SQL DDL, or Arrow schemas (belongs in `30-detailed-design/` and `40-interfaces-and-contracts/`).
- Operational CLI runbooks (belongs in `80-operations/`).
