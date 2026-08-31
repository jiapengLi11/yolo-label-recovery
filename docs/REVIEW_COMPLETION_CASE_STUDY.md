# Review Completion Case Study

## Outcome

The multi-user review workflow completed all `30,183 / 30,183` candidates on a trusted campus LAN with no unresolved runtime state:

| Final decision | Count |
|---|---:|
| `ACCEPT_ADD` | 15,283 |
| `ACCEPT_EVAL_LABEL` | 6,307 |
| `ACCEPT_REPLACE_GT` | 551 |
| `REJECT` | 8,042 |
| Pending / claimed / escalated | 0 |

These are review-workflow counts. They do not claim model accuracy, annotation precision or maximum concurrent-user capacity.

## Why the lock unit is an image

A review task still represents one candidate box, because each box needs an independent decision, version and audit trail. Concurrency ownership uses a wider boundary:

```text
image_key = (project_id, split, image_name)
```

Claiming one candidate locks every sibling row under `PESSIMISTIC_WRITE`. If another reviewer has a live lease on any sibling, the image is unavailable. Otherwise all pending or expired candidates from that image receive the same owner and lease deadline.

This prevents a joint scene such as `person + helmet + smoking` from being split across reviewers. The left rail, one-click auto-advance, heartbeat and release all operate inside the owned image group, while decisions remain candidate-level.

The implementation deliberately separates three concurrency mechanisms:

1. **Pessimistic database lock:** short transaction-time protection while allocating or updating an image group.
2. **Renewable business lease:** longer user think-time ownership represented by `claimed_by` and `lease_until`.
3. **Optimistic version:** stale browser submissions carry `expectedVersion` and receive `409 Conflict` instead of overwriting newer state.

## Closeout boundary

The web platform is mutable operational state. Model training requires a frozen, reproducible input. The finalizer therefore applies these gates:

1. Stop the API so no reviewer can write during export.
2. Create a transactionally consistent MySQL snapshot with `mysqldump --single-transaction`.
3. Join decisions to the geometry-rich source template by stable `candidate_id`.
4. Reject duplicate IDs, unknown IDs, task/template count drift, missing decisions and `UNCERTAIN` outcomes.
5. Copy the review policy and exact class-remap manifest.
6. Generate `SHA256SUMS.txt` for delivery verification.

The original review package and source labels remain read-only. The apply stage creates a versioned derived dataset instead of editing the source in place.

## Exact smoking-label repair

One imported source subset used single-class YOLO labels where class `0` meant `smoking`; after merging into the six-class schema, class `0` meant `person`. A global `0 -> 5` replacement would corrupt legitimate person labels. The repair therefore uses an exact manifest containing image identity and normalized box geometry. Only a manifest-matched old box is remapped from `person(0)` to `smoking(5)`.

This is an example of why schema migration must preserve provenance: the same numeric class ID has no meaning without its source taxonomy.

## Train, validation and test policy

- Accepted training candidates create additional supervision in the derived training split.
- Validation/test labels are changed only for explicit `ACCEPT_EVAL_LABEL` decisions.
- Evaluation reports retain both the original holdout and the reviewed holdout, preventing a corrected answer key from being presented as an unexplained model gain.
- New and baseline models must use the same architecture, initialization, image size and evaluation parameters when measuring the effect of data governance.

## Handoff to retraining

The final delivery contains the complete decision CSV, database snapshot, review policy, exact remap manifest, GT/AUTO coverage summary and checksums. The 5090-side apply script verifies the bundle, builds a new dataset version, emits applied/rejected/held manifests, runs label-integrity checks and only then starts training.

## Interview narrative

The strongest explanation is not “I built a labeling page.” It is:

> I separated GPU evidence generation, concurrent human authorization and immutable dataset application. During real two-user review I found that candidate-level claiming broke joint-scene context, so I changed the lock boundary to the source image while preserving candidate-level decisions. After all 30,183 decisions were complete, I froze the database and evidence by stable IDs and checksums, then handed a versioned, reversible dataset transformation to the training machine.

That story demonstrates ML data governance, transaction design, concurrency control, human-in-the-loop UX, auditability and reproducible handoff in one workflow.
