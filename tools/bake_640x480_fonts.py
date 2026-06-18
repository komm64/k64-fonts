#!/usr/bin/env python3
"""Bake the final 16px font set for the 640x480 monitor target.

This target is a square-dot 16px path, separate from the existing 640x240
tall-dot Reecho fonts.
"""
from __future__ import annotations

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
GAME = ROOT / "game" / "640x480"
WEB = ROOT / "web" / "640x480"
DOCS = ROOT / "docs" / "640x480"

sys.path.insert(0, str(ROOT / "tools"))
from bake_320x240_fonts import (  # noqa: E402
    FT_FLAGS,
    bake_pixel_outline_font,
    draw_shaped_run,
    save_ttf_and_woff2,
    set_line_metrics,
    set_names,
)

UPM_16 = 1600
DESCENT_16 = -400

OUT = {
    "j": (
        "k64-640x480-j-shinonome-mincho-16px",
        "K64 640x480 J Shinonome Mincho 16px",
    ),
    "ck": (
        "k64-640x480-ck-unifont-16px",
        "K64 640x480 CK Unifont 16px",
    ),
    "thai": (
        "k64-640x480-thai-light-16px",
        "K64 640x480 Thai Light 16px",
    ),
    "arabic": (
        "k64-640x480-arabic-light-16px",
        "K64 640x480 Arabic Light 16px",
    ),
}


def shift_glyf_y(tt: TTFont, dy: int) -> None:
    glyf = tt["glyf"]
    for glyph_name in tt.getGlyphOrder():
        glyph = glyf[glyph_name]
        if glyph.numberOfContours > 0:
            glyph.coordinates = type(glyph.coordinates)(
                [(x, y + dy) for x, y in glyph.coordinates]
            )
            glyph.recalcBounds(glyf)
        elif glyph.numberOfContours < 0:
            for component in glyph.components:
                component.y += dy
            glyph.recalcBounds(glyf)
    tt["head"].yMin += dy
    tt["head"].yMax += dy


def fix_shinonome_16px() -> tuple[Path, Path]:
    source = SRC / "JF-Dot-ShinonomeMin16.ttf"
    tt = TTFont(source)
    upm = tt["head"].unitsPerEm
    set_line_metrics(tt, upm, 0)
    if "EBLC" in tt:
        for strike in tt["EBLC"].strikes:
            hori = strike.bitmapSizeTable.hori
            hori.ascender = 16
            hori.descender = 0
            hori.maxBeforeBL = 16
            hori.minAfterBL = 0
            for sub in strike.indexSubTables:
                metrics = getattr(sub, "metrics", None)
                if metrics is not None and getattr(metrics, "height", None) == 16:
                    metrics.horiBearingY = 16
    stem, family = OUT["j"]
    set_names(tt, family, "K64640x480JShinonomeMincho16px-Regular")
    return save_ttf_and_woff2(tt, stem, game_dir=GAME, web_dir=WEB)


def fix_unifont_16px() -> tuple[Path, Path]:
    source = SRC / "unifont-16px.ttf"
    tt = TTFont(source)
    upm = tt["head"].unitsPerEm
    shift_glyf_y(tt, upm // 8)
    set_line_metrics(tt, upm, 0)
    if "OS/2" in tt:
        tt["OS/2"].usWinAscent = upm
        tt["OS/2"].usWinDescent = 0
    stem, family = OUT["ck"]
    set_names(tt, family, "K64640x480CKUnifont16px-Regular")
    return save_ttf_and_woff2(tt, stem, transform_tables=False, game_dir=GAME, web_dir=WEB)


def bake_thai_16px() -> tuple[Path, Path]:
    stem, family = OUT["thai"]
    return bake_pixel_outline_font(
        SRC / "NotoSansThai-Light.ttf",
        stem,
        family,
        "K64640x480ThaiLight16px-Regular",
        base_size=16,
        mark_size=16,
        upm=UPM_16,
        thai_mark16=True,
        descent=DESCENT_16,
        game_dir=GAME,
        web_dir=WEB,
    )


def bake_arabic_16px() -> tuple[Path, Path]:
    stem, family = OUT["arabic"]
    return bake_pixel_outline_font(
        SRC / "NotoSansArabic-Light.ttf",
        stem,
        family,
        "K64640x480ArabicLight16px-Regular",
        base_size=16,
        mark_size=16,
        upm=UPM_16,
        thai_mark16=False,
        descent=DESCENT_16,
        game_dir=GAME,
        web_dir=WEB,
    )


def make_preview(paths: dict[str, Path]) -> Path:
    DOCS.mkdir(parents=True, exist_ok=True)
    out = DOCS / "preview.png"
    img = Image.new("RGB", (640, 480), "white")
    draw = ImageDraw.Draw(img)
    label = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 8)
    title = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 12)
    draw.text((16, 10), "K64 640x480 square-dot target", fill=(0, 0, 0), font=title)
    draw.text((16, 42), "K64 16px target stack", fill=(70, 70, 70), font=label)
    for y in (104, 168, 232):
        draw.line((16, y, 624, y), fill=(210, 235, 255))

    x = 16
    baseline = 88
    x = draw_shaped_run(img, paths["j"], "日本語 ", x, baseline, 16) + 8
    x = draw_shaped_run(img, paths["ck"], "你好 한국어 ", x, baseline, 16, lang="ko") + 8
    x = draw_shaped_run(img, paths["thai"], "กา กิ กี ก่ ก้ ", x, baseline, 16, lang="th") + 8
    draw_shaped_run(img, paths["arabic"], "السلام ١٢٣", x, baseline, 16, lang="ar", direction="rtl")

    draw.text((16, 126), "Thai marks", fill=(70, 70, 70), font=label)
    draw_shaped_run(
        img,
        paths["thai"],
        "กา กิ กี กึ กื กุ กู เก แก ก่ ก้ ก๊ ก๋ ก์ ก่ำ ก้ำ กึ่ กื้",
        16,
        152,
        16,
        lang="th",
    )

    draw.text((16, 190), "Arabic shaping", fill=(70, 70, 70), font=label)
    draw_shaped_run(
        img,
        paths["arabic"],
        "السلام عليكم مرحبا بالعالم ١٢٣٤",
        16,
        216,
        16,
        lang="ar",
        direction="rtl",
    )

    img.resize((1280, 960), Image.Resampling.NEAREST).save(out)
    return out


def main() -> int:
    outputs = {
        "j": fix_shinonome_16px()[0],
        "ck": fix_unifont_16px()[0],
        "thai": bake_thai_16px()[0],
        "arabic": bake_arabic_16px()[0],
    }
    preview = make_preview(outputs)
    print("wrote 640x480 fonts:")
    for path in outputs.values():
        print(f"  {path.relative_to(ROOT)}")
    print(f"  {preview.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
