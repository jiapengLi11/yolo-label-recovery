# Exhaustive GT/AUTO human-review gate

[English](HUMAN_REVIEW.md) | [简体中文](HUMAN_REVIEW.zh-CN.md)

## Motivation

A Teacher prediction is evidence, not ground truth. Confidence alone cannot safely decide whether a box is a missing object, a duplicate of an existing annotation, a differently sized box for the same target, or a conflict with another class. The review gate makes those cases explicit before any derived label dataset is created.

## Complete image/class state space

Every image and class belongs to exactly one state:

| State | Existing GT | Teacher evidence | Default handling |
|---|---:|---:|---|
| `GT0_AUTO0` | No | No | No action; retained for coverage accounting |
| `GT1_AUTO0` | Yes | No | Keep the existing GT |
| `GT0_AUTO1` | No | Yes | Evaluate confidence, geometry and split policy |
| `GT1_AUTO1` | Yes | Yes | Resolve already-labelled, same-target ambiguity or distinct targets |

The matrix is generated for every image/class pair, not only for images containing candidates. This prevents a report from silently ignoring absence cases.

## Complementary geometry

For candidate box $A$ and target box $B$, intersection-over-union is:

$$
\operatorname{IoU}(A,B)=\frac{|A\cap B|}{|A\cup B|}
$$

IoU becomes small when one valid box is contained in a much larger box. Intersection-over-smaller-area therefore provides a second signal:

$$
\operatorname{IoS}(A,B)=\frac{|A\cap B|}{\min(|A|,|B|)}
$$

The normalized center distance is:

$$
d_c(A,B)=\frac{\sqrt{(c_x^A-c_x^B)^2+(c_y^A-c_y^B)^2}}{\sqrt{\min(|A|,|B|)}}
$$

The area ratio is:

$$
r_a(A,B)=\frac{\max(|A|,|B|)}{\min(|A|,|B|)}
$$

The default policy uses these signals as follows:

- Already labelled: `IoU >= 0.60`, or `IoS >= 0.90` with normalized center distance `<= 0.35`.
- Same target, ambiguous extent: `IoU >= 0.20`, or `IoS >= 0.55` with normalized center distance `<= 0.80`.
- Near-duplicate Teacher candidates: same-class candidate IoU `>= 0.90`; only the higher-confidence candidate survives.
- Cross-class conflict: cross-class IoU `>= 0.65` and area ratio `<= 2.0`; route to a human instead of deleting a potentially valid nested small object.

## Candidate terminal states

Each Teacher candidate receives one terminal state:

| Terminal state | Human review | Allowed result |
|---|---:|---|
| `INVALID` | No | Reject |
| `MODEL_DUPLICATE` | No | Reject lower-confidence duplicate |
| `GT_ALREADY_LABELED` | No | Keep GT, do not add another box |
| `GT_SAME_AMBIGUOUS` | Yes | Explicitly replace the matched GT or reject |
| `GT_CROSS_CLASS_CONFLICT` | Yes | Add as a distinct class or reject |
| `TRAIN_MISSING_HIGH/MEDIUM` | Yes | Add or reject |
| `EVAL_MISSING_HIGH/MEDIUM` | Yes | Accept as gold-evaluation evidence or reject |
| `BELOW_REVIEW_THRESHOLD` | No by default | Preserve in the audit table; optionally include in review |
| `SPLIT_DISABLED` | No | Reject |

High confidence does not bypass the human gate. The policy separates evidence strength from permission to change labels.

## Offline review bundle

```powershell
yolo-label-recovery review-build D:\data\dataset D:\runs\candidates_all.csv `
  --policy configs\review_policy.example.yaml `
  --output-dir D:\runs\company-review `
  --render `
  --redact-paths
```

The output contains the complete audit table, review queue, decision template, rendered candidates, matrix coverage, an HTML summary and an offline Tk reviewer. The reviewer autosaves `company_decisions.csv` and resumes from the first unfinished row.

Review keys:

- `A`: accept a distinct missing box.
- `P`: replace the highlighted same-class GT.
- `E`: accept a val/test gold-label candidate.
- `D`: reject.
- `U`: temporarily uncertain; must be resolved before apply.

## Safe apply

```powershell
yolo-label-recovery review-apply D:\data\dataset D:\runs\company-review\company_decisions.csv `
  --policy configs\review_policy.example.yaml `
  --output-root D:\data\dataset-reviewed
```

The apply stage enforces the following invariants:

- Blank and uncertain decisions block the entire operation.
- The output cannot equal, contain or be a parent of the source dataset.
- Source images and labels are never modified.
- Replace is valid only for `GT_SAME_AMBIGUOUS` and only if the referenced GT has not changed since review.
- Accepted additions are checked again against the latest derived labels before writing.
- Val/test decisions are held by default to avoid silently changing the evaluation contract.
- Every applied, replaced, held and rejected row remains auditable.

## Public demo

```powershell
python examples\create_review_fixture.py --output-dir .demo-review-fixture
yolo-label-recovery review-build .demo-review-fixture\dataset .demo-review-fixture\candidates.csv `
  --output-dir .demo-review-result --render --redact-paths
```

The fixture intentionally covers all four image/class states and the main candidate terminal decisions without requiring a GPU, private image or model weight.
