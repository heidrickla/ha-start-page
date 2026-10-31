"""Build the app icon, logo and page glyph from brand/icon-source.png.

python brand/make_brand.py

"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON = os.path.join(HERE, "..", "start_page")
BLUE = (79, 179, 232, 255)
BONE = (232, 227, 216, 255)


def house(size: int) -> Image.Image:
    """Resize the approved mark for the app and page glyph."""
    with Image.open(os.path.join(HERE, "icon-source.png")) as source:
        return source.convert("RGBA").resize((size, size), Image.LANCZOS)


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
