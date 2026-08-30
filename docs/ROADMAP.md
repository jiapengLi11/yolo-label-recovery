# Roadmap

The roadmap separates implemented behavior from ideas that still need evidence. An item moves to completed only after code, tests and a reproducible example exist. Chinese readers should also use [the evidence matrix](PROJECT_EVIDENCE.zh-CN.md) to distinguish implementation, real-world validation and architecture design.

## Completed through 1.1

### Dataset governance and recovery

- Sequential multi-teacher scanning with one YOLO model resident on the GPU at a time.
- Per-class AUTO/REVIEW thresholds, same-class GT filtering and candidate deduplication.
- Read-only source labels, derived label trees and optional trainable dataset materialization.
- Streaming CSV output, bounded visualization samples and adaptive OOM recovery.
- Atomic checkpoints, run signatures, idempotent resume and machine-readable manifests.
- Model-free dataset audit, image integrity checks and exact cross-split duplicate detection.
- Threshold calibration with Wilson precision lower bounds and REVIEW recall targets.
- Independent cross-Teacher consensus with one-to-one spatial matching and conservative downgrade.
- Perceptual near-duplicate grouping with dHash/aHash, BK-tree search and visual safeguards.
- Diversity-aware active review queues using uncertainty, dynamic class rarity and perceptual distance.

### Human authority and safe writeback

- Exhaustive `GT0_AUTO0`, `GT1_AUTO0`, `GT0_AUTO1` and `GT1_AUTO1` accounting.
- Multi-signal same-target reasoning with IoU, IoS, normalized center distance and area ratio.
- Image-grouped bilingual desktop review with action-aware controls, shortcuts and autosave/resume.
- Append-only JSONL journal, atomic CSV checkpoints and crash-safe replay.
- Safe apply with unresolved-decision blocking, source-GT drift detection, duplicate rechecks and evaluation-split isolation.

### Multi-user collaboration platform

- Spring Boot 4, Vue 3 and MySQL collaboration platform.
- JWT authentication, global roles and project-level membership isolation.
- Pessimistic atomic task claim, renewable leases and optimistic versions.
- Idempotent bounded-batch import of review queues and historical desktop decisions.
- Read-only visual serving with path-traversal protection and immutable audit events.
- One-click decision and automatic advance, image-grouped candidate navigation, reviewer-scoped correction and keyboard controls.
- Docker Compose and trusted-LAN deployment paths, Flyway migrations, backend integration tests and frontend CI builds.
- Real-scale workflow validation with 30,183 imported tasks, 4,465 migrated decisions and two simultaneous campus-LAN reviewer accounts.

### Open-source and portfolio delivery

- Installable CLI, dependency-light smoke tests, pytest suite, wheel build and GitHub Actions CI.
- Public synthetic fixtures and pre-generated reports for audit, calibration, consensus, near duplicates, prioritization and human review.
- English-first GitHub landing page with a complete Chinese engineering guide.
- Documentation hub, reproducible demo guide, core-code walkthrough, evidence matrix, mining-system design and interview Q&A.
- Repository-local Markdown link validation and structured issue/pull-request templates.
- Illustrated project blog and a generated development/interview handbook.

## Planned for 1.2

- Teacher adapter interface for non-Ultralytics detectors.
- Optional Parquet evidence output for very large scans.
- Export of reviewer throughput, disagreement and correction metrics with privacy-safe aggregation.
- MySQL Testcontainers concurrency tests for claim, lease expiry and stale-version conflicts.
- Versioned review-decision export manifest and writeback change summary.
- English versions of the detailed Chinese code, demo and evidence guides.

## Full mining-system evolution

These items belong to the broader mining-safety platform and are not yet claimed as completed by this repository:

- Multi-channel RTSP capture with latest-frame slots, bounded queues and dynamic GPU batching.
- Event-level temporal rules, alert deduplication and work-order state machines.
- Versioned RAG safety knowledge base with hybrid retrieval, citations and high-risk refusal.
- Function Calling Agent with tool allowlists, idempotency keys, approval gates and audit.
- Redis for high-frequency ephemeral state and Kafka with a transactional outbox for asynchronous fan-out.
- Reproducible Jetson/TensorRT deployment benchmarks and end-to-end latency decomposition.

## Research backlog

- Diversity-aware embedding adapters beyond perceptual hashes.
- Statistical sampling plans that separate policy calibration, model evaluation and production drift monitoring.
- Cross-camera hard-example mining and event-level active learning.

## Non-goals

- Treating teacher predictions as ground truth without audit.
- Modifying source labels in place.
- Shipping private datasets, trained weights, credentials or unredacted machine paths.
- Claiming that one threshold policy transfers safely to every domain.
- Presenting screenshots, training loss or biased review samples as model-accuracy evidence.
- Adding middleware or microservices before a measured bottleneck justifies them.
