"""Create a deterministic six-class fixture for active review prioritization."""

from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance

CLASS_COUNTS = {"person": 10, "helmet": 8, "vest": 6, "tractor": 5, "slipper": 4, "smoking": 3}
COLORS = ["#287c8e", "#e5aa35", "#8abf45", "#bd493d", "#7b5ca7", "#d06b91"]


def _scene(class_index: int, group: int) -> Image.Image:
    image = Image.new("RGB", (480, 320), "#e9e4d8")
    draw = ImageDraw.Draw(image)
    color = COLORS[class_index]
    offset = 18 * (group % 5)
    draw.rectangle((30 + offset, 35, 250 + offset, 265), fill=color, outline="#173440", width=10)
    draw.ellipse((245 - offset // 2, 70 + offset // 3, 430 - offset // 2, 255 + offset // 3), fill="#f0c35c", outline="#173440", width=8)
    draw.line((15, 295 - offset, 455, 25 + offset), fill="#213d52", width=12)
    for step in range(class_index + 1):
        x = 25 + step * 42
        draw.polygon(((x, 18), (x + 16, 48), (x - 16, 48)), fill="#f7f1df")
    return image


def create_fixture(output_dir: Path, force: bool = False) -> Path:
    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists():
        if not force:
            raise FileExistsError(f"{output_dir} already exists; pass --force to replace it")
        shutil.rmtree(output_dir)
    dataset = output_dir / "dataset"
    image_root = dataset / "images" / "train"
    image_root.mkdir(parents=True)
    rows = []
    for class_index, (class_name, count) in enumerate(CLASS_COUNTS.items()):
        for index in range(count):
            base = _scene(class_index, index // 2)
            filename = f"{class_name}_{index:02d}.{'png' if index % 2 == 0 else 'jpg'}"
            path = image_root / filename
            if index % 2:
                ImageEnhance.Brightness(base.resize((720, 480))).enhance(1.05).save(path, quality=82)
            else:
                base.save(path)
            confidence = 0.40 + ((index * 7 + class_index * 3) % 30) / 100
            rows.append(["train", filename, class_name, f"{confidence:.2f}", "review", 0.5, 0.5, 0.2, 0.2])
    (dataset / "data.yaml").write_text(
        "path: .\ntrain: images/train\nval: images/train\nnames:\n"
        + "".join(f"  {index}: {name}\n" for index, name in enumerate(CLASS_COUNTS)),
        encoding="utf-8",
    )
    with (output_dir / "candidates_review.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["split", "image", "class_name", "conf", "mode", "cx", "cy", "w", "h"])
        writer.writerows(rows)
    print(output_dir)
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    create_fixture(args.output_dir, args.force)


if __name__ == "__main__":
    main()
