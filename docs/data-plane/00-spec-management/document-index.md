# Master Document Index (`docs/data-plane/`)

**Document ID:** `DOC-DP-00-INDEX`  
**Version:** `1.0.0`  
**Status:** `APPROVED_PHASE_1_BASELINE`

---

## Complete Specification Pack Catalog

| Folder | File | Owner Role | Purpose |
|---|---|---|---|
| Root | [`docs/data-plane/README.md`](../README.md) | Architect | Top-level entry point and navigation |
| `00-spec-management/` | [`README.md`](README.md) | Architect | Folder rules and governance |
| `00-spec-management/` | [`document-index.md`](document-index.md) | Architect | Master file catalog |
| `00-spec-management/` | [`document-control.md`](document-control.md) | Architect | Versioning, evidence tags, and legacy supersession map |
| `00-spec-management/` | [`glossary.md`](glossary.md) | Architect | Authoritative domain and platform definitions |
| `00-spec-management/` | [`repository-and-hardware-audit.md`](repository-and-hardware-audit.md) | SRE / QA | Measured host hardware, toolchain, and test baseline |
| `00-spec-management/` | [`architecture-principles.md`](architecture-principles.md) | Architect | Engineering invariants and design rules |
| `00-spec-management/` | [`gap-analysis-and-upgrade-decisions.md`](gap-analysis-and-upgrade-decisions.md) | Architect | AS-IS vs TO-BE matrix, KEEP/IMPROVE/REPLACE/ADD/REMOVE, risk register |
| `00-spec-management/` | [`traceability-matrix.md`](traceability-matrix.md) | Architect | End-to-end `REQ -> COMP -> ADR -> IFC -> WI -> TC` mapping |
| `00-spec-management/` | [`work-item-board.md`](work-item-board.md) | Architect | Phase 2/3 wave plan and non-overlapping file ownership |
| `00-spec-management/` | [`change-log.md`](change-log.md) | Architect | Specification revision history |
| `10-requirements/` | [`README.md`](../10-requirements/README.md) | Architect | Requirements folder governance |
| `10-requirements/` | [`data-plane-srs.md`](../10-requirements/data-plane-srs.md) | Architect | Formal `REQ-DP-*` functional & non-functional requirements |
| `10-requirements/` | [`performance-and-resource-targets.md`](../10-requirements/performance-and-resource-targets.md) | SRE / QA | Measured baselines, `TARGET_TO_BE_ESTABLISHED`, `IFC-DP-010` metrics |
| `20-architecture/` | [`README.md`](../20-architecture/README.md) | Architect | Architecture folder governance |
| `20-architecture/` | [`system-architecture-specification.md`](../20-architecture/system-architecture-specification.md) | Architect | 3-plane decoupled target architecture and `COMP-DP-*` specs |
| `20-architecture/` | [`diagrams-architecture.md`](../20-architecture/diagrams-architecture.md) | Architect | Context, C4 Container (AS-IS vs TO-BE), Component, Deployment, Roadmap diagrams |
| `30-detailed-design/` | [`README.md`](../30-detailed-design/README.md) | Data Eng | Detailed design folder governance |
| `30-detailed-design/` | [`data-lake-design.md`](../30-detailed-design/data-lake-design.md) | Data Eng | Immutable Bronze/Silver/Gold lake, manifests, compaction, schema evolution |
| `30-detailed-design/` | [`data-warehouse-design.md`](../30-detailed-design/data-warehouse-design.md) | Data Eng | Persistent DuckDB star schema, single-writer lease, `dw-v{N}.duckdb` snapshots |
| `30-detailed-design/` | [`data-quality-design.md`](../30-detailed-design/data-quality-design.md) | Data Eng | 10+ SLA rules, `agg_trade_id` continuity, cross-layer parity, non-splitting commits |
| `30-detailed-design/` | [`diagrams-storage-and-warehouse.md`](../30-detailed-design/diagrams-storage-and-warehouse.md) | Data Eng | Storage, ERD, Star Schema, Snapshot, and Retention Mermaid diagrams |
| `30-detailed-design/` | [`ingestion-and-streaming-design.md`](../30-detailed-design/ingestion-and-streaming-design.md) | Stream / Orch | WS reconnect, aggTrade/1m gap heal, producer spill, NATS `_conn_epoch` |
| `30-detailed-design/` | [`reliability-and-recovery-design.md`](../30-detailed-design/reliability-and-recovery-design.md) | Stream / Orch | Micro-batch state machine, post-commit dedup/ACK, closed-bar ordering, DLQ replay |
| `30-detailed-design/` | [`hot-state-and-cache-design.md`](../30-detailed-design/hot-state-and-cache-design.md) | Stream / Orch | `HotStateCache` over NATS JetStream KV (`StorageType.MEMORY`) + bounded `TTLCache` |
| `30-detailed-design/` | [`orchestration-design.md`](../30-detailed-design/orchestration-design.md) | Stream / Orch | SQL durable workflow engine, leases, heartbeats, reaper, schedules |
| `30-detailed-design/` | [`diagrams-streaming-and-orchestration.md`](../30-detailed-design/diagrams-streaming-and-orchestration.md) | Stream / Orch | Streaming, Bridge, State Machine, Recovery, and Workflow DAG diagrams |
| `40-interfaces-and-contracts/` | [`README.md`](../40-interfaces-and-contracts/README.md) | Stream / Orch | Interface contracts folder governance |
| `40-interfaces-and-contracts/` | [`storage-and-database-schemas.md`](../40-interfaces-and-contracts/storage-and-database-schemas.md) | Data Eng | `IFC-DP-005`, `IFC-DP-006`, `IFC-DP-008` DDL, Arrow schemas, `StorageBackend` v2 |
| `40-interfaces-and-contracts/` | [`api-and-service-contracts.md`](../40-interfaces-and-contracts/api-and-service-contracts.md) | Stream / Orch | `IFC-DP-007` workflow REST & API boundary rules |
| `40-interfaces-and-contracts/` | [`event-and-message-contracts.md`](../40-interfaces-and-contracts/event-and-message-contracts.md) | Stream / Orch | `IFC-DP-001..004`, `IFC-DP-009` events, subjects, JetStream, KV, `HotStateCache` |
| `40-interfaces-and-contracts/` | [`configuration-specification.md`](../40-interfaces-and-contracts/configuration-specification.md) | Stream / Orch | `IFC-DP-011` unified `config.yaml`, `.env`, `Settings`, dependency pinning |
| `50-architecture-decisions/` | [`README.md`](../50-architecture-decisions/README.md) | Architect | ADR folder governance |
| `50-architecture-decisions/` | [`ADR-INDEX.md`](../50-architecture-decisions/ADR-INDEX.md) | Architect | ADR summary & supersession registry |
| `50-architecture-decisions/` | [`ADR-DP-001-runtime-profiles-and-process-topology.md`](../50-architecture-decisions/ADR-DP-001-runtime-profiles-and-process-topology.md) | Architect | `LITE` vs `STANDARD` vs optional `EXTENDED` topology |
| `50-architecture-decisions/` | [`ADR-DP-002-microbatch-durability-and-post-commit-ack.md`](../50-architecture-decisions/ADR-DP-002-microbatch-durability-and-post-commit-ack.md) | Architect | Six-stage micro-batch state machine & post-commit ACK |
| `50-architecture-decisions/` | [`ADR-DP-003-immutable-data-lake-and-sql-manifests.md`](../50-architecture-decisions/ADR-DP-003-immutable-data-lake-and-sql-manifests.md) | Architect | Immutable Bronze/Silver/Gold lake + SQL manifests |
| `50-architecture-decisions/` | [`ADR-DP-004-persistent-duckdb-warehouse-and-snapshots.md`](../50-architecture-decisions/ADR-DP-004-persistent-duckdb-warehouse-and-snapshots.md) | Architect | Persistent DuckDB Star Schema & `dw-v{N}.duckdb` snapshots |
| `50-architecture-decisions/` | [`ADR-DP-005-hot-state-cache-nats-kv-and-redis-evaluation.md`](../50-architecture-decisions/ADR-DP-005-hot-state-cache-nats-kv-and-redis-evaluation.md) | Architect | `HotStateCache` on NATS KV (`MEMORY`) vs Redis |
| `50-architecture-decisions/` | [`ADR-DP-006-durable-sql-workflow-orchestrator.md`](../50-architecture-decisions/ADR-DP-006-durable-sql-workflow-orchestrator.md) | Architect | Durable SQL workflow engine separate from JetStream |
| `50-architecture-decisions/` | [`ADR-DP-007-serving-gateway-bridge-over-nats.md`](../50-architecture-decisions/ADR-DP-007-serving-gateway-bridge-over-nats.md) | Architect | Cross-process `ServingGatewayBridge` over NATS Core/KV |
| `60-security-and-governance/` | [`README.md`](../60-security-and-governance/README.md) | SRE / QA | Security & governance folder rules |
| `60-security-and-governance/` | [`security-and-threat-model.md`](../60-security-and-governance/security-and-threat-model.md) | SRE / QA | Auth coverage, error sanitization, rate limits, test isolation |
| `60-security-and-governance/` | [`data-governance-lineage-retention.md`](../60-security-and-governance/data-governance-lineage-retention.md) | Data Eng | Manifest-derived catalog, lineage edges, safe retention |
| `70-testing/` | [`README.md`](../70-testing/README.md) | SRE / QA | Testing folder governance |
| `70-testing/` | [`test-strategy-and-plan.md`](../70-testing/test-strategy-and-plan.md) | SRE / QA | 4 test stages, markers, `TEST-ISO` isolation, CI boundaries |
| `70-testing/` | [`test-case-catalog.md`](../70-testing/test-case-catalog.md) | SRE / QA | Formal `TC-DP-*` catalog covering D1–D25 and `REQ-DP-*` |
| `70-testing/` | [`reliability-and-performance-test-spec.md`](../70-testing/reliability-and-performance-test-spec.md) | SRE / QA | Fault injection `S1–S14`, sustained load, recovery drills |
| `80-operations/` | [`README.md`](../80-operations/README.md) | SRE / QA | Operations folder governance |
| `80-operations/` | [`deployment-and-env-guide.md`](../80-operations/deployment-and-env-guide.md) | SRE / QA | Native `LITE`/`STANDARD`/`EXTENDED` deployment & worker launch |
| `80-operations/` | [`monitoring-and-alerting-spec.md`](../80-operations/monitoring-and-alerting-spec.md) | SRE / QA | Per-process metrics, staleness/lag/disk alerts |
| `80-operations/` | [`backup-restore-and-recovery-runbook.md`](../80-operations/backup-restore-and-recovery-runbook.md) | SRE / QA | Backup/restore for SQLite, Lake manifests, DuckDB snapshots |
| `80-operations/` | [`rollback-and-troubleshooting.md`](../80-operations/rollback-and-troubleshooting.md) | SRE / QA | Rollback procedures and failure diagnosis |
| `80-operations/` | [`production-readiness-checklist.md`](../80-operations/production-readiness-checklist.md) | SRE / QA | Objective readiness gates (`UNVERIFIED`/`FAIL` until Phase 2/3) |
