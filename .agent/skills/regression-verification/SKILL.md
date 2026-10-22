---
name: regression-verification
description: Verify implementation changes with targeted regression tests, build checks, and an evidence-based completion report.
---

# Regression Verification Skill

## Procedure
1. Capture the exact initial failure and expected behavior.
2. Add a test that fails on the old code where practical.
3. Implement the smallest root-cause fix.
4. Run the new test and adjacent tests.
5. Run the full backend suite, frontend type check/build, and end-to-end smoke workflow as feasible.
6. Inspect diffs for accidental changes, fake production data, secrets, dead controls, and unrelated refactors.
7. Update the audit with status: Open, Fixed + Verified, Fixed but Not Verified, or Accepted Risk.
8. Report exact commands and actual results; mark unavailable checks as NOT RUN with a reason.

## Completion standard
A successful static review is not a passing test. A passing frontend build does not prove API integration. Report these separately.
