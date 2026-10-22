---
name: api-contract-validation
description: Diagnose and prevent FastAPI/Pydantic response validation errors and backend/frontend contract drift.
---

# API Contract Validation Skill

## Procedure
1. Read the endpoint decorator and its `response_model`.
2. Read the Pydantic schema, including required fields, defaults, aliases, and nested models.
3. Trace every return branch through the service, including empty results and error cases.
4. Reproduce the smallest failing case. For the reported `/market/klines` error, an empty candle query is the minimum case.
5. Correct the source return contract explicitly; preserve response validation.
6. Add tests for empty results, non-empty results, and indicator arrays. Assert all required keys and semantic values.
7. Search for similar response-model mismatch patterns across all route modules.
8. Check the frontend TypeScript interface and empty-state handling against the API contract.

## Specific known defect
`backend/app/schemas/market.py::MarketDataResponseSchema` requires `count: int`. In `backend/app/services/market_service.py::MarketService.get_klines_with_indicators`, the empty-result branch currently returns `symbol`, `timeframe`, `candles`, and `indicators` but omits `count`. Return `count: 0` for this branch and test it. Do not remove `response_model`, suppress validation, or change a required field to optional solely to mask the defect.

## Acceptance checks
- Empty result returns HTTP 200 with `count == 0`, `candles == []`, and `indicators == {}`.
- Populated result returns `count == len(candles)`.
- Pydantic response validation succeeds for both.
- No route has an undocumented payload shape for empty data.
