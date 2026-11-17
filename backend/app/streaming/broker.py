"""Message Broker abstraction with NATS JetStream production backend & test adapter."""

from abc import ABC, abstractmethod
import asyncio
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import fnmatch
from typing import Any, Awaitable, Callable, Deque, Dict, List, Optional

from backend.app.core.config import settings
from backend.app.core.logging import get_logger

logger = get_logger("MessageBroker")


@dataclass
class BrokerMessage:
    """Unified broker message wrapper supporting explicit ACK, NAK, TERM, and metadata."""
    subject: str
    payload: bytes
    headers: Dict[str, str]
    stream_seq: int
    delivery_count: int
    redelivered: bool
    _ack_cb: Callable[[], Awaitable[None]]
    _nak_cb: Callable[[Optional[float]], Awaitable[None]]
    _term_cb: Callable[[], Awaitable[None]]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    async def ack(self) -> None:
        await self._ack_cb()

    async def nak(self, delay: Optional[float] = None) -> None:
        await self._nak_cb(delay)

    async def term(self) -> None:
        await self._term_cb()


class PullSubscription(ABC):
    """Durable pull subscription interface."""

    @abstractmethod
    async def fetch(self, batch: int = 50, timeout: float = 1.0) -> List[BrokerMessage]:
        """Fetch up to `batch` pending messages, returning empty list on timeout."""

    @abstractmethod
    async def unsubscribe(self) -> None:
        """Cleanly close subscription handle without deleting durable state."""


