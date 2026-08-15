from __future__ import annotations

import csv
import json

import pytest

from yolo_label_recovery.consensus import run_consensus

FIELDS = ["split", "image", "label", "class_name", "class_id", "conf", "mode", "cx", "cy", "w", "h"]


def _row(
    image: str,
    confidence: float,
    mode: str,
    *,
    cx: float = 0.5,
    class_name: str = "person",
) -> dict[str, str]:
    return {
        "split": "train",
        "image": image,
        "label": image.replace(".jpg", ".txt"),
        "class_name": class_name,
        "class_id": "0",
        "conf": str(confidence),
        "mode": mode,
        "cx": str(cx),
        "cy": "0.5",
        "w": "0.2",
        "h": "0.3",
    }


def _write(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_consensus_matches_one_to_one_and_downgrades_unsupported_auto(tmp_path):
    primary_path = tmp_path / "primary.csv"
    verifier_path = tmp_path / "verifier.csv"
    _write(
        primary_path,
        [
            _row("shared.jpg", 0.92, "auto", cx=0.50),
            _row("shared.jpg", 0.88, "auto", cx=0.51),
            _row("low.jpg", 0.90, "auto"),
            _row("review.jpg", 0.60, "review", class_name="smoking"),
        ],
    )
    _write(
        verifier_path,
        [
            _row("shared.jpg", 0.85, "auto", cx=0.50),
            _row("low.jpg", 0.40, "review"),
            _row("review.jpg", 0.95, "auto", class_name="smoking"),
        ],
    )

    paths = run_consensus(
        primary_path,
        verifier_path,
        tmp_path / "output",
        agreement_iou=0.5,
        verifier_min_confidence=0.5,
        classes=None,
        redact_paths=True,
        label_additions_dir=tmp_path / "additions",
    )

    with paths["all"].open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["consensus_decision"] for row in rows].count("agreed_auto") == 1
    assert [row["consensus_decision"] for row in rows].count("downgraded_to_review") == 2
    assert rows[3]["consensus_decision"] == "primary_review"
    assert rows[3]["mode"] == "review"

    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload["primary_source"] == "<redacted>/primary.csv"
    assert payload["totals"]["agreed_auto"] == 1
    assert payload["totals"]["downgraded_to_review"] == 2
    assert "Cross-Teacher Consensus" in paths["html"].read_text(encoding="utf-8")
    addition_lines = (paths["label_additions"] / "train" / "shared.txt").read_text(encoding="utf-8").splitlines()
    assert len(addition_lines) == 1


def test_consensus_rejects_missing_required_columns(tmp_path):
    primary_path = tmp_path / "primary.csv"
    verifier_path = tmp_path / "verifier.csv"
    primary_path.write_text("class_name,conf\nperson,0.9\n", encoding="utf-8")
    _write(verifier_path, [_row("image.jpg", 0.8, "auto")])

    with pytest.raises(ValueError, match="missing required columns"):
        run_consensus(
            primary_path,
            verifier_path,
            tmp_path / "output",
            agreement_iou=0.5,
            verifier_min_confidence=0.5,
            classes=None,
            redact_paths=False,
            label_additions_dir=None,
        )


def test_consensus_handles_review_only_input(tmp_path):
    primary_path = tmp_path / "primary.csv"
    verifier_path = tmp_path / "verifier.csv"
    _write(primary_path, [_row("review.jpg", 0.60, "review")])
    _write(verifier_path, [_row("review.jpg", 0.90, "auto")])

    paths = run_consensus(
        primary_path,
        verifier_path,
        tmp_path / "output",
        agreement_iou=0.5,
        verifier_min_confidence=0.5,
        classes=None,
        redact_paths=False,
    )

    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload["totals"]["primary_auto"] == 0
    assert "0.0%" in paths["html"].read_text(encoding="utf-8")


def test_nonempty_additions_directory_fails_before_output_write(tmp_path):
    primary_path = tmp_path / "primary.csv"
    verifier_path = tmp_path / "verifier.csv"
    _write(primary_path, [_row("image.jpg", 0.90, "auto")])
    _write(verifier_path, [_row("image.jpg", 0.85, "auto")])
    additions = tmp_path / "additions"
    additions.mkdir()
    (additions / "stale.txt").write_text("stale", encoding="utf-8")
    output = tmp_path / "output"

    with pytest.raises(ValueError, match="must be empty"):
        run_consensus(
            primary_path,
            verifier_path,
            output,
            agreement_iou=0.5,
            verifier_min_confidence=0.5,
            classes=None,
            redact_paths=False,
            label_additions_dir=additions,
        )

    assert not output.exists()
