# Portfolio and interview guide

This guide turns the repository into evidence of engineering decisions rather than a list of scripts.

## 90-second project pitch

I worked on a multi-class safety-detection dataset where source datasets had been annotated for different tasks. In combined scenes, one class could be labeled while another visible class was missing. Those omissions become false negatives during training.

I built a conservative label-recovery pipeline around specialist single-class teacher models. It first audits the YOLO dataset without a GPU, then loads one teacher at a time, streams inference in bounded batches, matches predictions only against same-class labels, and routes unmatched predictions to AUTO, REVIEW or IGNORE using class-specific thresholds. It never edits source labels.

The difficult part was operational reliability on a long `K x N` scan. I added transactional adaptive batching after CUDA OOM, atomic checkpoints, signature-validated resume, idempotent CSV/label writes, environment manifests and HTML evidence reports. The repository includes a synthetic public demo, tests and CI while excluding private data and weights.

## Capability evidence

| Capability | Repository evidence | What to explain |
|---|---|---|
| Data engineering | `audit` command | Schema validation, orphan labels, corrupt images and split leakage |
| Computer vision | IoU matching and class mapping | Why same-class GT matching differs from NMS deduplication |
| GPU engineering | Sequential teachers and adaptive batch | Peak memory versus total compute; safe OOM retries |
| Reliability | `state.json` and idempotent writes | Batch commit boundary and crash replay semantics |
| MLOps | `doctor` and `manifest.json` | Reproducing CUDA, package and configuration state |
| Human-in-the-loop ML | AUTO/REVIEW/IGNORE routing | Precision-first thresholds and audit evidence |
| Evaluation and policy | `calibrate` command | Turning reviewed outcomes into precision/recall-constrained class policies |
| Ensemble policy | `consensus` command | Independent evidence, one-to-one matching and coverage/risk tradeoffs |
| Scalable similarity search | `cluster` command | Perceptual hashes, BK-tree radius search and conservative collision guards |
| Software quality | package, CLI, tests and CI | Public fixture, privacy checks and release build |
| Communication | HTML reports and architecture docs | Turning model work into reviewable project evidence |

## Live demonstration

1. Run `python examples/create_synthetic_dataset.py --output .demo-dataset`.
2. Run `yolo-label-recovery audit .demo-dataset --output-dir .demo-audit --hash-images --check-images`.
3. Open `.demo-audit/dataset_audit.html` and point out the intentionally injected class error, orphan label and cross-split duplicate.
4. Open `examples/demo_output/report.html` to show the recovery quality report without exposing project data.
5. Open `examples/calibration/output/calibration.html` to explain why each class receives a different threshold.
6. Open `examples/consensus/output/consensus.html` to show unsupported AUTO candidates being downgraded.
7. Open `examples/near_duplicates/output/near_duplicate_report.html` to show review compression and split leakage.
8. Run `yolo-label-recovery doctor` to show environment diagnostics.

This demonstration works without a GPU or private model weights. A full teacher scan remains an optional second demonstration when suitable public weights and data are available.

## Design questions to expect

**Why not overwrite the labels directly?**

Source immutability makes experiments reversible, reviewable and safe to compare. A derived label tree can be deleted without losing the annotation baseline.

**Why six passes instead of loading all teachers?**

The compute remains approximately `K x N`, but loading one model at a time bounds peak GPU memory. This is a deliberate throughput/reliability tradeoff.

**Why are AUTO thresholds different by class?**

Teacher calibration and object difficulty differ. Small smoking/slipper targets should not inherit a threshold justified by a large tractor detector. Thresholds are policy and need validation data.

**How did you choose the thresholds instead of guessing them?**

The `calibrate` command sorts reviewed candidates once and builds cumulative precision-recall curves. AUTO uses the lowest threshold whose Wilson precision lower bound reaches the target at the selected confidence level, subject to a minimum sample count. REVIEW uses the highest threshold retaining the target positive recall, which minimizes review workload. Unsupported targets produce no fallback threshold.

**What makes resume safe?**

The state advances only after the current batch's labels and CSV rows are flushed. If a crash occurs between output and state commit, replay checks stable candidate keys and exact label lines, preventing duplication.

**Why not load both Teachers together and ensemble their tensors?**

Separate scans preserve the one-model GPU memory bound and allow different detector implementations to participate through a stable CSV contract. The consensus stage uses one-to-one IoU matching, keeps evidence auditable and downgrades unsupported AUTO candidates instead of deleting them.

**Does high confidence make a prediction ground truth?**

No. It makes the prediction stronger evidence. The project retains REVIEW routing, visual samples and an audit trail because confidence alone does not prove correctness under domain shift.

**Why not compare every image pair for near duplicates?**

Brute force grows as `O(N²)`. The `cluster` command stores compact fingerprints and uses a BK-tree for Hamming-radius candidate search, then applies aHash, aspect-ratio and low-texture luminance safeguards. It still treats every group as review evidence rather than an automatic deletion decision.

## Claims to avoid

- Do not claim the teachers eliminate all missing labels.
- Do not claim thresholds are universal.
- Do not quote private dataset metrics without permission and a precise test definition.
- Do not describe exact hashing as perceptual near-duplicate detection.
- Do not imply the synthetic demo is a production benchmark.

Honest scope makes the real engineering contributions more credible.
