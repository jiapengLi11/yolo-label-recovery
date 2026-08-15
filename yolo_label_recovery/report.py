"""Generate a self-contained HTML quality report from a recovery output directory."""

from __future__ import annotations

import argparse
import csv
import html
import json
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_root", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--gallery-per-class", type=int, default=3)
    parser.add_argument("--redact-paths", action="store_true", help="Hide local dataset paths in a shareable report.")
    return parser.parse_args(argv)


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _histogram(values: Iterable[float], bins: int = 10) -> list[int]:
    counts = [0] * bins
    for value in values:
        index = min(bins - 1, max(0, int(value * bins)))
        counts[index] += 1
    return counts


def _bar_chart(counts: list[int], label: str, color: str) -> str:
    peak = max(counts, default=0) or 1
    bars = []
    for index, count in enumerate(counts):
        height = round(96 * count / peak)
        x = 12 + index * 38
        y = 118 - height
        bars.append(
            f'<rect x="{x}" y="{y}" width="24" height="{height}" rx="4" fill="{color}">'
            f'<title>{index / 10:.1f}-{(index + 1) / 10:.1f}: {count}</title></rect>'
        )
        bars.append(f'<text x="{x + 12}" y="136" text-anchor="middle">{index / 10:.1f}</text>')
    return (
        f'<div class="chart"><div class="chart-title">{html.escape(label)}</div>'
        f'<svg viewBox="0 0 400 150" role="img">{"".join(bars)}</svg></div>'
    )


def _gallery(output_root: Path, classes: list[str], limit: int) -> str:
    sections = []
    for class_name in classes:
        class_dir = output_root / "auto_samples" / class_name
        images = []
        if class_dir.is_dir():
            images = sorted(
                path for path in class_dir.iterdir()
                if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".svg"}
            )[:limit]
        if not images:
            continue
        cards = []
        for image_path in images:
            relative = image_path.relative_to(output_root).as_posix()
            cards.append(
                f'<figure><img loading="lazy" src="{html.escape(relative)}" '
                f'alt="{html.escape(class_name)} sample"><figcaption>{html.escape(image_path.name)}</figcaption></figure>'
            )
        sections.append(
            f'<section class="gallery-class"><h3>{html.escape(class_name)}</h3>'
            f'<div class="gallery-grid">{"".join(cards)}</div></section>'
        )
    if not sections:
        return '<p class="muted">No sampled images were found. Run with --draw-auto-samples N to create a gallery.</p>'
    return "".join(sections)


def generate_report(output_root: Path, output: Path, gallery_per_class: int = 3, redact_paths: bool = False) -> Path:
    output_root = output_root.expanduser().resolve()
    summary_path = output_root / "summary.json"
    if not summary_path.is_file():
        raise FileNotFoundError(f"Missing summary.json: {summary_path}")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    manifest_path = output_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    environment = manifest.get("environment", {})
    cuda = environment.get("cuda", {})
    gpu_names = ", ".join(device.get("name", "unknown") for device in cuda.get("devices", [])) or "not recorded"
    auto_rows = _read_rows(output_root / "candidates_auto.csv")
    review_rows = _read_rows(output_root / "candidates_review.csv")
    classes = list(summary.get("classes") or summary.get("stats", {}).keys())
    stats = summary.get("stats", {})

    auto_by_class: dict[str, int] = defaultdict(int)
    review_by_class: dict[str, int] = defaultdict(int)
    for row in auto_rows:
        auto_by_class[row.get("class_name", "unknown")] += 1
    for row in review_rows:
        review_by_class[row.get("class_name", "unknown")] += 1

    total_scanned = sum(int(stats.get(name, {}).get("images_scanned", 0)) for name in classes)
    total_oom = sum(int(stats.get(name, {}).get("oom_retries", 0)) for name in classes)
    table_rows = []
    for name in classes:
        item = stats.get(name, {})
        table_rows.append(
            "<tr>"
            f"<td><span class='class-dot'></span>{html.escape(name)}</td>"
            f"<td>{int(item.get('images_scanned', 0)):,}</td>"
            f"<td>{int(auto_by_class.get(name, item.get('auto_added', 0))):,}</td>"
            f"<td>{int(review_by_class.get(name, item.get('review_candidates', 0))):,}</td>"
            f"<td>{int(item.get('matched_existing', 0)):,}</td>"
            f"<td>{int(item.get('duplicate_candidates', 0)):,}</td>"
            f"<td>{int(item.get('initial_batch', summary.get('batch', 0)))} -> "
            f"{int(item.get('stable_batch', summary.get('batch', 0)))}</td>"
            f"<td>{int(item.get('oom_retries', 0))}</td>"
            "</tr>"
        )

    auto_conf = [float(row["conf"]) for row in auto_rows if row.get("conf")]
    review_conf = [float(row["conf"]) for row in review_rows if row.get("conf")]
    auto_iou = [float(row["max_iou_same_class"]) for row in auto_rows if row.get("max_iou_same_class")]

    template = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>YOLO Label Recovery Report</title>
