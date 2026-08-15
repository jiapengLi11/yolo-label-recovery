"""Runtime diagnostics and reproducible run manifests."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def collect_environment() -> dict[str, Any]:
    """Collect useful diagnostics without requiring CUDA to be available."""
    environment: dict[str, Any] = {
        "tool_version": __version__,
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "packages": {
            name: _package_version(name)
            for name in ("ultralytics", "torch", "torchvision", "opencv-python", "Pillow", "PyYAML", "numpy")
        },
    }
    try:
        import torch

        cuda_available = torch.cuda.is_available()
        cuda: dict[str, Any] = {
            "available": cuda_available,
            "torch_cuda_version": torch.version.cuda,
            "cudnn_version": torch.backends.cudnn.version() if torch.backends.cudnn.is_available() else None,
            "device_count": torch.cuda.device_count() if cuda_available else 0,
            "devices": [],
        }
        if cuda_available:
            for index in range(torch.cuda.device_count()):
                properties = torch.cuda.get_device_properties(index)
                cuda["devices"].append({
                    "index": index,
                    "name": properties.name,
                    "total_memory_bytes": properties.total_memory,
                    "compute_capability": f"{properties.major}.{properties.minor}",
                })
        environment["cuda"] = cuda
    except Exception as error:
        environment["cuda"] = {"available": False, "diagnostic_error": str(error)}
    return environment


def _json_ready(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(_json_ready(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def write_run_manifest(
    path: Path,
    *,
    signature: str,
    arguments: dict[str, Any],
    inventory: dict[str, Any],
    resume: bool,
) -> dict[str, Any]:
    """Create or refresh a local manifest at the start of a run."""
    existing: dict[str, Any] = {}
    if resume and path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
    now = _utc_now()
    environment = collect_environment()
    current_arguments = _json_ready(arguments)
    manifest = {
        "schema_version": 1,
        "tool": "yolo-label-recovery",
        "tool_version": __version__,
        "run_signature": signature,
        "status": "running",
        "created_at": existing.get("created_at", now),
        "last_started_at": now,
        "completed_at": None,
        "resume_count": int(existing.get("resume_count", 0)) + (1 if resume else 0),
        "arguments": existing.get("arguments", current_arguments),
        "last_invocation_arguments": current_arguments,
        "inventory": _json_ready(inventory),
        "initial_environment": existing.get("initial_environment", existing.get("environment", environment)),
        "environment": environment,
    }
    write_json_atomic(path, manifest)
    return manifest


def finalize_run_manifest(path: Path, summary: dict[str, Any]) -> None:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["status"] = "complete"
    manifest["completed_at"] = _utc_now()
    manifest["result"] = {
        "total_auto_added": summary.get("total_auto_added", 0),
        "total_review_candidates": summary.get("total_review_candidates", 0),
        "stats": summary.get("stats", {}),
    }
    write_json_atomic(path, manifest)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Print the runtime environment used by YOLO Label Recovery.")
    parser.add_argument("--output", type=Path, help="Optionally save the diagnostics as JSON.")
    parser.add_argument("--redact-paths", action="store_true", help="Hide the local Python executable path.")
    args = parser.parse_args(argv)
    environment = collect_environment()
    if args.redact_paths:
        environment["python_executable"] = "<redacted>"
    rendered = json.dumps(environment, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        write_json_atomic(args.output.expanduser().resolve(), environment)


if __name__ == "__main__":
    main()
