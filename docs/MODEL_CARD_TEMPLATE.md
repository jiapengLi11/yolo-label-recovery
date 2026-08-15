# Detection model card template

Use this template for every model trained from a recovered dataset. Do not report a metric without naming its split and data lineage.

## Model identity

- Model name and version:
- Architecture and initialization weights:
- Weight checksum (SHA-256):
- Training code commit:
- Export formats:

## Intended use

- Supported scenarios:
- Unsupported scenarios:
- Expected camera distance, angle and resolution:
- Deployment input size and confidence policy:

## Dataset lineage

- Source dataset version/checksum:
- Dataset audit report:
- Label-recovery run signature:
- AUTO/REVIEW thresholds:
- Human review performed:
- Train/validation/test image and object counts:
- Exact or near-duplicate leakage checks:

## Training configuration

- Image size, batch and epochs:
- Optimizer and learning-rate schedule:
- Augmentation policy:
- Hardware, CUDA, PyTorch and Ultralytics versions:
- Random seed and deterministic settings:

## Evaluation

| Split | Precision | Recall | mAP50 | mAP50-95 |
|---|---:|---:|---:|---:|
| Validation | | | | |
| Test | | | | |

Add per-class metrics, confusion matrices, PR curves and representative failure cases. For temporal alarms, report event-level precision/recall separately from frame-level detection metrics.

## Limitations and risks

- Small/occluded target limitations:
- Domain-shift risks:
- Known class interactions:
- False-positive consequences:
- False-negative consequences:

## Deployment monitoring

- Input and inference latency percentiles:
- Dropped-frame policy:
- Temporal event aggregation rule:
- Drift/failure sampling policy:
- Rollback model and trigger:

