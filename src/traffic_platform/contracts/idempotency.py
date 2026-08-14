"""Bounded idempotency and message-order guards."""

from collections import OrderedDict
from uuid import UUID

from traffic_platform.common.errors import ErrorCode, PlatformError
from traffic_platform.contracts.models import TrafficMessage


class IdempotencyGuard:
    """Reject duplicate IDs and non-monotonic sequences per source."""

    def __init__(self, capacity: int = 10_000) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._capacity = capacity
        self._seen: OrderedDict[UUID, None] = OrderedDict()
        self._last_sequence: dict[tuple[str, str], int] = {}

    def accept(self, message: TrafficMessage, *, check_order: bool = True) -> None:
        """Validate expiry, duplicate identity and optional per-source ordering."""

        message.ensure_not_expired()
        if message.message_id in self._seen:
            raise PlatformError(
                ErrorCode.DUPLICATE_MESSAGE,
                f"message {message.message_id} was already processed",
            )
        source_key = (message.source_id, message.experiment_id)
        last = self._last_sequence.get(source_key)
        if check_order and last is not None and message.sequence_number <= last:
            raise PlatformError(
                ErrorCode.OUT_OF_ORDER_MESSAGE,
                f"sequence {message.sequence_number} is not above {last}",
            )
        self._seen[message.message_id] = None
        self._seen.move_to_end(message.message_id)
        if len(self._seen) > self._capacity:
            self._seen.popitem(last=False)
        if check_order:
            self._last_sequence[source_key] = message.sequence_number
