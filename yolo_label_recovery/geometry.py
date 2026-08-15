"""Bounding-box conversion and IoU operations."""

from __future__ import annotations

import torch

from .domain import Box


def box_to_xyxy(box: Box) -> tuple[float, float, float, float]:
    return box.cx - box.w / 2, box.cy - box.h / 2, box.cx + box.w / 2, box.cy + box.h / 2


def iou(a: Box, b: Box) -> float:
    ax1, ay1, ax2, ay2 = box_to_xyxy(a)
    bx1, by1, bx2, by2 = box_to_xyxy(b)
    inter_w = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    inter_h = max(0.0, min(ay2, by2) - max(ay1, by1))
    intersection = inter_w * inter_h
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - intersection
    return intersection / union if union > 0 else 0.0


def batch_iou_xyxy(pred_xyxy: torch.Tensor, existing_xyxy: torch.Tensor) -> torch.Tensor:
    """Return maximum same-class GT IoU for each prediction."""
    if existing_xyxy.shape[0] == 0:
        return torch.zeros(pred_xyxy.shape[0], device=pred_xyxy.device, dtype=pred_xyxy.dtype)
    pred = pred_xyxy[:, None, :]
    existing = existing_xyxy[None, :, :]
    intersection_min = torch.maximum(pred[..., :2], existing[..., :2])
    intersection_max = torch.minimum(pred[..., 2:], existing[..., 2:])
    intersection_wh = (intersection_max - intersection_min).clamp(min=0)
    intersection = intersection_wh[..., 0] * intersection_wh[..., 1]
    pred_area = (pred[..., 2] - pred[..., 0]).clamp(min=0) * (pred[..., 3] - pred[..., 1]).clamp(min=0)
    existing_area = (existing[..., 2] - existing[..., 0]).clamp(min=0) * (
        existing[..., 3] - existing[..., 1]
    ).clamp(min=0)
    union = pred_area + existing_area - intersection
    pairwise = torch.where(union > 0, intersection / union, torch.zeros_like(union))
    return pairwise.max(dim=1).values


def xywhn_to_xyxy(xywhn: torch.Tensor) -> torch.Tensor:
    center = xywhn[:, :2]
    half = xywhn[:, 2:] / 2
    return torch.cat((center - half, center + half), dim=1)
