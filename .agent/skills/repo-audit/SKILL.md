---
name: repo-audit
description: Inspect the current repository, map architecture and risks, and produce evidence-backed findings before broad modifications.
---

# Repository Audit Skill

## Trigger
Use before refactors, when a bug crosses layers, or when a user asks for a codebase review.

## Procedure
1. Inspect Git status, branch, root structure, existing tests, dependency files, and documented run commands.
2. Trace the affected runtime path across route, schema, service, data/model layer, and frontend caller.
3. Search for sibling endpoints with the same response schema pattern or error-handling pattern.
4. Separate confirmed findings from hypotheses and prioritize by severity and impact.
5. For each finding, record file path, relevant symbol/line, reproduction evidence, user impact, recommended change, and regression test.
6. Preserve uncommitted work and do not execute destructive commands.
7. Save findings in `docs/audit/codebase-audit.md` and keep it concise enough to update as issues are resolved.

## Required checks
- Search for response schemas where required fields are missing on conditional return paths.
- Search for `HTTPException(detail=str(e))`, broad exception handling, unused `BackgroundTasks`, raw exception exposure, and blocking work in routes.
- Search for UI zero defaults masking unavailable data, API response type drift, hard-coded sample data, and inconsistent numeric formatting.
- Review missing-data, loading, stale-data, and failure behavior.

## Deliverable
An evidence-backed audit with severity, affected paths, fixes, tests, and residual risks. Do not claim code execution if the environment did not permit it.
