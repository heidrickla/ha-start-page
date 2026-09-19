"""Draw the add-on's icon.png (128x128), logo.png (256x100) and the page glyph.

    python brand/make_brand.py

A house with an open door: the page is the front door to the house's services.
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.join(HERE, "..", "start_page")
NAVY = (16, 16, 20, 255)
BLUE = (79, 179, 232, 255)
BONE = (232, 227, 216, 255)


def house(size: int) -> Image.Image:
    """The mark on a rounded navy tile, drawn at 4x and downsampled."""
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=s // 5, fill=NAVY)
    w = s * 0.62
    x0 = (s - w) / 2
    roof_y = s * 0.24
    wall_top = s * 0.50
    base = s * 0.80
    stroke = max(2, s // 22)
    # roof
    d.polygon([(x0 - stroke, wall_top), (s / 2, roof_y), (x0 + w + stroke, wall_top)], fill=BLUE)
    d.polygon(
        [
            (x0 + stroke * 1.6, wall_top),
            (s / 2, roof_y + stroke * 2.2),
            (x0 + w - stroke * 1.6, wall_top),
        ],
        fill=NAVY,
    )
    # walls
    d.rectangle((x0, wall_top - stroke / 2, x0 + w, base), outline=BLUE, width=stroke)
    # open door, lit
    dw = w * 0.26
    dx = s / 2 - dw / 2
    d.rectangle((dx, base - s * 0.22, dx + dw, base), fill=BONE)
    return img.resize((size, size), Image.LANCZOS)


def logo() -> Image.Image:
    img = Image.new("RGBA", (256, 100), (0, 0, 0, 0))
    mark = house(84)
    img.alpha_composite(mark, (8, 8))
    d = ImageDraw.Draw(img)
    # Wordmark drawn as bars, not text: no font dependency, and it stays
    # legible at the size the add-on store shows it.
    x = 108
    for i, width in enumerate((120, 84, 100)):
        y = 28 + i * 18
        d.rounded_rectangle((x, y, x + width, y + 10), radius=5, fill=BLUE if i == 0 else BONE)
    return img


def main() -> None:
    house(128).save(os.path.join(ADDON, "icon.png"))
    logo().save(os.path.join(ADDON, "logo.png"))
    house(64).save(os.path.join(ADDON, "www", "glyph.png"))
    for name in ("icon.png", "logo.png", os.path.join("www", "glyph.png")):
        path = os.path.join(ADDON, name)
        with Image.open(path) as im:
            print(f"{name}: {im.size[0]}x{im.size[1]} {os.path.getsize(path)} bytes")


if __name__ == "__main__":
    main()
