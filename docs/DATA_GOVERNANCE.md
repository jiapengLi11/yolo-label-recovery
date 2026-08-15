# Data governance and auditability

## Generated metadata is local by default

`manifest.json`, `summary.json`, `dataset_audit.json` and HTML reports may include absolute dataset, model or Python paths. This is useful for internal reproducibility but can reveal usernames or storage layout. Before publishing an artifact, use `--redact-paths` where supported and inspect the final file. The repository's synthetic demo is the only output intended to be public without project-specific review.

## Immutable source

The source dataset is input-only. Apply mode creates a separate `labels_autofill_v1` tree and appends only AUTO candidates there. A failed or low-quality experiment can be discarded without restoring the source labels.

## Candidate audit trail

Every candidate row records the split, image, label path, class, confidence, mode, same-class IoU and normalized box. This allows a reviewer to trace an added label back to the model decision that created it.

## Human review

- `AUTO`: above the class-specific automatic threshold.
- `REVIEW`: between review and automatic thresholds.
- `IGNORE`: below review threshold or already covered by same-class labels.

The output is not a replacement for annotation policy. High-confidence additions should still be sampled, especially for occlusion, small objects, crowded scenes and domain shifts.

## Publication checklist

- Remove all real image and label files.
- Remove all model weights and training outputs.
- Replace absolute paths in examples and reports.
- Keep only synthetic or licensed sample data.
- State that benchmark metrics depend on user-provided data and weights.
