# Perceptual near-duplicate grouping

[English](NEAR_DUPLICATES.md) | [简体中文](NEAR_DUPLICATES.zh-CN.md)

The `cluster` command reduces repeated human review and detects visually duplicated images crossing YOLO dataset splits. It is model-free, CPU-only and read-only: it never deletes, moves or rewrites an image or label.

## Usage

```powershell
yolo-label-recovery cluster D:\data\mining-safety `
  --output-dir D:\data\near-duplicate-audit `
  --splits train val test `
  --workers 4 `
  --max-distance 6 `
  --redact-paths
```

Use `--fail-on-cross-split` in CI when perceptual leakage must fail a data release.

## Algorithm

1. Decode one image per worker and apply EXIF orientation.
2. Produce a 64-bit difference hash (dHash), a 64-bit average hash (aHash), dimensions and luminance statistics.
3. Query dHash neighbors with a BK-tree instead of comparing every image pair.
4. Reject candidates that violate the aHash radius or aspect-ratio guard.
5. For two low-texture images, require similar mean luminance so black and white frames do not collide.
6. Convert accepted neighbor edges into deterministic connected components.
7. Select the highest-resolution image in each component as the first review representative.

For `N` images, fingerprint storage is `O(N)`. BK-tree search is usually far below brute-force `O(N²)`, although adversarial hash distributions can degrade. Pixel buffers are bounded by the worker count; the entire dataset is never decoded into RAM at once.

## Outputs

| File | Purpose |
|---|---|
| `near_duplicate_members.csv` | One row per clustered image with hashes and representative distance |
| `review_representatives.csv` | One highest-resolution representative per review group |
| `fingerprint_failures.csv` | Corrupt or unreadable image evidence |
| `near_duplicate_summary.json` | Policy, totals, group membership and leakage counts |
| `near_duplicate_report.html` | Self-contained visual report for review and delivery |

## Guardrails and limitations

- A cluster means visual similarity, not permission to delete data automatically.
- Connected components allow transitive chains: A may match B and B may match C even when A is farther from C. The report exposes maximum dHash distance to the selected representative so loose groups can be inspected.
- dHash is useful for resize, JPEG recompression and modest brightness changes. It is not designed for major crops, rotations or semantic similarity.
- Cross-split clusters are leakage candidates. Confirm provenance before moving images because visually similar frames may still represent intentional temporal evaluation.
- Thresholds are policy. Validate them on a reviewed sample from the target domain before bulk cleanup.

## Reproducible public fixture

```powershell
python examples\create_near_duplicate_fixture.py --output .near-duplicate-fixture
yolo-label-recovery cluster .near-duplicate-fixture `
  --output-dir .near-duplicate-output `
  --redact-paths
```

Expected result: `11` discovered files, `1` intentional fingerprint failure, `3` groups, `7` grouped images and `2` cross-split groups. Black and white low-texture frames remain separate.

## Interview framing

This feature is evidence of data-centric ML engineering rather than another training wrapper. The key design choices are bounded decoding, sub-quadratic candidate search, conservative false-positive guards, deterministic review groups, explicit leakage evidence and immutable source data.
