# Contributing

Thanks for helping improve the project.

## Development rules

- Never commit real images, labels, model weights, credentials or absolute local paths.
- Keep source labels read-only and write experiment results below a separate output directory.
- Add or update a test when changing IoU, class mapping, thresholding, candidate deduplication or label writing.
- Prefer small, reviewable changes over a complete rewrite of the workflow.
- Keep generated files out of the repository.

## Local checks

```powershell
python -m py_compile autolabel_with_single_class_models.py
ruff check autolabel_with_single_class_models.py yolo_label_recovery tests examples
python tests\run_smoke_tests.py
pytest  # optional, if pytest is installed
```

Before submitting a change, run a dry-run on a tiny synthetic dataset and inspect `summary.txt`, CSV files and at least one review image per class.
