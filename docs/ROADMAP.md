# Roadmap

The roadmap separates implemented behavior from ideas that still need evidence. It is intentionally conservative: an item moves to "completed" only after tests and a reproducible example exist.

## Completed through 0.9

- Sequential multi-teacher scanning with one YOLO model resident on the GPU at a time.
- Per-class AUTO and REVIEW thresholds.
- Existing-label IoU filtering and candidate deduplication.
- Read-only source labels with a separate derived label tree.
- Streaming CSV output and bounded visualization samples.
- Adaptive OOM recovery with transactional batch commits.
- Atomic checkpoints and idempotent resume.
- Self-contained HTML quality report.
- Installable CLI, tests, wheel build and GitHub Actions CI.
- Model-free dataset audit with label-schema, image-integrity and orphan-label checks.
- Exact duplicate hashing with cross-split leakage detection.
- Runtime doctor command and machine-readable run manifest.
- Public synthetic failure fixture for a reproducible demonstration.
- Bilingual English/Simplified Chinese landing page and interview guide.
- Lightweight audit/report installation separated from optional GPU inference dependencies.
- Empirical threshold calibration from human-reviewed candidate decisions.
- Per-class AUTO precision and REVIEW recall policy reports.
- Public six-class calibration fixture and static portfolio evidence.
- Wilson precision lower-bound gating for conservative AUTO calibration.
- Public 2,400-candidate confidence-aware calibration fixture and report.
- Model-free cross-Teacher consensus gate with one-to-one spatial matching.
- Conservative AUTO-to-REVIEW downgrade and agreed-only YOLO label export.
- Public six-class consensus fixture, report and static portfolio evidence.
- Perceptual near-duplicate grouping with dHash/aHash visual safeguards.
- BK-tree candidate search, representative review exports and cross-split leakage evidence.
- Public near-duplicate fixture, self-contained report and bilingual documentation.
- Image-level active review queues combining uncertainty, dynamic class rarity and visual diversity.
- Original-candidate preservation, ranked exports and explicit biased-sampling boundaries.
- Public six-class imbalanced review fixture, self-contained report and bilingual documentation.
- Exhaustive GT/AUTO image-class matrix and candidate terminal-state coverage.
- Multi-signal same-target matching with IoU, IoS, normalized center distance and area ratio.
- Portable offline review bundle with autosave/resume and explicit add/replace/evaluation decisions.
- Human-gated safe apply with source-GT drift checks, duplicate rechecks and evaluation-split isolation.
- Public no-GPU review fixture, static evidence, bilingual documentation and CI coverage.

## Planned for 1.0

- Teacher adapter interface for non-Ultralytics detectors.
- Precision-oriented benchmark fixtures for AUTO and REVIEW queues.
- Optional Parquet candidate output for very large scans.

## Research backlog

- Diversity-aware embedding adapters beyond perceptual hashes.
- Review UI integrations through an exporter/importer boundary.

## Non-goals

- Treating teacher predictions as ground truth without audit.
- Modifying source labels in place.
- Shipping private datasets or trained weights.
- Claiming that one threshold policy transfers safely to every domain.
