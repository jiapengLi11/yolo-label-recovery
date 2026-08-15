import json
from pathlib import Path

from yolo_label_recovery.report import generate_report
from yolo_label_recovery.state import build_run_signature, load_state, new_state, save_state


def test_state_signature_and_atomic_round_trip(tmp_path: Path):
    signature = build_run_signature({"dataset": "demo", "batch": 32})
    state = new_state(signature, {"person": {"stable_batch": 32}})
    path = tmp_path / "state.json"
    save_state(path, state)
    assert load_state(path, signature) == state
    assert not path.with_suffix(".json.tmp").exists()


def test_report_generation(tmp_path: Path):
    output_root = tmp_path / "run"
    output_root.mkdir()
    summary = {
        "dataset_root": "demo",
        "dry_run": True,
        "device": "cpu",
        "imgsz": 640,
        "batch": 4,
        "classes": ["person"],
        "stats": {
            "person": {
                "images_scanned": 12,
                "matched_existing": 4,
                "duplicate_candidates": 0,
                "auto_added": 1,
                "review_candidates": 0,
                "initial_batch": 4,
                "stable_batch": 2,
                "oom_retries": 1,
            }
        },
    }
    (output_root / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (output_root / "manifest.json").write_text(
        json.dumps({
            "tool_version": "0.3.0",
            "environment": {
                "python": "3.11-test",
                "packages": {"torch": "2.7-test"},
                "cuda": {"torch_cuda_version": "12.8-test", "devices": [{"name": "Synthetic GPU"}]},
            },
        }),
        encoding="utf-8",
    )
    report = generate_report(output_root, output_root / "report.html")
    content = report.read_text(encoding="utf-8")
    assert "YOLO Label Recovery" in content
    assert "4 -&gt; 2" not in content
    assert "4 -> 2" in content
    assert "OOM retries" in content
    assert "Synthetic GPU" in content
    assert "Reproducibility" in content

    redacted = generate_report(output_root, output_root / "report-public.html", redact_paths=True)
    redacted_content = redacted.read_text(encoding="utf-8")
    assert "&lt;redacted&gt;/demo" in redacted_content
