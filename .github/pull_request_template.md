## Summary

Describe the behavior changed and why it is safe for source labels.

## Verification

- [ ] `python -m compileall -q autolabel_with_single_class_models.py yolo_label_recovery tests`
- [ ] `python tests/run_smoke_tests.py`
- [ ] `pytest`
- [ ] No private images, labels, weights, credentials, logs, IP addresses or absolute local paths are included.
- [ ] Candidate-writing or resume changes include an idempotence test.

## Evidence

Include a synthetic fixture, sanitized output summary or screenshot when behavior is user-visible.
