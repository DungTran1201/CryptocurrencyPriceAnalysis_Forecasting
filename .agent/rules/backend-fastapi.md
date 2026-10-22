# Backend / FastAPI / Data Access Rules

- Use Pydantic response schemas as API contracts. Every successful return branch must satisfy the schema.
- Do not build one response shape for empty data and another incompatible shape for non-empty data.
- Prefer explicit response constructors or centralized response mappers for public API payloads.
- Catch only exceptions that can be handled meaningfully. Log internal details server-side with context and return safe, stable client errors.
- Do not send `str(exc)` directly through `HTTPException.detail` for unknown exceptions.
- SQLAlchemy `AsyncSession` instances are request-scoped unless explicitly created by a job/session factory. Never pass a request-scoped session to a background task that runs after the request closes.
- Avoid N+1 queries. Batch reads or use aggregation when loading summaries for many symbols.
- Validate symbol and interval against a supported allowlist or exchange metadata; normalize symbols consistently.
- Bound `limit` and date ranges. Validate `start_time <= end_time`; normalize naive/aware datetime behavior explicitly.
- Never imply that cached/DB-only prices are live. Include source and freshness metadata where relevant.
- Background jobs need observable lifecycle states and failure messages; `BackgroundTasks` parameters must actually be used or removed.
- Use transactions and idempotent operations for sync and forecast persistence.
- Keep CPU-heavy pandas/ML computation from blocking async event-loop work when workload can be significant.
