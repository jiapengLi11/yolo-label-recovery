"""Scan a YOLO dataset and add high-confidence missing labels safely.

The original labels are never modified. One detector is loaded at a time,
predictions are consumed as a stream, and candidate rows are written directly
to CSV files. In apply mode, a separate merged label tree is created.
"""
from __future__ import annotations

import argparse
import csv
import gc
import json
import os
import shutil
from collections.abc import Iterable, Sequence
from pathlib import Path

import cv2
import torch
import yaml
from PIL import ImageFile
from ultralytics import YOLO

from yolo_label_recovery.configuration import (
    parse_model_specs,
    parse_thresholds,
    resolve_model_spec_paths,
)
from yolo_label_recovery.dataset import load_dataset_metadata
from yolo_label_recovery.domain import (
    COLORS,
    CSV_FIELDS,
    DEFAULT_THRESHOLDS,
    IMAGE_EXTS,
    Box,
    Candidate,
    ModelSpec,
)
from yolo_label_recovery.geometry import batch_iou_xyxy, box_to_xyxy, iou, xywhn_to_xyxy
from yolo_label_recovery.runtime import finalize_run_manifest, write_run_manifest
from yolo_label_recovery.state import (
    build_run_signature,
    load_state,
    new_state,
    progress_key,
    save_state,
)

ImageFile.LOAD_TRUNCATED_IMAGES = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--models-json", type=Path, required=True)
    parser.add_argument("--splits", nargs="+", default=["train", "val", "test"])
    parser.add_argument("--classes", nargs="+", default=["helmet", "vest", "tractor", "slipper", "smoking"])
    parser.add_argument("--imgsz", type=int, default=832)
    parser.add_argument("--batch", type=int, default=32)
    parser.add_argument("--device", default="0")
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--iou-existing", type=float, default=0.50)
    parser.add_argument("--iou-candidate-duplicate", type=float, default=0.95,
                        help="Suppress only near-identical predictions after model NMS; keep this high to avoid dropping overlapping objects.")
    parser.add_argument("--nms-iou", type=float, default=0.70)
    parser.add_argument("--max-det", type=int, default=100)
    parser.add_argument("--threshold", action="append", default=[])
    parser.add_argument("--max-review-per-class", type=int, default=500)
    parser.add_argument("--draw-review", action="store_true")
    parser.add_argument("--draw-auto-samples", type=int, default=80)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume an interrupted run from out-root/state.json.",
    )
    parser.add_argument(
        "--adaptive-batch",
        action="store_true",
        help="Retry the current batch with half the size after CUDA OOM.",
    )
    parser.add_argument("--materialize-dataset", action="store_true",
                        help="Create a standard trainable dataset under out-root/trainable_dataset.")
    parser.add_argument("--image-mode", choices=["hardlink", "copy"], default="hardlink",
                        help="Image storage mode when --materialize-dataset is used.")
    half = parser.add_mutually_exclusive_group()
    half.add_argument("--half", dest="half", action="store_true")
    half.add_argument("--no-half", dest="half", action="store_false")
    half.add_argument("--fp16", dest="half", action="store_true", help=argparse.SUPPRESS)
    parser.set_defaults(half=True)
    return parser.parse_args()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_output_path(dataset_root: Path, out_root: Path, model_specs: dict[str, ModelSpec]) -> None:
    """Prevent --force from deleting source data or model weights."""
    if out_root == dataset_root or _is_relative_to(dataset_root, out_root):
        raise ValueError(
            f"Unsafe --out-root {out_root}: it is the dataset root or an ancestor of it."
        )
    for protected in (dataset_root / "images", dataset_root / "labels"):
        protected = protected.resolve()
        if out_root == protected or _is_relative_to(out_root, protected):
            raise ValueError(
                f"Unsafe --out-root {out_root}: output cannot be inside source {protected}."
            )
    for class_name, spec in model_specs.items():
        model_path = Path(spec.path).resolve()
        if model_path == out_root or _is_relative_to(model_path, out_root):
            raise ValueError(
                f"Unsafe --out-root {out_root}: model for {class_name} is inside the output tree "
                f"and would be deleted by --force: {model_path}"
            )


