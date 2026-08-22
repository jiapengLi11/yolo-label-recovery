"""Build an exhaustive, auditable GT/AUTO package for offline human review."""

from __future__ import annotations

import argparse
import csv
import html
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .dataset import load_dataset_metadata
from .domain import COLORS, IMAGE_EXTS, Box
from .review_decision import (
    best_match,
    classify_candidate,
    image_class_state,
    is_cross_class_conflict,
    overlap_metrics,
    same_class_relation,
    valid_box,
    validate_policy,
)


def _write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _read_gt(path: Path) -> list[tuple[int, Box]]:
    rows: list[tuple[int, Box]] = []
    if not path.is_file():
        return rows
    for line_index, raw in enumerate(path.read_text(encoding="utf-8-sig", errors="replace").splitlines()):
        parts = raw.split()
        if len(parts) != 5:
            continue
        try:
            box = Box(int(float(parts[0])), *map(float, parts[1:5]))
        except ValueError:
            continue
        if valid_box(box):
            rows.append((line_index, box))
    return rows


def _candidate_box(row: dict[str, str]) -> Box:
    return Box(
        int(float(row["class_id"])),
        float(row["cx"]),
        float(row["cy"]),
        float(row["w"]),
        float(row["h"]),
        float(row["conf"]),
    )


def _format_metric(value: float) -> str:
    return "inf" if value == float("inf") else f"{value:.6f}"


def _detect_model_duplicates(rows: list[dict[str, str]], threshold: float) -> dict[int, int]:
    groups: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    parsed: dict[int, Box] = {}
    for index, row in enumerate(rows):
        try:
            box = _candidate_box(row)
        except (KeyError, ValueError):
            continue
        if not valid_box(box):
            continue
        parsed[index] = box
        groups[(row.get("split", ""), Path(row.get("image", "")).name, row.get("class_name", ""))].append(index)

    duplicate_of: dict[int, int] = {}
    for indexes in groups.values():
        indexes.sort(key=lambda item: float(rows[item].get("conf", 0)), reverse=True)
        winners: list[int] = []
        for index in indexes:
            duplicate = next(
                (
                    winner
                    for winner in winners
                    if overlap_metrics(parsed[index], parsed[winner])["iou"] >= threshold
                ),
                None,
            )
            if duplicate is None:
                winners.append(index)
            else:
                duplicate_of[index] = duplicate
    return duplicate_of


def _to_pixels(box: Box, width: int, height: int) -> tuple[int, int, int, int]:
    return (
        round((box.cx - box.w / 2) * width),
        round((box.cy - box.h / 2) * height),
        round((box.cx + box.w / 2) * width),
        round((box.cy + box.h / 2) * height),
    )


def _render_candidate(
    source: Path,
    gt_rows: list[tuple[int, Box]],
    candidate: Box,
    row: dict[str, str],
    output: Path,
    names: list[str],
    max_side: int,
) -> None:
    image = ImageOps.exif_transpose(Image.open(source)).convert("RGB")
    if max(image.size) > max_side:
        scale = max_side / max(image.size)
        image = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    width, height = image.size
    line_width = max(2, round(max(width, height) / 450))
    matched_line = row.get("matched_gt_line_index", "")

    for line_index, gt in gt_rows:
        class_name = names[gt.cls] if 0 <= gt.cls < len(names) else f"class_{gt.cls}"
        rgb = COLORS.get(class_name, (35, 200, 235))
        color = (255, 205, 0) if str(line_index) == matched_line else rgb
        coordinates = _to_pixels(gt, width, height)
        draw.rectangle(coordinates, outline=color, width=line_width * (2 if str(line_index) == matched_line else 1))
        draw.text((coordinates[0] + 2, max(1, coordinates[1] - 12)), f"GT#{line_index} {class_name}", fill=color, font=font)

    coordinates = _to_pixels(candidate, width, height)
    draw.rectangle(coordinates, outline=(245, 45, 35), width=line_width * 2)
    title = (
        f"{row['candidate_id']} {row['case_code']} {row['class_name']} "
        f"conf={float(row['conf']):.3f} iou={float(row['same_iou']):.2f} ios={float(row['same_ios']):.2f}"
    )
    text_box = draw.textbbox((0, 0), title, font=font)
    draw.rectangle((2, 2, min(width - 2, text_box[2] + 10), 22), fill=(255, 255, 255))
    draw.text((6, 6), title, fill=(190, 20, 20), font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, quality=88, optimize=True)


