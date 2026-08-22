from __future__ import annotations

from yolo_label_recovery.domain import Box
from yolo_label_recovery.review_decision import (
    classify_candidate,
    image_class_state,
    overlap_metrics,
    same_class_relation,
)

GEOMETRY = {
    "existing_high_iou": 0.60,
    "existing_high_ios": 0.90,
    "existing_high_center_distance": 0.35,
    "existing_ambiguous_iou": 0.20,
    "existing_ambiguous_ios": 0.55,
    "existing_ambiguous_center_distance": 0.80,
}
CLASS_POLICY = {"high_conf": 0.80, "review_conf": 0.55}
SPLIT_POLICY = {"train": "review_and_apply", "val": "review_gold_only", "test": "review_gold_only"}


def _decide(**overrides):
    values = {
        "split": "train",
        "confidence": 0.90,
        "class_policy": CLASS_POLICY,
        "same_relation": "distinct_or_missing",
        "cross_conflict": False,
        "model_duplicate": False,
        "box_is_valid": True,
        "split_policy": SPLIT_POLICY,
    }
    values.update(overrides)
    return classify_candidate(**values)


def test_image_class_state_enumerates_all_four_gt_auto_cases():
    assert {image_class_state(gt, auto) for gt in (0, 1) for auto in (0, 1)} == {
        "GT0_AUTO0",
        "GT0_AUTO1",
        "GT1_AUTO0",
        "GT1_AUTO1",
    }


def test_terminal_decision_matrix():
    assert _decide(box_is_valid=False).case_code == "INVALID"
    assert _decide(model_duplicate=True).case_code == "MODEL_DUPLICATE"
    assert _decide(same_relation="already_labeled").case_code == "GT_ALREADY_LABELED"
    assert _decide(same_relation="ambiguous_same_target").case_code == "GT_SAME_AMBIGUOUS"
    assert _decide(cross_conflict=True).case_code == "GT_CROSS_CLASS_CONFLICT"
    assert _decide(confidence=0.90).case_code == "TRAIN_MISSING_HIGH"
    assert _decide(confidence=0.60).case_code == "TRAIN_MISSING_MEDIUM"
    assert _decide(confidence=0.30).case_code == "BELOW_REVIEW_THRESHOLD"
    assert _decide(split="test").case_code == "EVAL_MISSING_HIGH"
    assert _decide(split="unknown").case_code == "SPLIT_DISABLED"


def test_ios_and_center_distance_recover_scale_mismatch():
    gt = Box(0, 0.5, 0.5, 0.6, 0.6)
    contained = Box(0, 0.5, 0.5, 0.2, 0.2)
    metrics = overlap_metrics(contained, gt)
    assert metrics["iou"] < GEOMETRY["existing_high_iou"]
    assert metrics["ios"] == 1.0
    assert same_class_relation(metrics, GEOMETRY) == "already_labeled"


def test_partial_same_target_requires_explicit_replace_or_reject():
    gt = Box(0, 0.5, 0.5, 0.4, 0.4)
    shifted = Box(0, 0.65, 0.5, 0.4, 0.4)
    relation = same_class_relation(overlap_metrics(shifted, gt), GEOMETRY)
    decision = _decide(same_relation=relation)
    assert relation == "ambiguous_same_target"
    assert decision.recommended_action == "replace_or_reject"
