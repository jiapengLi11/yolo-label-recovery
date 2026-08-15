"""Create deterministic reviewed candidates for the public threshold-calibration demo."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

CLASS_POLICY = {
    "person": (0.78, 0.50, 5),
    "helmet": (0.80, 0.52, 5),
    "vest": (0.82, 0.55, 4),
    "tractor": (0.76, 0.48, 6),
    "slipper": (0.84, 0.50, 3),
    "smoking": (0.86, 0.46, 3),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("examples/calibration/reviewed_candidates.csv"))
    parser.add_argument("--samples-per-class", type=int, default=400)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.samples_per_class < 30:
        raise ValueError("samples-per-class must be at least 30 for a meaningful fixture.")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ["candidate_id", "class_name", "conf", "verdict", "split", "max_iou_same_class"]
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for class_index, (class_name, (clean_floor, useful_floor, mid_period)) in enumerate(CLASS_POLICY.items()):
            for index in range(args.samples_per_class):
                confidence = 0.30 + 0.69 * index / (args.samples_per_class - 1)
                if confidence >= clean_floor:
                    accepted = True
                elif confidence >= useful_floor:
                    accepted = (index + class_index) % mid_period != 0
                else:
                    accepted = (index + 2 * class_index) % 8 == 0
                writer.writerow(
                    {
                        "candidate_id": f"{class_name}-{index:04d}",
                        "class_name": class_name,
                        "conf": f"{confidence:.4f}",
                        "verdict": "accept" if accepted else "reject",
                        "split": ("train", "val", "test")[index % 3],
                        "max_iou_same_class": f"{0.02 + 0.21 * ((index * 7 + class_index) % 19) / 18:.4f}",
                    }
                )
    print(args.output.resolve())


if __name__ == "__main__":
    main()
