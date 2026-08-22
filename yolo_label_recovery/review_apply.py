"""Create a derived YOLO dataset from fully reviewed add/replace decisions."""

from __future__ import annotations

import argparse
import csv
import os
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from .dataset import load_dataset_metadata
from .domain import Box
from .review_decision import best_match, same_class_relation, valid_box, validate_policy


def _write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _parse_line(raw: str) -> Box | None:
    parts = raw.split()
    if len(parts) != 5:
        return None
    try:
        return Box(int(float(parts[0])), *map(float, parts[1:5]))
    except ValueError:
        return None


def _candidate_box(row: dict[str, str]) -> Box:
    return Box(
        int(float(row["class_id"])),
        float(row["cx"]),
        float(row["cy"]),
        float(row["w"]),
        float(row["h"]),
        float(row["conf"]),
    )


def _materialize(source: Path, output: Path, splits: list[str], image_mode: str) -> tuple[int, int, int]:
    hardlinks = copies = labels = 0
    for split in splits:
        source_images = source / "images" / split
        target_images = output / "images" / split
        source_labels = source / "labels" / split
        target_labels = output / "labels" / split
        target_images.mkdir(parents=True, exist_ok=True)
        target_labels.mkdir(parents=True, exist_ok=True)
        if source_images.is_dir():
            for image in (path for path in source_images.rglob("*") if path.is_file()):
                target = target_images / image.relative_to(source_images)
                target.parent.mkdir(parents=True, exist_ok=True)
                if image_mode == "hardlink":
                    try:
                        os.link(image, target)
                        hardlinks += 1
                        continue
                    except OSError:
                        pass
                shutil.copy2(image, target)
                copies += 1
        if source_labels.is_dir():
            for label in source_labels.rglob("*.txt"):
                target = target_labels / label.relative_to(source_labels)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(label, target)
                labels += 1
    return hardlinks, copies, labels


