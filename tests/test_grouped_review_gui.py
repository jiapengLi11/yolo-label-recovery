from __future__ import annotations

import csv
import json

import pytest

from yolo_label_recovery.review_gui import atomic_write_rows, group_rows, read_rows, replay_journal


def _row(candidate_id: str, image: str, class_name: str, *, split: str = "train", case: str = "TRAIN_MISSING_HIGH"):
    return {
        "candidate_id": candidate_id,
        "split": split,
        "image": f"images/{split}/{image}",
        "image_name": image,
        "class_name": class_name,
        "conf": "0.900",
        "case_code": case,
        "recommended_action": "accept_add_or_reject",
        "visual_file": f"visuals/{candidate_id}.jpg",
        "reviewer_decision": "",
        "reviewer_comment": "",
    }


def test_group_rows_keeps_candidates_from_one_image_together_and_prioritizes_rare_classes():
    rows = [
        _row("R1", "person.jpg", "person"),
        _row("R2", "joint.jpg", "smoking"),
        _row("R3", "joint.jpg", "helmet"),
        _row("R4", "eval.jpg", "tractor", split="val", case="EVAL_MISSING_HIGH"),
    ]

    groups = group_rows(rows)

    assert groups[0] == [2, 1]
    assert [rows[index]["image_name"] for index in groups[0]] == ["joint.jpg", "joint.jpg"]
    assert groups[-1] == [3]


def test_journal_replay_recovers_valid_events_and_skips_partial_tail(tmp_path):
    rows = {"R1": _row("R1", "one.jpg", "helmet"), "R2": _row("R2", "two.jpg", "vest")}
    journal = tmp_path / "progress.jsonl"
    journal.write_text(
        json.dumps({"candidate_id": "R1", "reviewer_decision": "accept_add", "reviewer_comment": "clear"})
        + "\n"
        + '{"candidate_id":"R2"',
        encoding="utf-8",
    )

    assert replay_journal(journal, rows) == 1
    assert rows["R1"]["reviewer_decision"] == "accept_add"
    assert rows["R2"]["reviewer_decision"] == ""


def test_atomic_export_round_trips_utf8_comments(tmp_path):
    rows = [_row("R1", "one.jpg", "helmet")]
    rows[0]["reviewer_comment"] = "边界清晰, 可以新增"
    fields = list(rows[0])
    output = tmp_path / "decisions.csv"

    atomic_write_rows(output, rows, fields)

    loaded, loaded_fields = read_rows(output)
    assert loaded_fields == fields
    assert loaded[0]["reviewer_comment"] == "边界清晰, 可以新增"
    assert not output.with_suffix(".csv.tmp").exists()


def test_read_rows_rejects_incomplete_schema(tmp_path):
    output = tmp_path / "invalid.csv"
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["candidate_id"])
        writer.writeheader()
        writer.writerow({"candidate_id": "R1"})

    with pytest.raises(ValueError, match="missing required columns"):
        read_rows(output)
