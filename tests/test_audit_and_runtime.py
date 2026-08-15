import json
import shutil
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from yolo_label_recovery.audit import audit_dataset, generate_audit_report
from yolo_label_recovery.runtime import finalize_run_manifest, write_run_manifest


def _image(path: Path, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 24), color).save(path)


def test_audit_finds_bad_labels_and_cross_split_leakage(tmp_path: Path):
    root = tmp_path / "dataset"
    (root / "data.yaml").parent.mkdir(parents=True)
    (root / "data.yaml").write_text("nc: 2\nnames: [person, helmet]\n", encoding="utf-8")

    train_image = root / "images" / "train" / "scene.png"
    _image(train_image, (20, 80, 130))
    train_label = root / "labels" / "train" / "scene.txt"
    train_label.parent.mkdir(parents=True)
    train_label.write_text("0 0.5 0.5 0.4 0.6\n", encoding="utf-8")

    val_image = root / "images" / "val" / "leaked.png"
    val_image.parent.mkdir(parents=True)
    shutil.copy2(train_image, val_image)
    val_label = root / "labels" / "val" / "leaked.txt"
    val_label.parent.mkdir(parents=True)
    val_label.write_text("8 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    (root / "labels" / "val" / "orphan.txt").write_text("1 0.5 0.5 0.2 0.2\n", encoding="utf-8")

    audit = audit_dataset(root, ["train", "val"], hash_images=True, check_images=True)
    assert audit["status"] == "fail"
    assert audit["critical_issues"] == 2
    assert audit["issue_counts"]["invalid_class_id"] == 1
    assert audit["issue_counts"]["orphan_label"] == 1
    assert audit["cross_split_duplicate_groups"] == 1
    assert audit["class_objects"] == {"person": 1, "helmet": 0}

    report = generate_audit_report(audit, tmp_path / "audit.html")
    assert "YOLO Dataset Audit" in report.read_text(encoding="utf-8")
    assert "cross_split_duplicate" in report.read_text(encoding="utf-8")

    bounded = audit_dataset(root, ["train", "val"], hash_images=True, max_issue_details=1)
    assert sum(bounded["issue_counts"].values()) == 3
    assert len(bounded["issues"]) == 1
    assert bounded["issue_details_truncated"] == 2


def test_manifest_lifecycle_is_atomic(tmp_path: Path):
    path = tmp_path / "manifest.json"
    fake_environment = {"python": "test", "cuda": {"available": False}}
    with patch("yolo_label_recovery.runtime.collect_environment", return_value=fake_environment):
        manifest = write_run_manifest(
            path,
            signature="abc123",
            arguments={"dataset_root": Path("demo")},
            inventory={"images_by_split": {"train": 4}},
            resume=False,
        )
    assert manifest["status"] == "running"
    assert manifest["resume_count"] == 0
    assert not path.with_suffix(".json.tmp").exists()

    finalize_run_manifest(path, {"total_auto_added": 3, "total_review_candidates": 2, "stats": {}})
    completed = json.loads(path.read_text(encoding="utf-8"))
    assert completed["status"] == "complete"
    assert completed["result"]["total_auto_added"] == 3

    with patch("yolo_label_recovery.runtime.collect_environment", return_value=fake_environment):
        resumed = write_run_manifest(
            path,
            signature="abc123",
            arguments={},
            inventory={},
            resume=True,
        )
    assert resumed["resume_count"] == 1
    assert resumed["created_at"] == completed["created_at"]
