"""Unified platform error codes and exceptions."""

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    """Stable machine-readable platform error codes."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    MESSAGE_EXPIRED = "MESSAGE_EXPIRED"
    DUPLICATE_MESSAGE = "DUPLICATE_MESSAGE"
    OUT_OF_ORDER_MESSAGE = "OUT_OF_ORDER_MESSAGE"
    EXPERIMENT_MISMATCH = "EXPERIMENT_MISMATCH"
    ALGORITHM_NOT_FOUND = "ALGORITHM_NOT_FOUND"
    ALGORITHM_TIMEOUT = "ALGORITHM_TIMEOUT"
    ALGORITHM_FAILURE = "ALGORITHM_FAILURE"
    MODEL_NOT_AVAILABLE = "MODEL_NOT_AVAILABLE"
    SAFETY_REJECTED = "SAFETY_REJECTED"
    SUMO_UNAVAILABLE = "SUMO_UNAVAILABLE"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class PlatformError(RuntimeError):
    """Base exception with a stable code and serializable details."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
