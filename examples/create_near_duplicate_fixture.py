"""Create a deterministic public fixture for perceptual near-duplicate grouping."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance


def _mine_scene() -> Image.Image:
    image = Image.new("RGB", (640, 420), "#bcd4ce")
    draw = ImageDraw.Draw(image)
    for y in range(420):
        draw.line((0, y, 639, y), fill=(45 + y // 4, 75 + y // 5, 72 + y // 6))
    draw.polygon(((0, 320), (180, 230), (360, 305), (520, 185), (639, 260), (639, 419), (0, 419)), fill="#9a633a")
    draw.rectangle((205, 185, 440, 315), fill="#e8a92c", outline="#182f36", width=10)
    draw.ellipse((225, 285, 305, 365), fill="#172d34")
    draw.ellipse((365, 285, 445, 365), fill="#172d34")
    draw.line((435, 205, 565, 100), fill="#e8a92c", width=28)
    draw.line((555, 110, 600, 170), fill="#263b40", width=16)
    return image


def _worker_scene() -> Image.Image:
    image = Image.new("RGB", (480, 640), "#e7e1d3")
    draw = ImageDraw.Draw(image)
    draw.rectangle((155, 115, 330, 515), fill="#f2b735", outline="#173a45", width=12)
    draw.ellipse((170, 35, 315, 180), fill="#edc348", outline="#173a45", width=10)
    draw.rectangle((165, 245, 320, 285), fill="#d9f05a")
    draw.line((155, 360, 330, 360), fill="#d9f05a", width=18)
    draw.line((195, 510, 130, 625), fill="#203a55", width=35)
    draw.line((285, 510, 345, 625), fill="#203a55", width=35)
    return image


def _tractor_scene() -> Image.Image:
    image = Image.new("RGB", (560, 360), "#acd7e5")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 250, 559, 359), fill="#7f9d44")
    draw.rectangle((115, 165, 410, 280), fill="#bf342d", outline="#192c33", width=9)
    draw.rectangle((250, 75, 390, 185), fill="#dde6dc", outline="#192c33", width=8)
    draw.ellipse((135, 245, 245, 355), fill="#192c33", outline="#e4d7a7", width=8)
    draw.ellipse((345, 240, 475, 359), fill="#192c33", outline="#e4d7a7", width=8)
    return image


def create_fixture(output: Path, force: bool = False) -> Path:
    output = output.expanduser().resolve()
    if output.exists():
        if not force:
            raise FileExistsError(f"{output} already exists; pass --force to replace it")
        shutil.rmtree(output)
    for split in ("train", "val", "test"):
        (output / "images" / split).mkdir(parents=True)

    mine = _mine_scene()
    mine.save(output / "images" / "train" / "mine_original.png")
    mine.resize((960, 630), Image.Resampling.LANCZOS).save(output / "images" / "val" / "mine_resized.jpg", quality=82)
    ImageEnhance.Brightness(mine).enhance(1.10).save(output / "images" / "test" / "mine_brighter.jpg", quality=88)

    worker = _worker_scene()
    worker.save(output / "images" / "train" / "worker_original.png")
    worker.resize((360, 480), Image.Resampling.LANCZOS).save(output / "images" / "train" / "worker_web.jpg", quality=78)

    tractor = _tractor_scene()
    tractor.save(output / "images" / "val" / "tractor.png")
    tractor.save(output / "images" / "test" / "tractor_exact_copy.png")

    unique = Image.new("RGB", (640, 420), "#ede7d5")
    unique_draw = ImageDraw.Draw(unique)
    for x in range(0, 640, 32):
        unique_draw.rectangle((x, 0, x + 15, 419), fill="#29445d")
    unique.save(output / "images" / "test" / "unique_stripes.png")
    Image.new("RGB", (320, 240), "black").save(output / "images" / "train" / "black_frame.png")
    Image.new("RGB", (320, 240), "white").save(output / "images" / "train" / "white_frame.png")
    (output / "images" / "test" / "corrupt.jpg").write_bytes(b"intentional corrupt fixture")
    (output / "data.yaml").write_text(
        "path: .\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: object\n",
        encoding="utf-8",
    )
    print(output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    create_fixture(args.output, args.force)


if __name__ == "__main__":
    main()
