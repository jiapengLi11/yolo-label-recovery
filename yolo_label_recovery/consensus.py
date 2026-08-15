"""Gate primary AUTO candidates with predictions from an independent verifier Teacher."""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_COLUMNS = {"split", "image", "class_name", "conf", "mode", "cx", "cy", "w", "h"}
CONSENSUS_COLUMNS = ["verifier_conf", "agreement_iou", "consensus_score", "consensus_decision"]


@dataclass(frozen=True)
class CandidateRow:
    index: int
    row: dict[str, str]
    split: str
    image: str
    class_name: str
    confidence: float
    mode: str
    box: tuple[float, float, float, float]


@dataclass(frozen=True)
class Agreement:
    verifier_index: int
    verifier_confidence: float
    overlap: float


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("primary_csv", type=Path, help="Primary Teacher candidates_all.csv.")
    parser.add_argument("verifier_csv", type=Path, help="Independent verifier Teacher candidates_all.csv.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--agreement-iou", type=float, default=0.50)
    parser.add_argument("--verifier-min-confidence", type=float, default=0.50)
    parser.add_argument("--classes", nargs="+", default=None, help="Optional class allowlist.")
    parser.add_argument(
        "--label-additions-dir",
        type=Path,
        default=None,
        help="Optional empty directory for agreed AUTO labels in YOLO txt format.",
    )
    parser.add_argument("--redact-paths", action="store_true")
    return parser.parse_args(argv)


def _parse_float(raw: str, name: str, row_number: int, *, unit_interval: bool = True) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as error:
        raise ValueError(f"row {row_number}: {name} must be numeric") from error
    if not math.isfinite(value) or (unit_interval and not 0.0 <= value <= 1.0):
        raise ValueError(f"row {row_number}: {name} must be finite and in [0, 1]")
    return value


def _normalize_image(path: str) -> str:
    return path.strip().replace("\\", "/").casefold()


