from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageEnhance

from yolo_label_recovery.near_duplicates import BKTree, hamming_distance, run_clustering


def _scene() -> Image.Image:
    image = Image.new("RGB", (320, 240), "#d6e3dc")
    draw = ImageDraw.Draw(image)
    for y in range(240):
        shade = 70 + y // 2
        draw.line((0, y, 319, y), fill=(shade, min(255, shade + 35), min(255, shade + 18)))
    draw.rectangle((38, 44, 145, 205), fill="#e9a63a", outline="#173e48", width=7)
    draw.ellipse((170, 55, 286, 171), fill="#236f79", outline="#f5e4b6", width=9)
    draw.line((24, 220, 300, 16), fill="#c82f3c", width=11)
    return image


def _build_dataset(root: Path) -> None:
    for split in ("train", "val", "test"):
        (root / "images" / split).mkdir(parents=True)
    base = _scene()
    base.save(root / "images" / "train" / "site.png")
    ImageEnhance.Brightness(base.resize((640, 480))).enhance(1.08).save(
        root / "images" / "val" / "site_resized.jpg", quality=83
    )
    different = Image.new("RGB", (320, 240), "#e8e2cf")
    draw = ImageDraw.Draw(different)
    for x in range(0, 320, 20):
        draw.rectangle((x, 0, x + 9, 239), fill="#162c4a")
    different.save(root / "images" / "test" / "different.png")
    Image.new("RGB", (320, 240), "black").save(root / "images" / "train" / "black.png")
    Image.new("RGB", (320, 240), "white").save(root / "images" / "train" / "white.png")
    (root / "images" / "test" / "broken.jpg").write_bytes(b"not an image")


def test_bk_tree_finds_hamming_neighbors():
    tree = BKTree()
    tree.add(0b0000, 0)
    tree.add(0b1111, 1)
    tree.add(0b0011, 2)

    matches = {node.value for _, node in tree.search(0b0001, 1)}

    assert matches == {0b0000, 0b0011}
    assert hamming_distance(0b1010, 0b1111) == 2


def test_cluster_groups_transforms_flags_leakage_and_rejects_flat_collision(tmp_path):
    dataset = tmp_path / "dataset"
    output = tmp_path / "output"
    _build_dataset(dataset)

    summary = run_clustering(dataset, output, splits=["train", "val", "test"], workers=2, redact_paths=True)

    assert summary["totals"]["images_discovered"] == 6
    assert summary["totals"]["images_fingerprinted"] == 5
    assert summary["totals"]["fingerprint_failures"] == 1
    assert summary["totals"]["clusters"] == 1
    assert summary["totals"]["clustered_images"] == 2
    assert summary["totals"]["cross_split_clusters"] == 1
    assert summary["dataset_root"].startswith("<redacted>/")
    assert set(summary["clusters"][0]["member_paths"]) == {
        "images/train/site.png",
        "images/val/site_resized.jpg",
    }

    with (output / "near_duplicate_members.csv").open(encoding="utf-8-sig") as handle:
        member_rows = list(csv.DictReader(handle))
    assert len(member_rows) == 2
    assert sum(row["is_representative"] == "true" for row in member_rows) == 1
    assert "different.png" not in (output / "near_duplicate_members.csv").read_text(encoding="utf-8-sig")
    assert "black.png" not in (output / "near_duplicate_members.csv").read_text(encoding="utf-8-sig")
    assert "white.png" not in (output / "near_duplicate_members.csv").read_text(encoding="utf-8-sig")
    assert "Perceptual near-duplicate audit" in (output / "near_duplicate_report.html").read_text(encoding="utf-8")
    assert json.loads((output / "near_duplicate_summary.json").read_text(encoding="utf-8"))["totals"] == summary["totals"]


def test_cluster_output_is_deterministic_except_timestamp(tmp_path):
    dataset = tmp_path / "dataset"
    _build_dataset(dataset)

    first = run_clustering(dataset, tmp_path / "first", splits=["train", "val", "test"], workers=1)
    second = run_clustering(dataset, tmp_path / "second", splits=["train", "val", "test"], workers=3)

    assert first["totals"] == second["totals"]
    assert first["clusters"] == second["clusters"]


def test_cluster_rejects_output_inside_source_dataset(tmp_path):
    dataset = tmp_path / "dataset"
    _build_dataset(dataset)

    with pytest.raises(ValueError, match="outside the source dataset"):
        run_clustering(dataset, dataset / "audit-output", splits=["train"], workers=1)
