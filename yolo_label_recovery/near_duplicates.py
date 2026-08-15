"""Cluster perceptually similar images without changing the source dataset."""

from __future__ import annotations

import argparse
import csv
import html
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageOps, ImageStat

from .domain import IMAGE_EXTS

MEMBER_COLUMNS = [
    "cluster_id",
    "cluster_size",
    "cross_split",
    "split",
    "path",
    "is_representative",
    "dhash",
    "ahash",
    "dhash_distance_to_representative",
    "width",
    "height",
    "aspect_ratio",
    "mean_luma",
    "luma_stddev",
]
REPRESENTATIVE_COLUMNS = [
    "cluster_id",
    "cluster_size",
    "cross_split",
    "splits",
    "representative_split",
    "representative_path",
    "max_dhash_distance_to_representative",
]


@dataclass(frozen=True)
class ImageFingerprint:
    """Compact visual fingerprint and matching guardrails for one image."""

    split: str
    path: str
    dhash: int
    ahash: int
    width: int
    height: int
    mean_luma: float
    luma_stddev: float

    @property
    def aspect_ratio(self) -> float:
        return self.width / self.height


@dataclass
class _BKNode:
    value: int
    indexes: list[int]
    children: dict[int, _BKNode]


class BKTree:
    """BK-tree specialized for 64-bit perceptual hashes."""

    def __init__(self) -> None:
        self.root: _BKNode | None = None

    def add(self, value: int, index: int) -> None:
        if self.root is None:
            self.root = _BKNode(value, [index], {})
            return
        node = self.root
        while True:
            distance = hamming_distance(value, node.value)
            if distance == 0:
                node.indexes.append(index)
                return
            child = node.children.get(distance)
            if child is None:
                node.children[distance] = _BKNode(value, [index], {})
                return
            node = child

    def search(self, value: int, radius: int) -> list[tuple[int, _BKNode]]:
        if self.root is None:
            return []
        matches: list[tuple[int, _BKNode]] = []
        pending = [self.root]
        while pending:
            node = pending.pop()
            distance = hamming_distance(value, node.value)
            if distance <= radius:
                matches.append((distance, node))
            low, high = distance - radius, distance + radius
            pending.extend(child for edge, child in node.children.items() if low <= edge <= high)
        return matches


class DisjointSet:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))
        self.rank = [0] * size

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root == right_root:
            return
        if self.rank[left_root] < self.rank[right_root]:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        if self.rank[left_root] == self.rank[right_root]:
            self.rank[left_root] += 1


def hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def _bits_to_int(bits: list[bool]) -> int:
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def fingerprint_image(path: Path, split: str, relative_path: str) -> ImageFingerprint:
    """Decode one image and compute dHash, aHash and low-texture safeguards."""
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        width, height = image.size
        if width <= 0 or height <= 0:
            raise ValueError("image dimensions must be positive")
        grayscale = image.convert("L")
        dhash_pixels = list(grayscale.resize((9, 8), Image.Resampling.LANCZOS).getdata())
        dhash = _bits_to_int(
            [dhash_pixels[row * 9 + column] < dhash_pixels[row * 9 + column + 1] for row in range(8) for column in range(8)]
        )
        ahash_pixels = list(grayscale.resize((8, 8), Image.Resampling.LANCZOS).getdata())
        ahash_mean = sum(ahash_pixels) / len(ahash_pixels)
        ahash = _bits_to_int([value >= ahash_mean for value in ahash_pixels])
        stats = ImageStat.Stat(grayscale.resize((64, 64), Image.Resampling.BILINEAR))
        return ImageFingerprint(
            split=split,
            path=relative_path,
            dhash=dhash,
            ahash=ahash,
            width=width,
            height=height,
            mean_luma=stats.mean[0],
            luma_stddev=stats.stddev[0],
        )