def _summary_html(summary: dict, output: Path) -> None:
    class_rows = "".join(
        f"<tr><td>{html.escape(name)}</td><td>{count}</td></tr>"
        for name, count in summary["review_by_class"].items()
    )
    case_rows = "".join(
        f"<tr><td>{html.escape(name)}</td><td>{count}</td></tr>"
        for name, count in summary["decision_cases"].items()
    )
    image_rows = "".join(
        f"<tr><td>{html.escape(name)}</td><td>{count}</td></tr>"
        for name, count in summary["image_class_cases"].items()
    )
    document = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>GT/AUTO Review Summary</title>
<style>:root{{--navy:#102d3b;--cyan:#14b8a6;--paper:#f2f5f3;--ink:#16313c;--line:#d9e3df}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 "Segoe UI",sans-serif}}
header{{padding:46px max(5vw,28px);background:linear-gradient(125deg,var(--navy),#176b72);color:white}}
main{{max-width:1120px;margin:-24px auto 60px;padding:0 24px}}.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}}
.card,section{{background:white;border-radius:14px;box-shadow:0 9px 26px #16313c12}}.card{{padding:20px}}.card span{{display:block;color:#668087}}
.card strong{{font-size:28px}}section{{margin-top:18px;padding:22px}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}}
table{{width:100%;border-collapse:collapse}}td,th{{padding:8px;border-bottom:1px solid var(--line);text-align:left}}
@media(max-width:800px){{.cards,.grid{{grid-template-columns:1fr}}}}</style></head><body>
<header><h1>GT/AUTO human-review gate</h1><p>Every Teacher candidate receives one terminal state before a human decision can create a derived label dataset.</p></header>
<main><div class="cards"><div class="card"><span>Candidate evidence</span><strong>{summary['prediction_rows']}</strong></div>
<div class="card"><span>Human review queue</span><strong>{summary['review_rows']}</strong></div>
<div class="card"><span>Render failures</span><strong>{summary['render_failures']}</strong></div></div>
<section><div class="grid"><div><h2>Review by class</h2><table>{class_rows}</table></div>
<div><h2>Terminal decisions</h2><table>{case_rows}</table></div>
<div><h2>Image/class matrix</h2><table>{image_rows}</table></div></div></section></main></body></html>"""
    output.write_text(document, encoding="utf-8")


def build_review_package(
    dataset_root: Path,
    candidates_csv: Path,
    policy_path: Path,
    output_dir: Path,
    *,
    splits: list[str] | None = None,
    render: bool = False,
    include_below_review: bool = False,
    max_side: int = 1280,
    force: bool = False,
    redact_paths: bool = False,
) -> dict[str, Path]:
    dataset_root = dataset_root.expanduser().resolve()
    candidates_csv = candidates_csv.expanduser().resolve()
    policy_path = policy_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    _, names = load_dataset_metadata(dataset_root)
    class_ids = {name: index for index, name in enumerate(names)}
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8-sig"))
    validate_policy(policy, names)
    geometry = policy["geometry"]
    split_names = list(dict.fromkeys(splits or ["train", "val", "test"]))

    if output_dir.exists():
        if not force:
            raise FileExistsError(f"Output exists: {output_dir}; use --force")
        if len(output_dir.parts) < 3:
            raise ValueError(f"Unsafe output path: {output_dir}")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    with candidates_csv.open(encoding="utf-8-sig", newline="") as handle:
        source_rows = list(csv.DictReader(handle))
    if not source_rows:
        raise ValueError("Candidate CSV is empty")
    required = {"split", "image", "class_name", "class_id", "conf", "cx", "cy", "w", "h"}
    missing = required - set(source_rows[0])
    if missing:
        raise ValueError(f"Candidate CSV is missing required columns: {sorted(missing)}")

    duplicate_of = _detect_model_duplicates(source_rows, float(geometry["candidate_duplicate_iou"]))
    gt_cache: dict[tuple[str, str], list[tuple[int, Box]]] = {}
    audited: list[dict[str, str]] = []

    for source_index, source_row in enumerate(source_rows):
        row = dict(source_row)
        split = row.get("split", "")
        image_name = Path(row.get("image", "")).name
        label_name = Path(row.get("label", "")).name or f"{Path(image_name).stem}.txt"
        key = split, label_name
        if key not in gt_cache:
            gt_cache[key] = _read_gt(dataset_root / "labels" / split / label_name)
        gt_rows = gt_cache[key]

        parse_error = ""
        try:
            candidate = _candidate_box(row)
            confidence = float(row["conf"])
            class_name = row["class_name"]
            expected_id = class_ids[class_name]
            if candidate.cls != expected_id:
                parse_error = "class_id_mismatch"
        except (KeyError, ValueError) as error:
            candidate = Box(-1, 0, 0, 0, 0)
            confidence = float("nan")
            class_name = row.get("class_name", "")
            expected_id = -1
            parse_error = repr(error)

        same_rows = [(line_index, gt) for line_index, gt in gt_rows if gt.cls == expected_id]
        same_index, same_metrics = best_match(candidate, [gt for _, gt in same_rows])
        matched_line = same_rows[same_index][0] if same_index is not None else None
        matched_box = same_rows[same_index][1] if same_index is not None else None
        relation = same_class_relation(same_metrics, geometry)
        cross_rows = [(line_index, gt) for line_index, gt in gt_rows if gt.cls != expected_id]
        cross_index, cross_metrics = best_match(candidate, [gt for _, gt in cross_rows])
        cross_gt = cross_rows[cross_index][1] if cross_index is not None else None
        model_duplicate = source_index in duplicate_of or row.get("scan_outcome") == "suppressed_candidate_duplicate"
        decision = classify_candidate(
            split=split,
            confidence=confidence,
            class_policy=policy["classes"].get(class_name, {"high_conf": 1.0, "review_conf": 1.0}),
            same_relation=relation,
            cross_conflict=is_cross_class_conflict(cross_metrics, geometry),
            model_duplicate=model_duplicate,
            box_is_valid=valid_box(candidate) and not parse_error,
            split_policy=policy["split_policy"],
        )
        include_low = include_below_review and decision.case_code == "BELOW_REVIEW_THRESHOLD"
        recommendation = decision.recommended_action
        apply_eligible = decision.apply_eligible
        if include_low:
            recommendation = "accept_add_or_reject" if split == "train" else "accept_eval_or_reject"
            apply_eligible = split == "train"
        if redact_paths:
            row["image"] = image_name
            row["label"] = label_name
        row.update(
            candidate_id=f"R{source_index + 1:08d}",
            image_name=image_name,
            label_name=label_name,
            gt_count=str(len(gt_rows)),
            same_class_gt_count=str(len(same_rows)),
            same_relation=relation,
            matched_gt_line_index="" if matched_line is None else str(matched_line),
            matched_gt_class_id="" if matched_box is None else str(matched_box.cls),
            matched_gt_cx="" if matched_box is None else _format_metric(matched_box.cx),
            matched_gt_cy="" if matched_box is None else _format_metric(matched_box.cy),
            matched_gt_w="" if matched_box is None else _format_metric(matched_box.w),
            matched_gt_h="" if matched_box is None else _format_metric(matched_box.h),
            same_iou=_format_metric(same_metrics["iou"]),
            same_ios=_format_metric(same_metrics["ios"]),
            same_ioc=_format_metric(same_metrics["ioc"]),
            same_iog=_format_metric(same_metrics["iog"]),
            same_center_distance=_format_metric(same_metrics["center_distance"]),
            same_area_ratio=_format_metric(same_metrics["area_ratio"]),
            cross_gt_class="" if cross_gt is None else names[cross_gt.cls],
            cross_iou=_format_metric(cross_metrics["iou"]),
            cross_ios=_format_metric(cross_metrics["ios"]),
            cross_area_ratio=_format_metric(cross_metrics["area_ratio"]),
            model_duplicate_of="" if source_index not in duplicate_of else f"R{duplicate_of[source_index] + 1:08d}",
            parse_error=parse_error,
            case_code=decision.case_code,
            review_required=str(decision.review_required or include_low),
            recommended_action=recommendation,
            apply_eligible=str(apply_eligible),
            decision_reason=decision.reason,
            visual_file="",
        )
        audited.append(row)

    review_rows = [row for row in audited if row["review_required"] == "True"]
    render_failures: list[dict[str, str]] = []
    if render:
        for row in review_rows:
            split = row["split"]
            source = dataset_root / "images" / split / row["image_name"]
            relative = (
                Path("visuals")
                / row["case_code"]
                / row["class_name"]
                / f"{row['candidate_id']}_{row['class_name']}_{float(row['conf']):.3f}.jpg"
            )
            row["visual_file"] = relative.as_posix()
            try:
                _render_candidate(
                    source,
                    gt_cache[(split, row["label_name"])],
                    _candidate_box(row),
                    row,
                    output_dir / relative,
                    names,
                    max_side,
                )
            except Exception as error:
                render_failures.append(dict(row, render_error=repr(error)))

    all_fields = list(audited[0])
    _write_csv(output_dir / "all_predictions_audit.csv", audited, all_fields)
    _write_csv(output_dir / "review_queue.csv", review_rows, all_fields)
    decision_fields = [*all_fields, "reviewer_decision", "reviewer_comment"]
    _write_csv(
        output_dir / "company_decisions_template.csv",
        [dict(row, reviewer_decision="", reviewer_comment="") for row in review_rows],
        decision_fields,
    )
    if render_failures:
        _write_csv(output_dir / "render_failures.csv", render_failures, [*all_fields, "render_error"])

    prediction_counts = Counter(
        (row.get("split", ""), Path(row.get("image", "")).name, row.get("class_name", "")) for row in source_rows
    )
    image_case_rows: list[dict[str, str]] = []
    for split in split_names:
        image_root = dataset_root / "images" / split
        if not image_root.is_dir():
            continue
        for image in sorted(path for path in image_root.iterdir() if path.suffix.lower() in IMAGE_EXTS):
            label_name = f"{image.stem}.txt"
            key = split, label_name
            if key not in gt_cache:
                gt_cache[key] = _read_gt(dataset_root / "labels" / split / label_name)
            gt_by_class = Counter(box.cls for _, box in gt_cache[key])
            for class_name, class_id in class_ids.items():
                gt_count = gt_by_class[class_id]
                auto_count = prediction_counts[(split, image.name, class_name)]
                image_case_rows.append(
                    {
                        "split": split,
                        "image": image.name,
                        "class_name": class_name,
                        "gt_count": str(gt_count),
                        "auto_count": str(auto_count),
                        "image_case": image_class_state(gt_count, auto_count),
                    }
                )
    _write_csv(
        output_dir / "image_class_gt_auto_cases.csv",
        image_case_rows,
        ["split", "image", "class_name", "gt_count", "auto_count", "image_case"],
    )
    coverage = Counter((row["class_name"], row["case_code"]) for row in audited)
    _write_csv(
        output_dir / "decision_matrix_coverage.csv",
        [
            {"class_name": class_name, "case_code": case_code, "count": str(count)}
            for (class_name, case_code), count in sorted(coverage.items())
        ],
        ["class_name", "case_code", "count"],
    )

    review_counts = Counter(row["class_name"] for row in review_rows)
    summary = {
        "schema_version": 1,
        "policy_version": policy.get("version"),
        "dataset_root": "<redacted>" if redact_paths else str(dataset_root),
        "candidates_csv": "<redacted>" if redact_paths else str(candidates_csv),
        "prediction_rows": len(source_rows),
        "review_rows": len(review_rows),
        "render_enabled": render,
        "include_below_review": include_below_review,
        "render_failures": len(render_failures),
        "source_dataset_modified": False,
        "review_by_class": {name: review_counts[name] for name in names},
        "decision_cases": dict(sorted(Counter(row["case_code"] for row in audited).items())),
        "image_class_cases": dict(sorted(Counter(row["image_case"] for row in image_case_rows).items())),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _summary_html(summary, output_dir / "review_summary.html")
    shutil.copy2(Path(__file__).with_name("review_gui.py"), output_dir / "review_gui.py")
    shutil.copy2(policy_path, output_dir / "review_policy_used.yaml")
    (output_dir / "START_REVIEW.bat").write_text(
        '@echo off\r\npython "%~dp0review_gui.py" --review-root "%~dp0"\r\nif errorlevel 1 pause\r\n',
        encoding="ascii",
    )
    (output_dir / "REVIEW_GUIDE_CN.txt").write_text(
        "公司人工审核说明\n"
        "1. 双击 START_REVIEW.bat 打开审核界面。\n"
        "2. 红框是 AUTO；其他颜色框是原 GT；金黄色加粗框是最接近的同类 GT。\n"
        "3. A=新增，P=替换高亮同类 GT，E=接受为 val/test 评测标签，D=拒绝，U=暂不确定。\n"
        "4. 决策自动保存到 company_decisions.csv，关闭后可以续审。\n"
        "5. 回传前必须处理全部空白和 uncertain，并回传整个文件夹。\n",
        encoding="utf-8",
    )
    return {
        "audit": output_dir / "all_predictions_audit.csv",
        "queue": output_dir / "review_queue.csv",
        "decisions": output_dir / "company_decisions_template.csv",
        "summary": output_dir / "summary.json",
        "html": output_dir / "review_summary.html",
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("candidates_csv", type=Path)
    parser.add_argument("--policy", type=Path, default=Path(__file__).with_name("review_policy.yaml"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--splits", nargs="+", default=["train", "val", "test"])
    parser.add_argument("--max-side", type=int, default=1280)
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--include-below-review", action="store_true")
    parser.add_argument("--redact-paths", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    paths = build_review_package(
        args.dataset_root,
        args.candidates_csv,
        args.policy,
        args.output_dir,
        splits=args.splits,
        render=args.render,
        include_below_review=args.include_below_review,
        max_side=args.max_side,
        force=args.force,
        redact_paths=args.redact_paths,
    )
    print(f"Review queue: {paths['queue']}")
    print(f"Offline review launcher: {args.output_dir.resolve() / 'START_REVIEW.bat'}")


if __name__ == "__main__":
    main()
