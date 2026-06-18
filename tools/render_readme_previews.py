#!/usr/bin/env python3
"""Render README preview images for both monitor targets."""
from __future__ import annotations

import sys
from pathlib import Path

import freetype
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SRC = ROOT / "src"
GAME = ROOT / "game"
WIN_FONTS = Path("C:/Windows/Fonts")

sys.path.insert(0, str(ROOT / "tools"))
from bake_320x240_fonts import FT_FLAGS, bitmap_rows, shape_gids  # noqa: E402

SAMPLES = {
    "latin": "HP 0123 / MENU",
    "cjk_j": "日本語 ",
    "cjk_c": "你好 ",
    "cjk_k": "한국어",
    "thai": "กา กิ กี ก่ ก้",
    "arabic": "السلام ١٢٣",
}


def label_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(WIN_FONTS / "arial.ttf"), size)


def shaped_width(font_path: Path, text: str, size: int, x_scale=1, lang=None, direction=None) -> int:
    shaped = shape_gids(font_path, text, size, lang=lang, direction=direction)
    width = sum(pos.x_advance for _, pos in shaped) / 64.0
    return int(round(width * x_scale))


def draw_run(img: Image.Image, font_path: Path, text: str, x: int, baseline: int,
             size: int, *, x_scale=1, y_scale=1, lang=None, direction=None,
             load_flags=FT_FLAGS) -> int:
    face = freetype.Face(str(font_path))
    shaped = shape_gids(font_path, text, size, lang=lang, direction=direction)
    pen_x = float(x)
    pix = img.load()
    for info, pos in shaped:
        gid = info.codepoint
        face.set_pixel_sizes(0, size)
        face.load_glyph(gid, load_flags)
        glyph = face.glyph
        rows = bitmap_rows(glyph.bitmap)
        gx = int(round(pen_x + (pos.x_offset / 64.0 + glyph.bitmap_left) * x_scale))
        gy = int(round(baseline - (pos.y_offset / 64.0 + glyph.bitmap_top) * y_scale))
        for yy, row in enumerate(rows):
            py0 = gy + yy * y_scale
            for xx, ink in enumerate(row):
                if not ink:
                    continue
                px0 = gx + xx * x_scale
                for dy in range(y_scale):
                    py = py0 + dy
                    if not 0 <= py < img.height:
                        continue
                    for dx in range(x_scale):
                        px = px0 + dx
                        if 0 <= px < img.width:
                            pix[px, py] = (0, 0, 0)
        pen_x += (pos.x_advance / 64.0) * x_scale
    return int(round(pen_x))


def draw_sequence(img: Image.Image, runs: list[tuple[Path, str, int, int, int, str | None, int]],
                  x: int, baseline: int) -> int:
    pen_x = x
    for font_path, text, size, x_scale, y_scale, lang, load_flags in runs:
        pen_x = draw_run(
            img, font_path, text, pen_x, baseline, size,
            x_scale=x_scale, y_scale=y_scale, lang=lang, load_flags=load_flags,
        )
    return pen_x


def draw_rtl(img: Image.Image, font_path: Path, text: str, right: int, baseline: int,
             size: int, *, x_scale=1, y_scale=1, lang="ar") -> int:
    width = shaped_width(font_path, text, size, x_scale=x_scale, lang=lang, direction="rtl")
    return draw_run(
        img, font_path, text, right - width, baseline, size,
        x_scale=x_scale, y_scale=y_scale, lang=lang, direction="rtl",
    )


def upscale(img: Image.Image, scale: int) -> Image.Image:
    return img.resize((img.width * scale, img.height * scale), Image.Resampling.NEAREST)


def draw_frame(img: Image.Image, title: str, left_x: int, right_x: int,
               header_y: int, label_size: int) -> ImageDraw.ImageDraw:
    draw = ImageDraw.Draw(img)
    draw.text((left_x, 6 if img.width == 640 else 5), title, fill=(0, 0, 0), font=label_font(label_size + 3))
    draw.text((left_x, header_y), "Default font", fill=(70, 70, 70), font=label_font(label_size))
    draw.text((right_x, header_y), "K64 target font", fill=(70, 70, 70), font=label_font(label_size))
    return draw


