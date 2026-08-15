"""Configuration parsing and model-path resolution."""

from __future__ import annotations

from pathlib import Path

from .domain import CLASS_IDS, DEFAULT_THRESHOLDS, ModelSpec


def parse_thresholds(overrides: list[str]) -> dict[str, tuple[float, float]]:
    thresholds = dict(DEFAULT_THRESHOLDS)
    for item in overrides:
        parts = item.split(":")
        if len(parts) != 3 or parts[0] not in CLASS_IDS:
            raise ValueError(f"Bad threshold override: {item}. Expected class:auto:review")
        auto, review = float(parts[1]), float(parts[2])
        if not 0 <= review <= auto <= 1:
            raise ValueError(f"Thresholds must satisfy 0 <= review <= auto <= 1: {item}")
        thresholds[parts[0]] = (auto, review)
    return thresholds


def parse_model_specs(raw: dict) -> dict[str, ModelSpec]:
    if not isinstance(raw, dict):
        raise ValueError("models.json must contain an object mapping class name to model spec")
    specs: dict[str, ModelSpec] = {}
    for class_name, value in raw.items():
        if isinstance(value, str):
            specs[class_name] = ModelSpec(path=value)
        elif isinstance(value, dict) and "path" in value:
            specs[class_name] = ModelSpec(
                path=str(value["path"]),
                pred_class=int(value.get("pred_class", 0)),
            )
        else:
            raise ValueError(
                f"Model spec for {class_name!r} must be a path string or an object with path/pred_class"
            )
    return specs


def resolve_model_spec_paths(
    specs: dict[str, ModelSpec], models_json: Path
) -> dict[str, ModelSpec]:
    resolved = {}
    base = models_json.resolve().parent
    for class_name, spec in specs.items():
        model_path = Path(spec.path).expanduser()
        if model_path.is_absolute():
            path = model_path.resolve()
        else:
            beside_json = (base / model_path).resolve()
            from_cwd = model_path.resolve()
            path = beside_json if beside_json.exists() or not from_cwd.exists() else from_cwd
        resolved[class_name] = ModelSpec(str(path), spec.pred_class)
    return resolved
