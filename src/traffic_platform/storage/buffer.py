"""Priority-aware in-memory buffering with backpressure and graceful flush."""

import asyncio
import json
import time
from collections import deque
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any

from traffic_platform.observability.logging import get_logger

BatchSink = Callable[[list["WriteItem"]], Awaitable[None]]
logger = get_logger(__name__)


class DataPriority(IntEnum):
    """Durability priority; larger values are never dropped by the buffer."""

    VISUALIZATION = 0
    TRAJECTORY = 1
    METRIC = 2
    CONTROL = 3
    EVENT = 4


@dataclass(frozen=True, slots=True)
class WriteItem:
    """One persistence item with explicit retention priority."""

    kind: str
    payload: dict[str, Any]
    priority: DataPriority


class BufferedBatchWriter:
    """Batch low-frequency writes and apply backpressure to critical data."""

    def __init__(
        self,
        sink: BatchSink,
        *,
        batch_size: int = 200,
        max_items: int = 10_000,
        flush_interval_s: float = 5.0,
        fallback_path: Path | None = None,
    ) -> None:
        if batch_size <= 0 or max_items < batch_size or flush_interval_s <= 0:
            raise ValueError("invalid buffer sizes or flush interval")
        self._sink = sink
        self._batch_size = batch_size
        self._max_items = max_items
        self._flush_interval_s = flush_interval_s
        self._fallback_path = fallback_path
        self._items: deque[WriteItem] = deque()
        self._condition = asyncio.Condition()
        self._worker: asyncio.Task[None] | None = None
        self._closing = False
        self.dropped_visualization = 0
        self.fallback_batches = 0
        self.write_latencies_ms: list[float] = []

    async def start(self) -> None:
        """Start the cancellable periodic flush worker."""

        if self._worker is None:
            self._worker = asyncio.create_task(
                self._run(),
                name="tiered-storage-buffer",
            )

    async def submit(self, item: WriteItem) -> bool:
        """Queue one item, dropping only low-priority visualization samples."""

        async with self._condition:
            while len(self._items) >= self._max_items:
                if item.priority <= DataPriority.VISUALIZATION:
                    self.dropped_visualization += 1
                    return False
                dropped = self._drop_one_visualization()
                if dropped:
                    self.dropped_visualization += 1
                    break
                await self._condition.wait()
            self._items.append(item)
            if len(self._items) >= self._batch_size:
                self._condition.notify_all()
            return True

    async def flush(self) -> int:
        """Flush all queued items in bounded batches."""

        total = 0
        while True:
            async with self._condition:
                if not self._items:
                    self._condition.notify_all()
                    return total
                batch = [
                    self._items.popleft()
                    for _ in range(min(self._batch_size, len(self._items)))
                ]
                self._condition.notify_all()
            await self._write(batch)
            total += len(batch)

    async def close(self) -> None:
        """Stop the worker and guarantee an end-of-experiment flush."""

        self._closing = True
        async with self._condition:
            self._condition.notify_all()
        if self._worker is not None:
            await self._worker
            self._worker = None
        await self.flush()

    async def _run(self) -> None:
        while not self._closing:
            async with self._condition:
                with suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._condition.wait(),
                        timeout=self._flush_interval_s,
                    )
            await self._flush_one_batch()

    async def _flush_one_batch(self) -> None:
        async with self._condition:
            if not self._items:
                return
            batch = [
                self._items.popleft()
                for _ in range(min(self._batch_size, len(self._items)))
            ]
            self._condition.notify_all()
        await self._write(batch)

    async def _write(self, batch: list[WriteItem]) -> None:
        started = time.perf_counter()
        try:
            await self._sink(batch)
        except Exception as exc:
            if self._fallback_path is None:
                raise
            logger.error(
                "storage_batch_degraded",
                error_type=type(exc).__name__,
                error=str(exc),
                batch_size=len(batch),
                fallback_path=str(self._fallback_path),
            )
            self._fallback_path.parent.mkdir(parents=True, exist_ok=True)
            with self._fallback_path.open("a", encoding="utf-8") as target:
                for item in batch:
                    target.write(
                        json.dumps(
                            {
                                "kind": item.kind,
                                "priority": item.priority.name,
                                "payload": item.payload,
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
            self.fallback_batches += 1
        finally:
            self.write_latencies_ms.append(
                (time.perf_counter() - started) * 1000.0
            )

    def _drop_one_visualization(self) -> bool:
        for index, queued in enumerate(self._items):
            if queued.priority <= DataPriority.VISUALIZATION:
                del self._items[index]
                return True
        return False
