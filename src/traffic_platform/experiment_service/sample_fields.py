"""Compact derived fields shared by experiment runners."""

from dataclasses import asdict
from typing import Any

from traffic_platform.contracts.models import CloudStrategy, RegionalState


def intersection_sample_fields(regional: RegionalState) -> dict[str, object]:
    """Return traceable per-intersection queue and speed observations."""

    states = regional.intersection_states
    queues = {state.intersection_id: state.total_queue for state in states}
    return {
        "intersection_queue_vehicles": queues,
        "intersection_mean_speed_m_s": {
            state.intersection_id: state.mean_speed for state in states
        },
        "max_intersection_queue_vehicles": max(queues.values(), default=0),
        "core_corridor_queue_vehicles": sum(
            queue for intersection_id, queue in queues.items() if intersection_id.startswith("K")
        ),
        "max_downstream_occupancy": max(
            (lane.downstream_occupancy for state in states for lane in state.lane_states),
            default=0.0,
        ),
    }


def prediction_sample_fields(
    strategies: dict[str, CloudStrategy],
    *,
    horizon_s: int = 60,
) -> dict[str, object]:
    """Expose only strategy forecasts produced by the real online model."""

    selected = [
        min(
            strategy.forecasts,
            key=lambda item: abs(item.horizon_s - horizon_s),
            default=None,
        )
        for strategy in strategies.values()
    ]
    forecasts = [item for item in selected if item is not None]
    if not forecasts:
        return {
            "prediction_status": "not_available",
            "prediction_model_id": "not_available",
            "prediction_horizon_s": horizon_s,
            "prediction_confidence": 0.0,
            "predicted_queue_vehicles": 0.0,
            "predicted_spillback_risk": 0.0,
            "predicted_intersection_queue_vehicles": {},
        }
    intersection_queues = {
        intersection_id: round(sum(forecast.phase_queues.values()), 4)
        for (intersection_id, strategy), forecast in zip(
            strategies.items(),
            selected,
            strict=False,
        )
        if forecast is not None
    }
    return {
        "prediction_status": (
            "ready" if all(item.confidence >= 0.55 for item in forecasts) else "warming_up"
        ),
        "prediction_model_id": forecasts[0].model_id,
        "prediction_horizon_s": forecasts[0].horizon_s,
        "prediction_confidence": sum(item.confidence for item in forecasts) / len(forecasts),
        "predicted_queue_vehicles": sum(intersection_queues.values()),
        "predicted_spillback_risk": max(
            (item.spillback_risk for item in forecasts),
            default=0.0,
        ),
        "predicted_intersection_queue_vehicles": intersection_queues,
    }


def runner_manifest_fields(config: Any) -> dict[str, object]:
    """Return execution switches that affect timing or retained evidence."""

    return {
        "isolate_algorithms": config.isolate_algorithms,
        "publish_feedback_to_bus": config.publish_feedback_to_bus,
        "publish_runtime_telemetry_to_bus": config.publish_runtime_telemetry_to_bus,
        "include_communication_events": config.include_communication_events,
        "surrogate_safety_interval_s": config.surrogate_safety_interval_s,
    }


def runner_options(config: Any) -> dict[str, object]:
    """Serialize non-scenario runner controls into every raw result."""

    return {
        **runner_manifest_fields(config),
        "scheduled_faults": [asdict(item) for item in config.scheduled_faults],
        "sumo_extra_args": list(config.sumo_extra_args),
    }
