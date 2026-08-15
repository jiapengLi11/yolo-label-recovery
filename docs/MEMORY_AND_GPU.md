# GPU and CPU memory design

## What caused the original pressure

The scan touches every image once per specialist model, but the resource peak is not the total dataset size. The main peak contributors are:

- input resolution (`imgsz`)
- batch size
- model parameters and intermediate feature maps
- NMS candidate tensors
- live PyTorch tensors and allocator reservations
- model-switching fragmentation
- unbounded Python lists containing candidates or images

## GPU lifecycle

The tool keeps one model in GPU memory at a time:

```text
load person -> scan all splits -> release
load helmet -> scan all splits -> release
...
```

Each batch uses `stream=True`. Result objects are consumed immediately, and the code performs object deletion, garbage collection and CUDA cache cleanup at batch and model boundaries. FP16 is enabled only for CUDA devices.

## CPU lifecycle

The tool stores image paths rather than decoding the whole dataset into RAM. It keeps only the current batch, the current class's label cache and bounded review samples. Candidate rows are streamed directly to:

- `candidates_auto.csv`
- `candidates_review.csv`
- `candidates_all.csv`

This avoids RAM growing linearly with the number of candidates.

## OOM policy

With `--adaptive-batch`, the tool reports the class, split and failing batch, discards the uncommitted current batch, and retries at half the batch size. The fallback schedule is:

```text
32 -> 16 -> 8 -> 4 -> 2 -> 1
```

The current batch is committed to CSV and labels only after successful inference and candidate generation. This prevents a failed attempt from duplicating rows or labels. Without `--adaptive-batch`, the tool fails loudly and prints the next batch size to try manually.

## Why not reduce image size first

If deployment is fixed at `832`, changing the training or annotation-scan resolution changes the comparison conditions. Reduce batch first to preserve the spatial scale; reduce `imgsz` only when the target system also changes.