def apply_review_decisions(
    dataset_root: Path,
    decisions_csv: Path,
    policy_path: Path,
    output_root: Path,
    *,
    image_mode: str = "hardlink",
    apply_reviewed_eval: bool = False,
    force: bool = False,
) -> dict[str, Path]:
    source = dataset_root.expanduser().resolve()
    decisions_csv = decisions_csv.expanduser().resolve()
    policy_path = policy_path.expanduser().resolve()
    output = output_root.expanduser().resolve()
    if source == output or source in output.parents or output in source.parents:
        raise ValueError("Output must be separate from the source dataset and its parent directories")
    if image_mode not in {"hardlink", "copy"}:
        raise ValueError(f"Unknown image mode: {image_mode}")
    if output.exists():
        if not force:
            raise FileExistsError(f"Output exists: {output}; use --force")
        if len(output.parts) < 3:
            raise ValueError(f"Unsafe output path: {output}")
        shutil.rmtree(output)

    data, names = load_dataset_metadata(source)
    class_ids = {name: index for index, name in enumerate(names)}
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8-sig"))
    validate_policy(policy, names)
    geometry = policy["geometry"]
    with decisions_csv.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("Decision CSV is empty")
    unresolved = [row for row in rows if row.get("reviewer_decision", "") in {"", "uncertain"}]
    if unresolved:
        raise ValueError(f"Review is incomplete: {len(unresolved)} blank/uncertain decisions remain")

    output.mkdir(parents=True)
    splits = [split for split in ("train", "val", "test") if (source / "images" / split).is_dir()]
    hardlinks, copies, copied_labels = _materialize(source, output, splits, image_mode)
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    rejected: list[dict[str, str]] = []
    held_eval: list[dict[str, str]] = []
    for row in rows:
        decision = row.get("reviewer_decision", "")
        if decision == "reject":
            continue
        if decision == "accept_eval_label" and not apply_reviewed_eval:
            held_eval.append(dict(row, apply_status="held", apply_reason="reviewed_eval_not_enabled"))
            continue
        if decision not in {"accept_add", "accept_replace_gt", "accept_eval_label"}:
            rejected.append(dict(row, apply_status="rejected", apply_reason="unknown_decision"))
            continue
        grouped[(row["split"], row["label_name"])].append(row)

    applied: list[dict[str, str]] = []
    counts: Counter = Counter()
    for (split, label_name), candidates in grouped.items():
        if split != "train" and not apply_reviewed_eval:
            continue
        label_path = output / "labels" / split / label_name
        lines = label_path.read_text(encoding="utf-8-sig", errors="replace").splitlines() if label_path.exists() else []
        changed = False
        for row in sorted(candidates, key=lambda item: float(item["conf"]), reverse=True):
            record = dict(row)
            class_name = row["class_name"]
            expected_id = class_ids.get(class_name, -1)
            try:
                box = _candidate_box(row)
            except (KeyError, ValueError):
                rejected.append(dict(record, apply_status="rejected", apply_reason="invalid_candidate_box"))
                continue
            if box.cls != expected_id or not valid_box(box):
                rejected.append(dict(record, apply_status="rejected", apply_reason="class_or_box_validation_failed"))
                continue

            if row["reviewer_decision"] == "accept_replace_gt":
                if row.get("case_code") != "GT_SAME_AMBIGUOUS":
                    rejected.append(dict(record, apply_status="rejected", apply_reason="replace_not_allowed_for_case"))
                    continue
                try:
                    line_index = int(row["matched_gt_line_index"])
                    expected = Box(
                        int(row["matched_gt_class_id"]),
                        float(row["matched_gt_cx"]),
                        float(row["matched_gt_cy"]),
                        float(row["matched_gt_w"]),
                        float(row["matched_gt_h"]),
                    )
                except (KeyError, ValueError):
                    rejected.append(dict(record, apply_status="rejected", apply_reason="missing_replace_gt_reference"))
                    continue
                current = _parse_line(lines[line_index]) if 0 <= line_index < len(lines) else None
                if current is None or current.cls != expected.cls or max(
                    abs(a - b)
                    for a, b in zip(
                        (current.cx, current.cy, current.w, current.h),
                        (expected.cx, expected.cy, expected.w, expected.h),
                        strict=True,
                    )
                ) > 1e-5:
                    rejected.append(dict(record, apply_status="rejected", apply_reason="source_gt_changed_since_review"))
                    continue
                lines[line_index] = f"{box.cls} {box.cx:.6f} {box.cy:.6f} {box.w:.6f} {box.h:.6f}"
                applied.append(dict(record, apply_status="replaced", apply_reason="explicit_human_replace"))
                counts[f"replaced_{class_name}"] += 1
                changed = True
                continue

            parsed = [parsed for raw in lines if (parsed := _parse_line(raw)) is not None]
            _, metrics = best_match(box, [parsed_box for parsed_box in parsed if parsed_box.cls == box.cls])
            relation = same_class_relation(metrics, geometry)
            if relation != "distinct_or_missing":
                rejected.append(dict(record, apply_status="rejected", apply_reason=f"duplicate_recheck_{relation}"))
                continue
            lines.append(f"{box.cls} {box.cx:.6f} {box.cy:.6f} {box.w:.6f} {box.h:.6f}")
            applied.append(dict(record, apply_status="applied", apply_reason="explicit_human_accept_add"))
            counts[f"added_{class_name}"] += 1
            changed = True
        if changed:
            label_path.parent.mkdir(parents=True, exist_ok=True)
            label_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    data_out = dict(data)
    data_out["path"] = output.as_posix()
    for split in splits:
        data_out[split] = f"images/{split}"
    data_out["review_policy_version"] = policy.get("version")
    data_out["source_dataset"] = source.as_posix()
    (output / "data.yaml").write_text(yaml.safe_dump(data_out, allow_unicode=True, sort_keys=False), encoding="utf-8")

    fields = [*rows[0], "apply_status", "apply_reason"]
    _write_csv(output / "applied_or_replaced.csv", applied, fields)
    _write_csv(output / "rejected_during_apply.csv", rejected, fields)
    _write_csv(output / "held_reviewed_eval.csv", held_eval, fields)
    summary = [
        "Human-reviewed dataset apply summary",
        f"source_dataset: {source}",
        f"output_dataset: {output}",
        "source_dataset_modified: False",
        f"apply_reviewed_eval: {apply_reviewed_eval}",
        f"decision_rows: {len(rows)}",
        f"applied_or_replaced: {len(applied)}",
        f"rejected_during_apply: {len(rejected)}",
        f"held_reviewed_eval: {len(held_eval)}",
        f"hardlinked_images: {hardlinks}",
        f"copied_images: {copies}",
        f"copied_labels: {copied_labels}",
    ]
    for name in names:
        summary.append(f"added_{name}: {counts[f'added_{name}']}")
        summary.append(f"replaced_{name}: {counts[f'replaced_{name}']}")
    (output / "apply_summary.txt").write_text("\n".join(summary) + "\n", encoding="utf-8")
    return {
        "dataset": output,
        "summary": output / "apply_summary.txt",
        "applied": output / "applied_or_replaced.csv",
        "rejected": output / "rejected_during_apply.csv",
        "held_eval": output / "held_reviewed_eval.csv",
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("decisions_csv", type=Path)
    parser.add_argument("--policy", type=Path, default=Path(__file__).with_name("review_policy.yaml"))
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--image-mode", choices=("hardlink", "copy"), default="hardlink")
    parser.add_argument("--apply-reviewed-eval", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    paths = apply_review_decisions(
        args.dataset_root,
        args.decisions_csv,
        args.policy,
        args.output_root,
        image_mode=args.image_mode,
        apply_reviewed_eval=args.apply_reviewed_eval,
        force=args.force,
    )
    print(paths["summary"].read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