def render_640() -> Path:
    out = DOCS / "640x240" / "preview.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (640, 240), "white")
    draw = draw_frame(img, "K64 640x240 tall-dot target", 16, 330, 24, 8)
    defaults = {
        "latin": WIN_FONTS / "arial.ttf",
        "cjk_j": WIN_FONTS / "YuGothR.ttc",
        "cjk_k": WIN_FONTS / "malgun.ttf",
        "thai": WIN_FONTS / "tahoma.ttf",
        "arabic": WIN_FONTS / "tahoma.ttf",
    }
    k64 = {
        "latin": SRC / "komm64Fantasy.ttf",
        "j": SRC / "JF-Dot-ShinonomeMin16_12px_or1.ttf",
        "cjk": SRC / "unifont-16px_12px_or1.ttf",
        "thai": GAME / "k64-thai-pixel-12w-or12-y1-prop.ttf",
        "arabic": GAME / "k64-arabic-sans-medium-pixel-20px-thin-y1.ttf",
    }
    rows = [("Latin", 64), ("J / CJK", 110), ("Thai", 154), ("Arabic", 210)]
    for _label, baseline in rows:
        draw.line((16, baseline + 14, 624, baseline + 14), fill=(210, 235, 255))

    draw_run(img, defaults["latin"], SAMPLES["latin"], 16, rows[0][1], 32)
    draw_run(img, k64["latin"], SAMPLES["latin"], 330, rows[0][1], 16, x_scale=2, y_scale=2)

    draw_sequence(
        img,
        [
            (defaults["cjk_j"], SAMPLES["cjk_j"], 32, 1, 1, None, FT_FLAGS),
            (defaults["cjk_j"], SAMPLES["cjk_c"], 32, 1, 1, None, FT_FLAGS),
            (defaults["cjk_k"], SAMPLES["cjk_k"], 32, 1, 1, "ko", FT_FLAGS),
        ],
        16,
        rows[1][1],
    )
    draw_sequence(
        img,
        [
            (k64["j"], SAMPLES["cjk_j"], 16, 1, 2, None, FT_FLAGS | freetype.FT_LOAD_NO_BITMAP),
            (k64["cjk"], SAMPLES["cjk_c"], 16, 1, 2, None, FT_FLAGS),
            (k64["cjk"], SAMPLES["cjk_k"], 16, 1, 2, "ko", FT_FLAGS),
        ],
        330,
        rows[1][1],
    )

    draw_run(img, defaults["thai"], SAMPLES["thai"], 16, rows[2][1], 32, lang="th")
    draw_run(img, k64["thai"], SAMPLES["thai"], 330, rows[2][1], 16, y_scale=2, lang="th")

    draw_rtl(img, defaults["arabic"], SAMPLES["arabic"], 310, rows[3][1], 32)
    draw_rtl(img, k64["arabic"], SAMPLES["arabic"], 624, rows[3][1], 20, y_scale=2)

    upscale(img, 2).save(out)
    return out


def render_320() -> Path:
    out = DOCS / "320x240" / "preview.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (320, 240), "white")
    draw = draw_frame(img, "K64 320x240 square-dot target", 8, 168, 24, 6)
    defaults = {
        "latin": WIN_FONTS / "arial.ttf",
        "cjk_j": WIN_FONTS / "YuGothR.ttc",
        "cjk_k": WIN_FONTS / "malgun.ttf",
        "thai": WIN_FONTS / "tahoma.ttf",
        "arabic": WIN_FONTS / "tahoma.ttf",
    }
    base = GAME / "320x240"
    k64 = {
        "j": base / "k64-320-j-shinonome-mincho-12px.ttf",
        "cjk": base / "k64-320-cjk-fallback-12px.ttf",
        "thai": base / "k64-320-thai-light-12px-mark16-max2.ttf",
        "arabic": base / "k64-320-arabic-light-12px.ttf",
    }
    rows = [("Latin", 56), ("J / CJK", 100), ("Thai", 144), ("Arabic", 198)]
    for _label, baseline in rows:
        draw.line((8, baseline + 12, 312, baseline + 12), fill=(210, 235, 255))

    draw_run(img, defaults["latin"], SAMPLES["latin"], 8, rows[0][1], 12)
    draw_run(img, k64["j"], SAMPLES["latin"], 168, rows[0][1], 12)

    draw_sequence(
        img,
        [
            (defaults["cjk_j"], SAMPLES["cjk_j"], 12, 1, 1, None, FT_FLAGS),
            (defaults["cjk_j"], SAMPLES["cjk_c"], 12, 1, 1, None, FT_FLAGS),
            (defaults["cjk_k"], SAMPLES["cjk_k"], 12, 1, 1, "ko", FT_FLAGS),
        ],
        8,
        rows[1][1],
    )
    draw_sequence(
        img,
        [
            (k64["j"], SAMPLES["cjk_j"], 12, 1, 1, None, FT_FLAGS),
            (k64["cjk"], SAMPLES["cjk_c"], 12, 1, 1, None, FT_FLAGS),
            (k64["cjk"], SAMPLES["cjk_k"], 12, 1, 1, "ko", FT_FLAGS),
        ],
        168,
        rows[1][1],
    )

    draw_run(img, defaults["thai"], SAMPLES["thai"], 8, rows[2][1], 12, lang="th")
    draw_run(img, k64["thai"], SAMPLES["thai"], 168, rows[2][1], 12, lang="th")

    draw_rtl(img, defaults["arabic"], SAMPLES["arabic"], 152, rows[3][1], 12)
    draw_rtl(img, k64["arabic"], SAMPLES["arabic"], 312, rows[3][1], 12)

    upscale(img, 4).save(out)
    return out


def main() -> int:
    for renderer in (render_640, render_320):
        preview = renderer()
        print(f"wrote {preview.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
