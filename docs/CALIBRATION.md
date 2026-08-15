# Threshold calibration

[English](CALIBRATION.md) | [简体中文](CALIBRATION.zh-CN.md)

The `calibrate` command turns a human-reviewed candidate sample into an explicit, class-specific AUTO/REVIEW policy. It answers the question that a hard-coded confidence threshold cannot: how much audited evidence supports automatic label insertion?

## Input contract

The default CSV columns are:

| Column | Meaning |
|---|---|
| `class_name` | Dataset class name |
| `conf` | Teacher confidence in `[0, 1]` |
| `verdict` | Human decision such as `accept` or `reject` |

Column names are configurable. Accepted verdict aliases include `accept`, `true`, `yes`, `tp` and `1`; rejected aliases include `reject`, `false`, `no`, `fp` and `0`.

The reviewed sample should come from the target camera/domain and must not be reused as a claimed independent test set.

## Selection policy

For every class, candidates are sorted by confidence once. Cumulative true/false positives produce all threshold points in `O(N log N)` time.

For threshold `t`:

```text
precision(t) = accepted candidates with confidence >= t / all candidates with confidence >= t
recall(t)    = accepted candidates with confidence >= t / all accepted candidates
```

For AUTO, the tool also computes the Wilson score lower confidence bound for the observed precision. Unlike raw empirical precision, this bound penalizes small samples. For example, `10/10` accepted candidates have empirical precision `100%`, but their lower bound is only about `72.25%` at `95%` confidence; `100/100` raises it to about `96.30%`.

The AUTO threshold is the lowest threshold that satisfies both:

- the Wilson precision lower bound is at least `--target-auto-precision` at `--auto-confidence-level`;
- the AUTO region contains at least `--min-auto-samples` audited candidates.

Choosing the lowest qualifying threshold maximizes automatic coverage under the precision constraint.

The REVIEW threshold is the highest threshold at or below AUTO that retains at least `--target-review-recall` of accepted candidates. Choosing the highest qualifying threshold minimizes human review workload under the recall constraint.

If a target cannot be supported, the result is `auto_target_not_met`, `review_target_not_met` or `no_positive_samples`. The tool deliberately returns no unsafe fallback threshold.

## Example

```powershell
python examples\create_calibration_fixture.py

yolo-label-recovery calibrate `
  examples\calibration\reviewed_candidates.csv `
  --output-dir examples\calibration\output `
  --target-auto-precision 0.95 `
  --auto-confidence-level 0.95 `
  --target-review-recall 0.90 `
  --min-auto-samples 20 `
  --redact-paths
```

Outputs:

- `calibration.json`: policy, class results and ready-to-use threshold override strings;
- `threshold_curve.csv`: every class/threshold empirical precision, Wilson lower bound and recall point;
- `calibration.html`: self-contained visual evidence report.

## Interpretation guardrails

- Confidence is teacher- and domain-specific; recalibrate after model, camera, lighting or label-policy changes.
- Wilson bounds reduce small-sample overconfidence but do not correct biased or unrepresentative review samples.
- Set `--auto-confidence-level 0` only when reproducing the legacy empirical-precision policy.
- Sample all operating conditions rather than reviewing only easy or high-confidence images.
- Keep calibration data separate from final model evaluation data.
- A high-confidence Teacher prediction remains evidence, not ground truth.

## Interview explanation

The design separates model scoring from business risk. AUTO is confidence-bound precision-constrained because a false automatic label silently corrupts training data. REVIEW is recall-constrained because its cost is human time, not silent label corruption. Per-class policies are necessary because small targets such as smoking and slipper are calibrated differently from large targets such as tractor.