def validate_args(args: argparse.Namespace) -> None:
    if args.force and args.resume:
        raise ValueError("--force and --resume are mutually exclusive")
    if args.batch < 1:
        raise ValueError("--batch must be >= 1")
    if args.imgsz < 1:
        raise ValueError("--imgsz must be >= 1")
    if args.max_det < 1:
        raise ValueError("--max-det must be >= 1")
    if args.workers < 0:
        raise ValueError("--workers must be >= 0")
    if args.draw_auto_samples < 0 or args.max_review_per_class < 0:
        raise ValueError("visual sample limits must be >= 0")
    if not 0 <= args.iou_existing <= 1:
        raise ValueError("--iou-existing must be between 0 and 1")
    if not 0 <= args.iou_candidate_duplicate <= 1:
        raise ValueError("--iou-candidate-duplicate must be between 0 and 1")
    if not 0 <= args.nms_iou <= 1:
        raise ValueError("--nms-iou must be between 0 and 1")
    if len(set(args.classes)) != len(args.classes):
        raise ValueError("--classes contains duplicates; that would run a class twice and duplicate labels")
    if len(set(args.splits)) != len(args.splits):
        raise ValueError("--splits contains duplicates; that would scan images more than once")


def use_half_precision(args: argparse.Namespace, device: str) -> bool:
    # FP16 is intended for CUDA here. Avoid passing half=True to CPU/MPS by accident.
    return bool(args.half and (device.startswith("cuda:") or device == "cuda"))


def resolve_device(raw: str) -> str:
    value = str(raw).strip()
    if value.lower() == "cpu":
        return "cpu"
    if value.isdigit():
        if not torch.cuda.is_available():
            return "cpu"
        return f"cuda:{value}"
    return value


def is_oom_error(error: BaseException) -> bool:
    text = str(error).lower()
    return "out of memory" in text or ("cuda error" in text and "memory" in text)


def read_label_file(path: Path) -> list[Box]:
    boxes: list[Box] = []
    if not path.exists():
        return boxes
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = line.strip().split()
        if len(parts) < 5:
            continue
        try:
            cls = int(float(parts[0]))
            cx, cy, w, h = (float(v) for v in parts[1:5])
        except ValueError:
            continue
        if w <= 0 or h <= 0:
            continue
        boxes.append(Box(cls, cx, cy, w, h))
    return boxes


def preload_labels(dataset_root: Path, splits: Iterable[str], class_id: int) -> dict[tuple[str, str], list[Box]]:
    cache: dict[tuple[str, str], list[Box]] = {}
    for split in splits:
        label_dir = dataset_root / "labels" / split
        if not label_dir.exists():
            continue
        for label_file in label_dir.glob("*.txt"):
            boxes = [box for box in read_label_file(label_file) if box.cls == class_id]
            cache[(split, label_file.stem)] = boxes
    return cache


def find_images(images_dir: Path) -> list[Path]:
    images: list[Path] = []
    for ext in IMAGE_EXTS:
        images.extend(images_dir.glob(f"*{ext}"))
        images.extend(images_dir.glob(f"*{ext.upper()}"))
    return sorted(set(images))


def label_for_image(dataset_root: Path, image: Path, split: str) -> Path:
    return dataset_root / "labels" / split / f"{image.stem}.txt"


def copy_label_tree(dataset_root: Path, out_root: Path, splits: Iterable[str]) -> Path:
    out_labels = out_root / "labels_autofill_v1"
    for split in splits:
        src = dataset_root / "labels" / split
        dst = out_labels / split
        dst.mkdir(parents=True, exist_ok=True)
        if src.exists():
            for label in src.glob("*.txt"):
                shutil.copy2(label, dst / label.name)
    return out_labels


def append_batch_labels(out_labels: Path, candidates: list[Candidate]) -> None:
    by_label: dict[Path, list[Candidate]] = {}
    for candidate in candidates:
        path = out_labels / candidate.split / candidate.label.name
        by_label.setdefault(path, []).append(candidate)
    for path, items in by_label.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        existing_lines = set()
        if path.is_file():
            existing_lines = {
                line.strip() for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            }
        pending_lines = []
        for candidate in items:
            box = candidate.box
            line = f"{candidate.class_id} {box.cx:.6f} {box.cy:.6f} {box.w:.6f} {box.h:.6f}"
            if line in existing_lines:
                continue
            existing_lines.add(line)
            pending_lines.append(line)
        if pending_lines:
            with path.open("a", encoding="utf-8") as handle:
                handle.write("\n".join(pending_lines) + "\n")