def _is_match(
    left: ImageFingerprint,
    right: ImageFingerprint,
    *,
    max_dhash_distance: int,
    max_ahash_distance: int,
    max_aspect_delta: float,
    low_texture_stddev: float,
    low_texture_mean_delta: float,
) -> bool:
    if hamming_distance(left.dhash, right.dhash) > max_dhash_distance:
        return False
    if hamming_distance(left.ahash, right.ahash) > max_ahash_distance:
        return False
    aspect_delta = abs(left.aspect_ratio - right.aspect_ratio) / max(left.aspect_ratio, right.aspect_ratio)
    if aspect_delta > max_aspect_delta:
        return False
    left_low_texture = left.luma_stddev < low_texture_stddev
    right_low_texture = right.luma_stddev < low_texture_stddev
    if left_low_texture or right_low_texture:
        return left_low_texture and right_low_texture and abs(left.mean_luma - right.mean_luma) <= low_texture_mean_delta
    return True


def cluster_fingerprints(
    fingerprints: list[ImageFingerprint],
    *,
    max_dhash_distance: int = 6,
    max_ahash_distance: int = 10,
    max_aspect_delta: float = 0.05,
    low_texture_stddev: float = 8.0,
    low_texture_mean_delta: float = 12.0,
    min_cluster_size: int = 2,
) -> tuple[list[dict], int]:
    """Generate deterministic connected components from perceptual-neighbor edges."""
    tree = BKTree()
    components = DisjointSet(len(fingerprints))
    candidate_edges = 0
    for index, fingerprint in enumerate(fingerprints):
        for _, node in tree.search(fingerprint.dhash, max_dhash_distance):
            for candidate_index in node.indexes:
                candidate_edges += 1
                if _is_match(
                    fingerprint,
                    fingerprints[candidate_index],
                    max_dhash_distance=max_dhash_distance,
                    max_ahash_distance=max_ahash_distance,
                    max_aspect_delta=max_aspect_delta,
                    low_texture_stddev=low_texture_stddev,
                    low_texture_mean_delta=low_texture_mean_delta,
                ):
                    components.union(index, candidate_index)
                    break
        tree.add(fingerprint.dhash, index)

    grouped: dict[int, list[int]] = {}
    for index in range(len(fingerprints)):
        grouped.setdefault(components.find(index), []).append(index)

    groups: list[dict] = []
    retained = [indexes for indexes in grouped.values() if len(indexes) >= min_cluster_size]
    retained.sort(key=lambda indexes: fingerprints[min(indexes, key=lambda item: fingerprints[item].path)].path)
    for cluster_number, indexes in enumerate(retained, 1):
        representative_index = max(indexes, key=lambda item: (fingerprints[item].width * fingerprints[item].height, fingerprints[item].path))
        representative = fingerprints[representative_index]
        members = sorted((fingerprints[index] for index in indexes), key=lambda item: (item.split, item.path))
        distances = [hamming_distance(member.dhash, representative.dhash) for member in members]
        splits = sorted({member.split for member in members})
        groups.append(
            {
                "cluster_id": f"ND-{cluster_number:05d}",
                "size": len(members),
                "representative": representative,
                "members": members,
                "splits": splits,
                "cross_split": len(splits) > 1,
                "max_dhash_distance_to_representative": max(distances),
            }
        )
    return groups, candidate_edges


def _discover_images(dataset_root: Path, splits: list[str]) -> list[tuple[Path, str, str]]:
    discovered = []
    for split in dict.fromkeys(splits):
        image_root = dataset_root / "images" / split
        if not image_root.is_dir():
            continue
        for path in sorted(item for item in image_root.rglob("*") if item.is_file() and item.suffix.lower() in IMAGE_EXTS):
            discovered.append((path, split, path.relative_to(dataset_root).as_posix()))
    return discovered


def _fingerprint_task(item: tuple[Path, str, str]) -> tuple[ImageFingerprint | None, dict | None]:
    path, split, relative_path = item
    try:
        return fingerprint_image(path, split, relative_path), None
    except Exception as error:  # Pillow exposes format-specific exceptions.
        return None, {"split": split, "path": relative_path, "error": str(error)[:300]}


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _hex_hash(value: int) -> str:
    return f"{value:016x}"


