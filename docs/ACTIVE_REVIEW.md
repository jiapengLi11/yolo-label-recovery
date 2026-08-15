# Active review prioritization

[English](ACTIVE_REVIEW.md) | [简体中文](ACTIVE_REVIEW.zh-CN.md)

The `prioritize` command converts a large candidate CSV into a deterministic, image-level human-review queue. It balances three signals instead of sorting by confidence alone:

- **Uncertainty:** normalized Bernoulli entropy of detector confidence, highest near `0.5`.
- **Rarity:** inverse square-root class frequency, dynamically decayed as that class receives review slots.
- **Visual diversity:** greedy minimum dHash/aHash distance from the already selected images.

The command is CPU-only and read-only. It never changes source candidates, images or labels.

## Usage

```powershell
yolo-label-recovery prioritize D:\runs\candidates_review.csv D:\data\mining-safety `
  --output-dir D:\runs\priority-review `
  --budget 500 `
  --workers 4 `
  --uncertainty-weight 0.45 `
  --rarity-weight 0.20 `
  --diversity-weight 0.35 `
  --redact-paths
```

The weights must be non-negative and sum to `1`. REVIEW is the only default mode; add `--modes review auto` only when AUTO spot checks intentionally share the same queue.

## Image-level acquisition

Human review normally opens an image, not an isolated prediction row. The command therefore groups every filtered candidate with the same `split + image`, keeps all associated classes/boxes together and computes image-level uncertainty and rarity. Candidate paths may be absolute, dataset-relative or split-relative, but they must resolve inside the dataset root.

For every queue position, the acquisition function is:

```text
priority = 0.45 * uncertainty
         + 0.20 * dynamic_class_rarity
         + 0.35 * min_visual_distance_to_selected_set
```

After an image is selected, class coverage counts and every remaining image's minimum visual distance are updated. This greedy process is deterministic and requires approximately `O(N * B)` compact-hash comparisons for `N` review images and budget `B`; full-resolution pixels are not retained in memory.

## Outputs

| File | Purpose |
|---|---|
| `review_queue.csv` | One ranked row per selected image with score components |
| `review_queue_candidates.csv` | Original candidate rows for selected images with priority rank |
| `review_pool.csv` | All readable review images and selected status |
| `image_failures.csv` | Missing, escaping or corrupt image evidence |
| `prioritization_summary.json` | Policy, totals, distributions and queue data |
| `prioritization_report.html` | Self-contained report for delivery and portfolio use |

## Statistical boundary

This queue is intentionally biased toward uncertain, rare and diverse examples. It improves issue discovery per reviewer-hour, but **must not** be used to estimate unbiased precision, recall or defect prevalence. Use a separate random or stratified-random audit sample for metrics; use this active queue for remediation.

Detector confidence is also not a calibrated probability by default. Entropy is an acquisition heuristic here, not proof that a prediction is incorrect. Calibration and human verdicts remain separate stages.

## Public fixture

```powershell
python examples\create_prioritization_fixture.py --output-dir .priority-fixture
yolo-label-recovery prioritize .priority-fixture\candidates_review.csv .priority-fixture\dataset `
  --output-dir .priority-output `
  --budget 12 `
  --redact-paths
```

The fixture contains `36` review images with intentionally imbalanced classes. The queue selects `12`, covers all `6` classes, and gives each class one position within the first six selections before assigning additional slots.
