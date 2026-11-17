# 60 — Security and Governance

## Purpose
Stores security architecture, threat modeling, authentication/authorization specifications, secret/error handling rules, data governance metadata models, lineage policies, and storage retention specifications for the Data Plane.

## Document Types Stored
- **Threat Models & Security Specs:** Trust boundaries, attack surfaces, input validation, rate limiting, token enforcement, error sanitization, and test-isolation controls.
- **Data Governance Specs:** Persistent Data Catalog derivation rules, cross-layer lineage contracts, schema evolution rules, and manifest-aware retention policies.

## Naming Rules
- Lowercase `kebab-case.md` filenames descriptive of the security or governance domain (e.g., `security-and-threat-model.md`, `data-governance-lineage-retention.md`).
- Security requirement references use `REQ-DP-SEC-*` (plus `TEST-ISO` for test-safety isolation).
- Folder index is always `README.md`.

## Document Structure
Every specification in this folder MUST contain:
1. Header block (`Document ID`, `Status`, `Owner`, `Satisfies` IDs).
2. Scope and Trust Boundaries / Governance Scope.
3. Current AS-IS Gaps (`OBSERVED` file:line citations).
4. Target Controls / Policy Rules with explicit verification criteria.
5. Compliance & Audit Checklist linking to `70-testing/` test cases (`TC-DP-*`).

## Cross-Folder Relationships
- **From `10-requirements/`:** Implements `REQ-DP-SEC-01..03`, `REQ-DP-LAKE-05`, and catalog/lineage requirements.
- **From `40-interfaces-and-contracts/`:** Enforces schema validation (`IFC-DP-001`), error envelopes (`IFC-DP-007`), and `StorageBackend` path/prefix safety (`IFC-DP-008`).
- **To `70-testing/`:** Security and governance invariants map 1:1 to `TC-DP-*` cases in `test-case-catalog.md`.
- **To `80-operations/`:** Feeds secret rotation, admin token setup, and retention alerting into operational runbooks and readiness gates.

## Agent Rules
- **Verify against actual routes:** Never claim an endpoint is protected without checking `backend/app/api/v1/*.py` for `Depends(require_admin_if_configured)`.
- **No secret leakage:** Never embed real tokens, `.env` secrets, or internal host credentials in any spec or test example.
- **Keep ownership clear:** `@sre-qa` maintains `README.md` and `security-and-threat-model.md`; `@data-eng` maintains `data-governance-lineage-retention.md`.

## Exclusions
- Does NOT store functional pipeline designs or DuckDB schemas (see `30-detailed-design/` and `40-interfaces-and-contracts/`).
- Does NOT store executable test code or CI workflow YAML (see `tests/` and `.github/workflows/`).
- Does NOT store incident/recovery runbooks (see `80-operations/`).
