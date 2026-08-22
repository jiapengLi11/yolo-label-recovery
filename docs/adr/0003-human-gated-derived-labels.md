# ADR 0003: Human-gated derived labels

## Status

Accepted for 0.9.0.

## Context

The original pipeline could route high-confidence Teacher evidence into an AUTO label tree. Production review showed that confidence and same-class IoU alone cannot reliably separate missing objects from box-extent disagreement, nested cross-class objects and repeated Teacher boxes.

## Decision

Introduce an exhaustive GT/AUTO decision layer and require explicit human decisions before the new review workflow writes labels. Same-target ambiguity must use `accept_replace_gt`; it cannot keep both boxes. Evaluation-split decisions remain held unless a caller explicitly opts into changing the evaluation dataset.

## Consequences

- Label creation becomes slower but has a clear authority boundary.
- Candidate evidence and human decisions remain independently auditable.
- Source datasets remain immutable and experiments remain reversible.
- High confidence is treated as evidence strength rather than write permission.
- Production teams can own final annotation decisions without requiring model code or GPU access.
