"""Prioritize image-level human review using uncertainty, rarity and visual diversity."""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .near_duplicates import ImageFingerprint, fingerprint_image, hamming_distance

REQUIRED_COLUMNS = {"split", "image", "class_name", "conf", "mode"}
QUEUE_COLUMNS = [
    "priority_rank",
    "priority_score",
    "uncertainty_score",
    "rarity_score",
    "diversity_score",
    "split",
    "image",
    "candidate_count",
    "candidate_classes",
    "min_confidence",
    "max_confidence",
]


@dataclass(frozen=True)
class ReviewCandidate:
    row_number: int
    row: dict[str, str]
    split: str
    image: str
    class_name: str
    confidence: float
    mode: str


@dataclass(frozen=True)
class ReviewItem:
    split: str
    image: str
    resolved_path: Path
    relative_path: str
    candidates: tuple[ReviewCandidate, ...]
    fingerprint: ImageFingerprint
    uncertainty: float
    rarity: float


@dataclass(frozen=True)
class RankedItem:
    rank: int
    item: ReviewItem
    priority_score: float
    rarity: float
    diversity: float


def read_candidates(
    path: Path,
    *,
    modes: set[str],
    classes: set[str] | None = None,
) -> tuple[list[ReviewCandidate], list[str]]:
    path = path.expanduser().resolve()
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"{path}: CSV header is missing")
        missing = REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing:
            raise ValueError(f"{path}: missing required columns: {', '.join(sorted(missing))}")
        rows = []
        for row_number, row in enumerate(reader, 2):
            split = row["split"].strip()
            image = row["image"].strip()
            class_name = row["class_name"].strip()
            mode = row["mode"].strip().lower()
            if not split or not image or not class_name:
                raise ValueError(f"row {row_number}: split, image and class_name must not be empty")
            if mode not in {"auto", "review"}:
                raise ValueError(f"row {row_number}: mode must be 'auto' or 'review'")
            try:
                confidence = float(row["conf"])
            except ValueError as error:
                raise ValueError(f"row {row_number}: conf must be numeric") from error
            if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                raise ValueError(f"row {row_number}: conf must be finite and in [0, 1]")
            if mode not in modes or (classes is not None and class_name not in classes):
                continue
            rows.append(ReviewCandidate(row_number, dict(row), split, image, class_name, confidence, mode))
    if not rows:
        raise ValueError(f"{path}: no candidates remain after mode/class filtering")
    return rows, list(reader.fieldnames)


def confidence_entropy(confidence: float) -> float:
    """Return normalized Bernoulli entropy in [0, 1]."""
    if confidence <= 0 or confidence >= 1:
        return 0.0
    return -(confidence * math.log(confidence) + (1 - confidence) * math.log(1 - confidence)) / math.log(2)


def visual_distance(left: ImageFingerprint, right: ImageFingerprint) -> float:
    """Combine local-gradient and global-layout hash distance in [0, 1]."""
    return 0.7 * hamming_distance(left.dhash, right.dhash) / 64 + 0.3 * hamming_distance(left.ahash, right.ahash) / 64


def _resolve_image(dataset_root: Path, split: str, raw_image: str) -> Path:
    raw_path = Path(raw_image)
    candidates = [raw_path] if raw_path.is_absolute() else [
        dataset_root / raw_path,
        dataset_root / "images" / split / raw_path,
        dataset_root / "images" / raw_path,
    ]
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved.is_file() and resolved.is_relative_to(dataset_root):
            return resolved
    raise FileNotFoundError("image was not found inside the dataset root")


def _fingerprint_task(task: tuple[tuple[str, str], Path, Path]) -> tuple[tuple[str, str], ImageFingerprint | None, dict | None]:
    key, path, dataset_root = task
    split, raw_image = key
    try:
        relative_path = path.relative_to(dataset_root).as_posix()
        return key, fingerprint_image(path, split, relative_path), None
    except Exception as error:  # Pillow exposes format-specific exceptions.
        return key, None, {"split": split, "image": raw_image, "error": str(error)[:300]}


