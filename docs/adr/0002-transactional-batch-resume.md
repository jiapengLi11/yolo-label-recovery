# ADR 0002: Commit recovery work at batch boundaries

- Status: accepted
- Date: 2026-08-15

## Context

Multi-teacher scans can run for hours. CUDA OOM, network interruptions or machine restarts should not force a complete restart, but resuming after partially written labels can create duplicate annotations.

## Decision

Predictions for the current batch are buffered as a small CPU representation. Candidate CSV and derived-label writes occur only after inference and candidate generation succeed. Files are flushed before the atomic state cursor advances. Candidate keys and normalized label lines make replay idempotent if a crash occurs between data and state commits.

## Consequences

- The last uncommitted batch may be recomputed, but committed batches are skipped.
- Adaptive OOM recovery can halve and retry the current batch without leaking partial candidates.
- Resume requires the same run signature, preventing accidental configuration mixing.

