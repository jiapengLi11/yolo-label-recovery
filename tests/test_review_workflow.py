from __future__ import annotations

import csv
import json
from pathlib import Path

import yaml
from PIL import Image

from yolo_label_recovery.review import build_review_package
from yolo_label_recovery.review_apply import apply_review_decisions

NAMES = ["person", "helmet", "vest", "tractor", "slipper", "smoking"]
CANDIDATE_FIELDS = ["split", "image", "label", "class_name", "class_id", "conf", "mode", "cx", "cy", "w", "h"]


def _create_dataset(root: Path) -> None:
    for split in ("train", "val", "test"):
        (root / "images" / split).mkdir(parents=True)
        (root / "labels" / split).mkdir(parents=True)
    for name in ("missing", "same", "cross", "quiet"):
        Image.new("RGB", (320, 240), (225, 230, 220)).save(root / "images" / "train" / f"{name}.jpg")
    Image.new("RGB", (320, 240), (220, 225, 235)).save(root / "images" / "val" / "eval.jpg")
    (root / "labels" / "train" / "missing.txt").write_text("", encoding="utf-8")
    (root / "labels" / "train" / "same.txt").write_text(
        "0 0.500000 0.500000 0.200000 0.400000\n", encoding="utf-8"
    )
    (root / "labels" / "train" / "cross.txt").write_text(
        "0 0.500000 0.500000 0.250000 0.400000\n", encoding="utf-8"
    )
    (root / "labels" / "train" / "quiet.txt").write_text(
        "1 0.300000 0.300000 0.100000 0.100000\n", encoding="utf-8"
    )
    (root / "labels" / "val" / "eval.txt").write_text("", encoding="utf-8")
    (root / "data.yaml").write_text(
        yaml.safe_dump(
            {
                "path": root.as_posix(),
                "train": "images/train",
                "val": "images/val",
                "test": "images/test",
                "nc": len(NAMES),
                "names": NAMES,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _candidate(
    image: str,
    class_name: str,
    class_id: int,
    confidence: float,
    cx: float,
    cy: float,
    width: float,
    height: float,
    *,
    split: str = "train",
) -> dict[str, str]:
    return {
        "split": split,
        "image": str(Path("images") / split / image),
        "label": str(Path("labels") / split / f"{Path(image).stem}.txt"),
        "class_name": class_name,
        "class_id": str(class_id),
        "conf": str(confidence),
        "mode": "auto",
        "cx": str(cx),
        "cy": str(cy),
        "w": str(width),
        "h": str(height),
    }


def _write_candidates(path: Path) -> None:
    rows = [
        _candidate("missing.jpg", "helmet", 1, 0.92, 0.3, 0.3, 0.1, 0.1),
        _candidate("same.jpg", "person", 0, 0.94, 0.58, 0.5, 0.3, 0.5),
        _candidate("cross.jpg", "helmet", 1, 0.90, 0.5, 0.5, 0.25, 0.4),
        _candidate("eval.jpg", "smoking", 5, 0.88, 0.6, 0.4, 0.08, 0.08, split="val"),
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANDIDATE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _policy() -> Path:
    return Path(__file__).parents[1] / "configs" / "review_policy.example.yaml"


def test_build_review_package_covers_matrix_and_renders_offline_bundle(tmp_path):
    dataset = tmp_path / "dataset"
    candidates = tmp_path / "candidates.csv"
    output = tmp_path / "review"
    _create_dataset(dataset)
    _write_candidates(candidates)

    paths = build_review_package(
        dataset,
        candidates,
        _policy(),
        output,
        render=True,
        redact_paths=True,
    )

    with paths["audit"].open(newline="", encoding="utf-8-sig") as handle:
        audited = list(csv.DictReader(handle))
    assert {row["case_code"] for row in audited} == {
        "TRAIN_MISSING_HIGH",
        "GT_SAME_AMBIGUOUS",
        "GT_CROSS_CLASS_CONFLICT",
        "EVAL_MISSING_HIGH",
    }
    with (output / "image_class_gt_auto_cases.csv").open(newline="", encoding="utf-8-sig") as handle:
        image_cases = {row["image_case"] for row in csv.DictReader(handle)}
    assert image_cases == {"GT0_AUTO0", "GT0_AUTO1", "GT1_AUTO0", "GT1_AUTO1"}
    assert len(list((output / "visuals").rglob("*.jpg"))) == 4
    assert (output / "START_REVIEW.bat").is_file()
    assert (output / "review_gui.py").is_file()
    summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
    assert summary["dataset_root"] == "<redacted>"
    assert summary["source_dataset_modified"] is False


def test_review_apply_adds_replaces_holds_eval_and_preserves_source(tmp_path):
    dataset = tmp_path / "dataset"
    candidates = tmp_path / "candidates.csv"
    review = tmp_path / "review"
    output = tmp_path / "reviewed-dataset"
    _create_dataset(dataset)
    _write_candidates(candidates)
    build_review_package(dataset, candidates, _policy(), review)

    template = review / "company_decisions_template.csv"
    with template.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
        fields = list(rows[0])
    for row in rows:
        row["reviewer_decision"] = {
            "TRAIN_MISSING_HIGH": "accept_add",
            "GT_SAME_AMBIGUOUS": "accept_replace_gt",
            "GT_CROSS_CLASS_CONFLICT": "reject",
            "EVAL_MISSING_HIGH": "accept_eval_label",
        }[row["case_code"]]
    decisions = review / "company_decisions.csv"
    with decisions.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    source_same = (dataset / "labels" / "train" / "same.txt").read_text(encoding="utf-8")
    paths = apply_review_decisions(dataset, decisions, _policy(), output, image_mode="copy")

    assert (dataset / "labels" / "train" / "same.txt").read_text(encoding="utf-8") == source_same
    assert (output / "labels" / "train" / "missing.txt").read_text(encoding="utf-8").startswith("1 ")
    replaced = (output / "labels" / "train" / "same.txt").read_text(encoding="utf-8").strip()
    assert replaced == "0 0.580000 0.500000 0.300000 0.500000"
    assert (output / "labels" / "val" / "eval.txt").read_text(encoding="utf-8") == ""
    summary = paths["summary"].read_text(encoding="utf-8")
    assert "source_dataset_modified: False" in summary
    assert "applied_or_replaced: 2" in summary
    assert "held_reviewed_eval: 1" in summary


def test_review_apply_rejects_unresolved_decisions(tmp_path):
    dataset = tmp_path / "dataset"
    candidates = tmp_path / "candidates.csv"
    review = tmp_path / "review"
    _create_dataset(dataset)
    _write_candidates(candidates)
    build_review_package(dataset, candidates, _policy(), review)
    decisions = review / "company_decisions_template.csv"

    try:
        apply_review_decisions(dataset, decisions, _policy(), tmp_path / "output")
    except ValueError as error:
        assert "blank/uncertain" in str(error)
    else:
        raise AssertionError("Unresolved review decisions must block dataset writes")
