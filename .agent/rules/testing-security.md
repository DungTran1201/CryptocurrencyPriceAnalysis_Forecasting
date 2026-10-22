# Testing, Security, and Release Rules

- Add a targeted regression test for each fixed defect before or alongside the fix.
- Test both empty and populated data paths, including valid schema shape.
- Mock external HTTP calls in automated tests; do not make tests rely on Binance uptime.
- Check backend tests, frontend TypeScript, frontend build, and end-to-end smoke tests when feasible.
- Record exact commands and outcomes. Clearly mark checks as failed, blocked, or not run.
- Do not expose raw exceptions, secrets, internal hostnames, filesystem paths, SQL, or tracebacks in client responses.
- Validate and bound request parameters; explicitly configure CORS and rate limits according to deployment needs.
- Treat administrative sync/train actions as privileged operations in any authenticated deployment.
- Review dependencies and lockfiles before adding/upgrading packages.
- No production mock mode unless explicitly opt-in and visibly labeled as demo/test.
