"""Environment-driven selection of the production or deterministic message bus."""

from collections.abc import Mapping

from traffic_platform.messaging.base import MessageBus
from traffic_platform.messaging.emulated import EmulatedMessageBus
from traffic_platform.messaging.mqtt import MqttMessageBus


def _environment_bool(
    environment: Mapping[str, str],
    name: str,
    *,
    default: bool = False,
) -> bool:
    value = environment.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def message_bus_from_environment(
    environment: Mapping[str, str],
    *,
    seed: int,
) -> MessageBus:
    """Create the explicitly configured bus without hiding missing MQTT settings."""

    mode = environment.get("TRAFFIC_MESSAGE_BUS", "emulated").strip().lower()
    if mode == "emulated":
        return EmulatedMessageBus(seed=seed)
    if mode != "mqtt":
        raise ValueError(
            "TRAFFIC_MESSAGE_BUS must be either 'emulated' or 'mqtt'"
        )

    host = (
        environment.get("MQTT_HOST")
        or environment.get("TRAFFIC_MQTT_HOST")
        or ""
    ).strip()
    if not host:
        raise ValueError("MQTT_HOST is required when TRAFFIC_MESSAGE_BUS=mqtt")
    port_text = environment.get("MQTT_PORT", "1883")
    try:
        port = int(port_text)
    except ValueError as exc:
        raise ValueError("MQTT_PORT must be an integer") from exc
    if not 1 <= port <= 65_535:
        raise ValueError("MQTT_PORT must be between 1 and 65535")

    username = environment.get("MQTT_USERNAME") or None
    password = environment.get("MQTT_PASSWORD") or None
    return MqttMessageBus(
        host,
        port,
        username=username,
        password=password,
        tls_enabled=_environment_bool(environment, "MQTT_TLS_ENABLED"),
        ca_cert=environment.get("MQTT_CA_CERT") or None,
        client_cert=environment.get("MQTT_CLIENT_CERT") or None,
        client_key=environment.get("MQTT_CLIENT_KEY") or None,
        tls_insecure=_environment_bool(environment, "MQTT_TLS_INSECURE"),
    )
