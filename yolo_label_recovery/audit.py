"""Model-free quality audit for YOLO detection datasets."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from .dataset import load_dataset_metadata
from .domain import IMAGE_EXTS


class IssueCollector:
    """Count every finding while retaining only bounded evidence rows."""

    def __init__(self, detail_limit: int) -> None:
        self.detail_limit = detail_limit
        self.counts: Counter = Counter()
        self.details: list[dict] = []

    def add(self, split: str, relative_path: str, line: int | None, kind: str, detail: str) -> None:
        self.counts[kind] += 1
        if len(self.details) < self.detail_limit:
            self.details.append({"split": split, "path": relative_path, "line": line, "kind": kind, "detail": detail})


def _find_images(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_EXTS)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_stem(path: Path, root: Path) -> str:
    return path.relative_to(root).with_suffix("").as_posix()


def _audit_label_file(
    label_path: Path,
    split: str,
    relative_path: str,
    class_count: int,
    class_objects: Counter,
    findings: IssueCollector,
) -> tuple[int, int]:
    object_count = 0
    bad_count = 0
    lines = label_path.read_text(encoding="utf-8", errors="replace").splitlines()
    seen_lines: set[str] = set()
    for line_number, raw_line in enumerate(lines, 1):
        parts = raw_line.strip().split()
        if not parts:
            continue
        normalized = " ".join(parts)
        if normalized in seen_lines:
            findings.add(split, relative_path, line_number, "duplicate_label_line", normalized[:160])
        else:
            seen_lines.add(normalized)
        if len(parts) != 5:
            findings.add(split, relative_path, line_number, "malformed_line", f"expected 5 columns, got {len(parts)}")
            bad_count += 1
            continue
        try:
            values = [float(value) for value in parts]
        except ValueError:
            findings.add(split, relative_path, line_number, "non_numeric", raw_line[:160])
            bad_count += 1
            continue
        if not all(math.isfinite(value) for value in values):
            findings.add(split, relative_path, line_number, "non_finite", raw_line[:160])
            bad_count += 1
            continue

        class_value, cx, cy, width, height = values
        class_id = int(class_value)
        if class_value != class_id or not 0 <= class_id < class_count:
            findings.add(split, relative_path, line_number, "invalid_class_id", str(class_value))
            bad_count += 1
            continue
        if width <= 0 or height <= 0 or width > 1 or height > 1 or not 0 <= cx <= 1 or not 0 <= cy <= 1:
            findings.add(split, relative_path, line_number, "invalid_box", f"{cx:g} {cy:g} {width:g} {height:g}")
            bad_count += 1
            continue

        object_count += 1
        class_objects[class_id] += 1
        if cx - width / 2 < 0 or cy - height / 2 < 0 or cx + width / 2 > 1 or cy + height / 2 > 1:
            findings.add(split, relative_path, line_number, "box_crosses_image_edge", f"{cx:g} {cy:g} {width:g} {height:g}")
    return object_count, bad_count


def audit_dataset(
    dataset_root: Path,
    splits: Iterable[str] = ("train", "val", "test"),
    *,
    hash_images: bool = False,
    check_images: bool = False,
    max_issue_details: int = 5000,
) -> dict:
    """Return a JSON-serializable audit without changing the dataset."""
    dataset_root = dataset_root.expanduser().resolve()
    _, names = load_dataset_metadata(dataset_root)
    split_names = list(dict.fromkeys(splits))
    findings = IssueCollector(max_issue_details)
    split_stats: dict[str, dict] = {}
    class_objects: Counter = Counter()
    hashes: dict[str, list[dict[str, str]]] = defaultdict(list)

    for split in split_names:
        image_root = dataset_root / "images" / split
        label_root = dataset_root / "labels" / split
        images = _find_images(image_root)
        labels = sorted(label_root.rglob("*.txt")) if label_root.is_dir() else []
        image_stems = {_relative_stem(path, image_root) for path in images}
        label_stems = {_relative_stem(path, label_root) for path in labels}
        missing_labels = image_stems - label_stems
        orphan_labels = label_stems - image_stems
        empty_labels = 0
        objects = 0
        bad_lines = 0
        corrupt_images = 0

        for stem in orphan_labels:
            findings.add(split, f"labels/{split}/{stem}.txt", None, "orphan_label", "no matching image")

        for image_path in images:
            relative_image = image_path.relative_to(dataset_root).as_posix()
            stem = _relative_stem(image_path, image_root)
            label_path = label_root / f"{stem}.txt"
            if label_path.is_file():
                if label_path.stat().st_size == 0:
                    empty_labels += 1
                found, bad = _audit_label_file(
                    label_path,
                    split,
                    label_path.relative_to(dataset_root).as_posix(),
                    len(names),
                    class_objects,
                    findings,
                )
                objects += found
                bad_lines += bad
            if check_images:
                try:
                    with Image.open(image_path) as image:
                        image.verify()
                except Exception as error:  # Pillow exposes format-specific exception types.
                    corrupt_images += 1
                    findings.add(split, relative_image, None, "corrupt_image", str(error)[:160])
            if hash_images:
                hashes[_sha256(image_path)].append({"split": split, "path": relative_image})

        split_stats[split] = {
            "images": len(images),
            "labels": len(labels),
            "objects": objects,
            "images_without_label": len(missing_labels),
            "empty_labels": empty_labels,
            "orphan_labels": len(orphan_labels),
            "bad_label_lines": bad_lines,
            "corrupt_images": corrupt_images,
        }

    duplicate_group_count = 0
    cross_split_group_count = 0
    duplicate_examples: list[list[dict[str, str]]] = []
    for group in hashes.values():
        if len(group) < 2:
            continue
        duplicate_group_count += 1
        if len(duplicate_examples) < 20:
            duplicate_examples.append(group)
        group_splits = {item["split"] for item in group}
        if len(group_splits) > 1:
            cross_split_group_count += 1
            findings.add(
                ",".join(sorted(group_splits)),
                group[0]["path"],
                None,
                "cross_split_duplicate",
                "; ".join(item["path"] for item in group),
            )

    issue_counts = findings.counts
    critical_kinds = {"orphan_label", "malformed_line", "non_numeric", "non_finite", "invalid_class_id", "invalid_box", "corrupt_image"}
    critical_count = sum(issue_counts[kind] for kind in critical_kinds)
    warning_count = sum(issue_counts.values()) - critical_count
    status = "fail" if critical_count else "warn" if warning_count else "pass"
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_root": str(dataset_root),
        "status": status,
        "class_names": names,
        "splits": split_stats,
        "class_objects": {name: class_objects[index] for index, name in enumerate(names)},
        "issue_counts": dict(sorted(issue_counts.items())),
        "critical_issues": critical_count,
        "warning_issues": warning_count,
        "hash_images": hash_images,
        "check_images": check_images,
        "exact_duplicate_groups": duplicate_group_count,
        "cross_split_duplicate_groups": cross_split_group_count,
        "duplicate_examples": duplicate_examples,
        "issue_detail_limit": max_issue_details,
        "issue_details_truncated": max(0, sum(issue_counts.values()) - len(findings.details)),
        "issues": findings.details,
    }


def _metric_card(label: str, value: object) -> str:
    return f'<div class="card"><span>{html.escape(label)}</span><strong>{html.escape(str(value))}</strong></div>'


def generate_audit_report(audit: dict, output: Path) -> Path:
    """Write a self-contained, shareable HTML audit report."""
    status = audit["status"]
    split_rows = "".join(
        "<tr>" + "".join(
            f"<td>{html.escape(str(value))}</td>"
            for value in (name, stats["images"], stats["labels"], stats["objects"], stats["images_without_label"], stats["orphan_labels"], stats["bad_label_lines"], stats["corrupt_images"])
        ) + "</tr>"
        for name, stats in audit["splits"].items()
    )
    class_rows = "".join(
        f"<tr><td>{html.escape(name)}</td><td>{count}</td></tr>"
        for name, count in audit["class_objects"].items()
    )
    issue_rows = "".join(
        f"<tr><td>{html.escape(issue['kind'])}</td><td>{html.escape(issue['split'])}</td><td>{html.escape(issue['path'])}</td><td>{issue['line'] or ''}</td><td>{html.escape(issue['detail'])}</td></tr>"
        for issue in audit["issues"][:500]
    ) or '<tr><td colspan="5" class="empty">No issues found.</td></tr>'
    cards = "".join([
        _metric_card("Status", status.upper()),
        _metric_card("Critical issues", audit["critical_issues"]),
        _metric_card("Warnings", audit["warning_issues"]),
        _metric_card("Cross-split duplicates", audit["cross_split_duplicate_groups"]),
    ])
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>YOLO Dataset Audit</title><style>
:root{{--navy:#081a2f;--cyan:#16c1c8;--amber:#f5ae2b;--paper:#f4f7fa;--ink:#142338;--line:#dce5ed}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 "Segoe UI",sans-serif}}
header{{padding:48px max(5vw,28px);color:white;background:linear-gradient(125deg,var(--navy),#123d5d)}}
header p{{max-width:900px;color:#c9d9e7;word-break:break-all}} main{{max-width:1180px;margin:-24px auto 60px;padding:0 24px}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}} .card{{padding:20px;background:white;border-radius:14px;box-shadow:0 8px 28px #0a233d14}}
.card span{{display:block;color:#60758a;font-size:12px;text-transform:uppercase;letter-spacing:.08em}} .card strong{{font-size:25px}}
section{{margin-top:20px;padding:24px;background:white;border-radius:14px}} table{{width:100%;border-collapse:collapse}} th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}} th{{color:#526a80;font-size:12px;text-transform:uppercase}}
.status-{status}{{color:{'#1c8b67' if status == 'pass' else '#c77805' if status == 'warn' else '#c43d4b'}}} .empty{{text-align:center;color:#71859a}}
code{{font-family:"Cascadia Code",monospace}} @media(max-width:800px){{.cards{{grid-template-columns:1fr 1fr}}section{{overflow-x:auto}}}}
</style></head><body><header><h1>YOLO Dataset Audit</h1><h2 class="status-{status}">{status.upper()}</h2><p>{html.escape(audit['dataset_root'])}</p></header><main>
<div class="cards">{cards}</div>
<section><h2>Split integrity</h2><table><thead><tr><th>Split</th><th>Images</th><th>Labels</th><th>Objects</th><th>No label</th><th>Orphan</th><th>Bad lines</th><th>Corrupt</th></tr></thead><tbody>{split_rows}</tbody></table></section>
<section><h2>Class distribution</h2><table><thead><tr><th>Class</th><th>Objects</th></tr></thead><tbody>{class_rows}</tbody></table></section>
<section><h2>Issue evidence</h2><p>Showing up to 500 retained findings; {audit['issue_details_truncated']} additional details were omitted by the memory bound. Missing label files are treated as possible background images, not critical errors.</p><table><thead><tr><th>Kind</th><th>Split</th><th>Path</th><th>Line</th><th>Detail</th></tr></thead><tbody>{issue_rows}</tbody></table></section>
</main></body></html>"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8")
    return output


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--splits", nargs="+", default=["train", "val", "test"])
    parser.add_argument("--hash-images", action="store_true", help="Detect exact duplicates and cross-split leakage.")
    parser.add_argument("--check-images", action="store_true", help="Decode every image with Pillow to find corrupt files.")
    parser.add_argument("--max-issue-details", type=int, default=5000, help="Bound retained evidence rows while preserving full counts.")
    parser.add_argument("--fail-on-error", action="store_true", help="Exit non-zero when critical issues are found.")
    parser.add_argument("--fail-on-leakage", action="store_true", help="Exit non-zero when exact images cross splits.")
    parser.add_argument("--redact-paths", action="store_true", help="Hide the absolute dataset root in saved reports.")
    args = parser.parse_args(argv)
    dataset_root = args.dataset_root.expanduser().resolve()
    output_dir = (args.output_dir or dataset_root.parent / f"{dataset_root.name}-audit").expanduser().resolve()
    if args.max_issue_details < 0:
        raise ValueError("--max-issue-details must be >= 0")
    audit = audit_dataset(
        dataset_root,
        args.splits,
        hash_images=args.hash_images,
        check_images=args.check_images,
        max_issue_details=args.max_issue_details,
    )
    if args.redact_paths:
        audit["dataset_root"] = f"<redacted>/{dataset_root.name}"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "dataset_audit.json"
    json_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path = generate_audit_report(audit, output_dir / "dataset_audit.html")
    print(f"status={audit['status']} critical={audit['critical_issues']} warnings={audit['warning_issues']}")
    print(json_path)
    print(html_path)
    if args.fail_on_error and audit["critical_issues"]:
        raise SystemExit(2)
    if args.fail_on_leakage and audit["cross_split_duplicate_groups"]:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
