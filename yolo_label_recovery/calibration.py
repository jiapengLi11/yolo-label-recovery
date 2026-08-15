"""Calibrate class-specific AUTO and REVIEW thresholds from audited candidate decisions."""

from __future__ import annotations

import argparse
import csv
import html
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist

POSITIVE_VERDICTS = {"1", "accept", "accepted", "positive", "true", "tp", "yes"}
NEGATIVE_VERDICTS = {"0", "false", "fp", "negative", "no", "reject", "rejected"}


@dataclass(frozen=True)
class ReviewedCandidate:
    class_name: str
    confidence: float
    accepted: bool


@dataclass(frozen=True)
class CurvePoint:
    threshold: float
    selected: int
    true_positive: int
    false_positive: int
    precision: float | None
    precision_lower_bound: float | None
    recall: float | None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reviewed_csv", type=Path, help="CSV containing class, confidence and human verdict columns.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--class-column", default="class_name")
    parser.add_argument("--confidence-column", default="conf")
    parser.add_argument("--verdict-column", default="verdict")
    parser.add_argument("--classes", nargs="+", default=None, help="Optional class allowlist.")
    parser.add_argument("--target-auto-precision", type=float, default=0.98)
    parser.add_argument(
        "--auto-confidence-level",
        type=float,
        default=0.95,
        help="Wilson confidence level for AUTO precision. Use 0 to select by empirical precision only.",
    )
    parser.add_argument("--target-review-recall", type=float, default=0.95)
    parser.add_argument("--min-auto-samples", type=int, default=20)
    parser.add_argument("--redact-paths", action="store_true")
    return parser.parse_args(argv)


def _parse_verdict(raw_value: str, row_number: int) -> bool:
    value = raw_value.strip().lower()
    if value in POSITIVE_VERDICTS:
        return True
    if value in NEGATIVE_VERDICTS:
        return False
    raise ValueError(
        f"Row {row_number}: unsupported verdict {raw_value!r}. "
        f"Use one of {sorted(POSITIVE_VERDICTS | NEGATIVE_VERDICTS)}."
    )


def read_reviewed_candidates(
    path: Path,
    *,
    class_column: str = "class_name",
    confidence_column: str = "conf",
    verdict_column: str = "verdict",
    classes: set[str] | None = None,
) -> list[ReviewedCandidate]:
    path = path.expanduser().resolve()
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {class_column, confidence_column, verdict_column}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing required CSV columns: {', '.join(sorted(missing))}")

        candidates = []
        for row_number, row in enumerate(reader, start=2):
            class_name = row[class_column].strip()
            if not class_name:
                raise ValueError(f"Row {row_number}: class name is empty.")
            if classes is not None and class_name not in classes:
                continue
            try:
                confidence = float(row[confidence_column])
            except ValueError as error:
                raise ValueError(f"Row {row_number}: confidence is not numeric.") from error
            if not 0.0 <= confidence <= 1.0:
                raise ValueError(f"Row {row_number}: confidence must be between 0 and 1.")
            candidates.append(
                ReviewedCandidate(
                    class_name=class_name,
                    confidence=confidence,
                    accepted=_parse_verdict(row[verdict_column], row_number),
                )
            )
    if not candidates:
        raise ValueError("No reviewed candidates were found after filtering.")
    return candidates


def wilson_lower_bound(successes: int, total: int, confidence_level: float) -> float | None:
    if total == 0:
        return None
    if confidence_level == 0:
        return successes / total
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("auto_confidence_level must be 0 or in (0, 1).")
    proportion = successes / total
    z = NormalDist().inv_cdf(0.5 + confidence_level / 2.0)
    z_squared = z * z
    denominator = 1.0 + z_squared / total
    center = proportion + z_squared / (2.0 * total)
    margin = z * ((proportion * (1.0 - proportion) + z_squared / (4.0 * total)) / total) ** 0.5
    return (center - margin) / denominator


