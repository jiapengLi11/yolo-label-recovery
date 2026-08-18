# Changelog

## 0.9.0

- Added exhaustive `GT0_AUTO0`, `GT1_AUTO0`, `GT0_AUTO1` and `GT1_AUTO1` image/class accounting.
- Added pure-Python IoU, IoS, normalized center-distance and area-ratio decision rules for same-target and cross-class conflicts.
- Added `review-build` for portable visual review bundles, full audit CSVs, decision templates and HTML summaries.
- Added `review-ui`, an offline autosaving Tk reviewer with explicit add, replace, evaluation, reject and uncertain actions.
- Added `review-apply` with unresolved-decision blocking, source-GT drift detection, duplicate rechecks and immutable derived datasets.
- Added a packaged default six-class policy, public no-GPU fixture, static preview, bilingual documentation, ADR and CI coverage.

## 0.8.0

- Added the CPU-only, read-only `prioritize` command for image-level active human-review queues.
- Added normalized confidence entropy, dynamically decayed class rarity and greedy dHash/aHash visual diversity.
- Added safe resolution of absolute and relative candidate image paths with dataset-boundary enforcement.
- Added ranked image/candidate exports, full-pool evidence, failure isolation and a self-contained HTML report.
- Added a reproducible imbalanced six-class fixture, static screenshot, bilingual documentation and CI coverage.

## 0.7.0

- Added the model-free, read-only `cluster` command for perceptual near-duplicate review grouping.
- Added 64-bit dHash/aHash fingerprints, BK-tree radius search and deterministic connected components.
- Added aspect-ratio and low-texture luminance safeguards to reduce false-positive groups.
- Added cross-split near-duplicate leakage evidence, corrupt-image isolation and representative review exports.
- Added a reproducible public fixture, self-contained HTML report, static screenshot, bilingual documentation and CI coverage.

## 0.6.0

- Added the model-free `consensus` command for independent cross-Teacher AUTO verification.
- Added deterministic one-to-one spatial matching so one verifier box cannot approve multiple primary candidates.
- Added conservative downgrade-to-REVIEW behavior for unsupported primary AUTO candidates.
- Added optional agreed-only YOLO label additions, machine-readable summaries and a self-contained HTML report.
- Added a reproducible six-class consensus fixture, static screenshot, bilingual documentation and CI coverage.

## 0.5.0

- Added Wilson score precision lower bounds for confidence-aware AUTO threshold calibration.
- Made `95%` statistical confidence the CLI default while retaining `0` as an empirical-policy compatibility mode.
- Expanded the deterministic public calibration fixture from 600 to 2,400 reviewed candidates.
- Added empirical precision and precision lower-bound evidence to CSV, JSON and HTML reports.
- Added statistical boundary tests demonstrating why small perfect samples are insufficient evidence.

## 0.4.0

- Added pre-generated, path-redacted audit and recovery screenshots to both README languages for offline presentation.
- Added the `calibrate` command for class-specific AUTO precision and REVIEW recall policies.
- Added machine-readable threshold recommendations, threshold-curve CSV and a self-contained HTML calibration report.
- Added a deterministic six-class, 600-candidate public calibration fixture and screenshot.
- Added calibration algorithm, validation and artifact tests.

## 0.3.1

- Added a complete Simplified Chinese README and interview portfolio guide.
- Added English/Chinese language navigation to the repository landing page.
- Split lightweight audit/report dependencies from optional GPU inference dependencies.
- Added an actionable CLI error when `run` is used without the `inference` extra.
- Added tests for optional inference dependency loading.

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