def candidate_row(candidate: Candidate) -> dict[str, str | int]:
    box = candidate.box
    return {
        "split": candidate.split,
        "image": str(candidate.image),
        "label": str(candidate.label),
        "class_name": candidate.class_name,
        "class_id": candidate.class_id,
        "conf": f"{candidate.conf:.6f}",
        "mode": candidate.mode,
        "max_iou_same_class": f"{candidate.max_iou_same_class:.6f}",
        "cx": f"{box.cx:.6f}",
        "cy": f"{box.cy:.6f}",
        "w": f"{box.w:.6f}",
        "h": f"{box.h:.6f}",
    }


def candidate_key(candidate: Candidate) -> tuple:
    box = candidate.box
    return (
        candidate.split,
        str(candidate.image),
        candidate.class_id,
        candidate.mode,
        round(box.cx, 6),
        round(box.cy, 6),
        round(box.w, 6),
        round(box.h, 6),
    )


def candidate_from_row(row: dict[str, str]) -> Candidate:
    class_id = int(row["class_id"])
    confidence = float(row["conf"])
    box = Box(
        class_id,
        float(row["cx"]),
        float(row["cy"]),
        float(row["w"]),
        float(row["h"]),
        confidence,
    )
    return Candidate(
        split=row["split"],
        image=Path(row["image"]),
        label=Path(row["label"]),
        class_name=row["class_name"],
        class_id=class_id,
        conf=confidence,
        box=box,
        mode=row["mode"],
        max_iou_same_class=float(row["max_iou_same_class"]),
    )


class CandidateWriter:
    """Stream CSV rows and retain top-confidence *unique images* for visualization.

    The old implementation sampled individual boxes. That could select the same image
    many times and made each preview show only one box. Here each retained sample is
    an image group and all retained candidates from that image/class are kept.
    """

    def __init__(
        self,
        out_root: Path,
        classes: list[str],
        max_review: int,
        max_auto: int,
        resume: bool = False,
    ):
        self.handles = {}
        self.writers = {}
        self.seen: dict[str, set[tuple]] = {name: set() for name in ("auto", "review", "all")}
        existing_candidates: list[Candidate] = []
        for name in ("auto", "review", "all"):
            path = out_root / f"candidates_{name}.csv"
            if resume and path.is_file():
                with path.open("r", newline="", encoding="utf-8-sig") as existing_handle:
                    for row in csv.DictReader(existing_handle):
                        candidate = candidate_from_row(row)
                        self.seen[name].add(candidate_key(candidate))
                        if name == "all":
                            existing_candidates.append(candidate)
            mode = "a" if resume else "w"
            handle = path.open(mode, newline="", encoding="utf-8-sig")
            self.handles[name] = handle
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            if not resume or path.stat().st_size == 0:
                writer.writeheader()
            self.writers[name] = writer

        self.max_samples = {"auto": max_auto, "review": max_review}
        # key -> image-key -> [score, sequence, candidates]
        self.sample_groups: dict[str, dict[tuple[str, str], list]] = {
            f"{mode}:{class_name}": {}
            for mode in ("auto", "review")
            for class_name in classes
        }
        self.sequence = 0
        for candidate in existing_candidates:
            self._retain_sample(candidate)

    def _retain_sample(self, candidate: Candidate) -> None:
        self.sequence += 1
        mode = candidate.mode
        limit = self.max_samples[mode]
        if limit <= 0:
            return

        key = f"{mode}:{candidate.class_name}"
        image_key = (candidate.split, str(candidate.image))
        groups = self.sample_groups[key]

        if image_key in groups:
            groups[image_key][2].append(candidate)
            if candidate.conf > groups[image_key][0]:
                groups[image_key][0] = candidate.conf
            return

        if len(groups) < limit:
            groups[image_key] = [candidate.conf, self.sequence, [candidate]]
            return

        weakest_key, weakest = min(
            groups.items(),
            key=lambda item: (item[1][0], item[1][1]),
        )
        if (candidate.conf, self.sequence) > (weakest[0], weakest[1]):
            del groups[weakest_key]
            groups[image_key] = [candidate.conf, self.sequence, [candidate]]

    def write(self, candidate: Candidate) -> bool:
        row = candidate_row(candidate)
        mode = candidate.mode
        key = candidate_key(candidate)
        wrote = False
        for target in (mode, "all"):
            if key in self.seen[target]:
                continue
            self.writers[target].writerow(row)
            self.seen[target].add(key)
            wrote = True
        if not wrote:
            return False

        self._retain_sample(candidate)
        return True

    def get_sample_groups(self, mode: str, class_name: str) -> list[list[Candidate]]:
        groups = self.sample_groups[f"{mode}:{class_name}"].values()
        ordered = sorted(groups, key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in ordered]

    def close(self) -> None:
        for handle in self.handles.values():
            handle.close()

    def flush(self) -> None:
        for handle in self.handles.values():
            handle.flush()