def build_threshold_curve(
    candidates: list[ReviewedCandidate], *, confidence_level: float = 0.0
) -> list[CurvePoint]:
    positives = sum(candidate.accepted for candidate in candidates)
    ordered = sorted(candidates, key=lambda candidate: candidate.confidence, reverse=True)
    curve = []
    selected = 0
    true_positive = 0
    index = 0
    while index < len(ordered):
        threshold = ordered[index].confidence
        while index < len(ordered) and ordered[index].confidence == threshold:
            selected += 1
            true_positive += int(ordered[index].accepted)
            index += 1
        false_positive = selected - true_positive
        curve.append(
            CurvePoint(
                threshold=threshold,
                selected=selected,
                true_positive=true_positive,
                false_positive=false_positive,
                precision=true_positive / selected,
                precision_lower_bound=wilson_lower_bound(true_positive, selected, confidence_level),
                recall=true_positive / positives if positives else None,
            )
        )
    return list(reversed(curve))


def calibrate_class(
    candidates: list[ReviewedCandidate],
    *,
    target_auto_precision: float,
    auto_confidence_level: float,
    target_review_recall: float,
    min_auto_samples: int,
) -> tuple[dict[str, object], list[CurvePoint]]:
    curve = build_threshold_curve(candidates, confidence_level=auto_confidence_level)
    positives = sum(candidate.accepted for candidate in candidates)
    negatives = len(candidates) - positives

    auto_options = [
        point
        for point in curve
        if point.selected >= min_auto_samples
        and point.precision_lower_bound is not None
        and point.precision_lower_bound >= target_auto_precision
    ]
    auto_point = min(auto_options, key=lambda point: point.threshold, default=None)

    review_ceiling = auto_point.threshold if auto_point is not None else 1.0
    review_options = [
        point
        for point in curve
        if point.threshold <= review_ceiling
        and point.recall is not None
        and point.recall >= target_review_recall
    ]
    review_point = max(review_options, key=lambda point: point.threshold, default=None)

    if positives == 0:
        status = "no_positive_samples"
    elif auto_point is None:
        status = "auto_target_not_met"
    elif review_point is None:
        status = "review_target_not_met"
    else:
        status = "calibrated"

    auto_threshold = auto_point.threshold if auto_point else None
    review_threshold = review_point.threshold if review_point else None
    review_queue = [
        candidate
        for candidate in candidates
        if review_threshold is not None
        and candidate.confidence >= review_threshold
        and (auto_threshold is None or candidate.confidence < auto_threshold)
    ]
    review_accepted = sum(candidate.accepted for candidate in review_queue)

    result: dict[str, object] = {
        "status": status,
        "samples": len(candidates),
        "accepted": positives,
        "rejected": negatives,
        "acceptance_rate": positives / len(candidates),
        "auto_threshold": auto_threshold,
        "auto_precision": auto_point.precision if auto_point else None,
        "auto_precision_lower_bound": auto_point.precision_lower_bound if auto_point else None,
        "auto_recall": auto_point.recall if auto_point else None,
        "auto_samples": auto_point.selected if auto_point else 0,
        "review_threshold": review_threshold,
        "captured_positive_recall": review_point.recall if review_point else None,
        "review_queue_samples": len(review_queue),
        "review_queue_acceptance_rate": review_accepted / len(review_queue) if review_queue else None,
    }
    return result, curve


