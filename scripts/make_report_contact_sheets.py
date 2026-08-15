from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def font(size: int):
    path = Path("C:/Windows/Fonts/arial.ttf")
    return ImageFont.truetype(str(path), size) if path.is_file() else ImageFont.load_default()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--per-sheet", type=int, default=6)
    args = parser.parse_args()
    pages = sorted(args.input_dir.glob("page-*.png"), key=lambda p: int(p.stem.split("-")[-1]))
    if not pages:
        raise SystemExit("no page PNGs")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise SystemExit("output_dir must be new and empty")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    thumb_width = 390
    label_height = 38
    gap = 24
    columns = 2
    rows = (args.per_sheet + columns - 1) // columns
    for offset in range(0, len(pages), args.per_sheet):
        chunk = pages[offset : offset + args.per_sheet]
        with Image.open(chunk[0]) as first:
            ratio = first.height / first.width
        thumb_height = int(thumb_width * ratio)
        canvas = Image.new(
            "RGB",
            (
                columns * thumb_width + (columns + 1) * gap,
                rows * (thumb_height + label_height) + (rows + 1) * gap,
            ),
            "#DDE2E7",
        )
        draw = ImageDraw.Draw(canvas)
        for index, page in enumerate(chunk):
            row, column = divmod(index, columns)
            x = gap + column * (thumb_width + gap)
            y = gap + row * (thumb_height + label_height + gap)
            with Image.open(page) as image:
                thumb = image.convert("RGB")
                thumb.thumbnail((thumb_width, thumb_height))
                canvas.paste(thumb, (x, y))
            page_number = int(page.stem.split("-")[-1])
            draw.text((x, y + thumb_height + 6), f"Trang {page_number}", font=font(22), fill="#18324A")
        sheet_number = (offset // args.per_sheet) + 1
        canvas.save(args.output_dir / f"contact-{sheet_number}.png", optimize=True)
    print(f"SHEETS={(len(pages) + args.per_sheet - 1) // args.per_sheet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