def _class_name(class_id: int, class_names: Sequence[str]) -> str:
    if 0 <= class_id < len(class_names):
        return class_names[class_id]
    return f"class_{class_id}"


def _draw_box(image, box: Box, text: str, color, thickness: int = 2) -> None:
    height, width = image.shape[:2]
    x1, y1, x2, y2 = box_to_xyxy(box)
    x1 = max(0.0, min(1.0, x1))
    y1 = max(0.0, min(1.0, y1))
    x2 = max(0.0, min(1.0, x2))
    y2 = max(0.0, min(1.0, y2))
    if x2 <= x1 or y2 <= y1:
        return
    p1 = (int(x1 * width), int(y1 * height))
    p2 = (min(width - 1, int(x2 * width)), min(height - 1, int(y2 * height)))
    cv2.rectangle(image, p1, p2, color, thickness)
    cv2.putText(
        image, text, (p1[0], max(20, p1[1] - 8)),
        cv2.FONT_HERSHEY_SIMPLEX, 0.62, color, max(1, thickness),
    )


def sample_output_name(candidate: Candidate) -> str:
    suffix = candidate.image.suffix.lower().lstrip(".") or "img"
    # Include split + original extension so same-stem .jpg/.png files do not overwrite.
    return f"{candidate.split}_{candidate.image.stem}_{suffix}.jpg"


