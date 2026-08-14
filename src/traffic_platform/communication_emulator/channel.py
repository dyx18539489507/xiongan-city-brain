"""Priority-queue communication channel without wall-clock sleeps."""

import heapq
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ChannelConfig:
    """Probabilistic channel behavior in simulated time."""

    base_latency_ms: float = 0.0
    jitter_ms: float = 0.0
    packet_loss_rate: float = 0.0
    duplicate_rate: float = 0.0
    reorder_rate: float = 0.0
    corruption_rate: float = 0.0
    timeout_ms: float = 1000.0
    bandwidth_bytes_s: float | None = None

    def __post_init__(self) -> None:
        if self.base_latency_ms < 0 or self.jitter_ms < 0 or self.timeout_ms <= 0:
            raise ValueError("latency and jitter must be non-negative; timeout positive")
        for value in (
            self.packet_loss_rate,
            self.duplicate_rate,
            self.reorder_rate,
            self.corruption_rate,
        ):
            if not 0 <= value <= 1:
                raise ValueError("probabilities must be between 0 and 1")
        if self.bandwidth_bytes_s is not None and self.bandwidth_bytes_s <= 0:
            raise ValueError("bandwidth_bytes_s must be positive")


@dataclass(frozen=True, slots=True)
class DeliveryRecord:
    """One recorded communication outcome."""

    message_id: str
    channel: str
    source: str
    destination: str
    message_type: str
    sent_at_s: float
    scheduled_at_s: float | None
    configured_latency_ms: float
    actual_latency_ms: float
    dropped: bool
    duplicated: bool
    reordered: bool
    corrupted: bool
    timeout: bool
    offline: bool
    recovery_time_s: float | None


@dataclass(order=True, slots=True)
class _Scheduled[T]:
    deliver_at_s: float
    order: int
    message_id: str = field(compare=False)
    payload: T = field(compare=False)


class SimulatedChannel[T]:
    """Deterministic seeded delivery queue advanced by simulation time."""

    def __init__(
        self,
        config: ChannelConfig,
        seed: int = 0,
        *,
        corruptor: Callable[[T], T] | None = None,
    ) -> None:
        self.config = config
        self._random = random.Random(seed)
        self._queue: list[_Scheduled[T]] = []
        self._counter = 0
        self._offline_until_s = -1.0
        self._corruptor = corruptor
        self.records: list[DeliveryRecord] = []

    def set_offline(self, current_time_s: float, duration_s: float) -> None:
        """Make the channel unavailable for a simulation-time interval."""

        if duration_s <= 0:
            raise ValueError("duration_s must be positive")
        self._offline_until_s = max(self._offline_until_s, current_time_s + duration_s)

    def send(
        self,
        message_id: str,
        payload: T,
        *,
        current_time_s: float,
        size_bytes: int = 0,
        force_offline: bool = False,
        recovery_time_s: float | None = None,
        channel: str = "",
        source: str = "",
        destination: str = "",
        message_type: str = "",
    ) -> DeliveryRecord:
        """Schedule zero, one or two deliveries and record the impairment."""

        offline = force_offline or current_time_s < self._offline_until_s
        dropped = offline or self._random.random() < self.config.packet_loss_rate
        duplicated = not dropped and self._random.random() < self.config.duplicate_rate
        reordered = not dropped and self._random.random() < self.config.reorder_rate
        corruptor = self._corruptor
        corrupted = (
            not dropped
            and corruptor is not None
            and self._random.random() < self.config.corruption_rate
        )
        jitter = self._random.gauss(0.0, self.config.jitter_ms)
        latency_ms = max(0.0, self.config.base_latency_ms + jitter)
        if self.config.bandwidth_bytes_s is not None:
            latency_ms += max(size_bytes, 0) / self.config.bandwidth_bytes_s * 1000
        if reordered:
            latency_ms += self.config.jitter_ms + self.config.base_latency_ms
        timed_out = latency_ms > self.config.timeout_ms
        scheduled = None if dropped or timed_out else current_time_s + latency_ms / 1000
        if scheduled is not None:
            scheduled_payload = (
                corruptor(payload)
                if corrupted and corruptor is not None
                else payload
            )
            self._push(message_id, scheduled_payload, scheduled)
            if duplicated:
                duplicate_delay_s = max(0.001, self.config.jitter_ms / 1000)
                self._push(
                    message_id,
                    scheduled_payload,
                    scheduled + duplicate_delay_s,
                )
        record = DeliveryRecord(
            message_id=message_id,
            channel=channel,
            source=source,
            destination=destination,
            message_type=message_type,
            sent_at_s=current_time_s,
            scheduled_at_s=scheduled,
            configured_latency_ms=self.config.base_latency_ms,
            actual_latency_ms=latency_ms,
            dropped=dropped,
            duplicated=duplicated,
            reordered=reordered,
            corrupted=corrupted,
            timeout=timed_out,
            offline=offline,
            recovery_time_s=(
                recovery_time_s
                if force_offline
                else (
                    max(0.0, self._offline_until_s - current_time_s)
                    if offline
                    else None
                )
            ),
        )
        self.records.append(record)
        return record

    def _push(self, message_id: str, payload: T, deliver_at_s: float) -> None:
        self._counter += 1
        heapq.heappush(
            self._queue,
            _Scheduled(deliver_at_s, self._counter, message_id, payload),
        )

    def advance(self, current_time_s: float) -> list[tuple[str, T]]:
        """Deliver all events whose simulation timestamps are due."""

        delivered: list[tuple[str, T]] = []
        while self._queue and self._queue[0].deliver_at_s <= current_time_s:
            event = heapq.heappop(self._queue)
            delivered.append((event.message_id, event.payload))
        return delivered
