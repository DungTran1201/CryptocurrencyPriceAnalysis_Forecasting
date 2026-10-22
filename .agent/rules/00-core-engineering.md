# Core Engineering Rules

- Diagnose from code and runtime evidence, not guesses.
- Trace a request across route → service → repository/database → schema → frontend consumer.
- Make narrow, reviewable edits; do not rewrite working modules just for style.
- Never hide validation errors by disabling response validation or broadly using `Any`.
- Type all external contracts and validate user-supplied parameters at boundaries.
- Use UTC-aware timestamps and explicit serialization rules.
- Distinguish zero, unknown, missing, stale, and failed values in schemas and UI.
- Keep configuration outside source code; keep `.env` and user data out of Git.
- Add tests with bug fixes. Prefer regression tests that fail before the fix.
- No destructive Git operations, no unrequested commits/pushes, and no overwriting user edits.
- Do not introduce a new framework or runtime dependency without explaining why it is needed.
- Maintain English as the default language for application UI and project documentation unless an existing product decision says otherwise.
