from __future__ import annotations

import csv
import json

import pytest

from yolo_label_recovery.calibration import (
    ReviewedCandidate,
    build_threshold_curve,
    calibrate,
    read_reviewed_candidates,
    wilson_lower_bound,
    write_outputs,
)


def _candidate(confidence: float, accepted: bool, class_name: str = "smoking") -> ReviewedCandidate:
    return ReviewedCandidate(class_name=class_name, confidence=confidence, accepted=accepted)


def test_calibration_selects_precision_and_recall_constrained_thresholds():
    candidates = [
        _candidate(0.95, True),
        _candidate(0.90, True),
        _candidate(0.85, True),
        _candidate(0.80, False),
        _candidate(0.75, False),
        _candidate(0.70, True),
        _candidate(0.60, False),
    ]

    results, _ = calibrate(
        candidates,
        target_auto_precision=1.0,
        auto_confidence_level=0.0,
        target_review_recall=1.0,
        min_auto_samples=3,
    )

    smoking = results["smoking"]
    assert smoking["status"] == "calibrated"
    assert smoking["auto_threshold"] == pytest.approx(0.85)
    assert smoking["auto_precision"] == pytest.approx(1.0)
    assert smoking["review_threshold"] == pytest.approx(0.70)
    assert smoking["captured_positive_recall"] == pytest.approx(1.0)
    assert smoking["review_queue_samples"] == 3


def test_curve_aggregates_equal_confidences_once():
    curve = build_threshold_curve(
        [_candidate(0.8, True), _candidate(0.8, False), _candidate(0.5, True)]
    )

    assert [point.threshold for point in curve] == [0.5, 0.8]
    assert curve[1].selected == 2
    assert curve[1].precision == pytest.approx(0.5)


def test_calibration_refuses_unattainable_auto_policy():
    candidates = [_candidate(0.9, False), _candidate(0.8, True), _candidate(0.7, False)]

    results, _ = calibrate(
        candidates,
        target_auto_precision=1.0,
        auto_confidence_level=0.0,
        target_review_recall=1.0,
        min_auto_samples=2,
    )

    assert results["smoking"]["status"] == "auto_target_not_met"
    assert results["smoking"]["auto_threshold"] is None


def test_csv_validation_and_output_artifacts(tmp_path):
    reviewed_csv = tmp_path / "reviewed.csv"
    with reviewed_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["class_name", "conf", "verdict"])
        writer.writeheader()
        writer.writerows(
            [
                {"class_name": "helmet", "conf": "0.95", "verdict": "accept"},
                {"class_name": "helmet", "conf": "0.80", "verdict": "reject"},
            ]
        )

    candidates = read_reviewed_candidates(reviewed_csv)
    results, curves = calibrate(
        candidates,
        target_auto_precision=1.0,
        auto_confidence_level=0.0,
        target_review_recall=1.0,
        min_auto_samples=1,
    )
    paths = write_outputs(
        reviewed_csv,
        tmp_path / "output",
        results=results,
        curves=curves,
        target_auto_precision=1.0,
        auto_confidence_level=0.0,
        target_review_recall=1.0,
        min_auto_samples=1,
        redact_paths=True,
    )

    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload["source"] == "<redacted>/reviewed.csv"
    assert payload["threshold_overrides"]["helmet"] == "helmet:0.950:0.950"
    assert paths["curve"].is_file()
    assert "Threshold Calibration Report" in paths["html"].read_text(encoding="utf-8")


def test_csv_rejects_unknown_verdict(tmp_path):
    reviewed_csv = tmp_path / "bad.csv"
    reviewed_csv.write_text("class_name,conf,verdict\nperson,0.9,maybe\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported verdict"):
        read_reviewed_candidates(reviewed_csv)


def test_wilson_lower_bound_penalizes_small_perfect_samples():
    assert wilson_lower_bound(10, 10, 0.95) == pytest.approx(0.7225, abs=0.0001)
    assert wilson_lower_bound(100, 100, 0.95) == pytest.approx(0.9630, abs=0.0001)
    assert wilson_lower_bound(10, 10, 0.0) == pytest.approx(1.0)


def test_confidence_aware_calibration_requires_statistical_support():
    candidates = [_candidate(0.99 - index * 0.001, True) for index in range(100)]

    results, _ = calibrate(
        candidates,
        target_auto_precision=0.95,
        auto_confidence_level=0.95,
        target_review_recall=1.0,
        min_auto_samples=20,
    )

    smoking = results["smoking"]
    assert smoking["status"] == "calibrated"
    assert smoking["auto_samples"] >= 73
    assert smoking["auto_precision"] == pytest.approx(1.0)
    assert smoking["auto_precision_lower_bound"] >= 0.95
