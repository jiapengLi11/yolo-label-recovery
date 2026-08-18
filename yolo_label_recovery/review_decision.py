"""Pure geometry and decision rules for exhaustive GT/AUTO review."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .domain import Box


@dataclass(frozen=True)
class ReviewDecision:
    case_code: str
    review_required: bool
    recommended_action: str
    apply_eligible: bool
    reason: str


EMPTY_METRICS = {
    "iou": 0.0,
    "ios": 0.0,
    "ioc": 0.0,
    "iog": 0.0,
    "center_distance": math.inf,
    "area_ratio": math.inf,
}


def valid_box(box: Box) -> bool:
    values = (box.cx, box.cy, box.w, box.h)
    return (
        all(math.isfinite(value) for value in values)
        and 0 <= box.cx <= 1
        and 0 <= box.cy <= 1
        and 0 < box.w <= 1
        and 0 < box.h <= 1
    )


def _xyxy(box: Box) -> tuple[float, float, float, float]:
    return box.cx - box.w / 2, box.cy - box.h / 2, box.cx + box.w / 2, box.cy + box.h / 2


def overlap_metrics(candidate: Box, target: Box) -> dict[str, float]:
    """Return complementary overlap signals for boxes with different scales."""
    ax1, ay1, ax2, ay2 = _xyxy(candidate)
    bx1, by1, bx2, by2 = _xyxy(target)
    intersection_width = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    intersection_height = max(0.0, min(ay2, by2) - max(ay1, by1))
    intersection = intersection_width * intersection_height
    candidate_area = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    target_area = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = candidate_area + target_area - intersection
    smaller_area = min(candidate_area, target_area)
    center_scale = math.sqrt(smaller_area) if smaller_area > 0 else 1.0
    return {
        "iou": intersection / union if union > 0 else 0.0,
        "ios": intersection / smaller_area if smaller_area > 0 else 0.0,
        "ioc": intersection / candidate_area if candidate_area > 0 else 0.0,
        "iog": intersection / target_area if target_area > 0 else 0.0,
        "center_distance": math.hypot(candidate.cx - target.cx, candidate.cy - target.cy) / center_scale,
        "area_ratio": max(candidate_area, target_area) / smaller_area if smaller_area > 0 else math.inf,
    }


def best_match(candidate: Box, targets: list[Box]) -> tuple[int | None, dict[str, float]]:
    if not targets:
        return None, dict(EMPTY_METRICS)
    scored = [(index, overlap_metrics(candidate, target)) for index, target in enumerate(targets)]
    return max(scored, key=lambda item: (item[1]["iou"], item[1]["ios"], -item[1]["center_distance"]))


def same_class_relation(metrics: dict[str, float], geometry: dict[str, float]) -> str:
    if metrics["iou"] >= geometry["existing_high_iou"]:
        return "already_labeled"
    if (
        metrics["ios"] >= geometry["existing_high_ios"]
        and metrics["center_distance"] <= geometry["existing_high_center_distance"]
    ):
        return "already_labeled"
    if metrics["iou"] >= geometry["existing_ambiguous_iou"]:
        return "ambiguous_same_target"
    if (
        metrics["ios"] >= geometry["existing_ambiguous_ios"]
        and metrics["center_distance"] <= geometry["existing_ambiguous_center_distance"]
    ):
        return "ambiguous_same_target"
    return "distinct_or_missing"


def is_cross_class_conflict(metrics: dict[str, float], geometry: dict[str, float]) -> bool:
    return (
        metrics["iou"] >= geometry["cross_class_conflict_iou"]
        and metrics["area_ratio"] <= geometry["cross_class_conflict_area_ratio"]
    )


def confidence_band(confidence: float, class_policy: dict[str, float]) -> str:
    if confidence >= class_policy["high_conf"]:
        return "high"
    if confidence >= class_policy["review_conf"]:
        return "medium"
    return "low"


def image_class_state(gt_count: int, auto_count: int) -> str:
    """Enumerate every image/class combination, including absence states."""
    return f"GT{int(gt_count > 0)}_AUTO{int(auto_count > 0)}"


def classify_candidate(
    *,
    split: str,
    confidence: float,
    class_policy: dict[str, float],
    same_relation: str,
    cross_conflict: bool,
    model_duplicate: bool,
    box_is_valid: bool,
    split_policy: dict[str, str],
) -> ReviewDecision:
    if not box_is_valid or not math.isfinite(confidence):
        return ReviewDecision("INVALID", False, "reject", False, "invalid numeric value or normalized box")
    if model_duplicate:
        return ReviewDecision("MODEL_DUPLICATE", False, "reject", False, "near-identical lower-confidence prediction")
    if same_relation == "already_labeled":
        return ReviewDecision(
            "GT_ALREADY_LABELED",
            False,
            "keep_gt",
            False,
            "prediction already represented by same-class GT",
        )
    if same_relation == "ambiguous_same_target":
        return ReviewDecision(
            "GT_SAME_AMBIGUOUS",
            True,
            "replace_or_reject",
            split_policy.get(split) == "review_and_apply",
            "same target likely but box extent differs",
        )
    if cross_conflict:
        return ReviewDecision(
            "GT_CROSS_CLASS_CONFLICT",
            True,
            "add_or_reject",
            split_policy.get(split) == "review_and_apply",
            "candidate nearly duplicates a different-class GT",
        )

    band = confidence_band(confidence, class_policy)
    if band == "low":
        return ReviewDecision(
            "BELOW_REVIEW_THRESHOLD",
            False,
            "reject",
            False,
            "confidence below class review threshold",
        )

    policy = split_policy.get(split, "disabled")
    if policy == "review_gold_only":
        return ReviewDecision(
            f"EVAL_MISSING_{band.upper()}",
            True,
            "accept_eval_or_reject",
            False,
            "possible missing evaluation annotation; never auto-apply to training",
        )
    if policy != "review_and_apply":
        return ReviewDecision("SPLIT_DISABLED", False, "reject", False, f"split policy is {policy}")
    return ReviewDecision(
        f"TRAIN_MISSING_{band.upper()}",
        True,
        "accept_add_or_reject",
        True,
        f"distinct missing-label candidate in {band} confidence band",
    )


def validate_policy(policy: dict[str, Any], class_names: list[str]) -> None:
    """Fail early when a policy cannot cover the target dataset."""
    for section in ("classes", "geometry", "split_policy"):
        if not isinstance(policy.get(section), dict):
            raise ValueError(f"Review policy requires a mapping named '{section}'")
    missing = [name for name in class_names if name not in policy["classes"]]
    if missing:
        raise ValueError(f"Review policy is missing classes: {missing}")
    for name in class_names:
        high = float(policy["classes"][name]["high_conf"])
        review = float(policy["classes"][name]["review_conf"])
        if not 0 <= review <= high <= 1:
            raise ValueError(f"Invalid thresholds for {name}: review={review}, high={high}")
