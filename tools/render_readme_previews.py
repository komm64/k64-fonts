#!/usr/bin/env python3
"""Render the target-specific README preview images."""
from __future__ import annotations

import sys
from pathlib import Path

import freetype
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
WEB = ROOT / "web"
GAME = ROOT / "game"

sys.path.insert(0, str(ROOT / "tools"))
from bake_320x240_fonts import FT_FLAGS, bitmap_rows, draw_shaped_run, shape_gids  # noqa: E402


def label_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype("C:/Windows/Fonts/arial.ttf", size)


def shaped_width(font_path: Path, text: str, size: int, lang=None, direction=None) -> int:
    shaped = shape_gids(font_path, text, size, lang=lang, direction=direction)
    width = sum(pos.x_advance for _, pos in shaped) / 64.0
    return int(round(width))


def draw_rtl(img: Image.Image, font_path: Path, text: str, right: int, baseline: int,
             size: int, lang="ar") -> int:
    width = shaped_width(font_path, text, size, lang=lang, direction="rtl")
    return draw_shaped_run(img, font_path, text, right - width, baseline, size, lang=lang, direction="rtl")


def draw_shaped_run_scaled(img: Image.Image, font_path: Path, text: str, x: int, baseline: int,
                           size: int, x_scale: int = 1, y_scale: int = 1,
                           lang=None, direction=None) -> int:
    face = freetype.Face(str(font_path))
    shaped = shape_gids(font_path, text, size, lang=lang, direction=direction)
    pen_x = float(x)
    pix = img.load()
    for info, pos in shaped:
        gid = info.codepoint
        face.set_pixel_sizes(0, size)
        face.load_glyph(gid, FT_FLAGS)
        g = face.glyph
        rows = bitmap_rows(g.bitmap)
        gx = int(round(pen_x + (pos.x_offset / 64.0 + g.bitmap_left) * x_scale))
        gy = int(round(baseline - (pos.y_offset / 64.0 + g.bitmap_top) * y_scale))
        for yy, row in enumerate(rows):
            py0 = gy + yy * y_scale
            for xx, ink in enumerate(row):
                if not ink:
                    continue
                px0 = gx + xx * x_scale
                for dy in range(y_scale):
                    py = py0 + dy
                    if not (0 <= py < img.height):
                        continue
                    for dx in range(x_scale):
                        px = px0 + dx
                        if 0 <= px < img.width:
                            pix[px, py] = (0, 0, 0)
        pen_x += (pos.x_advance / 64.0) * x_scale
    return int(round(pen_x))


def draw_rtl_scaled(img: Image.Image, font_path: Path, text: str, right: int, baseline: int,
                    size: int, x_scale: int = 1, y_scale: int = 1, lang="ar") -> int:
    width = shaped_width(font_path, text, size, lang=lang, direction="rtl") * x_scale
    return draw_shaped_run_scaled(
        img, font_path, text, right - width, baseline, size,
        x_scale=x_scale, y_scale=y_scale, lang=lang, direction="rtl",
    )


def upscale_nearest(img: Image.Image, scale: int) -> Image.Image:
    return img.resize((img.width * scale, img.height * scale), Image.Resampling.NEAREST)


def render_640(paths: dict[str, Path]) -> Path:
    out = DOCS / "640x240" / "preview.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (640, 240), "white")
    draw = ImageDraw.Draw(img)
    title = label_font(11)
    label = label_font(8)
    draw.text((8, 6), "K64 640x240 32px tall-dot font set", fill=(0, 0, 0), font=title)
    rows = [
        ("K64F", 48),
        ("J / CJK", 88),
        ("Thai 12w or12", 132),
        ("Arabic 20px thin", 188),
    ]
    for name, base in rows:
        draw.text((8, base - 36), name, fill=(70, 70, 70), font=label)
        draw.line((8, base + 8, 632, base + 8), fill=(210, 235, 255))

    draw_shaped_run_scaled(img, paths["k64f"], "HP 0123 / MENU / SCORE", 24, rows[0][1], 16, x_scale=2, y_scale=2)

    x = 24
    x = draw_shaped_run_scaled(img, paths["jp"], "日本語 こんにちは世界", x, rows[1][1], 16, y_scale=2) + 16
    draw_shaped_run_scaled(img, paths["cjk"], "中国語 敏捷的白狐 한국어", x, rows[1][1], 16, y_scale=2)

    draw_shaped_run_scaled(
        img,
        paths["thai"],
        "กา กิ กี กึ กื กุ กู เก แก ก่ ก้ ก๊ ก๋ ก์ ก่ำ ก้ำ",
        24,
        rows[2][1],
        16,
        y_scale=2,
        lang="th",
    )

    draw_shaped_run_scaled(img, paths["k64f"], "HP 0123", 24, rows[3][1], 16, x_scale=2, y_scale=2)
    draw_rtl_scaled(img, paths["arabic"], "السلام عليكم مرحبا بالعالم ١٢٣", 616, rows[3][1], 20, y_scale=2)

    upscale_nearest(img, 2).save(out)
    return out


