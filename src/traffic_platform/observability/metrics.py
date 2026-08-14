"""Low-cardinality Prometheus metrics shared by platform services."""

from prometheus_client import Counter, Gauge, Histogram

CONTROL_DECISION_SECONDS = Histogram(
    "traffic_control_decision_seconds",
    "Algorithm decision wall-clock duration.",
    ["algorithm"],
)
UNSAFE_COMMANDS = Counter(
    "traffic_unsafe_command_total",
    "Safety-kernel modified or rejected actions.",
    ["outcome", "reason"],
)
SERVICE_READY = Gauge(
    "traffic_service_ready",
    "Whether a platform service reports ready.",
    ["service"],
)
COMMUNICATION_EVENTS = Counter(
    "traffic_communication_event_total",
    "Communication delivery outcomes.",
    ["channel", "outcome"],
)

