"""Create deterministic primary/verifier candidate CSVs for the public consensus demo."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

CLASSES = ["person", "helmet", "vest", "tractor", "slipper", "smoking"]
FIELDS = [
    "split",
    "image",
    "label",
    "class_name",
    "class_id",
    "conf",
    "mode",
    "max_iou_same_class",
    "cx",
    "cy",
    "w",
    "h",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("examples/consensus"))
    return parser.parse_args()


def _base_row(class_name: str, class_id: int, index: int, mode: str) -> dict[str, str]:
    split = ("train", "val", "test")[index % 3]
    stem = f"{class_name}_{index:03d}"
    return {
        "split": split,
        "image": f"fixtures/images/{split}/{stem}.jpg",
        "label": f"fixtures/labels/{split}/{stem}.txt",
        "class_name": class_name,
        "class_id": str(class_id),
        "mode": mode,
        "max_iou_same_class": f"{0.05 + (index % 4) * 0.04:.3f}",
        "cy": f"{0.35 + (index % 5) * 0.06:.3f}",
        "w": f"{0.12 + class_id * 0.01:.3f}",
        "h": f"{0.16 + class_id * 0.015:.3f}",
    }


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    primary_path = args.output_dir / "primary_candidates.csv"
    verifier_path = args.output_dir / "verifier_candidates.csv"
    with primary_path.open("w", newline="", encoding="utf-8") as primary_handle, verifier_path.open(
        "w", newline="", encoding="utf-8"
    ) as verifier_handle:
        primary_writer = csv.DictWriter(primary_handle, fieldnames=FIELDS)
        verifier_writer = csv.DictWriter(verifier_handle, fieldnames=FIELDS)
        primary_writer.writeheader()
        verifier_writer.writeheader()
        for class_id, class_name in enumerate(CLASSES):
            for index in range(16):
                mode = "auto" if index < 12 else "review"
                primary = _base_row(class_name, class_id, index, mode)
                center_x = 0.20 + (index % 6) * 0.12
                primary.update({"conf": f"{0.92 - index * 0.018:.3f}", "cx": f"{center_x:.3f}"})
                primary_writer.writerow(primary)

                if index < 12 and index % 3 != 0:
                    verifier = dict(primary)
                    verifier.update(
                        {
                            "conf": f"{0.88 - index * 0.014:.3f}",
                            "mode": "auto" if index % 2 else "review",
                            "cx": f"{center_x + (0.006 if index % 2 else -0.006):.3f}",
                        }
                    )
                    verifier_writer.writerow(verifier)
            # Add unrelated verifier evidence to prove image/class alignment is required.
            unrelated = _base_row(class_name, class_id, 99, "auto")
            unrelated.update({"conf": "0.940", "cx": "0.850"})
            verifier_writer.writerow(unrelated)
    print(primary_path.resolve())
    print(verifier_path.resolve())


if __name__ == "__main__":
    main()
