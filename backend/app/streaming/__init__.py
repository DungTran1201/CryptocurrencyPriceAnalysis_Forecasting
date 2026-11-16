"""Streaming ingestion, NATS JetStream broker, durable consumers, and WS broadcast hub."""

from backend.app.streaming.broker import (
    BrokerMessage,
    InMemoryBroker,
    MessageBroker,
    NatsJetStreamBroker,
    PullSubscription,
    create_broker,
)
from backend.app.streaming.normalizer import (
    NormalizationError,
    normalize_binance_ws_payload,
    subject_for_event,
)
from backend.app.streaming.producer import BoundedEventProducer
from backend.app.streaming.consumers import MedallionStreamConsumer, BoundedDedupCache
from backend.app.streaming.ws_hub import WSBroadcastHub
from backend.app.streaming.runtime import StreamPlatformRuntime, stream_runtime

__all__ = [
    "BrokerMessage",
    "InMemoryBroker",
    "MessageBroker",
    "NatsJetStreamBroker",
    "PullSubscription",
    "create_broker",
    "NormalizationError",
    "normalize_binance_ws_payload",
    "subject_for_event",
    "BoundedEventProducer",
    "MedallionStreamConsumer",
    "BoundedDedupCache",
    "WSBroadcastHub",
    "StreamPlatformRuntime",
    "stream_runtime",
]

