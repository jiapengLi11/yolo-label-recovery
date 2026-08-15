# Changelog

## 0.3.0

- Added the model-free `audit` command for YOLO schema, label, image and split-integrity checks.
- Added optional exact-image hashing to detect train/val/test leakage.
- Added the `doctor` command for Python, package, CUDA and GPU diagnostics.
- Added atomic `manifest.json` lifecycle records to every recovery run.
- Added an intentionally flawed synthetic dataset generator for a one-minute public demo.
- Expanded automated coverage to include audit findings, HTML audit output and manifest lifecycle.
- Added path-redaction options for shareable reports and diagnostics.

## 0.2.0

- Renamed the project to YOLO Label Recovery.
- Added an installable CLI package with `run` and `report` commands.
- Added atomic batch checkpoints and `--resume` support.
- Added idempotent candidate/label writes for interrupted-batch recovery.
- Added an HTML quality report with class statistics, distributions and sample galleries.
- Added runtime initial/stable batch and OOM retry metrics.
- Split domain, geometry, configuration, state and reporting into modules.
- Added a synthetic public demo and GitHub Actions CI.

## 0.1.0

- Extracted the resource-aware single-class scanning workflow into a clean repository.
- Added immutable-source output handling and audit CSVs.
- Added class-specific thresholds and separate existing-label/candidate-duplicate IoU controls.
- Added relative model configuration examples, tests and interview documentation.
- Added opt-in transactional adaptive batch retry after CUDA OOM.