def render_320() -> Path:
    out = DOCS / "320x240" / "preview.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (320, 240), "white")
    draw = ImageDraw.Draw(img)
    title = label_font(9)
    label = label_font(7)
    draw.text((6, 5), "K64 320x240 12px square-dot font set", fill=(0, 0, 0), font=title)
    paths = {
        "j": GAME / "320x240" / "k64-320-j-shinonome-mincho-12px.ttf",
        "cjk": GAME / "320x240" / "k64-320-cjk-fallback-12px.ttf",
        "thai": GAME / "320x240" / "k64-320-thai-light-12px-mark16-max2.ttf",
        "arabic": GAME / "320x240" / "k64-320-arabic-light-12px.ttf",
    }
    rows = [
        ("J / CJK", 34),
        ("Chinese / Korean", 70),
        ("Thai mark16 max2", 112),
        ("Arabic Light", 158),
        ("Dense mixed line", 202),
    ]
    for name, base in rows:
        draw.text((6, base - 28), name, fill=(70, 70, 70), font=label)
        draw.line((6, base + 6, 314, base + 6), fill=(210, 235, 255))

    x = 12
    x = draw_shaped_run(img, paths["j"], "日本語 いろはにほへと", x, rows[0][1], 12) + 8
    draw_shaped_run(img, paths["cjk"], "漢字", x, rows[0][1], 12)

    x = 12
    x = draw_shaped_run(img, paths["cjk"], "中国語 敏捷的白狐", x, rows[1][1], 12) + 8
    draw_shaped_run(img, paths["cjk"], "한국어 안녕하세요", x, rows[1][1], 12)

    draw_shaped_run(
        img,
        paths["thai"],
        "กา กิ กี กึ กื กุ กู เก แก ก่ ก้ ก๊ ก๋ ก์ ก่ำ ก้ำ",
        12,
        rows[2][1],
        12,
        lang="th",
    )

    draw_rtl(img, paths["arabic"], "السلام عليكم مرحبا بالعالم ١٢٣٤", 308, rows[3][1], 12)

    x = 12
    x = draw_shaped_run(img, paths["j"], "日本語", x, rows[4][1], 12) + 6
    x = draw_shaped_run(img, paths["cjk"], "天地玄黄", x, rows[4][1], 12) + 6
    x = draw_shaped_run(img, paths["thai"], "น้ำ", x, rows[4][1], 12, lang="th") + 6
    draw_rtl(img, paths["arabic"], "سلام", 308, rows[4][1], 12)

    upscale_nearest(img, 4).save(out)
    return out


def main() -> int:
    paths_640 = {
        "k64f": ROOT / "src" / "komm64Fantasy.ttf",
        "jp": ROOT / "src" / "JF-Dot-ShinonomeMin16_12px_or1.ttf",
        "cjk": ROOT / "src" / "unifont-16px_12px_or1.ttf",
        "thai": GAME / "k64-thai-pixel-12w-or12-y1-prop.ttf",
        "arabic": GAME / "k64-arabic-sans-medium-pixel-20px-thin-y1.ttf",
    }
    preview_640 = render_640(paths_640)
    preview_320 = render_320()
    print(f"wrote {preview_640.relative_to(ROOT)}")
    print(f"wrote {preview_320.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
