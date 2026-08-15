"""Domain objects and public defaults used across the recovery pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
CLASS_NAMES = ["person", "helmet", "vest", "tractor", "slipper", "smoking"]
CLASS_IDS = {name: idx for idx, name in enumerate(CLASS_NAMES)}
DEFAULT_THRESHOLDS = {
    "person": (0.75, 0.55),
    "helmet": (0.75, 0.55),
    "vest": (0.75, 0.55),
    "tractor": (0.70, 0.50),
    "slipper": (0.65, 0.45),
    "smoking": (0.65, 0.40),
}
COLORS = {
    "person": (60, 220, 60),
    "helmet": (255, 180, 40),
    "vest": (40, 200, 255),
    "tractor": (40, 80, 255),
    "slipper": (255, 80, 220),
    "smoking": (220, 80, 255),
}
CSV_FIELDS = [
    "split", "image", "label", "class_name", "class_id", "conf", "mode",
    "max_iou_same_class", "cx", "cy", "w", "h",
]


@dataclass(frozen=True)
class Box:
    cls: int
    cx: float
    cy: float
    w: float
    h: float
    conf: float = 1.0


@dataclass(frozen=True)
class Candidate:
    split: str
    image: Path
    label: Path
    class_name: str
    class_id: int
    conf: float
    box: Box
    mode: str
    max_iou_same_class: float


@dataclass(frozen=True)
class ModelSpec:
    path: str
    pred_class: int = 0