<style>
:root{--ink:#102a43;--blue:#0b74b8;--cyan:#11a7a2;--amber:#f2a93b;--paper:#f5f8fb;--line:#d8e2eb;--muted:#627d98}
*{box-sizing:border-box}body{margin:0;background:linear-gradient(135deg,#e9f2f7,#fff 45%,#eef7f4);color:var(--ink);font:15px/1.55 "Segoe UI",sans-serif}
main{max-width:1180px;margin:auto;padding:42px 24px 72px}header{padding:36px;border-radius:24px;background:#0d2e48;color:white;box-shadow:0 20px 60px #102a4320}
.eyebrow{color:#7fddda;text-transform:uppercase;letter-spacing:.14em;font-weight:700}h1{font-size:42px;line-height:1.08;margin:10px 0}header p{max-width:760px;color:#d6e8f2}.meta{display:flex;gap:16px;flex-wrap:wrap;color:#a9c7d8}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:24px 0}.card,.panel{background:#fff;border:1px solid var(--line);border-radius:18px;box-shadow:0 12px 32px #102a4310}.card{padding:20px}.value{font-size:30px;font-weight:750}.label,.muted{color:var(--muted)}
.panel{padding:24px;margin-top:20px}h2{font-size:23px;margin:0 0 16px}h3{margin:22px 0 10px}table{width:100%;border-collapse:collapse;overflow:hidden}th,td{padding:12px 10px;border-bottom:1px solid var(--line);text-align:right}th:first-child,td:first-child{text-align:left}th{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.05em}.class-dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--cyan);margin-right:8px}
.charts{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.chart{border:1px solid var(--line);border-radius:14px;padding:14px}.chart-title{font-weight:700}.chart text{font-size:9px;fill:var(--muted)}
.gallery-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}figure{margin:0;border:1px solid var(--line);border-radius:14px;overflow:hidden;background:var(--paper)}figure img{display:block;width:100%;aspect-ratio:4/3;object-fit:contain;background:#17222b}figcaption{padding:8px 10px;color:var(--muted);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.runtime-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.runtime-item{padding:14px;border:1px solid var(--line);border-radius:12px}.runtime-item span{display:block;color:var(--muted);font-size:12px}.runtime-item strong{display:block;margin-top:4px;word-break:break-word}
footer{color:var(--muted);margin-top:28px}@media(max-width:850px){.cards,.charts,.runtime-grid{grid-template-columns:repeat(2,1fr)}.gallery-grid{grid-template-columns:1fr 1fr}}@media(max-width:560px){h1{font-size:32px}.cards,.charts,.gallery-grid,.runtime-grid{grid-template-columns:1fr}.panel{overflow:auto}}
</style></head><body><main>
<header><div class="eyebrow">Multi-Teacher Missing Label Recovery</div><h1>YOLO Label Recovery</h1>
<p>Auditable recovery of missing annotations using specialist teacher models, same-class IoU matching and confidence routing.</p>
<div class="meta"><span>Dataset: __DATASET__</span><span>Mode: __MODE__</span><span>Device: __DEVICE__</span><span>Image size: __IMGSZ__</span></div></header>
<section class="cards"><div class="card"><div class="value">__SCANNED__</div><div class="label">Image-model scans</div></div><div class="card"><div class="value">__AUTO__</div><div class="label">AUTO candidates</div></div><div class="card"><div class="value">__REVIEW__</div><div class="label">REVIEW candidates</div></div><div class="card"><div class="value">__OOM__</div><div class="label">OOM retries</div></div></section>
<section class="panel"><h2>Class-level recovery summary</h2><table><thead><tr><th>Class</th><th>Scanned</th><th>AUTO</th><th>REVIEW</th><th>Matched GT</th><th>Duplicates</th><th>Batch</th><th>OOM</th></tr></thead><tbody>__ROWS__</tbody></table></section>
<section class="panel"><h2>Reproducibility</h2><div class="runtime-grid"><div class="runtime-item"><span>Tool version</span><strong>__TOOL_VERSION__</strong></div><div class="runtime-item"><span>Python</span><strong>__PYTHON__</strong></div><div class="runtime-item"><span>PyTorch / CUDA</span><strong>__TORCH_CUDA__</strong></div><div class="runtime-item"><span>GPU</span><strong>__GPU__</strong></div></div></section>
<section class="panel"><h2>Candidate distributions</h2><div class="charts">__CHARTS__</div></section>
<section class="panel"><h2>Visual quality samples</h2>__GALLERY__</section>
<footer>Generated from summary.json and candidate audit CSV files. Source labels remain unchanged.</footer>
</main></body></html>"""

    charts = "".join(
        [
            _bar_chart(_histogram(auto_conf), "AUTO confidence", "#11a7a2"),
            _bar_chart(_histogram(review_conf), "REVIEW confidence", "#f2a93b"),
            _bar_chart(_histogram(auto_iou), "AUTO max same-class IoU", "#0b74b8"),
        ]
    )
    dataset_value = str(summary.get("dataset_root", "unknown"))
    if redact_paths and dataset_value != "unknown":
        dataset_value = f"<redacted>/{Path(dataset_value).name}"
    replacements = {
        "__DATASET__": html.escape(dataset_value),
        "__MODE__": "dry-run" if summary.get("dry_run") else "apply",
        "__DEVICE__": html.escape(str(summary.get("device", "unknown"))),
        "__IMGSZ__": html.escape(str(summary.get("imgsz", "unknown"))),
        "__SCANNED__": f"{total_scanned:,}",
        "__AUTO__": f"{len(auto_rows):,}",
        "__REVIEW__": f"{len(review_rows):,}",
        "__OOM__": f"{total_oom:,}",
        "__TOOL_VERSION__": html.escape(str(manifest.get("tool_version", "not recorded"))),
        "__PYTHON__": html.escape(str(environment.get("python", "not recorded"))),
        "__TORCH_CUDA__": html.escape(
            f"{environment.get('packages', {}).get('torch') or 'unknown'} / {cuda.get('torch_cuda_version') or 'CPU'}"
        ),
        "__GPU__": html.escape(gpu_names),
        "__ROWS__": "".join(table_rows),
        "__CHARTS__": charts,
        "__GALLERY__": _gallery(output_root, classes, gallery_per_class),
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)

    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(template, encoding="utf-8")
    return output


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    output_root = args.output_root.expanduser().resolve()
    output = args.output or (output_root / "report.html")
    print(generate_report(output_root, output, args.gallery_per_class, args.redact_paths))


if __name__ == "__main__":
    main()
