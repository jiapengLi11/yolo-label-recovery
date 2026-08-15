# Cross-Teacher consensus

[English](CONSENSUS.md) | [简体中文](CONSENSUS.zh-CN.md)

The `consensus` command adds an independent verification gate after candidate generation. It is model-free: two Teachers run separately, so only one model needs to occupy GPU memory at a time. Their candidate CSV files are then aligned by split, normalized image path, class and box IoU.

## Why use it

A high-confidence prediction from one Teacher can still be a systematic false positive. Requiring spatial support from a second Teacher can reduce risky AUTO additions. The command follows a conservative rule:

- primary REVIEW candidates remain REVIEW;
- primary AUTO candidates with verifier support remain AUTO;
- unsupported primary AUTO candidates are downgraded to REVIEW, never silently discarded.

This is a policy gate, not a claim that model agreement creates ground truth.

## Matching algorithm

For each `(split, image, class)` group, candidate pairs are eligible when:

- verifier confidence is at least `--verifier-min-confidence`;
- normalized-box IoU is at least `--agreement-iou`.

All eligible edges are sorted by IoU and then confidence. Greedy one-to-one assignment prevents one verifier box from approving several overlapping primary boxes. The consensus score is the geometric mean of primary and verifier confidence, while the original confidence and agreement IoU remain available for audit.

## Workflow

Run the recovery pipeline twice in `--dry-run` mode using independent model configurations. Prefer different architectures, training seeds or data sources; two near-identical checkpoints can share the same errors.

The verifier CSV contains only predictions retained by its original scan. Therefore, the effective verifier floor is the larger of that scan's REVIEW threshold and `--verifier-min-confidence`. Configure the verifier scan REVIEW threshold low enough to preserve all evidence needed by consensus.

```powershell
yolo-label-recovery consensus `
  outputs\primary\candidates_all.csv `
  outputs\verifier\candidates_all.csv `
  --output-dir outputs\consensus `
  --agreement-iou 0.50 `
  --verifier-min-confidence 0.50 `
  --label-additions-dir outputs\consensus-additions `
  --redact-paths
```

Outputs:

- `consensus_all.csv`: every primary candidate with the final mode and evidence;
- `consensus_auto.csv`: agreed AUTO candidates;
- `consensus_review.csv`: original REVIEW plus downgraded AUTO candidates;
- `consensus.json`: machine-readable policy and class statistics;
- `consensus.html`: self-contained visual report;
- optional label additions directory: agreed AUTO boxes only, grouped as YOLO label files.

The additions directory does not contain original labels. Merge it into a separate derived label tree; never append it directly to the immutable source dataset.

## Complexity and resources

Inference remains two sequential scans. The consensus stage uses grouped CSV records and box geometry only, with no PyTorch, image decoding or GPU allocation. For typical object counts per image, matching cost is small compared with inference. The implementation never performs an all-dataset pairwise comparison.

## Guardrails

- Audit both Teachers on the target domain before using agreement as an AUTO gate.
- Record the verifier scan thresholds; missing low-confidence rows cannot be recovered during consensus.
- Keep primary and verifier model errors as independent as practical.
- Tune IoU by object size; small objects can need a lower spatial threshold, but this increases accidental matches.
- Measure precision and coverage before and after gating. Agreement normally trades AUTO coverage for lower risk.
- Human-review samples should include both agreed and downgraded candidates.

## Interview explanation

This stage separates compute scheduling from decision policy. Models remain sequential for bounded peak GPU memory, while a model-agnostic CSV boundary allows independent detectors to participate. One-to-one bipartite-style matching avoids double approval, and downgrade-not-delete semantics protect recall and preserve an audit queue.
