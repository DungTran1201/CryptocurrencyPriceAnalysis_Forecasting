# 80 — Operations and Runbooks

## Purpose
Provides operational guides, deployment topologies, monitoring and alerting rules, backup/restore procedures, troubleshooting playbooks, and the authoritative production-readiness checklist for running the Data Plane reliably on single-node Windows and Linux hosts.

## Document Types Stored
- **Deployment & Environment Guides:** Profile topologies (`LITE`, `STANDARD`, `EXTENDED`), environment variable references, Windows/Linux launcher workflows, and host prerequisite constraints.
- **Monitoring & Alerting Specs:** Prometheus scrape topology, active staleness/lag rules, disk/memory alert thresholds, and structured logging standards.
- **Runbooks & Playbooks:** Backup/restore procedures, NATS replay & DLQ recovery, gap backfill, rollback paths, and symptom-to-fix troubleshooting.
- **Readiness Gate:** `production-readiness-checklist.md` tracking Phase 1 -> Phase 3 evidence status honestly.

## Naming Rules
- Lowercase `kebab-case.md` filenames (`deployment-and-env-guide.md`, `monitoring-and-alerting-spec.md`, `backup-restore-and-recovery-runbook.md`, `rollback-and-troubleshooting.md`, `production-readiness-checklist.md`).
- Folder index is always `README.md`.

## Document Structure
Every document in this folder MUST include:
1. Header block (`Document ID`, `Status`, `Owner`, `Applies To`).
2. Verified host/environment preconditions (referencing `DP-SPEC-001`).
3. Exact commands (using `.venv\Scripts\python.exe`, `nats-server.exe`, or explicit Docker caveats) and clear rollback/verification steps.
4. Honest status indicators (`PASS`, `FAIL`, `UNVERIFIED`, `NOT_APPLICABLE`) where readiness is assessed.

## Cross-Folder Relationships
- **From `00-spec-management/`:** Grounded in host toolchain and `data/` layout audited in `repository-and-hardware-audit.md`.
- **From `10-requirements/`:** Implements operational thresholds and `IFC-DP-010` metrics from `performance-and-resource-targets.md`.
- **From `30-detailed-design/` & `50-architecture-decisions/`:** Operationalizes `ADR-DP-001..007` (DuckDB snapshot swaps, NATS `MEMORY` KV, SQL workflow reaper, `ServingGatewayBridge`).
- **From `70-testing/`:** Links readiness sign-off directly to `TC-DP-*` and `TC-DP-PERF-*` execution reports.

## Agent Rules
- **Verify every command and path against the host:** Do not instruct operators to run `docker compose` or `redis-cli` on hosts where they are absent without flagging host constraints.
- **Preserve honesty on readiness:** Never mark a checklist gate `PASS` until Phase 2/3 tests and measurements prove it on the target runtime.
- **Owner:** `@sre-qa` maintains all documents under `80-operations/`.

## Exclusions
- Does NOT store architecture rationales (see `50-architecture-decisions/`).
- Does NOT store threat models or token design specs (see `60-security-and-governance/`).
- Does NOT store test case steps or defect catalogs (see `70-testing/`).