def draw_sample_group(
    candidates: list[Candidate],
    out_path: Path,
    class_names: Sequence[str],
    out_labels: Path | None,
) -> bool:
    """Draw a complete image preview, not one candidate box per file.

    Original labels are always shown. In apply mode, all auto-added labels from the
    merged label tree are shown too. The sampled candidates are then highlighted so
    multiple objects on the same image remain visible in one preview.
    """
    if not candidates:
        return False
    anchor = candidates[0]
    image = cv2.imread(str(anchor.image))
    if image is None:
        return False

    original_boxes = read_label_file(anchor.label)
    merged_boxes = original_boxes
    if out_labels is not None:
        merged_path = out_labels / anchor.split / anchor.label.name
        if merged_path.exists():
            merged_boxes = read_label_file(merged_path)

    # Draw the complete current label state first. If apply mode is active, this is
    # original + every auto-added class for the image.
    original_count = len(original_boxes)
    for idx, box in enumerate(merged_boxes):
        name = _class_name(box.cls, class_names)
        color = COLORS.get(name, (0, 255, 255))
        prefix = "GT" if idx < original_count else "AUTO"
        _draw_box(image, box, f"{prefix} {name}", color, 2 if prefix == "GT" else 3)

    # In dry-run there is no merged label tree, so auto candidates would otherwise
    # be absent. For review mode, candidates are intentionally not in merged labels.
    # Highlighting also makes it obvious which predictions caused this sample.
    for candidate in candidates:
        name = candidate.class_name
        color = COLORS.get(name, (0, 255, 255))
        _draw_box(
            image, candidate.box,
            f"{candidate.mode.upper()} {name} {candidate.conf:.2f}",
            color, 3,
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    return cv2.imwrite(str(out_path), image)


def write_metadata_yaml(dataset_root: Path, out_root: Path, out_labels: Path) -> None:
    data = yaml.safe_load((dataset_root / "data.yaml").read_text(encoding="utf-8"))
    data["path"] = str(dataset_root)
    data["autofill_labels"] = str(out_labels)
    data["note"] = "This metadata file does not override Ultralytics label resolution. Use trainable_dataset/data.yaml."
    (out_root / "data_autofill_labels.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def link_or_copy(src: Path, dst: Path, mode: str) -> bool:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if mode == "hardlink":
        try:
            os.link(src, dst)
            return True
        except OSError:
            shutil.copy2(src, dst)
            return False
    shutil.copy2(src, dst)
    return False


def materialize_dataset(
    dataset_root: Path,
    out_root: Path,
    out_labels: Path,
    splits: Iterable[str],
    image_mode: str,
    dataset_meta: dict,
    class_names: Sequence[str],
) -> Path:
    dataset_out = out_root / "trainable_dataset"
    fallback_count = 0
    materialized_splits: list[str] = []

    for split in splits:
        source_images = dataset_root / "images" / split
        if not source_images.is_dir():
            continue
        materialized_splits.append(split)
        target_images = dataset_out / "images" / split
        target_labels = dataset_out / "labels" / split
        target_images.mkdir(parents=True, exist_ok=True)
        target_labels.mkdir(parents=True, exist_ok=True)

        for image in find_images(source_images):
            used_hardlink = link_or_copy(image, target_images / image.name, image_mode)
            if image_mode == "hardlink" and not used_hardlink:
                fallback_count += 1

        source_labels = out_labels / split
        if source_labels.exists():
            for label in source_labels.glob("*.txt"):
                shutil.copy2(label, target_labels / label.name)

    data = {
        "path": str(dataset_out),
        "nc": len(class_names),
        "names": list(class_names),
        "sources": ["original_dataset", "single-class-autolabel-v3"],
        "image_mode": image_mode,
        "hardlink_fallback_copies": fallback_count,
    }
    for split in materialized_splits:
        data[split] = f"images/{split}"

    # Preserve useful optional metadata without overriding the newly materialized paths.
    for key in ("download", "license"):
        if key in dataset_meta:
            data[key] = dataset_meta[key]

    (dataset_out / "data.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return dataset_out


def main() -> None:
    args = parse_args()
    validate_args(args)

    dataset_root = args.dataset_root.expanduser().resolve()
    out_root = args.out_root.expanduser().resolve()
    models_json = args.models_json.expanduser().resolve()
    if not dataset_root.is_dir():
        raise FileNotFoundError(dataset_root)
    if not models_json.is_file():
        raise FileNotFoundError(models_json)

    dataset_meta, dataset_class_names = load_dataset_metadata(dataset_root)
    dataset_class_ids = {name: idx for idx, name in enumerate(dataset_class_names)}
    thresholds = parse_thresholds(args.threshold)
    model_specs = parse_model_specs(json.loads(models_json.read_text(encoding="utf-8")))
    model_specs = resolve_model_spec_paths(model_specs, models_json)
    device = resolve_device(args.device)

    for class_name in args.classes:
        if class_name not in DEFAULT_THRESHOLDS:
            raise ValueError(
                f"Unknown class for this script: {class_name}. Supported: {sorted(DEFAULT_THRESHOLDS)}"
            )
        if class_name not in dataset_class_ids:
            raise ValueError(
                f"Class {class_name!r} is not present in data.yaml names={dataset_class_names}"
            )
        if class_name not in model_specs:
            raise KeyError(f"Missing model path for class: {class_name}")
        if not Path(model_specs[class_name].path).is_file():
            raise FileNotFoundError(model_specs[class_name].path)
        if model_specs[class_name].pred_class < 0:
            raise ValueError(f"pred_class for {class_name} must be >= 0")

    validate_output_path(dataset_root, out_root, model_specs)

    existing_split_dirs = [
        split for split in args.splits
        if (dataset_root / "images" / split).is_dir()
    ]
    if not existing_split_dirs:
        raise FileNotFoundError(
            f"None of the requested image splits exist under {dataset_root / 'images'}: {args.splits}"
        )
    missing_splits = [split for split in args.splits if split not in existing_split_dirs]
    if missing_splits:
        print(f"[warn] requested splits not found and will be skipped: {missing_splits}")

    # Scan filenames once and reuse them for every single-class model.
    images_by_split = {
        split: find_images(dataset_root / "images" / split)
        for split in args.splits
    }
    if sum(len(items) for items in images_by_split.values()) == 0:
        raise FileNotFoundError(
            f"No supported images found in requested splits. Extensions: {IMAGE_EXTS}"
        )

    signature_payload = {
        "dataset_root": str(dataset_root),
        "dataset_yaml": (dataset_root / "data.yaml").read_text(encoding="utf-8"),
        "models": {
            name: {
                "path": model_specs[name].path,
                "pred_class": model_specs[name].pred_class,
                "size": Path(model_specs[name].path).stat().st_size,
                "mtime_ns": Path(model_specs[name].path).stat().st_mtime_ns,
            }
            for name in args.classes
        },
        "classes": args.classes,
        "splits": args.splits,
        "thresholds": {name: thresholds[name] for name in args.classes},
        "imgsz": args.imgsz,
        "iou_existing": args.iou_existing,
        "iou_candidate_duplicate": args.iou_candidate_duplicate,
        "nms_iou": args.nms_iou,
        "max_det": args.max_det,
        "dry_run": args.dry_run,
    }
    run_signature = build_run_signature(signature_payload)
    state_path = out_root / "state.json"

    if args.resume:
        if not out_root.is_dir():
            raise FileNotFoundError(f"Resume output directory does not exist: {out_root}")
        state = load_state(state_path, run_signature)
    else:
        if out_root.exists():
            if not args.force:
                raise FileExistsError(f"{out_root} exists. Use --force to overwrite or --resume to continue.")
            shutil.rmtree(out_root)
        out_root.mkdir(parents=True, exist_ok=True)
        state = None

    fresh_stats: dict[str, dict[str, int]] = {
        name: {
            "images_scanned": sum(len(images_by_split[split]) for split in args.splits),
            "predictions_after_review_conf": 0,
            "matched_existing": 0,
            "duplicate_candidates": 0,
            "auto_added": 0,
            "review_candidates": 0,
            "skip_error": 0,
            "initial_batch": args.batch,
            "stable_batch": args.batch,
            "oom_retries": 0,
        }
        for name in args.classes
    }
    if state is None:
        stats = fresh_stats
        state = new_state(run_signature, stats)
        save_state(state_path, state)
    else:
        stats = state.get("stats", fresh_stats)
        for name in args.classes:
            if name not in stats:
                stats[name] = fresh_stats[name]
            for key, value in fresh_stats[name].items():
                stats[name].setdefault(key, value)

    manifest_path = out_root / "manifest.json"
    write_run_manifest(
        manifest_path,
        signature=run_signature,
        arguments=vars(args),
        inventory={
            "dataset_class_names": dataset_class_names,
            "images_by_split": {split: len(images) for split, images in images_by_split.items()},
            "models": {
                name: {
                    "path": model_specs[name].path,
                    "pred_class": model_specs[name].pred_class,
                    "size_bytes": Path(model_specs[name].path).stat().st_size,
                }
                for name in args.classes
            },
        },
        resume=args.resume,
    )

    out_labels = None
    if not args.dry_run:
        if args.resume:
            out_labels = out_root / "labels_autofill_v1"
            if not out_labels.is_dir():
                raise FileNotFoundError(f"Resume label output is missing: {out_labels}")
        else:
            out_labels = copy_label_tree(dataset_root, out_root, args.splits)

    writer = CandidateWriter(
        out_root,
        args.classes,
        args.max_review_per_class if args.draw_review else 0,
        args.draw_auto_samples,
        resume=args.resume,
    )

    try:
        for class_name in args.classes:
            class_id = dataset_class_ids[class_name]
            auto_thr, review_thr = thresholds[class_name]
            label_cache = preload_labels(dataset_root, args.splits, class_id)
            model = None
            print(f"[start] {class_name}: model={model_specs[class_name].path}")
            try:
                model = YOLO(model_specs[class_name].path)
                model_names = getattr(model, "names", None)
                pred_class = model_specs[class_name].pred_class
                if isinstance(model_names, dict) and pred_class not in model_names:
                    raise ValueError(
                        f"pred_class={pred_class} for {class_name} is not in model.names={model_names}"
                    )
                if isinstance(model_names, (list, tuple)) and pred_class >= len(model_names):
                    raise ValueError(
                        f"pred_class={pred_class} for {class_name} exceeds model class count {len(model_names)}"
                    )
                current_batch = int(stats[class_name].get("stable_batch", args.batch))
                for split in args.splits:
                    images = images_by_split[split]
                    if not images:
                        continue
                    unit = progress_key(class_name, split)
                    chunk_start = int(state["progress"].get(unit, 0))
                    if chunk_start > len(images):
                        raise ValueError(
                            f"Resume cursor {chunk_start} exceeds image count {len(images)} for {unit}"
                        )
                    if chunk_start:
                        print(f"[resume] {unit}: {chunk_start}/{len(images)} images already committed")
                    while chunk_start < len(images):
                        chunk_imgs = images[chunk_start:chunk_start + current_batch]
                        img_paths = [str(path) for path in chunk_imgs]
                        batch_auto: list[Candidate] = []
                        batch_candidates: list[Candidate] = []
                        results = None
                        stats_before_batch = dict(stats[class_name])
                        try:
                            results = model.predict(
                                source=img_paths,
                                imgsz=args.imgsz,
                                batch=len(chunk_imgs),
                                device=device,
                                workers=args.workers,
                                conf=review_thr,
                                iou=args.nms_iou,
                                max_det=args.max_det,
                                verbose=False,
                                half=use_half_precision(args, device),
                                stream=True,
                            )
                            for image_path, result in zip(chunk_imgs, results, strict=False):
                                try:
                                    if result.boxes is None or len(result.boxes) == 0:
                                        continue
                                    existing = label_cache.get((split, image_path.stem), [])
                                    xywhn = result.boxes.xywhn
                                    confs = result.boxes.conf
                                    pred_classes = result.boxes.cls
                                    mask = pred_classes == model_specs[class_name].pred_class
                                    if not bool(mask.any()):
                                        continue
                                    xywhn = xywhn[mask]
                                    confs = confs[mask]
                                    stats[class_name]["predictions_after_review_conf"] += len(confs)

                                    pred_xyxy = xywhn_to_xyxy(xywhn)
                                    if existing:
                                        existing_xyxy = torch.tensor(
                                            [box_to_xyxy(box) for box in existing],
                                            device=pred_xyxy.device,
                                            dtype=pred_xyxy.dtype,
                                        )
                                        max_ious = batch_iou_xyxy(pred_xyxy, existing_xyxy)
                                    else:
                                        max_ious = torch.zeros(len(pred_xyxy), device=pred_xyxy.device, dtype=pred_xyxy.dtype)

                                    order = torch.argsort(confs, descending=True)
                                    for index in order.tolist():
                                        max_iou = float(max_ious[index].item())
                                        if max_iou >= args.iou_existing:
                                            stats[class_name]["matched_existing"] += 1
                                            continue
                                        conf = float(confs[index].item())
                                        values = [float(value) for value in xywhn[index].tolist()]
                                        candidate_box = Box(class_id, values[0], values[1], values[2], values[3], conf)
                                        mode = "auto" if conf >= auto_thr else "review"
                                        duplicate = any(
                                            iou(candidate_box, accepted.box) >= args.iou_candidate_duplicate
                                            for accepted in batch_candidates
                                            if accepted.image == image_path and accepted.class_name == class_name
                                        )
                                        if duplicate:
                                            stats[class_name]["duplicate_candidates"] += 1
                                            continue
                                        candidate = Candidate(
                                            split=split,
                                            image=image_path,
                                            label=label_for_image(dataset_root, image_path, split),
                                            class_name=class_name,
                                            class_id=class_id,
                                            conf=conf,
                                            box=candidate_box,
                                            mode=mode,
                                            max_iou_same_class=max_iou,
                                        )
                                        batch_candidates.append(candidate)
                                        if mode == "auto":
                                            batch_auto.append(candidate)
                                            stats[class_name]["auto_added"] += 1
                                        else:
                                            stats[class_name]["review_candidates"] += 1
                                except Exception as error:
                                    if is_oom_error(error):
                                        raise
                                    stats[class_name]["skip_error"] += 1
                                    print(f"[warn] skipped {image_path.name}: {error}")
                                finally:
                                    del result
                            for candidate in batch_candidates:
                                writer.write(candidate)
                            if out_labels is not None and batch_auto:
                                append_batch_labels(out_labels, batch_auto)
                            writer.flush()
                            chunk_start += len(chunk_imgs)
                            state["progress"][unit] = chunk_start
                            state["stats"] = stats
                            save_state(state_path, state)
                        except Exception as error:
                            if is_oom_error(error):
                                if torch.cuda.is_available():
                                    torch.cuda.empty_cache()
                                stats[class_name].clear()
                                stats[class_name].update(stats_before_batch)
                                if args.adaptive_batch and len(chunk_imgs) > 1:
                                    current_batch = max(1, len(chunk_imgs) // 2)
                                    stats[class_name]["stable_batch"] = current_batch
                                    stats[class_name]["oom_retries"] += 1
                                    state["stats"] = stats
                                    save_state(state_path, state)
                                    print(
                                        f"[oom] class={class_name} split={split} "
                                        f"batch={len(chunk_imgs)}; retrying with batch={current_batch}"
                                    )
                                    continue
                                raise RuntimeError(
                                    f"CUDA out of memory in class={class_name}, split={split}, "
                                    f"batch={len(chunk_imgs)}. Retry with --batch {max(1, len(chunk_imgs) // 2)}."
                                ) from error
                            raise
                        finally:
                            if results is not None:
                                del results
                            gc.collect()
                            if torch.cuda.is_available():
                                torch.cuda.empty_cache()
            finally:
                if model is not None:
                    del model
                del label_cache
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            print(f"[done] {class_name}: auto={stats[class_name]['auto_added']} review={stats[class_name]['review_candidates']}")
    finally:
        writer.close()

    review_written = {name: 0 for name in args.classes}
    auto_written = {name: 0 for name in args.classes}
    for class_name in args.classes:
        if args.draw_review:
            for group in writer.get_sample_groups("review", class_name):
                anchor = group[0]
                output = out_root / "review_images" / class_name / sample_output_name(anchor)
                if draw_sample_group(group, output, dataset_class_names, out_labels):
                    review_written[class_name] += 1
        for group in writer.get_sample_groups("auto", class_name):
            anchor = group[0]
            output = out_root / "auto_samples" / class_name / sample_output_name(anchor)
            if draw_sample_group(group, output, dataset_class_names, out_labels):
                auto_written[class_name] += 1

    trainable_dataset = None
    if out_labels is not None:
        write_metadata_yaml(dataset_root, out_root, out_labels)
        if args.materialize_dataset:
            trainable_dataset = materialize_dataset(
                dataset_root, out_root, out_labels, args.splits, args.image_mode,
                dataset_meta, dataset_class_names,
            )

    summary = {
        "dataset_root": str(dataset_root),
        "out_root": str(out_root),
        "labels_output": str(out_labels) if out_labels else None,
        "trainable_dataset": str(trainable_dataset) if trainable_dataset else None,
        "dry_run": args.dry_run,
        "device": device,
        "imgsz": args.imgsz,
        "batch": args.batch,
        "workers": args.workers,
        "half": use_half_precision(args, device),
        "splits": args.splits,
        "classes": args.classes,
        "dataset_class_names": dataset_class_names,
        "dataset_class_ids": {name: dataset_class_ids[name] for name in args.classes},
        "thresholds": {name: {"auto": thresholds[name][0], "review": thresholds[name][1]} for name in args.classes},
        "iou_existing": args.iou_existing,
        "iou_candidate_duplicate": args.iou_candidate_duplicate,
        "stats": stats,
        "total_auto_added": sum(item["auto_added"] for item in stats.values()),
        "total_review_candidates": sum(item["review_candidates"] for item in stats.values()),
        "review_images_written": review_written,
        "auto_sample_images_written": auto_written,
        "run_signature": run_signature,
        "manifest": str(manifest_path),
    }
    (out_root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_lines = [
        "Single-class auto-label scan summary (v3 fixed)",
        f"dataset_root: {dataset_root}",
        f"out_root: {out_root}",
        f"dry_run: {args.dry_run}",
        f"device: {device}",
        f"batch: {args.batch}",
        f"workers: {args.workers}",
        f"half: {use_half_precision(args, device)}",
        f"total_auto_added: {summary['total_auto_added']}",
        f"total_review_candidates: {summary['total_review_candidates']}",
        "",
    ]
    for name, item in stats.items():
        summary_lines.append(
            f"{name}: scanned={item['images_scanned']} preds={item['predictions_after_review_conf']} "
            f"matched={item['matched_existing']} duplicate={item['duplicate_candidates']} "
            f"auto={item['auto_added']} review={item['review_candidates']} skip_error={item['skip_error']} "
            f"batch={item['initial_batch']}->{item['stable_batch']} oom_retries={item['oom_retries']}"
        )
    (out_root / "summary.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    state["status"] = "complete"
    state["stats"] = stats
    save_state(state_path, state)
    finalize_run_manifest(manifest_path, summary)
    print((out_root / "summary.txt").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
