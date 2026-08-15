"""Shared helpers for reading a YOLO detection dataset."""

from __future__ import annotations

from pathlib import Path

import yaml


def load_dataset_metadata(dataset_root: Path) -> tuple[dict, list[str]]:
    """Load and validate class metadata from a standard YOLO ``data.yaml``."""
    data_yaml = dataset_root / "data.yaml"
    if not data_yaml.is_file():
        raise FileNotFoundError(f"Missing YOLO data.yaml: {data_yaml}")
    data = yaml.safe_load(data_yaml.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Invalid data.yaml: expected a mapping, got {type(data).__name__}")

    raw_names = data.get("names")
    if isinstance(raw_names, list):
        names = [str(name) for name in raw_names]
    elif isinstance(raw_names, dict):
        try:
            indexed = {int(key): str(value) for key, value in raw_names.items()}
        except (TypeError, ValueError) as error:
            raise ValueError("data.yaml names dict must use integer-like keys") from error
        if indexed:
            expected = set(range(max(indexed) + 1))
            if set(indexed) != expected:
                raise ValueError("data.yaml names ids must be contiguous from 0")
            names = [indexed[index] for index in range(max(indexed) + 1)]
        else:
            names = []
    else:
        raise ValueError("data.yaml must contain names as a list or id->name mapping")

    if not names:
        raise ValueError("data.yaml contains no class names")
    if len(set(names)) != len(names):
        raise ValueError("data.yaml contains duplicate class names; class ids would be ambiguous")
    nc = data.get("nc")
    if nc is not None and int(nc) != len(names):
        raise ValueError(f"data.yaml nc={nc} but names contains {len(names)} classes")
    return data, names

