# 70 — Testing Specification

## Purpose
Defines the verification architecture, isolation rules, test case catalog, fault-injection protocols, and performance benchmarking specifications required to prove Data Plane correctness, reliability, security, and resource compliance.

## Document Types Stored
- **Test Strategy & Plan:** Pytest marker taxonomy, 4-stage execution pipeline, `TEST-ISO` workspace isolation rules, mocking policy, and CI/CD execution gates.
- **Test Case Catalog (`TC-DP-*`):** Formal, reproducible test specifications mapped 1:1 to `REQ-DP-*` requirements and Phase 1 defects `D1–D25`.
- **Reliability & Performance Test Specs:** Fault-injection scenarios (`S1–S14`), sustained load tests, crash-recovery drills, stress tests, and production simulation suites.

## Naming Rules
- Lowercase `kebab-case.md` filenames (`test-strategy-and-plan.md`, `test-case-catalog.md`, `reliability-and-performance-test-spec.md`).
- Test case IDs follow `TC-DP-001..029` (defects/requirements & new component contracts), `TC-DP-FI-01..14` (fault injection `S1–S14`), and `TC-DP-PERF-01..05` (load/soak/stress).
- Folder index is always `README.md`.

## Document Structure
Every document in this folder MUST include:
1. Header block (`Document ID`, `Status`, `Owner`, `Applies To`).
2. Test boundaries and isolation preconditions (`TEST-ISO`).
3. Structured specifications (Objective, Preconditions, Steps, Expected Result, Pass/Fail Oracle).
4. Explicit traceability to `REQ-DP-*`, `COMP-DP-*`, and `WI-DP-*`.

## Cross-Folder Relationships
- **From `00-spec-management/`:** Maps `TC-DP-*` IDs back to `traceability-matrix.md` and defects in `repository-and-hardware-audit.md`.
- **From `10-requirements/`:** Verifies functional requirements (`data-plane-srs.md`) and populates `TARGET_TO_BE_ESTABLISHED` baselines (`performance-and-resource-targets.md`).
- **From `60-security-and-governance/`:** Verifies `REQ-DP-SEC-01..03` and catalog/retention safety.
- **To `80-operations/`:** Feeds verification evidence into `production-readiness-checklist.md`.

## Agent Rules
- **Never run retention or lake tests against live `./data/`:** Every automated test MUST satisfy `TEST-ISO` (`tmp_path` redirection).
- **Never point fault-injection NATS restarts at default port `4222`:** Spawn isolated ephemeral `nats-server` instances on free ports with `tmp_path` `store_dir`.
- **Mock external Binance HTTP/WS in default CI:** Live internet checks belong exclusively under `@pytest.mark.live`.
- **Owner:** `@sre-qa` maintains all documents under `70-testing/`.

## Exclusions
- Does NOT store executable `.py` test modules (those live in `tests/`).
- Does NOT store production deployment guides or incident runbooks (see `80-operations/`).
- Does NOT invent passing results or unmeasured performance numbers before execution.
