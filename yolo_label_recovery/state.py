"""Atomic run-state helpers for long multi-teacher scans."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

STATE_VERSION = 1


def build_run_signature(payload: dict[str, Any]) -> str:
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def new_state(signature: str, stats: dict) -> dict:
    return {
        "version": STATE_VERSION,
        "signature": signature,
        "status": "running",
        "progress": {},
        "stats": stats,
    }


def load_state(path: Path, expected_signature: str) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"Resume requested but state file is missing: {path}")
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("version") != STATE_VERSION:
        raise ValueError(
            f"Unsupported state version {state.get('version')}; expected {STATE_VERSION}"
        )
    if state.get("signature") != expected_signature:
        raise ValueError(
            "Resume configuration does not match the original run. "
            "Use the same dataset, models, classes, splits and thresholds."
        )
    return state


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def progress_key(class_name: str, split: str) -> str:
    return f"{class_name}/{split}"