class MessageBroker(ABC):
    """Abstract durable message broker interface."""

    @abstractmethod
    async def connect(self) -> None:
        """Connect to broker and provision required streams."""

    @abstractmethod
    async def close(self) -> None:
        """Gracefully close broker connection."""

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if broker connection is currently healthy."""

    @abstractmethod
    async def publish(
        self,
        subject: str,
        payload: bytes,
        msg_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> int:
        """Publish durable message and return assigned stream sequence number."""

    @abstractmethod
    async def pull_subscribe(
        self,
        subject: str,
        durable: str,
        stream: Optional[str] = None,
    ) -> PullSubscription:
        """Create or bind to a durable pull consumer."""

    @abstractmethod
    async def get_stream_info(self) -> Dict[str, Any]:
        """Return stream & consumer lag metrics for observability."""

    @abstractmethod
    async def replay_messages(
        self,
        subject: str = "market.>",
        start_seq: Optional[int] = None,
        start_time: Optional[datetime] = None,
        max_msgs: int = 200,
    ) -> List[Dict[str, Any]]:
        """Read historical messages from broker stream by sequence or timestamp."""


class _NatsPullSubscription(PullSubscription):
    """PullSubscription adapter wrapping nats-py JetStream PullSubscription."""

    def __init__(self, sub: Any):
        self._sub = sub

    async def fetch(self, batch: int = 50, timeout: float = 1.0) -> List[BrokerMessage]:
        import nats.errors

        try:
            msgs = await self._sub.fetch(batch=batch, timeout=timeout)
        except nats.errors.TimeoutError:
            return []
        except Exception as exc:
            if "timeout" in str(exc).lower():
                return []
            raise

        wrapped: List[BrokerMessage] = []
        for msg in msgs:
            meta = getattr(msg, "metadata", None)
            seq = int(meta.sequence.stream) if meta and meta.sequence else 0
            deliveries = int(meta.num_delivered) if meta else 1
            ts = meta.timestamp if meta and getattr(meta, "timestamp", None) else datetime.now(timezone.utc)

            async def _ack(m=msg):
                await m.ack()

            async def _nak(delay: Optional[float] = None, m=msg):
                await m.nak(delay=delay)

            async def _term(m=msg):
                await m.term()

            wrapped.append(
                BrokerMessage(
                    subject=msg.subject,
                    payload=msg.data,
                    headers=dict(msg.headers or {}),
                    stream_seq=seq,
                    delivery_count=deliveries,
                    redelivered=deliveries > 1,
                    _ack_cb=_ack,
                    _nak_cb=_nak,
                    _term_cb=_term,
                    timestamp=ts,
                )
            )
        return wrapped

    async def unsubscribe(self) -> None:
        try:
            await self._sub.unsubscribe()
        except Exception:
            pass


class NatsJetStreamBroker(MessageBroker):
    """Production NATS JetStream broker using nats-py."""

    def __init__(
        self,
        nats_url: Optional[str] = None,
        stream_name: Optional[str] = None,
        dlq_stream_name: Optional[str] = None,
    ):
        self.nats_url = nats_url or settings.streaming.nats_url
        self.stream_name = stream_name or settings.streaming.nats_stream_name
        self.dlq_stream_name = dlq_stream_name or settings.streaming.nats_dlq_stream_name
        self._nc: Any = None
        self._js: Any = None
        self._connected: bool = False
        self._connect_lock = asyncio.Lock()
        self._conn_epoch: int = 0

    async def connect(self) -> None:
        import nats

        async with self._connect_lock:
            if self._nc is not None and self._nc.is_connected:
                self._connected = True
                return

            self._conn_epoch += 1
            epoch = self._conn_epoch

            async def _disconnected_cb():
                if self._conn_epoch == epoch:
                    self._connected = False
                    logger.warning("Disconnected from NATS JetStream")

            async def _reconnected_cb():
                if self._conn_epoch == epoch:
                    self._connected = True
                    logger.info("Reconnected to NATS JetStream")

            self._nc = await nats.connect(
                servers=[self.nats_url],
                connect_timeout=5,
                reconnect_time_wait=2,
                max_reconnect_attempts=-1,
                disconnected_cb=_disconnected_cb,
                reconnected_cb=_reconnected_cb,
            )
            self._js = self._nc.jetstream()
            self._connected = True
            await self._ensure_streams()
            logger.info(f"Connected to NATS JetStream at {self.nats_url} (stream={self.stream_name})")

    async def close(self) -> None:
        async with self._connect_lock:
            self._conn_epoch += 1
            self._connected = False
            if self._nc is not None:
                try:
                    await self._nc.drain()
                    await self._nc.close()
                except Exception:
                    pass
                self._nc = None
                self._js = None
            logger.info("Closed NATS JetStream connection cleanly")

    async def _ensure_streams(self) -> None:
        from nats.js.api import StreamConfig, StorageType, RetentionPolicy
        from nats.js.errors import NotFoundError, ServerError

        total_budget_bytes = settings.streaming.nats_max_file_mb * 1024 * 1024
        main_max_bytes = int(total_budget_bytes * 0.75)
        dlq_max_bytes = max(4 * 1024 * 1024, int(total_budget_bytes * 0.20))
        dedup_ns = settings.streaming.nats_dedup_window_sec

        async def _upsert_stream(name: str, subjects: List[str], max_b: int, max_age_s: int, dedup: Optional[int] = None):
            cfg = StreamConfig(
                name=name,
                subjects=subjects,
                retention=RetentionPolicy.LIMITS,
                storage=StorageType.FILE,
                max_bytes=max_b,
                max_age=max_age_s,
                duplicate_window=dedup,
            )
            try:
                await self._js.stream_info(name)
                try:
                    await self._js.update_stream(cfg)
                except ServerError as srv_err:
                    if "insufficient storage" in str(srv_err).lower():
                        logger.warning(f"Keeping existing NATS stream '{name}' size within server storage cap.")
                    else:
                        raise
            except NotFoundError:
                candidate_sizes = [max_b]
                for cap_mb in (32, 8, 2):
                    cap_bytes = cap_mb * 1024 * 1024
                    if cap_bytes < max_b:
                        candidate_sizes.append(cap_bytes)
                candidate_sizes.append(512 * 1024)
                last_err: Optional[Exception] = None
                for size_bytes in candidate_sizes:
                    cfg.max_bytes = size_bytes
                    try:
                        await self._js.add_stream(cfg)
                        last_err = None
                        break
                    except ServerError as srv_err:
                        if "insufficient storage" in str(srv_err).lower():
                            last_err = srv_err
                            continue
                        raise
                if last_err is not None:
                    raise last_err

        subj_prefix = getattr(self, "_subject_prefix", "market")
        await _upsert_stream(
            self.stream_name,
            [f"{subj_prefix}.aggtrade.*", f"{subj_prefix}.kline.>"],
            main_max_bytes,
            settings.resources.retention_bronze_days * 86400,
            dedup=dedup_ns,
        )
        await _upsert_stream(
            self.dlq_stream_name,
            [f"{subj_prefix}.dlq.>"],
            dlq_max_bytes,
            settings.resources.retention_silver_days * 86400,
        )

    async def close(self) -> None:
        self._connected = False
        if self._nc is not None:
            try:
                await self._nc.drain()
            except Exception:
                try:
                    await self._nc.close()
                except Exception:
                    pass
            self._nc = None
            self._js = None

    def is_connected(self) -> bool:
        return bool(self._connected and self._nc is not None and self._nc.is_connected)

    async def publish(
        self,
        subject: str,
        payload: bytes,
        msg_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> int:
        if not self._js:
            raise RuntimeError("NATS JetStream broker is not connected")
        pub_headers = dict(headers or {})
        if msg_id:
            pub_headers["Nats-Msg-Id"] = msg_id
        ack = await self._js.publish(subject=subject, payload=payload, headers=pub_headers or None)
        return int(ack.seq)

    async def pull_subscribe(
        self,
        subject: str,
        durable: str,
        stream: Optional[str] = None,
    ) -> PullSubscription:
        from nats.js.api import ConsumerConfig, AckPolicy

        if not self._js:
            raise RuntimeError("NATS JetStream broker is not connected")
        cfg = ConsumerConfig(
            durable_name=durable,
            ack_policy=AckPolicy.EXPLICIT,
            ack_wait=settings.streaming.nats_ack_wait_sec,
            max_deliver=settings.streaming.nats_max_deliver,
            max_ack_pending=max(
                settings.resources.bronze_flush_max_records * 2,
                settings.resources.consumer_batch_size * 4,
                500,
            ),
        )
        sub = await self._js.pull_subscribe(
            subject=subject,
            durable=durable,
            stream=stream or self.stream_name,
            config=cfg,
        )
        return _NatsPullSubscription(sub)

    async def get_stream_info(self) -> Dict[str, Any]:
        if not self.is_connected() or not self._js:
            return {"connected": False, "backend": "nats_jetstream", "url": self.nats_url}
        try:
            s_info = await self._js.stream_info(self.stream_name)
            dlq_info = await self._js.stream_info(self.dlq_stream_name)
            consumers = []
            total_lag = 0
            for c_info in await self._js.consumers_info(self.stream_name):
                lag = int(c_info.num_pending or 0) + int(c_info.num_ack_pending or 0)
                total_lag += lag
                consumers.append({
                    "name": c_info.name,
                    "num_pending": int(c_info.num_pending or 0),
                    "num_ack_pending": int(c_info.num_ack_pending or 0),
                    "num_redelivered": int(c_info.num_redelivered or 0),
                    "lag": lag,
                })
            return {
                "connected": True,
                "backend": "nats_jetstream",
                "url": self.nats_url,
                "stream": self.stream_name,
                "messages": int(s_info.state.messages),
                "bytes": int(s_info.state.bytes),
                "first_seq": int(s_info.state.first_seq),
                "last_seq": int(s_info.state.last_seq),
                "dlq_messages": int(dlq_info.state.messages),
                "total_consumer_lag": total_lag,
                "consumers": consumers,
            }
        except Exception as exc:
            return {"connected": False, "backend": "nats_jetstream", "error": str(exc)}

    async def replay_messages(
        self,
        subject: str = "market.>",
        start_seq: Optional[int] = None,
        start_time: Optional[datetime] = None,
        max_msgs: int = 200,
    ) -> List[Dict[str, Any]]:
        from nats.js.api import ConsumerConfig, DeliverPolicy, AckPolicy
        import nats.errors

        if not self._js:
            raise RuntimeError("NATS JetStream broker is not connected")

        if start_seq is not None and start_seq >= 1:
            cfg = ConsumerConfig(
                deliver_policy=DeliverPolicy.BY_START_SEQUENCE,
                opt_start_seq=start_seq,
                ack_policy=AckPolicy.NONE,
            )
        elif start_time is not None:
            ts = start_time if start_time.tzinfo else start_time.replace(tzinfo=timezone.utc)
            cfg = ConsumerConfig(
                deliver_policy=DeliverPolicy.BY_START_TIME,
                opt_start_time=ts.isoformat(),
                ack_policy=AckPolicy.NONE,
            )
        else:
            cfg = ConsumerConfig(
                deliver_policy=DeliverPolicy.ALL,
                ack_policy=AckPolicy.NONE,
            )

        sub = await self._js.pull_subscribe(subject=subject, stream=self.stream_name, config=cfg)
        records: List[Dict[str, Any]] = []
        try:
            while len(records) < max_msgs:
                batch_sz = min(50, max_msgs - len(records))
                try:
                    msgs = await sub.fetch(batch=batch_sz, timeout=0.5)
                except nats.errors.TimeoutError:
                    break
                if not msgs:
                    break
                for m in msgs:
                    meta = getattr(m, "metadata", None)
                    records.append({
                        "seq": int(meta.sequence.stream) if meta and meta.sequence else 0,
                        "subject": m.subject,
                        "payload": m.data,
                        "timestamp": meta.timestamp.isoformat() if meta and meta.timestamp else None,
                    })
        finally:
            await sub.unsubscribe()
        return records


class _MemoryPullSubscription(PullSubscription):
    """Durable pull subscription backed by InMemoryBroker."""

    def __init__(self, broker: "InMemoryBroker", subject: str, durable: str):
        self._broker = broker
        self._subject = subject
        self._durable = durable

    async def fetch(self, batch: int = 50, timeout: float = 1.0) -> List[BrokerMessage]:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            msgs = self._broker._pull_batch(self._subject, self._durable, batch)
            if msgs:
                return msgs
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return []
            await asyncio.sleep(min(0.05, remaining))

    async def unsubscribe(self) -> None:
        return None


class InMemoryBroker(MessageBroker):
    """Bounded in-memory durable broker for isolated unit & recovery tests."""

    def __init__(self, max_messages: int = 10000, dedup_window_sec: int = 120):
        self._max_messages = max_messages
        self._dedup_window = timedelta(seconds=dedup_window_sec)
        self._connected = False
        self._seq = 0
        self._messages: Deque[Dict[str, Any]] = deque(maxlen=max_messages)
        self._dedup_ids: Dict[str, datetime] = {}
        self._consumer_offsets: Dict[str, int] = {}
        self._redelivery_queues: Dict[str, Deque[Dict[str, Any]]] = {}
        self._acked_seqs: Dict[str, set] = {}

    async def connect(self) -> None:
        self._connected = True

    async def close(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def _subject_matches(self, pattern: str, subject: str) -> bool:
        if pattern == subject:
            return True
        p_tokens = pattern.split(".")
        s_tokens = subject.split(".")
        for idx, pt in enumerate(p_tokens):
            if pt == ">":
                return True
            if idx >= len(s_tokens):
                return False
            if pt != "*" and not fnmatch.fnmatch(s_tokens[idx], pt):
                return False
        return len(p_tokens) == len(s_tokens)

    async def publish(
        self,
        subject: str,
        payload: bytes,
        msg_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> int:
        if not self._connected:
            raise RuntimeError("InMemoryBroker not connected")
        now = datetime.now(timezone.utc)
        if msg_id:
            prev = self._dedup_ids.get(msg_id)
            if prev and (now - prev) < self._dedup_window:
                return self._seq
            self._dedup_ids[msg_id] = now
            if len(self._dedup_ids) > self._max_messages:
                oldest = next(iter(self._dedup_ids))
                self._dedup_ids.pop(oldest, None)

        self._seq += 1
        self._messages.append({
            "seq": self._seq,
            "subject": subject,
            "payload": payload,
            "headers": dict(headers or {}),
            "timestamp": now,
            "deliveries": {},
        })
        return self._seq

    async def pull_subscribe(
        self,
        subject: str,
        durable: str,
        stream: Optional[str] = None,
    ) -> PullSubscription:
        self._consumer_offsets.setdefault(durable, 0)
        self._redelivery_queues.setdefault(durable, deque())
        self._acked_seqs.setdefault(durable, set())
        return _MemoryPullSubscription(self, subject, durable)

    def _pull_batch(self, subject_pattern: str, durable: str, batch: int) -> List[BrokerMessage]:
        out: List[BrokerMessage] = []
        redeliv_q = self._redelivery_queues[durable]
        while redeliv_q and len(out) < batch:
            item = redeliv_q.popleft()
            if item["seq"] not in self._acked_seqs[durable]:
                out.append(self._wrap(item, durable))

        last_seq = self._consumer_offsets[durable]
        for item in list(self._messages):
            if len(out) >= batch:
                break
            if item["seq"] <= last_seq:
                continue
            self._consumer_offsets[durable] = item["seq"]
            if self._subject_matches(subject_pattern, item["subject"]):
                out.append(self._wrap(item, durable))
        return out

    def _wrap(self, item: Dict[str, Any], durable: str) -> BrokerMessage:
        d_count = item["deliveries"].get(durable, 0) + 1
        item["deliveries"][durable] = d_count
        seq = item["seq"]

        async def _ack():
            self._acked_seqs[durable].add(seq)

        async def _nak(delay: Optional[float] = None):
            if seq not in self._acked_seqs[durable]:
                self._redelivery_queues[durable].append(item)

        async def _term():
            self._acked_seqs[durable].add(seq)

        return BrokerMessage(
            subject=item["subject"],
            payload=item["payload"],
            headers=item["headers"],
            stream_seq=seq,
            delivery_count=d_count,
            redelivered=d_count > 1,
            _ack_cb=_ack,
            _nak_cb=_nak,
            _term_cb=_term,
            timestamp=item["timestamp"],
        )

    async def get_stream_info(self) -> Dict[str, Any]:
        dlq_count = sum(1 for m in self._messages if m["subject"].startswith("market.dlq."))
        main_count = len(self._messages) - dlq_count
        consumers = []
        total_lag = 0
        for name, off in self._consumer_offsets.items():
            lag = max(0, self._seq - off) + len(self._redelivery_queues.get(name, ()))
            total_lag += lag
            consumers.append({"name": name, "num_pending": lag, "num_ack_pending": 0, "lag": lag})
        return {
            "connected": self._connected,
            "backend": "in_memory",
            "stream": "MARKET_EVENTS",
            "messages": main_count,
            "bytes": sum(len(m["payload"]) for m in self._messages),
            "first_seq": self._messages[0]["seq"] if self._messages else 0,
            "last_seq": self._seq,
            "dlq_messages": dlq_count,
            "total_consumer_lag": total_lag,
            "consumers": consumers,
        }

    async def replay_messages(
        self,
        subject: str = "market.>",
        start_seq: Optional[int] = None,
        start_time: Optional[datetime] = None,
        max_msgs: int = 200,
    ) -> List[Dict[str, Any]]:
        res: List[Dict[str, Any]] = []
        for m in self._messages:
            if start_seq is not None and m["seq"] < start_seq:
                continue
            if start_time is not None:
                st = start_time if start_time.tzinfo else start_time.replace(tzinfo=timezone.utc)
                if m["timestamp"] < st:
                    continue
            if self._subject_matches(subject, m["subject"]):
                res.append({
                    "seq": m["seq"],
                    "subject": m["subject"],
                    "payload": m["payload"],
                    "timestamp": m["timestamp"].isoformat(),
                })
                if len(res) >= max_msgs:
                    break
        return res


def create_broker() -> MessageBroker:
    """Create configured broker backend."""
    if settings.streaming.broker_backend == "memory":
        return InMemoryBroker(
            max_messages=settings.resources.stream_queue_maxsize * 4,
            dedup_window_sec=settings.streaming.nats_dedup_window_sec,
        )
    return NatsJetStreamBroker()
