"""Deterministic assignment of configured vehicle types to routed trips."""

import random
import xml.etree.ElementTree as ET
from pathlib import Path


def assign_vehicle_types(
    route_file: Path,
    ratios: dict[str, float],
    *,
    seed: int,
) -> dict[str, int]:
    """Assign types reproducibly and rewrite a generated SUMO route file."""

    if abs(sum(ratios.values()) - 1.0) > 1e-6:
        raise ValueError("vehicle type ratios must sum to 1")
    tree = ET.parse(route_file)
    root = tree.getroot()
    vehicles = root.findall("vehicle")
    names = sorted(ratios)
    cumulative: list[tuple[float, str]] = []
    running = 0.0
    for name in names:
        running += ratios[name]
        cumulative.append((running, name))
    counts = {name: 0 for name in names}
    randomizer = random.Random(seed)
    for vehicle in vehicles:
        draw = randomizer.random()
        chosen = cumulative[-1][1]
        for threshold, name in cumulative:
            if draw <= threshold:
                chosen = name
                break
        vehicle.set("type", chosen)
        counts[chosen] += 1
    ET.indent(tree, space="    ")
    tree.write(route_file, encoding="utf-8", xml_declaration=True)
    return counts

