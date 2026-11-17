# 40-interfaces-and-contracts — Interfaces, Schemas, and Configuration Contracts

## 1. Purpose
This directory defines the normative, versioned external and internal contracts for the Cryptocurrency Financial Data Intelligence Data Plane: canonical market events, NATS subjects and JetStream stream/KV configurations, REST API payloads and boundary validation rules, storage/database schemas, and unified configuration/profile budgets. Implementation modules and tests MUST conform to these exact contract specifications.

## 2. Document Types Stored
- **Event & Messaging Contracts (`event-and-message-contracts.md`)**: Canonical event schemas (`IFC-DP-001`), NATS subject taxonomy (`IFC-DP-002`), JetStream stream/consumer definitions (`IFC-DP-003`), NATS KV buckets (`IFC-DP-004`), and the `HotStateCache` protocol (`IFC-DP-009`).
- **Storage & Database Contracts (`storage-and-database-schemas.md`)**: Medallion lake layouts and SQL manifest tables (`IFC-DP-005`), DuckDB Warehouse star schema and snapshot pointers (`IFC-DP-006`), and `StorageBackend` v2 methods (`IFC-DP-008`).
- **API & Service Contracts (`api-and-service-contracts.md`)**: Workflow and streaming REST/WS endpoints, typed response schemas (`IFC-DP-007`), error sanitization rules, and non-blocking event-loop guarantees.
- **Configuration Specification (`configuration-specification.md`)**: Precedence rules unifying `config.yaml`, `.env`, `Settings`, profile budgets (`LITE`/`STANDARD`/`EXTENDED`), new settings keys (`IFC-DP-011`), and dependency pinning policy.

## 3. Naming Rules
- File names use lowercase kebab-case descriptive titles (`<domain>-contracts.md` or `configuration-specification.md`).
- Contract identifiers strictly follow `IFC-DP-NNN` matching the master registry in `00-spec-management/traceability-matrix.md`.
- Event/API schema versions use semantic versioning (`MAJOR.MINOR.PATCH`).

## 4. Document Structure
Every contract document in this folder MUST include:
1. Metadata header (`Document ID`, `Status`, `Owner`, `Traceability` to `REQ-DP-*`, `COMP-DP-*`, `ADR-DP-*`, `WI-DP-*`).
2. Authoritative schema tables, field types, constraints, nullability, and validation rules.
3. Backward-compatibility / evolution and error-handling semantics.
4. Explicit AS-IS drift callouts (`[OBSERVED]`) where existing code diverges from the contract.

## 5. Cross-Folder Relationships
- **Upstream**: Implements functional and non-functional requirements from `10-requirements/` and architectural constraints from `20-architecture/` and `50-architecture-decisions/`.
- **Peers**: Referenced directly by `30-detailed-design/` component specs and `60-security-and-governance/` security rules.
- **Downstream**: Verified by test cases in `70-testing/` and operationalized by runbooks/deployments in `80-operations/`.

## 6. Agent Rules for Creating and Updating Documents
- Preserve exact identifier spelling (`IFC-DP-001` through `IFC-DP-011`) and field names across all documents and Phase 2 code.
- Never silently drop required API response fields (such as `MarketDataResponseSchema.count`) or relax Pydantic contracts to mask runtime errors (`AGENTS.md` Rule #3).
- Update `00-spec-management/change-log.md` and `00-spec-management/traceability-matrix.md` via `@architect` if any contract ID or breaking field signature changes.
- Respect file ownership boundaries (`storage-and-database-schemas.md` is owned by `@data-eng`; streaming, API, event, and configuration contracts are owned by `@stream-orch`).

## 7. Exclusions (What Does NOT Belong Here)
- Detailed internal class algorithms, retry loop internals, or Mermaid sequence diagrams (place in `30-detailed-design/`).
- Hardware benchmark reports or test execution logs (place in `00-spec-management/` or `70-testing/`).
- Deployment scripts, troubleshooting runbooks, or production checklists (place in `80-operations/`).
- Architectural trade-off justifications (place in `50-architecture-decisions/`).
