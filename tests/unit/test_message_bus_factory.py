"""Message-bus environment selection stays explicit and testable."""

import pytest

from traffic_platform.messaging.emulated import EmulatedMessageBus
from traffic_platform.messaging.factory import message_bus_from_environment
from traffic_platform.messaging.mqtt import MqttMessageBus


def test_defaults_to_deterministic_emulator() -> None:
    bus = message_bus_from_environment({}, seed=11)
    assert isinstance(bus, EmulatedMessageBus)


def test_builds_real_mqtt_transport_from_environment() -> None:
    bus = message_bus_from_environment(
        {
            "TRAFFIC_MESSAGE_BUS": "mqtt",
            "MQTT_HOST": "mosquitto",
            "MQTT_PORT": "1883",
        },
        seed=11,
    )
    assert isinstance(bus, MqttMessageBus)
    assert bus.host == "mosquitto"
    assert bus.port == 1883


def test_rejects_invalid_mqtt_tls_boolean() -> None:
    with pytest.raises(ValueError, match="MQTT_TLS_ENABLED"):
        message_bus_from_environment(
            {
                "TRAFFIC_MESSAGE_BUS": "mqtt",
                "MQTT_HOST": "mosquitto",
                "MQTT_TLS_ENABLED": "sometimes",
            },
            seed=11,
        )


@pytest.mark.parametrize(
    "environment",
    [
        {"TRAFFIC_MESSAGE_BUS": "mqtt"},
        {
            "TRAFFIC_MESSAGE_BUS": "mqtt",
            "MQTT_HOST": "mosquitto",
            "MQTT_PORT": "not-a-port",
        },
        {"TRAFFIC_MESSAGE_BUS": "unknown"},
    ],
)
def test_rejects_invalid_transport_configuration(
    environment: dict[str, str],
) -> None:
    with pytest.raises(ValueError):
        message_bus_from_environment(environment, seed=11)
