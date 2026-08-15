from __future__ import annotations

import csv
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from yolo_label_recovery.prioritization import confidence_entropy, run_prioritization


def _pattern(color: str, shape: str) -> Image.Image:
    image = Image.new("RGB", (320, 240), "#e7e2d5")
    draw = ImageDraw.Draw(image)
    if shape == "circle":
        draw.ellipse((45, 25, 275, 220), fill=color, outline="#132f3b", width=12)
    elif shape == "stripe":
        for x in range(0, 320, 32):
            draw.rectangle((x, 0, x + 15, 239), fill=color)
    elif shape == "triangle":
        draw.polygon(((160, 15), (300, 220), (20, 220)), fill=color, outline="#132f3b")
    else:
        draw.rectangle((55, 35, 265, 210), fill=color, outline="#132f3b", width=12)
    return image


def _fixture(root: Path, csv_path: Path) -> None:
    image_root = root / "images" / "train"
    image_root.mkdir(parents=True)
    person = _pattern("#dc8935", "circle")
    person.save(image_root / "person_a.png")
    person.resize((640, 480)).save(image_root / "person_duplicate.jpg", quality=82)
    _pattern("#376b91", "stripe").save(image_root / "person_unique.png")
    _pattern("#d3bb31", "triangle").save(image_root / "helmet.png")
    smoking_path = image_root / "smoking.png"
    _pattern("#a24873", "box").save(smoking_path)
    rows = [
        ("person_a.png", "person", 0.50),
        ("person_duplicate.jpg", "person", 0.51),
        ("person_unique.png", "person", 0.55),
        ("helmet.png", "helmet", 0.82),
        (str(smoking_path.resolve()), "smoking", 0.50),
        ("missing.png", "slipper", 0.50),
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["split", "image", "class_name", "conf", "mode", "cx", "cy", "w", "h"])
        for image, class_name, confidence in rows:
            writer.writerow(["train", image, class_name, confidence, "review", 0.5, 0.5, 0.2, 0.2])


def test_confidence_entropy_has_expected_boundaries():
    assert confidence_entropy(0) == 0
    assert confidence_entropy(1) == 0
    assert confidence_entropy(0.5) == pytest.approx(1)
    assert confidence_entropy(0.6) == confidence_entropy(0.4)


def test_prioritization_favors_rare_uncertain_and_diverse_images(tmp_path):
    dataset = tmp_path / "dataset"
    candidates = tmp_path / "candidates.csv"
    output = tmp_path / "output"
    _fixture(dataset, candidates)

    summary = run_prioritization(candidates, dataset, output, budget=4, workers=2, redact_paths=True)

    assert summary["totals"] == {
        "candidate_rows": 6,
        "review_images": 5,
        "selected_images": 4,
        "unselected_images": 1,
        "image_failures": 1,
        "pool_classes": 3,
        "selected_classes": 3,
    }
    assert summary["queue"][0]["candidate_classes"] == "smoking"
    selected_paths = {row["image"] for row in summary["queue"]}
    assert not {"images/train/person_a.png", "images/train/person_duplicate.jpg"}.issubset(selected_paths)
    assert summary["sources"]["dataset_root"].startswith("<redacted>/")
    assert (output / "review_queue.csv").is_file()
    assert (output / "review_queue_candidates.csv").is_file()
    assert (output / "review_pool.csv").is_file()
    assert "Active review priority" in (output / "prioritization_report.html").read_text(encoding="utf-8")


def test_prioritization_is_deterministic_across_worker_counts(tmp_path):
    dataset = tmp_path / "dataset"
    candidates = tmp_path / "candidates.csv"
    _fixture(dataset, candidates)

    first = run_prioritization(candidates, dataset, tmp_path / "first", budget=4, workers=1)
    second = run_prioritization(candidates, dataset, tmp_path / "second", budget=4, workers=3)

    assert first["queue"] == second["queue"]
    assert first["class_distribution"] == second["class_distribution"]


def test_prioritization_rejects_invalid_weights_and_source_output(tmp_path):
    dataset = tmp_path / "dataset"
    candidates = tmp_path / "candidates.csv"
    _fixture(dataset, candidates)

    with pytest.raises(ValueError, match="sum to 1"):
        run_prioritization(candidates, dataset, tmp_path / "bad", uncertainty_weight=1, rarity_weight=1, diversity_weight=1)
    with pytest.raises(ValueError, match="outside the source dataset"):
        run_prioritization(candidates, dataset, dataset / "output")
