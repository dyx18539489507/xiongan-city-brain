"""Static scene-model generation and coordinate conversion for Web 3D."""

from traffic_platform.scene.coordinates import CoordinateDefinition, CoordinateService
from traffic_platform.scene.generator import generate_scene_document
from traffic_platform.scene.models import SceneDocument

__all__ = [
    "CoordinateDefinition",
    "CoordinateService",
    "SceneDocument",
    "generate_scene_document",
]
