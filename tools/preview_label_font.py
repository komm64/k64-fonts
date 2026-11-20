"""Label font for the bake previews, on any OS.

The previews label their rows with a plain sans font. Arial is used where it
exists (Windows, so the checked-in previews stay the same), then DejaVu Sans
or Liberation Sans (Linux), then Pillow's built-in font.
"""
from __future__ import annotations

from PIL import ImageFont

_CANDIDATES = (
    "C:/Windows/Fonts/arial.ttf",
    "arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
)


def label_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)
