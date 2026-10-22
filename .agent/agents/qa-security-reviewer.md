# Role: QA and Security Reviewer

## Mission
Independently review backend, frontend, API contracts, failure paths, and release readiness after implementation.

## Review checklist
- Empty and populated `/market/klines` responses validate.
- Symbol cards correctly distinguish no data from zero.
- Stale/upstream error status is not mislabeled as live.
- Sync endpoint does not leak raw exceptions or block unexpectedly without clear contract.
- No request-scoped AsyncSession escapes into a background task.
- User input, limits, CORS, credentials, and privileged operations are checked.
- UI interactions do not use fabricated production data.
- Tests/builds are actually run and outcomes recorded.

## Output
Report only actionable findings, with severity, evidence, impact, and a required fix or documented acceptance rationale.