def _member_rows(groups: list[dict]) -> list[dict]:
    rows = []
    for group in groups:
        representative = group["representative"]
        for member in group["members"]:
            rows.append(
                {
                    "cluster_id": group["cluster_id"],
                    "cluster_size": group["size"],
                    "cross_split": str(group["cross_split"]).lower(),
                    "split": member.split,
                    "path": member.path,
                    "is_representative": str(member.path == representative.path).lower(),
                    "dhash": _hex_hash(member.dhash),
                    "ahash": _hex_hash(member.ahash),
                    "dhash_distance_to_representative": hamming_distance(member.dhash, representative.dhash),
                    "width": member.width,
                    "height": member.height,
                    "aspect_ratio": f"{member.aspect_ratio:.6f}",
                    "mean_luma": f"{member.mean_luma:.3f}",
                    "luma_stddev": f"{member.luma_stddev:.3f}",
                }
            )
    return rows


def _representative_rows(groups: list[dict]) -> list[dict]:
    return [
        {
            "cluster_id": group["cluster_id"],
            "cluster_size": group["size"],
            "cross_split": str(group["cross_split"]).lower(),
            "splits": ",".join(group["splits"]),
            "representative_split": group["representative"].split,
            "representative_path": group["representative"].path,
            "max_dhash_distance_to_representative": group["max_dhash_distance_to_representative"],
        }
        for group in groups
    ]


