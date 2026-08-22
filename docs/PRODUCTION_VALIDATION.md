# Production-scale validation

This case study records a private six-class run without publishing images, model weights, local paths or dataset names. It shows that the review gate was exercised on production-scale evidence rather than only on the public synthetic fixture.

![Anonymized production validation summary](assets/production-validation-summary.svg)

## Run profile

| Item | Result |
|---|---:|
| Dataset images | 29,071 |
| Specialist Teachers | 6 |
| Image-model inference passes | 174,426 |
| Raw prediction evidence rows | 99,696 |
| Review rows | 30,183 |
| Render failures | 0 |
| Source labels modified | No |
| Human decisions completed | 0 at snapshot time |

The scan used CUDA FP16 inference at `832` pixels with `batch=32`, one Teacher resident on GPU at a time and all six classes evaluated over train, validation and test splits.

## Decision routing

| Terminal group | Rows | Share of review queue | Handling |
|---|---:|---:|---|
| Train missing candidates | 18,120 | 60.03% | Human add/reject decision |
| Evaluation missing candidates | 7,951 | 26.34% | Held from training writes by default |
| Same-target ambiguity | 3,688 | 12.22% | Replace or reject; never append a second box |
| Cross-class conflict | 424 | 1.41% | Human semantic decision |

Before the review queue was created, the engine suppressed `60,563` already-labelled predictions, `2,050` model duplicates and `6,900` below-review predictions. These `69,513` rows remain in the audit trail but do not consume reviewer time.

## Workload distribution

| Class | Review rows | Share |
|---|---:|---:|
| person | 25,066 | 83.05% |
| helmet | 1,823 | 6.04% |
| smoking | 1,265 | 4.19% |
| vest | 1,031 | 3.42% |
| slipper | 886 | 2.94% |
| tractor | 112 | 0.37% |

The person Teacher dominates the queue. This is useful operational evidence: a technically correct exhaustive queue can still be economically poor. The next review cycle should allocate a class-aware budget or calibrate the person policy from audited decisions instead of silently raising one global threshold.

## Qualitative findings

- Helmet, vest and slipper samples contain visually credible missing annotations.
- High-confidence smoking evidence includes hard negatives such as microphones near the mouth. This demonstrates why confidence is evidence strength, not write authority.
- Same-target extent disagreements are common enough (`3,688` rows) that IoU-only append logic would create harmful duplicate GT boxes.
- Validation and test candidates account for `7,951` rows. Holding them by default prevents remediation from silently moving the evaluation target.
- The package rendered every review image successfully, so it can be handed to a non-GPU annotation team as a portable review artifact.

## Reproducibility boundary

Only aggregate, anonymized evidence is published. The private run keeps its original manifest, policies, raw CSV streams and reviewer package locally. No private image, label, weight, hostname or filesystem path is committed to this repository.
