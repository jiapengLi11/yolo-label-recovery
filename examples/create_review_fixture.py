"""Create a public synthetic fixture for the GT/AUTO human-review workflow."""

from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path

import yaml
from PIL import Image, ImageDraw

NAMES = ["person", "helmet", "vest", "tractor", "slipper", "smoking"]
FIELDS = ["split", "image", "label", "class_name", "class_id", "conf", "mode", "cx", "cy", "w", "h"]


def _image(path: Path, title: str, accent: tuple[int, int, int]) -> None:
    image = Image.new("RGB", (720, 440), (235, 239, 231))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 720, 64), fill=(16, 45, 59))
    draw.text((24, 22), title, fill="white")
    draw.rectangle((245, 105, 475, 405), fill=(205, 214, 204), outline=accent, width=4)
    draw.ellipse((305, 82, 415, 192), fill=(205, 176, 142), outline=accent, width=3)
    draw.rectangle((292, 78, 430, 125), fill=accent)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _candidate(
    image: str,
    class_name: str,
    class_id: int,
    confidence: float,
    box: tuple[float, float, float, float],
    *,
    split: str = "train",
) -> dict[str, str]:
    cx, cy, width, height = box
    return {
        "split": split,
        "image": f"images/{split}/{image}",
        "label": f"labels/{split}/{Path(image).stem}.txt",
        "class_name": class_name,
        "class_id": str(class_id),
        "conf": f"{confidence:.3f}",
        "mode": "auto",
        "cx": str(cx),
        "cy": str(cy),
        "w": str(width),
        "h": str(height),
    }


def create_fixture(output_dir: Path, force: bool = False) -> tuple[Path, Path]:
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists():
        if not force:
            raise FileExistsError(f"Output exists: {output_dir}; use --force")
        shutil.rmtree(output_dir)
    dataset = output_dir / "dataset"
    for split in ("train", "val", "test"):
        (dataset / "images" / split).mkdir(parents=True)
        (dataset / "labels" / split).mkdir(parents=True)

    _image(dataset / "images/train/missing.jpg", "GT0_AUTO1: missing helmet candidate", (22, 184, 166))
    _image(dataset / "images/train/same.jpg", "GT1_AUTO1: same target, different extent", (245, 158, 11))
    _image(dataset / "images/train/cross.jpg", "GT1_AUTO1: cross-class conflict", (225, 69, 50))
    _image(dataset / "images/train/quiet.jpg", "GT1_AUTO0: existing label without Teacher evidence", (37, 99, 235))
    _image(dataset / "images/train/blank.jpg", "GT0_AUTO0: no GT and no Teacher evidence", (100, 116, 139))
    _image(dataset / "images/val/eval.jpg", "Evaluation split candidate: gold review only", (219, 39, 119))

    (dataset / "labels/train/missing.txt").write_text("", encoding="utf-8")
    (dataset / "labels/train/same.txt").write_text("0 0.500000 0.560000 0.250000 0.650000\n", encoding="utf-8")
    (dataset / "labels/train/cross.txt").write_text("0 0.500000 0.560000 0.280000 0.650000\n", encoding="utf-8")
    (dataset / "labels/train/quiet.txt").write_text("1 0.500000 0.230000 0.200000 0.130000\n", encoding="utf-8")
    (dataset / "labels/train/blank.txt").write_text("", encoding="utf-8")
    (dataset / "labels/val/eval.txt").write_text("", encoding="utf-8")
    (dataset / "data.yaml").write_text(
        yaml.safe_dump(
            {
                "path": dataset.as_posix(),
                "train": "images/train",
                "val": "images/val",
                "test": "images/test",
                "nc": 6,
                "names": NAMES,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    rows = [
        _candidate("missing.jpg", "helmet", 1, 0.93, (0.5, 0.23, 0.2, 0.13)),
        _candidate("same.jpg", "person", 0, 0.95, (0.58, 0.56, 0.34, 0.72)),
        _candidate("cross.jpg", "helmet", 1, 0.91, (0.5, 0.56, 0.28, 0.65)),
        _candidate("eval.jpg", "smoking", 5, 0.86, (0.58, 0.32, 0.09, 0.09), split="val"),
    ]
    candidates = output_dir / "candidates.csv"
    with candidates.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return dataset, candidates


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    dataset, candidates = create_fixture(args.output_dir, args.force)
    print(f"Dataset: {dataset}")
    print(f"Candidates: {candidates}")


if __name__ == "__main__":
    main()
