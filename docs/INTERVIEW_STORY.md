# Interview presentation

## One-minute version

The project solves incomplete annotations in a six-class industrial safety dataset. Instead of changing the source labels directly, I used six specialist single-class detectors as teacher models. Each teacher scans the full dataset, compares predictions with same-class GT using IoU, separates AUTO and REVIEW candidates by class-specific thresholds, and writes additions to a new label tree with a CSV audit trail.

Before inference, a model-free audit checks label syntax, class IDs, image integrity and exact train/validation/test leakage. This prevents spending GPU time on a dataset whose evaluation split is already contaminated.

The engineering challenge was memory: six models and tens of thousands of images cannot be held in memory together. I changed the pipeline to one model at a time, batch streaming, FP16 inference, bounded samples, streaming CSV output and explicit CUDA cleanup. The result is reproducible, reversible and suitable for human audit.

Long scans are checkpointed after every committed batch. Resume validates a run signature and uses idempotent CSV/label writes, so an interrupted batch can be replayed safely. A generated HTML report summarizes recovery volume, confidence/IoU distributions, adaptive batch behavior and visual samples.

## Strong technical points

- `6 x N` inference work is accepted as the cost of specialist evidence; peak memory is controlled independently.
- Existing-label IoU `0.50` is separated from candidate duplicate IoU `0.95`.
- Dataset class IDs come from `data.yaml`, avoiding silent single-model class-0 contamination.
- Dry-run and apply are separated so automatic labeling is an auditable decision, not an irreversible mutation.
- Hardlinks reduce disk duplication when building a trainable dataset.
- Atomic checkpoint/resume avoids restarting completed teacher/split work.
- The HTML report turns audit artifacts into a reviewable delivery and GitHub demo.
- Perceptual near-duplicate grouping uses compact hashes and BK-tree radius search to reduce repeated review without loading all pixels or comparing every pair.
- Active review ranking uses confidence entropy, diminishing class-rarity rewards and greedy visual diversity, while keeping metric estimation on a separate unbiased sample.
- `doctor` and `manifest.json` make environment differences visible instead of leaving CUDA and dependency drift implicit.

## Honest limitation

Adaptive retry and checkpoint/resume improve robustness, but teacher predictions are still evidence rather than ground truth. AUTO thresholds must be validated on representative samples, especially for small, occluded or domain-shifted targets.
