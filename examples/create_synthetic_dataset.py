"""Create a tiny, intentionally flawed YOLO dataset for the public audit demo."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from PIL import Image, ImageDraw


def scene(path: Path, color: str, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (320, 220), "#e8eef3")
    draw = ImageDraw.Draw(image)
    draw.rectangle((90, 35, 220, 205), fill=color, outline="#08233d", width=4)
    draw.text((104, 98), label, fill="white")
    image.save(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".demo-dataset"))
    args = parser.parse_args()
    root = args.output.expanduser().resolve()
    if root.exists():
        raise FileExistsError(f"{root} exists; choose a new output path")

    root.mkdir(parents=True)
    (root / "data.yaml").write_text("nc: 2\nnames: [person, helmet]\n", encoding="utf-8")

    train = root / "images" / "train" / "worker.png"
    scene(train, "#1976a3", "worker")
    label = root / "labels" / "train" / "worker.txt"
    label.parent.mkdir(parents=True)
    label.write_text("0 0.484375 0.545455 0.40625 0.772727\n", encoding="utf-8")

    background = root / "images" / "train" / "background.png"
    scene(background, "#7f98a8", "background")

    leaked = root / "images" / "val" / "worker-copy.png"
    leaked.parent.mkdir(parents=True)
    shutil.copy2(train, leaked)
    leaked_label = root / "labels" / "val" / "worker-copy.txt"
    leaked_label.parent.mkdir(parents=True)
    leaked_label.write_text("0 0.484375 0.545455 0.40625 0.772727\n", encoding="utf-8")

    bad = root / "images" / "test" / "bad-class.png"
    scene(bad, "#d18a22", "bad class id")
    bad_label = root / "labels" / "test" / "bad-class.txt"
    bad_label.parent.mkdir(parents=True)
    bad_label.write_text("7 0.5 0.5 0.4 0.6\n", encoding="utf-8")
    (root / "labels" / "test" / "orphan.txt").write_text("1 0.5 0.5 0.2 0.2\n", encoding="utf-8")
    print(root)


if __name__ == "__main__":
    main()