def calibrate(
    candidates: list[ReviewedCandidate],
    *,
    target_auto_precision: float,
    auto_confidence_level: float,
    target_review_recall: float,
    min_auto_samples: int,
) -> tuple[dict[str, dict[str, object]], dict[str, list[CurvePoint]]]:
    if not 0.0 < target_auto_precision <= 1.0:
        raise ValueError("target_auto_precision must be in (0, 1].")
    if auto_confidence_level != 0 and not 0.0 < auto_confidence_level < 1.0:
        raise ValueError("auto_confidence_level must be 0 or in (0, 1).")
    if not 0.0 < target_review_recall <= 1.0:
        raise ValueError("target_review_recall must be in (0, 1].")
    if min_auto_samples < 1:
        raise ValueError("min_auto_samples must be at least 1.")

    grouped: dict[str, list[ReviewedCandidate]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.class_name, []).append(candidate)

    results = {}
    curves = {}
    for class_name in sorted(grouped):
        result, curve = calibrate_class(
            grouped[class_name],
            target_auto_precision=target_auto_precision,
            auto_confidence_level=auto_confidence_level,
            target_review_recall=target_review_recall,
            min_auto_samples=min_auto_samples,
        )
        results[class_name] = result
        curves[class_name] = curve
    return results, curves


