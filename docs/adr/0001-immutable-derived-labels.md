# ADR 0001: Keep source labels immutable

- Status: accepted
- Date: 2026-08-15

## Context

Teacher predictions may be useful evidence but are not ground truth. Writing them directly into source labels makes rollback difficult, obscures provenance and can silently contaminate later experiments.

## Decision

The recovery pipeline treats the source `labels/` tree as read-only. Apply mode copies labels into `labels_autofill_v1`, appends accepted AUTO candidates there, and can materialize a separate trainable dataset. Every candidate remains represented in an audit CSV.

## Consequences

- Experiments are reversible and comparable.
- Extra disk space is required for derived labels; hardlinked images limit the larger image cost.
- Consumers must intentionally select the derived `data.yaml` rather than assuming the source changed.