def read_candidates(path: Path, *, classes: set[str] | None = None) -> tuple[list[CandidateRow], list[str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"{path}: CSV header is missing")
        missing = REQUIRED_COLUMNS - set(reader.fieldnames)
        if missing:
            raise ValueError(f"{path}: missing required columns: {', '.join(sorted(missing))}")

        candidates = []
        for row_number, row in enumerate(reader, start=2):
            class_name = row["class_name"].strip()
            if not class_name:
                raise ValueError(f"row {row_number}: class_name must not be empty")
            if classes is not None and class_name not in classes:
                continue
            if not row["split"].strip() or not row["image"].strip():
                raise ValueError(f"row {row_number}: split and image must not be empty")
            mode = row["mode"].strip().lower()
            if mode not in {"auto", "review"}:
                raise ValueError(f"row {row_number}: mode must be 'auto' or 'review'")
            confidence = _parse_float(row["conf"], "conf", row_number)
            box = tuple(_parse_float(row[name], name, row_number) for name in ("cx", "cy", "w", "h"))
            candidates.append(
                CandidateRow(
                    index=len(candidates),
                    row=dict(row),
                    split=row["split"].strip(),
                    image=_normalize_image(row["image"]),
                    class_name=class_name,
                    confidence=confidence,
                    mode=mode,
                    box=box,
                )
            )
    if not candidates:
        raise ValueError(f"{path}: no candidates found after filtering")
    return candidates, list(reader.fieldnames)


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    acx, acy, aw, ah = a
    bcx, bcy, bw, bh = b
    ax1, ay1, ax2, ay2 = acx - aw / 2, acy - ah / 2, acx + aw / 2, acy + ah / 2
    bx1, by1, bx2, by2 = bcx - bw / 2, bcy - bh / 2, bcx + bw / 2, bcy + bh / 2
    intersection = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(0.0, min(ay2, by2) - max(ay1, by1))
    union = aw * ah + bw * bh - intersection
    return intersection / union if union > 0 else 0.0


def _group_key(candidate: CandidateRow) -> tuple[str, str, str]:
    return candidate.split, candidate.image, candidate.class_name


def match_agreements(
    primary: list[CandidateRow],
    verifier: list[CandidateRow],
    *,
    agreement_iou: float,
    verifier_min_confidence: float,
) -> dict[int, Agreement]:
    primary_groups: dict[tuple[str, str, str], list[CandidateRow]] = defaultdict(list)
    verifier_groups: dict[tuple[str, str, str], list[CandidateRow]] = defaultdict(list)
    for candidate in primary:
        if candidate.mode == "auto":
            primary_groups[_group_key(candidate)].append(candidate)
    for candidate in verifier:
        if candidate.confidence >= verifier_min_confidence:
            verifier_groups[_group_key(candidate)].append(candidate)

    agreements: dict[int, Agreement] = {}
    for key, primary_items in primary_groups.items():
        edges = []
        for primary_candidate in primary_items:
            for verifier_candidate in verifier_groups.get(key, []):
                overlap = _iou(primary_candidate.box, verifier_candidate.box)
                if overlap >= agreement_iou:
                    edges.append(
                        (
                            -overlap,
                            -min(primary_candidate.confidence, verifier_candidate.confidence),
                            primary_candidate.index,
                            verifier_candidate.index,
                            verifier_candidate.confidence,
                        )
                    )
        used_primary: set[int] = set()
        used_verifier: set[int] = set()
        for negative_iou, _, primary_index, verifier_index, verifier_confidence in sorted(edges):
            if primary_index in used_primary or verifier_index in used_verifier:
                continue
            used_primary.add(primary_index)
            used_verifier.add(verifier_index)
            agreements[primary_index] = Agreement(
                verifier_index=verifier_index,
                verifier_confidence=verifier_confidence,
                overlap=-negative_iou,
            )
    return agreements


def build_consensus_rows(
    primary: list[CandidateRow], agreements: dict[int, Agreement]
) -> tuple[list[dict[str, str]], dict[str, dict[str, int]]]:
    rows = []
    stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "primary_candidates": 0,
            "primary_auto": 0,
            "agreed_auto": 0,
            "downgraded_to_review": 0,
            "primary_review": 0,
        }
    )
    for candidate in primary:
        class_stats = stats[candidate.class_name]
        class_stats["primary_candidates"] += 1
        output = dict(candidate.row)
        agreement = agreements.get(candidate.index)
        if candidate.mode == "review":
            decision = "primary_review"
            class_stats["primary_review"] += 1
        elif agreement is not None:
            decision = "agreed_auto"
            class_stats["primary_auto"] += 1
            class_stats["agreed_auto"] += 1
        else:
            decision = "downgraded_to_review"
            output["mode"] = "review"
            class_stats["primary_auto"] += 1
            class_stats["downgraded_to_review"] += 1

        verifier_confidence = agreement.verifier_confidence if agreement else None
        overlap = agreement.overlap if agreement else None
        score = math.sqrt(candidate.confidence * verifier_confidence) if verifier_confidence is not None else None
        output.update(
            {
                "verifier_conf": f"{verifier_confidence:.6f}" if verifier_confidence is not None else "",
                "agreement_iou": f"{overlap:.6f}" if overlap is not None else "",
                "consensus_score": f"{score:.6f}" if score is not None else "",
                "consensus_decision": decision,
            }
        )
        rows.append(output)
    return rows, dict(stats)


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_label_additions(path: Path, rows: list[dict[str, str]]) -> None:
    grouped: dict[Path, list[str]] = defaultdict(list)
    for row_number, row in enumerate(rows, start=2):
        if row["mode"].lower() != "auto":
            continue
        split = row["split"].strip()
        if not split or Path(split).name != split or split in {".", ".."}:
            raise ValueError(f"row {row_number}: split must be a safe directory name")
        label_name = Path(row.get("label", "").replace("\\", "/")).name
        if not label_name:
            image_stem = Path(row["image"].replace("\\", "/")).stem
            label_name = f"{image_stem}.txt"
        if Path(label_name).suffix.lower() != ".txt":
            raise ValueError(f"row {row_number}: label must resolve to a .txt filename")
        try:
            class_id = int(row["class_id"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"row {row_number}: class_id must be an integer") from error
        if class_id < 0:
            raise ValueError(f"row {row_number}: class_id must not be negative")
        line = f"{class_id} " + " ".join(f"{float(row[name]):.6f}" for name in ("cx", "cy", "w", "h"))
        grouped[path / split / label_name].append(line)
    for label_path, lines in grouped.items():
        label_path.parent.mkdir(parents=True, exist_ok=True)
        label_path.write_text("\n".join(dict.fromkeys(lines)) + "\n", encoding="utf-8")


def _generate_html(payload: dict[str, object]) -> str:
    stats = payload["classes"]
    assert isinstance(stats, dict)
    total_primary_auto = sum(int(item["primary_auto"]) for item in stats.values())
    total_agreed = sum(int(item["agreed_auto"]) for item in stats.values())
    total_downgraded = sum(int(item["downgraded_to_review"]) for item in stats.values())
    agreement_rate = total_agreed / total_primary_auto if total_primary_auto else 0.0
    table_rows = []
    bars = []
    for class_name, item in stats.items():
        primary_auto = int(item["primary_auto"])
        agreed = int(item["agreed_auto"])
        rate = agreed / primary_auto if primary_auto else 0.0
        table_rows.append(
            f"<tr><td><strong>{html.escape(class_name)}</strong></td><td>{item['primary_candidates']}</td>"
            f"<td>{primary_auto}</td><td>{agreed}</td><td>{item['downgraded_to_review']}</td>"
            f"<td>{item['primary_review']}</td><td>{rate:.1%}</td></tr>"
        )
        bars.append(
            f"<div class='bar-row'><span>{html.escape(class_name)}</span><div class='track'>"
            f"<i style='width:{rate * 100:.1f}%'></i></div><b>{rate:.1%}</b></div>"
        )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cross-Teacher Consensus Report</title><style>
:root{{--ink:#102a43;--navy:#0d2e48;--teal:#13a6a1;--orange:#ef9f32;--paper:#f4f8fb;--line:#d7e3ec;--muted:#627d98}}
*{{box-sizing:border-box}}body{{margin:0;background:linear-gradient(135deg,#e8f2f7,#fff 48%,#edf8f3);color:var(--ink);font:15px/1.55 "Segoe UI",sans-serif}}
main{{max-width:1180px;margin:auto;padding:42px 24px 72px}}header{{padding:38px;border-radius:24px;background:var(--navy);color:white;box-shadow:0 20px 60px #102a4320}}
.eyebrow{{color:#7fddda;letter-spacing:.14em;text-transform:uppercase;font-weight:700}}h1{{font-size:42px;line-height:1.08;margin:10px 0}}header p{{max-width:820px;color:#d6e8f2}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:24px 0}}.card,.panel{{background:white;border:1px solid var(--line);border-radius:18px;box-shadow:0 12px 32px #102a4310}}
.card{{padding:20px}}.value{{font-size:30px;font-weight:750}}.label,.muted{{color:var(--muted)}}.panel{{padding:24px;margin-top:20px;overflow:auto}}h2{{margin:0 0 16px}}
table{{width:100%;border-collapse:collapse}}th,td{{padding:12px 10px;border-bottom:1px solid var(--line);text-align:right}}th:first-child,td:first-child{{text-align:left}}th{{color:var(--muted);font-size:12px;text-transform:uppercase}}
.bar-row{{display:grid;grid-template-columns:110px 1fr 70px;gap:14px;align-items:center;margin:13px 0}}.track{{height:13px;background:#e7eef3;border-radius:10px;overflow:hidden}}.track i{{display:block;height:100%;background:linear-gradient(90deg,var(--teal),#67c7a5);border-radius:10px}}
.notice{{padding:14px 16px;border-left:4px solid var(--orange);background:#fff8e8;border-radius:8px}}@media(max-width:700px){{.cards{{grid-template-columns:1fr 1fr}}}}@media(max-width:480px){{.cards{{grid-template-columns:1fr}}h1{{font-size:32px}}}}
</style></head><body><main><header><div class="eyebrow">Independent model verification</div><h1>Cross-Teacher Consensus</h1>
<p>Primary AUTO candidates require spatial agreement from an independent verifier. Unsupported AUTO candidates are downgraded to REVIEW rather than silently discarded.</p>
<div class="muted">Primary: {html.escape(str(payload['primary_source']))}<br>Verifier: {html.escape(str(payload['verifier_source']))}</div></header>
<section class="cards"><div class="card"><div class="value">{total_primary_auto}</div><div class="label">Primary AUTO</div></div>
<div class="card"><div class="value">{total_agreed}</div><div class="label">Consensus AUTO</div></div>
<div class="card"><div class="value">{total_downgraded}</div><div class="label">Downgraded to REVIEW</div></div>
<div class="card"><div class="value">{agreement_rate:.1%}</div><div class="label">Agreement rate</div></div></section>
<section class="panel"><h2>Class-level decisions</h2><table><thead><tr><th>Class</th><th>Primary candidates</th><th>Primary AUTO</th><th>Agreed AUTO</th><th>Downgraded</th><th>Original REVIEW</th><th>Agreement</th></tr></thead><tbody>{''.join(table_rows)}</tbody></table></section>
<section class="panel"><h2>AUTO agreement by class</h2>{''.join(bars)}</section>
<section class="panel"><div class="notice"><strong>Guardrail:</strong> agreement is additional evidence, not ground truth. Use independent model families or training seeds and audit consensus errors on the target domain.</div></section>
</main></body></html>"""


def run_consensus(
    primary_csv: Path,
    verifier_csv: Path,
    output_dir: Path,
    *,
    agreement_iou: float,
    verifier_min_confidence: float,
    classes: set[str] | None,
    redact_paths: bool,
    label_additions_dir: Path | None = None,
) -> dict[str, Path]:
    if not 0.0 <= agreement_iou <= 1.0:
        raise ValueError("agreement_iou must be in [0, 1]")
    if not 0.0 <= verifier_min_confidence <= 1.0:
        raise ValueError("verifier_min_confidence must be in [0, 1]")
    if label_additions_dir is not None:
        if label_additions_dir.resolve() == output_dir.resolve():
            raise ValueError("label additions directory must differ from output_dir")
        if label_additions_dir.exists() and any(label_additions_dir.rglob("*")):
            raise ValueError(f"label additions directory must be empty: {label_additions_dir}")
    primary, fieldnames = read_candidates(primary_csv, classes=classes)
    verifier, _ = read_candidates(verifier_csv, classes=classes)
    agreements = match_agreements(
        primary,
        verifier,
        agreement_iou=agreement_iou,
        verifier_min_confidence=verifier_min_confidence,
    )
    rows, stats = build_consensus_rows(primary, agreements)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_fields = [*fieldnames, *(name for name in CONSENSUS_COLUMNS if name not in fieldnames)]
    paths = {
        "all": output_dir / "consensus_all.csv",
        "auto": output_dir / "consensus_auto.csv",
        "review": output_dir / "consensus_review.csv",
        "json": output_dir / "consensus.json",
        "html": output_dir / "consensus.html",
    }
    _write_csv(paths["all"], output_fields, rows)
    auto_rows = [row for row in rows if row["mode"].lower() == "auto"]
    _write_csv(paths["auto"], output_fields, auto_rows)
    _write_csv(paths["review"], output_fields, [row for row in rows if row["mode"].lower() == "review"])
    if label_additions_dir is not None:
        _write_label_additions(label_additions_dir, auto_rows)
        paths["label_additions"] = label_additions_dir
    payload: dict[str, object] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "primary_source": f"<redacted>/{primary_csv.name}" if redact_paths else str(primary_csv.resolve()),
        "verifier_source": f"<redacted>/{verifier_csv.name}" if redact_paths else str(verifier_csv.resolve()),
        "policy": {
            "agreement_iou": agreement_iou,
            "verifier_min_confidence": verifier_min_confidence,
            "unmatched_auto_action": "downgrade_to_review",
            "one_to_one_matching": True,
        },
        "classes": dict(sorted(stats.items())),
        "totals": {
            "primary_candidates": len(primary),
            "primary_auto": sum(item["primary_auto"] for item in stats.values()),
            "agreed_auto": sum(item["agreed_auto"] for item in stats.values()),
            "downgraded_to_review": sum(item["downgraded_to_review"] for item in stats.values()),
            "primary_review": sum(item["primary_review"] for item in stats.values()),
        },
    }
    paths["json"].write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    paths["html"].write_text(_generate_html(payload), encoding="utf-8")
    return paths


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    paths = run_consensus(
        args.primary_csv,
        args.verifier_csv,
        args.output_dir,
        agreement_iou=args.agreement_iou,
        verifier_min_confidence=args.verifier_min_confidence,
        classes=set(args.classes) if args.classes else None,
        redact_paths=args.redact_paths,
        label_additions_dir=args.label_additions_dir,
    )
    for name, path in paths.items():
        print(f"{name}={path.resolve()}")


if __name__ == "__main__":
    main()