def _fmt(value: object, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _line_chart(class_name: str, curve: list[CurvePoint], target_precision: float, target_recall: float) -> str:
    width, height = 560, 230
    left, top, plot_width, plot_height = 48, 20, 480, 160

    def points(metric: str) -> str:
        values = []
        for point in curve:
            value = getattr(point, metric)
            if value is None:
                continue
            x = left + point.threshold * plot_width
            y = top + (1.0 - value) * plot_height
            values.append(f"{x:.1f},{y:.1f}")
        return " ".join(values)

    target_precision_y = top + (1.0 - target_precision) * plot_height
    target_recall_y = top + (1.0 - target_recall) * plot_height
    return (
        f'<section class="chart"><h3>{html.escape(class_name)}</h3>'
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Threshold calibration curve for '
        f'{html.escape(class_name)}">'
        f'<line x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" y2="{top + plot_height}" class="axis"/>'
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" class="axis"/>'
        f'<line x1="{left}" y1="{target_precision_y:.1f}" x2="{left + plot_width}" y2="{target_precision_y:.1f}" class="target precision-target"/>'
        f'<line x1="{left}" y1="{target_recall_y:.1f}" x2="{left + plot_width}" y2="{target_recall_y:.1f}" class="target recall-target"/>'
        f'<polyline points="{points("precision")}" class="precision"/>'
        f'<polyline points="{points("precision_lower_bound")}" class="precision-lcb"/>'
        f'<polyline points="{points("recall")}" class="recall"/>'
        '<text x="48" y="207">0.0</text><text x="280" y="207">confidence threshold</text>'
        '<text x="517" y="207">1.0</text><text x="8" y="28">1.0</text><text x="8" y="184">0.0</text>'
        '</svg></section>'
    )


def _generate_html(payload: dict[str, object], curves: dict[str, list[CurvePoint]]) -> str:
    policy = payload["policy"]
    assert isinstance(policy, dict)
    class_results = payload["classes"]
    assert isinstance(class_results, dict)

    rows = []
    for class_name, raw_result in class_results.items():
        result = raw_result
        assert isinstance(result, dict)
        rows.append(
            "<tr>"
            f"<td><strong>{html.escape(class_name)}</strong><span class='status {html.escape(str(result['status']))}'>"
            f"{html.escape(str(result['status']))}</span></td>"
            f"<td>{result['samples']}</td><td>{result['accepted']}</td>"
            f"<td>{_fmt(result['auto_threshold'])}</td><td>{_fmt(result['auto_precision'])}</td>"
            f"<td>{_fmt(result['auto_precision_lower_bound'])}</td>"
            f"<td>{_fmt(result['review_threshold'])}</td><td>{_fmt(result['captured_positive_recall'])}</td>"
            f"<td>{result['review_queue_samples']}</td>"
            "</tr>"
        )

    charts = "".join(
        _line_chart(
            class_name,
            curves[class_name],
            float(policy["target_auto_precision"]),
            float(policy["target_review_recall"]),
        )
        for class_name in class_results
    )
    calibrated_count = sum(
        isinstance(result, dict) and result.get("status") == "calibrated" for result in class_results.values()
    )
    total_samples = sum(int(result["samples"]) for result in class_results.values() if isinstance(result, dict))
    confidence_level = float(policy["auto_confidence_level"])
    auto_guardrail = (
        f"AUTO uses a {confidence_level:.0%} Wilson precision lower bound."
        if confidence_level
        else "AUTO uses empirical precision because confidence-bound mode is disabled."
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>YOLO Threshold Calibration</title><style>
:root{{--ink:#102a43;--navy:#0d2e48;--teal:#13a6a1;--orange:#ef9f32;--paper:#f4f8fb;--line:#d7e3ec;--muted:#627d98;--red:#cf3d56}}
*{{box-sizing:border-box}}body{{margin:0;background:linear-gradient(135deg,#e8f2f7,#fff 48%,#edf8f3);color:var(--ink);font:15px/1.55 "Segoe UI",sans-serif}}
main{{max-width:1220px;margin:auto;padding:42px 24px 72px}}header{{padding:38px;border-radius:24px;background:var(--navy);color:white;box-shadow:0 20px 60px #102a4320}}
.eyebrow{{color:#7fddda;letter-spacing:.14em;text-transform:uppercase;font-weight:700}}h1{{font-size:42px;line-height:1.08;margin:10px 0}}header p{{max-width:820px;color:#d6e8f2}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:24px 0}}.card,.panel,.chart{{background:white;border:1px solid var(--line);border-radius:18px;box-shadow:0 12px 32px #102a4310}}
.card{{padding:20px}}.value{{font-size:30px;font-weight:750}}.label,.muted{{color:var(--muted)}}.panel{{padding:24px;margin-top:20px;overflow:auto}}h2{{margin:0 0 16px}}
table{{width:100%;border-collapse:collapse}}th,td{{padding:12px 10px;border-bottom:1px solid var(--line);text-align:right}}th:first-child,td:first-child{{text-align:left}}th{{color:var(--muted);font-size:12px;text-transform:uppercase}}
.status{{display:block;width:max-content;margin-top:4px;padding:2px 7px;border-radius:10px;background:#eef3f7;color:var(--muted);font-size:11px}}.status.calibrated{{background:#dff6ee;color:#13795b}}
.legend{{display:flex;gap:18px;flex-wrap:wrap;margin:12px 0;color:var(--muted)}}.swatch{{display:inline-block;width:22px;height:4px;border-radius:2px;margin-right:6px;vertical-align:middle}}.chart-grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}.chart{{padding:18px}}.chart h3{{margin:0 0 8px}}
svg{{display:block;width:100%}}.axis{{stroke:#9fb3c3;stroke-width:1}}.precision{{fill:none;stroke:var(--teal);stroke-width:4}}.precision-lcb{{fill:none;stroke:var(--navy);stroke-width:2.5;stroke-dasharray:5 4}}.recall{{fill:none;stroke:var(--orange);stroke-width:4}}.target{{stroke-width:1.5;stroke-dasharray:6 5}}.precision-target{{stroke:var(--teal)}}.recall-target{{stroke:var(--orange)}}svg text{{font-size:11px;fill:var(--muted)}}
.notice{{padding:14px 16px;border-left:4px solid var(--orange);background:#fff8e8;border-radius:8px}}code{{background:#edf2f6;padding:2px 6px;border-radius:5px}}@media(max-width:850px){{.cards,.chart-grid{{grid-template-columns:1fr 1fr}}}}@media(max-width:560px){{.cards,.chart-grid{{grid-template-columns:1fr}}h1{{font-size:32px}}}}
</style></head><body><main>
<header><div class="eyebrow">Human-in-the-loop policy calibration</div><h1>Threshold Calibration Report</h1>
<p>Class-specific AUTO thresholds maximize coverage while satisfying a confidence-bound precision target; REVIEW thresholds minimize queue size while preserving positive recall.</p>
<div class="muted">Source: {html.escape(str(payload['source']))}</div></header>
<section class="cards"><div class="card"><div class="value">{total_samples}</div><div class="label">Audited candidates</div></div>
<div class="card"><div class="value">{len(class_results)}</div><div class="label">Classes</div></div>
<div class="card"><div class="value">{float(policy['target_auto_precision']):.0%}</div><div class="label">AUTO precision lower-bound target</div></div>
<div class="card"><div class="value">{calibrated_count}/{len(class_results)}</div><div class="label">Classes calibrated</div></div></section>
<section class="panel"><h2>Recommended policy</h2><table><thead><tr><th>Class / status</th><th>Samples</th><th>Accepted</th><th>AUTO</th><th>Empirical precision</th><th>Precision LCB</th><th>REVIEW</th><th>Captured recall</th><th>Review queue</th></tr></thead><tbody>{''.join(rows)}</tbody></table></section>
<section class="panel"><h2>Precision-recall evidence</h2><div class="legend"><span><i class="swatch" style="background:var(--teal)"></i>Empirical precision</span><span><i class="swatch" style="background:var(--navy)"></i>Wilson precision LCB</span><span><i class="swatch" style="background:var(--orange)"></i>Recall</span><span>Dashed lines = policy targets</span></div><div class="chart-grid">{charts}</div></section>
<section class="panel"><div class="notice"><strong>Guardrail:</strong> {auto_guardrail} These thresholds are still sample-based recommendations, not universal constants. Recalibrate after teacher, camera, domain or label-policy changes.</div></section>
</main></body></html>"""


def write_outputs(
    reviewed_csv: Path,
    output_dir: Path,
    *,
    results: dict[str, dict[str, object]],
    curves: dict[str, list[CurvePoint]],
    target_auto_precision: float,
    auto_confidence_level: float,
    target_review_recall: float,
    min_auto_samples: int,
    redact_paths: bool,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    source = f"<redacted>/{reviewed_csv.name}" if redact_paths else str(reviewed_csv.expanduser().resolve())
    payload: dict[str, object] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "policy": {
            "target_auto_precision": target_auto_precision,
            "auto_confidence_level": auto_confidence_level,
            "target_review_recall": target_review_recall,
            "min_auto_samples": min_auto_samples,
        },
        "classes": results,
        "threshold_overrides": {
            class_name: (
                f"{class_name}:{result['auto_threshold']:.3f}:{result['review_threshold']:.3f}"
                if result["auto_threshold"] is not None and result["review_threshold"] is not None
                else None
            )
            for class_name, result in results.items()
        },
    }

    json_path = output_dir / "calibration.json"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    curve_path = output_dir / "threshold_curve.csv"
    with curve_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "class_name",
                "threshold",
                "selected",
                "true_positive",
                "false_positive",
                "precision",
                "precision_lower_bound",
                "recall",
            ],
        )
        writer.writeheader()
        for class_name, curve in curves.items():
            for point in curve:
                row = asdict(point)
                row["class_name"] = class_name
                writer.writerow(row)

    html_path = output_dir / "calibration.html"
    html_path.write_text(_generate_html(payload, curves), encoding="utf-8")
    return {"json": json_path, "curve": curve_path, "html": html_path}


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    candidates = read_reviewed_candidates(
        args.reviewed_csv,
        class_column=args.class_column,
        confidence_column=args.confidence_column,
        verdict_column=args.verdict_column,
        classes=set(args.classes) if args.classes else None,
    )
    results, curves = calibrate(
        candidates,
        target_auto_precision=args.target_auto_precision,
        auto_confidence_level=args.auto_confidence_level,
        target_review_recall=args.target_review_recall,
        min_auto_samples=args.min_auto_samples,
    )
    paths = write_outputs(
        args.reviewed_csv,
        args.output_dir,
        results=results,
        curves=curves,
        target_auto_precision=args.target_auto_precision,
        auto_confidence_level=args.auto_confidence_level,
        target_review_recall=args.target_review_recall,
        min_auto_samples=args.min_auto_samples,
        redact_paths=args.redact_paths,
    )
    for name, path in paths.items():
        print(f"{name}={path.resolve()}")


if __name__ == "__main__":
    main()