def generate_report(summary: dict, groups: list[dict], output: Path) -> Path:
    """Create a path-safe, self-contained report for review planning."""
    cluster_rows = "".join(
        "<tr>"
        f"<td><strong>{html.escape(group['cluster_id'])}</strong></td>"
        f"<td>{group['size']}</td>"
        f"<td><span class={'leak' if group['cross_split'] else 'safe'}>{'CROSS-SPLIT' if group['cross_split'] else 'within split'}</span></td>"
        f"<td>{html.escape(', '.join(group['splits']))}</td>"
        f"<td><code>{html.escape(group['representative'].path)}</code></td>"
        f"<td>{group['max_dhash_distance_to_representative']}</td>"
        "</tr>"
        for group in groups[:500]
    ) or '<tr><td colspan="6" class="empty">No clusters met the configured threshold.</td></tr>'
    distribution = Counter(group["size"] for group in groups)
    largest_count = max(distribution.values(), default=1)
    bars = "".join(
        f'<div class="bar-row"><span>{size} images</span><div><i style="width:{count / largest_count * 100:.1f}%"></i></div><b>{count}</b></div>'
        for size, count in sorted(distribution.items())
    ) or '<p class="empty">No cluster-size distribution available.</p>'
    cards = [
        ("Images scanned", summary["totals"]["images_discovered"]),
        ("Near-duplicate groups", summary["totals"]["clusters"]),
        ("Grouped images", summary["totals"]["clustered_images"]),
        ("Cross-split groups", summary["totals"]["cross_split_clusters"]),
    ]
    card_html = "".join(f"<article><span>{html.escape(label)}</span><strong>{value}</strong></article>" for label, value in cards)
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Near-duplicate image audit</title><style>
:root{{--ink:#132a33;--muted:#60747b;--paper:#f2f5ef;--panel:#fff;--teal:#087f75;--lime:#b7db55;--red:#bd3c32;--line:#dce4de}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 90% 0,#d9ead8 0,transparent 32%),var(--paper);color:var(--ink);font:15px/1.55 "Segoe UI",sans-serif}}
header{{padding:56px max(5vw,28px) 70px;background:linear-gradient(120deg,#102f37,#0b5b58);color:white}}header p{{max-width:850px;color:#d6e8e5}}header code{{word-break:break-all}}
main{{max-width:1180px;margin:-34px auto 64px;padding:0 24px}}.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}}article,section{{background:var(--panel);border:1px solid #e5ebe6;box-shadow:0 12px 32px #16383212}}
article{{padding:22px;border-radius:14px}}article span{{display:block;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em}}article strong{{font-size:28px}}section{{margin-top:20px;padding:25px;border-radius:14px;overflow-x:auto}}
table{{width:100%;border-collapse:collapse}}th,td{{padding:11px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.06em}}code{{font-family:"Cascadia Code",monospace;font-size:12px}}
.leak,.safe{{display:inline-block;padding:3px 8px;border-radius:999px;font-size:11px;font-weight:700}}.leak{{background:#ffe1dd;color:var(--red)}}.safe{{background:#dff2e7;color:#19704e}}
.bar-row{{display:grid;grid-template-columns:90px 1fr 50px;align-items:center;gap:12px;margin:10px 0}}.bar-row div{{height:12px;background:#edf1ed;border-radius:8px;overflow:hidden}}.bar-row i{{display:block;height:100%;background:linear-gradient(90deg,var(--teal),var(--lime));border-radius:8px}}.empty{{color:var(--muted)}}
@media(max-width:800px){{.cards{{grid-template-columns:1fr 1fr}}header{{padding-top:38px}}}}@media(max-width:480px){{.cards{{grid-template-columns:1fr}}}}
</style></head><body><header><h1>Perceptual near-duplicate audit</h1><p>Read-only grouping for review compression and split-leakage discovery. dHash candidates are filtered by aHash, aspect ratio and low-texture luminance safeguards.</p><code>{html.escape(summary['dataset_root'])}</code></header><main>
<div class="cards">{card_html}</div>
<section><h2>Review compression</h2><p>Review one high-resolution representative first, then expand only ambiguous groups. A group is evidence of visual similarity, not permission to delete data automatically.</p><div>{bars}</div></section>
<section><h2>Cluster index</h2><p>Showing {min(len(groups), 500)} of {len(groups)} groups. Connected components may contain transitive chains; inspect the reported representative distance for loose groups.</p><table><thead><tr><th>Group</th><th>Size</th><th>Leakage</th><th>Splits</th><th>Representative</th><th>Max dHash Δ</th></tr></thead><tbody>{cluster_rows}</tbody></table></section>
<section><h2>Policy</h2><p>dHash radius <strong>{summary['policy']['max_dhash_distance']}</strong>; aHash radius <strong>{summary['policy']['max_ahash_distance']}</strong>; aspect-ratio delta <strong>{summary['policy']['max_aspect_delta']:.1%}</strong>. Fingerprint failures: <strong>{summary['totals']['fingerprint_failures']}</strong>. Candidate hash comparisons: <strong>{summary['totals']['candidate_hash_comparisons']}</strong>.</p></section>
</main></body></html>"""
    output.write_text(document, encoding="utf-8")
    return output


def run_clustering(
    dataset_root: Path,
    output_dir: Path,
    *,
    splits: list[str],
    workers: int = 4,
    max_dhash_distance: int = 6,
    max_ahash_distance: int = 10,
    max_aspect_delta: float = 0.05,
    low_texture_stddev: float = 8.0,
    low_texture_mean_delta: float = 12.0,
    min_cluster_size: int = 2,
    redact_paths: bool = False,
) -> dict:
    dataset_root = dataset_root.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if output_dir == dataset_root or output_dir.is_relative_to(dataset_root):
        raise ValueError("--output-dir must be outside the source dataset so the read-only boundary stays explicit")
    discovered = _discover_images(dataset_root, splits)
    if not discovered:
        raise ValueError(f"no images found below {dataset_root / 'images'} for splits: {', '.join(splits)}")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(_fingerprint_task, discovered))
    fingerprints = sorted((item for item, error in results if item is not None), key=lambda item: (item.split, item.path))
    failures = [error for item, error in results if error is not None]
    groups, candidate_edges = cluster_fingerprints(
        fingerprints,
        max_dhash_distance=max_dhash_distance,
        max_ahash_distance=max_ahash_distance,
        max_aspect_delta=max_aspect_delta,
        low_texture_stddev=low_texture_stddev,
        low_texture_mean_delta=low_texture_mean_delta,
        min_cluster_size=min_cluster_size,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    members = _member_rows(groups)
    representatives = _representative_rows(groups)
    _write_csv(output_dir / "near_duplicate_members.csv", MEMBER_COLUMNS, members)
    _write_csv(
        output_dir / "review_representatives.csv",
        REPRESENTATIVE_COLUMNS,
        representatives,
    )
    _write_csv(output_dir / "fingerprint_failures.csv", ["split", "path", "error"], failures)
    summary = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_root": f"<redacted>/{dataset_root.name}" if redact_paths else str(dataset_root),
        "splits": list(dict.fromkeys(splits)),
        "policy": {
            "max_dhash_distance": max_dhash_distance,
            "max_ahash_distance": max_ahash_distance,
            "max_aspect_delta": max_aspect_delta,
            "low_texture_stddev": low_texture_stddev,
            "low_texture_mean_delta": low_texture_mean_delta,
            "min_cluster_size": min_cluster_size,
            "clustering": "BK-tree candidate search plus connected components",
        },
        "totals": {
            "images_discovered": len(discovered),
            "images_fingerprinted": len(fingerprints),
            "fingerprint_failures": len(failures),
            "candidate_hash_comparisons": candidate_edges,
            "clusters": len(groups),
            "clustered_images": len(members),
            "review_representatives": len(representatives),
            "review_rows_avoided": max(0, len(members) - len(representatives)),
            "cross_split_clusters": sum(group["cross_split"] for group in groups),
            "cross_split_images": sum(group["size"] for group in groups if group["cross_split"]),
            "largest_cluster": max((group["size"] for group in groups), default=0),
        },
        "clusters": [
            {
                **{key: value for key, value in group.items() if key not in {"representative", "members"}},
                "representative": asdict(group["representative"]) | {"dhash": _hex_hash(group["representative"].dhash), "ahash": _hex_hash(group["representative"].ahash)},
                "member_paths": [member.path for member in group["members"]],
            }
            for group in groups
        ],
        "failures": failures,
    }
    summary_path = output_dir / "near_duplicate_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    generate_report(summary, groups, output_dir / "near_duplicate_report.html")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_root", type=Path, help="YOLO dataset root containing images/<split> directories.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--splits", nargs="+", default=["train", "val", "test"])
    parser.add_argument("--workers", type=int, default=4, help="Parallel image-decoding workers; fingerprints remain bounded.")
    parser.add_argument("--max-distance", type=int, default=6, help="Maximum 64-bit dHash Hamming distance.")
    parser.add_argument("--max-ahash-distance", type=int, default=10)
    parser.add_argument("--max-aspect-delta", type=float, default=0.05)
    parser.add_argument("--low-texture-stddev", type=float, default=8.0)
    parser.add_argument("--low-texture-mean-delta", type=float, default=12.0)
    parser.add_argument("--min-cluster-size", type=int, default=2)
    parser.add_argument("--redact-paths", action="store_true")
    parser.add_argument("--fail-on-cross-split", action="store_true")
    return parser.parse_args(argv)


def _validate_args(args: argparse.Namespace) -> None:
    if args.workers < 1:
        raise ValueError("--workers must be >= 1")
    if not 0 <= args.max_distance <= 64 or not 0 <= args.max_ahash_distance <= 64:
        raise ValueError("hash distances must be in [0, 64]")
    if not 0 <= args.max_aspect_delta <= 1:
        raise ValueError("--max-aspect-delta must be in [0, 1]")
    if args.low_texture_stddev < 0 or args.low_texture_mean_delta < 0:
        raise ValueError("low-texture thresholds must be >= 0")
    if args.min_cluster_size < 2:
        raise ValueError("--min-cluster-size must be >= 2")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    _validate_args(args)
    summary = run_clustering(
        args.dataset_root,
        args.output_dir,
        splits=args.splits,
        workers=args.workers,
        max_dhash_distance=args.max_distance,
        max_ahash_distance=args.max_ahash_distance,
        max_aspect_delta=args.max_aspect_delta,
        low_texture_stddev=args.low_texture_stddev,
        low_texture_mean_delta=args.low_texture_mean_delta,
        min_cluster_size=args.min_cluster_size,
        redact_paths=args.redact_paths,
    )
    totals = summary["totals"]
    print(
        f"images={totals['images_fingerprinted']} clusters={totals['clusters']} "
        f"grouped={totals['clustered_images']} cross_split={totals['cross_split_clusters']}"
    )
    print(args.output_dir.expanduser().resolve() / "near_duplicate_report.html")
    if args.fail_on_cross_split and totals["cross_split_clusters"]:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
