# DEPRECATION NOTICE: Quarantined Legacy Modules

The modules in this directory (`llm_core/`) were identified during the repository audit as alien/copy-pasted artifacts from an unrelated Japanese education RAG application ("SenseiAgent", Anki flashcards, Voicevox TTS, JLPT vocabulary search).

These modules contained unresolved dependencies and have been deprecated.

All cryptocurrency time-series forecasting, baseline comparisons, and market analytics are now located in:
- `ml/`: Zero-leakage features, Naive & Rolling baselines, Gradient Boosting models, walk-forward cross-validation, and model registry gating.
- `backend/app/services/`: Synchronization engine (`sync_service.py`), Market analytics (`market_service.py`), and Forecast persistence & realization audit (`forecast_service.py`).