def build_review_items(
    candidates: list[ReviewCandidate],
    dataset_root: Path,
    *,
    workers: int,
) -> tuple[list[ReviewItem], list[dict], Counter]:
    grouped: dict[tuple[str, str], list[ReviewCandidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[(candidate.split, candidate.image)].append(candidate)

    failures: list[dict] = []
    resolved: dict[tuple[str, str], Path] = {}
    for key in sorted(grouped):
        try:
            resolved[key] = _resolve_image(dataset_root, *key)
        except Exception as error:
            failures.append({"split": key[0], "image": key[1], "error": str(error)[:300]})

    tasks = [(key, path, dataset_root) for key, path in sorted(resolved.items())]
    with ThreadPoolExecutor(max_workers=workers) as executor:
        fingerprint_results = list(executor.map(_fingerprint_task, tasks))
    fingerprints = {}
    for key, fingerprint, error in fingerprint_results:
        if error is not None:
            failures.append(error)
        elif fingerprint is not None:
            fingerprints[key] = fingerprint

    valid_candidates = [candidate for key in fingerprints for candidate in grouped[key]]
    class_counts = Counter(candidate.class_name for candidate in valid_candidates)
    minimum_class_count = min(class_counts.values())
    class_rarity = {name: math.sqrt(minimum_class_count / count) for name, count in class_counts.items()}
    items = []
    for key in sorted(fingerprints):
        rows = tuple(grouped[key])
        path = resolved[key]
        items.append(
            ReviewItem(
                split=key[0],
                image=key[1],
                resolved_path=path,
                relative_path=path.relative_to(dataset_root).as_posix(),
                candidates=rows,
                fingerprint=fingerprints[key],
                uncertainty=max(confidence_entropy(candidate.confidence) for candidate in rows),
                rarity=max(class_rarity[candidate.class_name] for candidate in rows),
            )
        )
    return items, failures, class_counts


def prioritize_items(
    items: list[ReviewItem],
    *,
    budget: int,
    uncertainty_weight: float,
    rarity_weight: float,
    diversity_weight: float,
) -> list[RankedItem]:
    """Greedily maximize a deterministic weighted acquisition function."""
    if not items:
        return []
    remaining = set(range(len(items)))
    minimum_distances = [1.0] * len(items)
    selected_class_counts: Counter = Counter()
    ranked: list[RankedItem] = []
    for rank in range(1, min(budget, len(items)) + 1):
        def dynamic_rarity(index: int) -> float:
            classes = {candidate.class_name for candidate in items[index].candidates}
            return max(items[index].rarity / math.sqrt(1 + selected_class_counts[class_name]) for class_name in classes)

        def score(index: int) -> float:
            item = items[index]
            return (
                uncertainty_weight * item.uncertainty
                + rarity_weight * dynamic_rarity(index)
                + diversity_weight * minimum_distances[index]
            )

        selected_index = min(remaining, key=lambda index: (-score(index), items[index].split, items[index].image))
        selected = items[selected_index]
        ranked.append(RankedItem(rank, selected, score(selected_index), dynamic_rarity(selected_index), minimum_distances[selected_index]))
        selected_class_counts.update({candidate.class_name for candidate in selected.candidates})
        remaining.remove(selected_index)
        for index in remaining:
            minimum_distances[index] = min(
                minimum_distances[index],
                visual_distance(items[index].fingerprint, selected.fingerprint),
            )
    return ranked


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _rank_row(ranked: RankedItem) -> dict:
    confidences = [candidate.confidence for candidate in ranked.item.candidates]
    return {
        "priority_rank": ranked.rank,
        "priority_score": f"{ranked.priority_score:.6f}",
        "uncertainty_score": f"{ranked.item.uncertainty:.6f}",
        "rarity_score": f"{ranked.rarity:.6f}",
        "diversity_score": f"{ranked.diversity:.6f}",
        "split": ranked.item.split,
        "image": ranked.item.relative_path,
        "candidate_count": len(ranked.item.candidates),
        "candidate_classes": ",".join(sorted({candidate.class_name for candidate in ranked.item.candidates})),
        "min_confidence": f"{min(confidences):.6f}",
        "max_confidence": f"{max(confidences):.6f}",
    }


def generate_report(summary: dict, queue_rows: list[dict], output: Path) -> Path:
    pool_counts = summary["class_distribution"]["pool_candidates"]
    queue_counts = summary["class_distribution"]["queue_candidates"]
    largest = max(pool_counts.values(), default=1)
    class_bars = "".join(
        f'<div class="class-row"><b>{html.escape(name)}</b><div><i style="width:{count / largest * 100:.1f}%"></i></div><span>{queue_counts.get(name, 0)} / {count}</span></div>'
        for name, count in sorted(pool_counts.items())
    )
    rows = "".join(
        "<tr>"
        f"<td><strong>#{row['priority_rank']}</strong></td><td>{row['priority_score']}</td>"
        f"<td>{row['uncertainty_score']}</td><td>{row['rarity_score']}</td><td>{row['diversity_score']}</td>"
        f"<td>{html.escape(row['candidate_classes'])}</td><td><code>{html.escape(row['image'])}</code></td></tr>"
        for row in queue_rows[:200]
    )
    totals = summary["totals"]
    cards = "".join(
        f"<article><span>{label}</span><strong>{value}</strong></article>"
        for label, value in (
            ("Candidate rows", totals["candidate_rows"]),
            ("Review images", totals["review_images"]),
            ("Selected queue", totals["selected_images"]),
            ("Class coverage", f"{totals['selected_classes']} / {totals['pool_classes']}"),
        )
    )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Active review priority</title><style>
:root{{--navy:#102536;--blue:#176b87;--orange:#f3a33c;--paper:#f3f1ea;--ink:#172b38;--muted:#62737d;--line:#e1e3de}}*{{box-sizing:border-box}}
body{{margin:0;background:radial-gradient(circle at 85% 0,#d7e7e5 0,transparent 34%),var(--paper);color:var(--ink);font:15px/1.55 "Segoe UI",sans-serif}}header{{padding:55px max(5vw,28px) 72px;background:linear-gradient(120deg,var(--navy),var(--blue));color:white}}header p{{max-width:880px;color:#d8e7ec}}header code{{word-break:break-all}}
main{{max-width:1220px;margin:-34px auto 64px;padding:0 24px}}.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}}article,section{{background:white;border-radius:15px;box-shadow:0 12px 32px #18344012}}article{{padding:22px}}article span{{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em}}article strong{{font-size:27px}}section{{margin-top:20px;padding:25px;overflow:auto}}
.class-row{{display:grid;grid-template-columns:90px 1fr 90px;gap:12px;align-items:center;margin:11px 0}}.class-row div{{height:13px;background:#edf0ec;border-radius:8px;overflow:hidden}}.class-row i{{display:block;height:100%;background:linear-gradient(90deg,var(--blue),var(--orange));border-radius:8px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left}}th{{font-size:11px;color:var(--muted);text-transform:uppercase}}code{{font:12px "Cascadia Code",monospace}}.note{{color:var(--muted)}}
@media(max-width:800px){{.cards{{grid-template-columns:1fr 1fr}}}}@media(max-width:480px){{.cards{{grid-template-columns:1fr}}}}
</style></head><body><header><h1>Active review priority</h1><p>A deterministic image-level queue balancing confidence entropy, rare-class coverage and greedy perceptual diversity. Source candidates and images remain unchanged.</p><code>{html.escape(summary['sources']['dataset_root'])}</code></header><main><div class="cards">{cards}</div>
<section><h2>Class coverage</h2><p class="note">Bars show all filtered candidates; labels show selected / pool candidate rows.</p>{class_bars}</section>
<section><h2>Priority queue</h2><table><thead><tr><th>Rank</th><th>Score</th><th>Uncertainty</th><th>Rarity</th><th>Diversity</th><th>Classes</th><th>Image</th></tr></thead><tbody>{rows}</tbody></table></section>
<section><h2>Acquisition policy</h2><p>Weights: uncertainty <strong>{summary['policy']['uncertainty_weight']:.0%}</strong>, rarity <strong>{summary['policy']['rarity_weight']:.0%}</strong>, diversity <strong>{summary['policy']['diversity_weight']:.0%}</strong>. The first item receives maximum diversity; later items use minimum perceptual distance to the selected set. Fingerprint/path failures: <strong>{totals['image_failures']}</strong>.</p></section>
</main></body></html>"""
    output.write_text(document, encoding="utf-8")
    return output


def run_prioritization(
    candidates_csv: Path,
    dataset_root: Path,
    output_dir: Path,
    *,
    budget: int = 200,
    modes: set[str] | None = None,
    classes: set[str] | None = None,
    workers: int = 4,
    uncertainty_weight: float = 0.45,
    rarity_weight: float = 0.20,
    diversity_weight: float = 0.35,
    redact_paths: bool = False,
) -> dict:
    modes = modes or {"review"}
    if budget < 1 or workers < 1:
        raise ValueError("budget and workers must be >= 1")
    weights = [uncertainty_weight, rarity_weight, diversity_weight]
    if any(weight < 0 for weight in weights) or not math.isclose(sum(weights), 1.0, abs_tol=1e-9):
        raise ValueError("priority weights must be non-negative and sum to 1")
    dataset_root = dataset_root.expanduser().resolve()
    candidates_csv = candidates_csv.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if output_dir == dataset_root or output_dir.is_relative_to(dataset_root):
        raise ValueError("--output-dir must be outside the source dataset")
    candidates, original_columns = read_candidates(candidates_csv, modes=modes, classes=classes)
    items, failures, class_counts = build_review_items(candidates, dataset_root, workers=workers)
    if not items:
        raise ValueError("no readable candidate images remain after path and fingerprint validation")
    ranked = prioritize_items(
        items,
        budget=budget,
        uncertainty_weight=uncertainty_weight,
        rarity_weight=rarity_weight,
        diversity_weight=diversity_weight,
    )
    queue_rows = [_rank_row(item) for item in ranked]
    selected_lookup = {(item.item.split, item.item.image): item.rank for item in ranked}
    ranked_lookup = {(item.item.split, item.item.image): item for item in ranked}
    candidate_rows = []
    queue_class_counts: Counter = Counter()
    for item in ranked:
        for candidate in item.item.candidates:
            queue_class_counts[candidate.class_name] += 1
            candidate_rows.append({**candidate.row, "priority_rank": item.rank})
    pool_rows = []
    for item in items:
        rank = selected_lookup.get((item.split, item.image))
        base = _rank_row(ranked_lookup[(item.split, item.image)]) if rank is not None else {
            "priority_rank": "",
            "priority_score": "",
            "uncertainty_score": f"{item.uncertainty:.6f}",
            "rarity_score": f"{item.rarity:.6f}",
            "diversity_score": "",
            "split": item.split,
            "image": item.relative_path,
            "candidate_count": len(item.candidates),
            "candidate_classes": ",".join(sorted({candidate.class_name for candidate in item.candidates})),
            "min_confidence": f"{min(candidate.confidence for candidate in item.candidates):.6f}",
            "max_confidence": f"{max(candidate.confidence for candidate in item.candidates):.6f}",
        }
        pool_rows.append({"selected": str(rank is not None).lower(), **base})

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "review_queue.csv", QUEUE_COLUMNS, queue_rows)
    candidate_columns = ["priority_rank", *[column for column in original_columns if column != "priority_rank"]]
    _write_csv(output_dir / "review_queue_candidates.csv", candidate_columns, candidate_rows)
    _write_csv(output_dir / "review_pool.csv", ["selected", *QUEUE_COLUMNS], pool_rows)
    _write_csv(output_dir / "image_failures.csv", ["split", "image", "error"], failures)
    summary = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "candidates_csv": f"<redacted>/{candidates_csv.name}" if redact_paths else str(candidates_csv),
            "dataset_root": f"<redacted>/{dataset_root.name}" if redact_paths else str(dataset_root),
        },
        "policy": {
            "modes": sorted(modes),
            "classes": sorted(classes) if classes else None,
            "budget": budget,
            "uncertainty": "normalized Bernoulli confidence entropy",
            "rarity": "sqrt(minimum class count / class count), decayed by selected class coverage",
            "diversity": "greedy minimum weighted dHash/aHash distance",
            "uncertainty_weight": uncertainty_weight,
            "rarity_weight": rarity_weight,
            "diversity_weight": diversity_weight,
        },
        "totals": {
            "candidate_rows": len(candidates),
            "review_images": len(items),
            "selected_images": len(ranked),
            "unselected_images": len(items) - len(ranked),
            "image_failures": len(failures),
            "pool_classes": len(class_counts),
            "selected_classes": len(queue_class_counts),
        },
        "class_distribution": {
            "pool_candidates": dict(sorted(class_counts.items())),
            "queue_candidates": dict(sorted(queue_class_counts.items())),
        },
        "queue": queue_rows,
        "failures": failures,
    }
    (output_dir / "prioritization_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    generate_report(summary, queue_rows, output_dir / "prioritization_report.html")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidates_csv", type=Path)
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--budget", type=int, default=200)
    parser.add_argument("--modes", nargs="+", default=["review"], choices=["review", "auto"])
    parser.add_argument("--classes", nargs="+", default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--uncertainty-weight", type=float, default=0.45)
    parser.add_argument("--rarity-weight", type=float, default=0.20)
    parser.add_argument("--diversity-weight", type=float, default=0.35)
    parser.add_argument("--redact-paths", action="store_true")
    return parser.parse_args(argv)


def _validate_args(args: argparse.Namespace) -> None:
    if args.budget < 1 or args.workers < 1:
        raise ValueError("--budget and --workers must be >= 1")
    weights = [args.uncertainty_weight, args.rarity_weight, args.diversity_weight]
    if any(weight < 0 for weight in weights) or not math.isclose(sum(weights), 1.0, abs_tol=1e-9):
        raise ValueError("priority weights must be non-negative and sum to 1")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    _validate_args(args)
    summary = run_prioritization(
        args.candidates_csv,
        args.dataset_root,
        args.output_dir,
        budget=args.budget,
        modes=set(args.modes),
        classes=set(args.classes) if args.classes else None,
        workers=args.workers,
        uncertainty_weight=args.uncertainty_weight,
        rarity_weight=args.rarity_weight,
        diversity_weight=args.diversity_weight,
        redact_paths=args.redact_paths,
    )
    totals = summary["totals"]
    print(
        f"candidates={totals['candidate_rows']} images={totals['review_images']} "
        f"selected={totals['selected_images']} classes={totals['selected_classes']}/{totals['pool_classes']}"
    )
    print(args.output_dir.expanduser().resolve() / "prioritization_report.html")


if __name__ == "__main__":
    main()
