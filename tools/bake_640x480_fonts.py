#!/usr/bin/env python3
"""Bake the final font set for the 640x480 monitor target.

This target is a square-dot 16px path, separate from the existing 640x240
tall-dot Reecho fonts.  Japanese and CK keep their native 16px pixel cells,
both placed 14px above / 2px below the shared roman baseline.  Mixed K64F/CJK
text uses a 20px line advance so the full CJK cell never touches another row.
"""
from __future__ import annotations

import sys
from array import array
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import freetype
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.scaleUpem import scale_upem
from fontTools.ttLib.tables.ttProgram import Program
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
GAME = ROOT / "game" / "640x480"
WEB = ROOT / "web" / "640x480"
DOCS = ROOT / "docs" / "640x480"
sys.path.insert(0, str(ROOT / "tools"))
from bake_320x240_fonts import (  # noqa: E402
    bake_pixel_outline_font,
    draw_shaped_run,
    emit_bitmap_glyph,
    glyph_bbox,
    render_gid,
    save_ttf_and_woff2,
    set_line_metrics,
    set_names,
)

UPM_16 = 1600
CJK_ASCENT = 14
CJK_DESCENT = 2
DESCENT_4 = -400

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


def bake_shinonome_16px() -> tuple[Path, Path]:
    source = SRC / "JF-Dot-ShinonomeMin16.ttf"
    if not source.exists():
        raise FileNotFoundError(source)

    stem, family = OUT["j"]

    # Godot/FreeType can use Shinonome's native 16px 1bpp strike.  Preserve
    # its 14px-above / 2px-below placement; only normalize the line metrics.
    game_tt = TTFont(source)
    game_upm = game_tt["head"].unitsPerEm
    set_line_metrics(
        game_tt,
        round(game_upm * CJK_ASCENT / 16),
        -round(game_upm * CJK_DESCENT / 16),
    )
    set_names(game_tt, family, "K64640x480JShinonomeMincho16px-Regular")
    game_tt["head"].modified = game_tt["head"].created
    game_tt.recalcTimestamp = False
    game_path = GAME / f"{stem}.ttf"
    game_tt.save(game_path)

    # Chromium does not reliably use Shinonome's embedded 1bpp strike.  Build
    # pixel-square outlines from that same 16px strike for identical geometry.
    face = freetype.Face(str(source))
    web_tt = TTFont(source)
    scale_upem(web_tt, UPM_16)
    glyph_order = web_tt.getGlyphOrder()
    glyf = web_tt["glyf"]
    hmtx = web_tt["hmtx"].metrics
    for table in ("fpgm", "prep", "cvt ", "EBDT", "EBLC"):
        if table in web_tt:
            del web_tt[table]

    pixel_hint_program = [0xB0, 0x00, 0x85, 0x00]
    prep = newTable("prep")
    prep.program = Program()
    prep.program.fromBytecode(pixel_hint_program)
    web_tt["prep"] = prep
    cvt = newTable("cvt ")
    cvt.values = array("h", [0])
    web_tt["cvt "] = cvt

    for gid, glyph_name in enumerate(glyph_order):
        rendered = render_gid(face, gid, 16)
        glyph = emit_bitmap_glyph(rendered)
        glyph.program = Program()
        glyph.program.fromBytecode(pixel_hint_program)
        glyf[glyph_name] = glyph
        box = glyph_bbox(glyph)
        hmtx[glyph_name] = (
            max(0, int(round(rendered.advance * 100))),
            box[0] if box else 0,
        )

    web_tt["head"].unitsPerEm = UPM_16
    web_tt["head"].yMin = -CJK_DESCENT * 100
    web_tt["head"].yMax = CJK_ASCENT * 100
    web_tt["hhea"].advanceWidthMax = max(advance for advance, _lsb in hmtx.values())
    set_line_metrics(web_tt, CJK_ASCENT * 100, -CJK_DESCENT * 100)
    if "maxp" in web_tt:
        maxp = web_tt["maxp"]
        maxp.maxZones = 1
        maxp.maxTwilightPoints = 0
        maxp.maxStorage = 0
        maxp.maxFunctionDefs = 0
        maxp.maxInstructionDefs = 0
        maxp.maxStackElements = 1
        maxp.maxSizeOfInstructions = len(pixel_hint_program)
    set_names(web_tt, family, "K64640x480JShinonomeMincho16pxPixel-Regular")
    web_tt["head"].modified = web_tt["head"].created
    web_tt.recalcTimestamp = False
    web_tt.flavor = "woff2"
    web_path = WEB / f"{stem}.woff2"
    web_tt.save(web_path)
    return game_path, web_path


def bake_unifont_16px() -> tuple[Path, Path]:
    source = SRC / "unifont-16px.ttf"
    if not source.exists():
        raise FileNotFoundError(source)

    stem, family = OUT["ck"]
    tt = TTFont(source)
    upm = tt["head"].unitsPerEm
    # Do not shift the outlines.  Unifont's native 16px geometry already uses
    # the same 14px-above / 2px-below ideographic placement as Shinonome.
    set_line_metrics(
        tt,
        round(upm * CJK_ASCENT / 16),
        -round(upm * CJK_DESCENT / 16),
    )
    set_names(tt, family, "K64640x480CKUnifont16px-Regular")
    return save_ttf_and_woff2(
        tt,
        stem,
        transform_tables=False,
        game_dir=GAME,
        web_dir=WEB,
    )


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
        descent=DESCENT_4,
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
        descent=DESCENT_4,
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
    draw.text((16, 42), "K64F 16px / native 16px CJK / 20px rows", fill=(70, 70, 70), font=label)
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
        "j": bake_shinonome_16px()[0],
        "ck": bake_unifont_16px()[0],
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
