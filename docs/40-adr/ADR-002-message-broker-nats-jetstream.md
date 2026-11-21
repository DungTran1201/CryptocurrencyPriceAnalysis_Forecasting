# ADR-002: NATS JetStream as Single-Node Durable Message Broker

- **Status:** Accepted
- **Date:** 2026-11-16
- **Context:** Real-time market ingestion requires durable buffering, consumer groups, explicit acknowledgements, replay by sequence/time, deduplication, and dead-letter handling without the ~1.5-2.5 GB RAM overhead of Kafka + ZooKeeper/KRaft.
- **Decision:** Adopt **NATS JetStream** (single `nats-server -js` binary, ~15-25 MB RSS native or `nats:2.10-alpine` with 128 MB cap in Docker) paired with `nats-py` async pull consumers. Configure `Nats-Msg-Id` deduplication window, bounded stream limits (`max_bytes`, `max_age`), `MaxAckPending` backpressure, and explicit DLQ routing (`market.dlq.*`) after `max_deliver`.
- **Consequences:** Enables full streaming durability, independent consumer recovery, and deterministic replay on an 8 GB personal computer. For unit tests when no broker daemon is started, an explicit `InMemoryJetStreamAdapter` test double implements the identical `BrokerClient` interface without replacing production NATS JetStream.

