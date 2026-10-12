r"""Board PNGs side by side on one sheet, each captioned with its file name.

  .venv\Scripts\python scripts\contact_sheet.py <png dir> <out.png> [columns] [scale]
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw


def sheet(pngs: list[Path], out: Path, cols: int = 3, scale: float = 0.5) -> None:
    tiles = [Image.open(p).convert("RGB") for p in pngs]
    tiles = [t.resize((int(t.width * scale), int(t.height * scale))) for t in tiles]
    w, h = max(t.width for t in tiles), max(t.height for t in tiles) + 16
    rows = (len(tiles) + cols - 1) // cols
    img = Image.new("RGB", (cols * w, rows * h), (12, 12, 16))
    draw = ImageDraw.Draw(img)
    for k, (p, t) in enumerate(zip(pngs, tiles)):
        x, y = (k % cols) * w, (k // cols) * h
        img.paste(t, (x, y + 16))
        draw.text((x + 4, y + 2), p.stem, fill=(255, 220, 120))
    img.save(out)


if __name__ == "__main__":
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    cols = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    scale = float(sys.argv[4]) if len(sys.argv) > 4 else 0.5
    sheet(sorted(src.glob("*.png")), dst, cols, scale)
    print(dst)
