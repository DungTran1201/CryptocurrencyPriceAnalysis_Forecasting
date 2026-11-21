# ADR-005: CPU-Friendly Machine Learning & Event-Triggered Inference

- **Status:** Accepted
- **Date:** 2026-11-16
- **Context:** GPU-heavy deep learning (PyTorch/CUDA) or retraining on every incoming tick violates the single-node CPU-first resource budget and introduces instability on an 8 GB host.
- **Decision:**
  - Use Scikit-learn CPU models (`HistGradientBoosting`, `Ridge`, `LogisticRegression`) plus statistical baselines (`NaivePersistenceBaseline`, `RollingMeanBaseline`) with bounded `ML_MAX_TRAIN_ROWS`.
  - Execute training offline/on-demand in a threadpool/worker (`asyncio.to_thread`) so FastAPI stays responsive, with single-class fold guards and strict expanding walk-forward CV gating.
  - Trigger automated realtime inference **only** on closed candle events (e.g., closed `kline_1m` / `1h` bar) or explicit API invocation — never per `aggTrade` tick.
- **Consequences:** Inference latency is sub-50 ms on CPU, training completes in seconds, and no GPU is required.

