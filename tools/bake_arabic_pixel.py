#!/usr/bin/env python3
"""Bake Noto Sans Arabic Medium into a K64-style pixel font.

Arabic shaping substitutes Unicode characters with contextual glyphs, so this
tool rasterizes every glyph by glyph name rather than only cmap characters.
GSUB/GPOS are preserved and rescaled for the emitted pixel-outline glyphs.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
from fontTools.misc.transform import Transform
from fontTools.pens.freetypePen import FreeTypePen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import Glyph as TtGlyph
from PIL import Image, ImageDraw, ImageFont

from compress_y2x_to_y1 import compress as compress_y2x_to_y1

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "NotoSansArabic-Medium.ttf"
WEB_OUT = ROOT / "web" / "k64-arabic-sans-medium-pixel-y2x.woff2"
GAME_OUT = ROOT / "game" / "k64-arabic-sans-medium-pixel-y1.ttf"
PREVIEW_OUT = ROOT / "game" / "k64-arabic-sans-medium-pixel-y1.preview.png"

SRC_ROWS = 16
PX_X = 100
PX_Y_WEB = 200
UPM_WEB = 3200
THRESHOLD = 80
DEFAULT_TOP_UNITS = 1100
DEFAULT_BOTTOM_UNITS = -500


def glyph_bbox(glyph):
    if not hasattr(glyph, "xMin"):
        return None
    return glyph.xMin, glyph.yMin, glyph.xMax, glyph.yMax


def coords_bbox(glyph):
    coords = getattr(glyph, "coordinates", None)
    if coords is None or not coords:
        return None
    xs = [p[0] for p in coords]
    ys = [p[1] for p in coords]
    return min(xs), min(ys), max(xs), max(ys)


def emit_pixels(bitmap, asc_rows, x_shift_px=0, scanline="none", px_y=PX_Y_WEB):
    pen = TTGlyphPen(None)
    has_ink = False
    h, w = bitmap.shape
    for x in range(w):
        y = 0
        while y < h:
            if not bitmap[y, x]:
                y += 1
                continue
            y_end = y
            while scanline == "none" and y_end + 1 < h and bitmap[y_end + 1, x]:
                y_end += 1
            has_ink = True
            x0 = (x + x_shift_px) * PX_X
            x1 = (x + 1 + x_shift_px) * PX_X
            y_top = (asc_rows - y) * px_y
            y_bot = (asc_rows - y_end - 1) * px_y
            if scanline == "erase-upper":
                y_top = y_bot + PX_X
            elif scanline == "erase-lower":
                y_bot = y_top - PX_X
            pen.moveTo((x0, y_bot))
            pen.lineTo((x0, y_top))
            pen.lineTo((x1, y_top))
            pen.lineTo((x1, y_bot))
            pen.closePath()
            y = y_end + 1
    return pen if has_ink else None


def render_glyph(glyph_set, glyph_name, cell_w, top_units, units_per_px_x,
                 units_per_px_y,
                 x_shift_px, threshold):
    pen = FreeTypePen(glyph_set)
    glyph_set[glyph_name].draw(pen)
    scale_x = 1.0 / units_per_px_x
    scale_y = 1.0 / units_per_px_y
    transform = Transform(scale_x, 0, 0, -scale_y, -x_shift_px,
                          top_units * scale_y)
    arr = pen.array(width=cell_w, height=SRC_ROWS, transform=transform)
    # FreeTypePen returns rows in the opposite vertical order from the
    # top-to-bottom bitmap convention used by emit_pixels().
    arr = np.flipud(arr)
    return (arr >= (threshold / 255.0)).astype(np.uint8)


def copy_glyph(glyph):
    pen = TTGlyphPen(None)
    glyph.draw(pen, None)
    return pen.glyph()


def snap_x(value, units_per_px_x):
    return int(round(value * (PX_X / units_per_px_x) / PX_X)) * PX_X


def snap_y(value, units_per_px_y, px_y=PX_Y_WEB):
    return int(round(value * (px_y / units_per_px_y) / px_y)) * px_y


def scale_gpos(tt, units_per_px_x, units_per_px_y, px_y=PX_Y_WEB):
    if "GPOS" not in tt:
        return

    def scale_anchor(anchor):
        if anchor is None:
            return
        if hasattr(anchor, "XCoordinate") and anchor.XCoordinate is not None:
            anchor.XCoordinate = snap_x(anchor.XCoordinate, units_per_px_x)
        if hasattr(anchor, "YCoordinate") and anchor.YCoordinate is not None:
            anchor.YCoordinate = snap_y(anchor.YCoordinate, units_per_px_y, px_y)

    def scale_value_record(vr):
        if vr is None:
            return
        for attr in ("XPlacement", "XAdvance"):
            if hasattr(vr, attr):
                value = getattr(vr, attr)
                if value is not None:
                    setattr(vr, attr, snap_x(value, units_per_px_x))
        for attr in ("YPlacement", "YAdvance"):
            if hasattr(vr, attr):
                value = getattr(vr, attr)
                if value is not None:
                    setattr(vr, attr, snap_y(value, units_per_px_y, px_y))

    def visit(subtable):
        name = subtable.__class__.__name__
        if name == "ExtensionPos":
            visit(subtable.ExtSubTable)
        elif name == "MarkBasePos":
            for mark in subtable.MarkArray.MarkRecord:
                scale_anchor(mark.MarkAnchor)
            for base in subtable.BaseArray.BaseRecord:
                for anchor in base.BaseAnchor:
                    scale_anchor(anchor)
        elif name == "MarkMarkPos":
            for mark in subtable.Mark1Array.MarkRecord:
                scale_anchor(mark.MarkAnchor)
            for mark2 in subtable.Mark2Array.Mark2Record:
                for anchor in mark2.Mark2Anchor:
                    scale_anchor(anchor)
        elif name == "MarkLigPos":
            for mark in subtable.MarkArray.MarkRecord:
                scale_anchor(mark.MarkAnchor)
            for lig in subtable.LigatureArray.LigatureAttach:
                for comp in lig.ComponentRecord:
                    for anchor in comp.LigatureAnchor:
                        scale_anchor(anchor)
        elif name == "CursivePos":
            for rec in subtable.EntryExitRecord:
                scale_anchor(rec.EntryAnchor)
                scale_anchor(rec.ExitAnchor)
        elif name == "PairPos":
            if subtable.Format == 1:
                for pair_set in subtable.PairSet:
                    for pair in pair_set.PairValueRecord:
                        scale_value_record(pair.Value1)
                        scale_value_record(pair.Value2)
            elif subtable.Format == 2:
                for class1 in subtable.Class1Record:
                    for class2 in class1.Class2Record:
                        scale_value_record(class2.Value1)
                        scale_value_record(class2.Value2)
        elif name == "SinglePos":
            if subtable.Format == 1:
                scale_value_record(subtable.Value)
            elif subtable.Format == 2:
                for value in subtable.Value:
                    scale_value_record(value)

    for lookup in tt["GPOS"].table.LookupList.Lookup:
        for subtable in lookup.SubTable:
            visit(subtable)


def rewrite_name(tt, family, style, full, postscript, unique):
    if "name" not in tt:
        return
    name = tt["name"]
    name.names = [r for r in name.names if r.nameID not in (1, 2, 3, 4, 6, 16, 17)]

    def add(name_id, value):
        name.setName(value, name_id, 3, 1, 0x409)

    add(1, family)
    add(2, style)
    add(3, unique)
    add(4, full)
    add(6, postscript)
    add(16, family)
    add(17, style)


def bake(source, output, *, flavor=None, threshold=THRESHOLD, scanline="none",
         top_units=DEFAULT_TOP_UNITS, bottom_units=DEFAULT_BOTTOM_UNITS,
         px_y=PX_Y_WEB, upm_out=UPM_WEB):
    tt = TTFont(str(source))
    src_upm = tt["head"].unitsPerEm
    units_per_px_x = src_upm / SRC_ROWS
    units_per_px_y = (top_units - bottom_units) / SRC_ROWS
    asc_rows = int(round(top_units / units_per_px_y))
    desc_rows = SRC_ROWS - asc_rows

    for table in ("prep", "fpgm", "cvt ", "gasp", "hdmx", "LTSH", "VDMX"):
        if table in tt:
            del tt[table]

    new_asc = asc_rows * px_y
    new_desc = -desc_rows * px_y
    tt["head"].unitsPerEm = upm_out
    tt["hhea"].ascent = new_asc
    tt["hhea"].descent = new_desc
    tt["hhea"].lineGap = 0
    if "OS/2" in tt:
        os2 = tt["OS/2"]
        os2.sTypoAscender = new_asc
        os2.sTypoDescender = new_desc
        os2.sTypoLineGap = 0
        os2.usWinAscent = new_asc
        os2.usWinDescent = -new_desc
        os2.sxHeight = snap_y(getattr(os2, "sxHeight", 0), units_per_px_y, px_y)
        os2.sCapHeight = snap_y(getattr(os2, "sCapHeight", 0), units_per_px_y, px_y)

    glyf = tt["glyf"]
    hmtx = tt["hmtx"].metrics
    glyph_set = tt.getGlyphSet()
    original_hmtx = dict(hmtx)
    glyph_order = tt.getGlyphOrder()
    processed = 0
    emptied = 0

    for glyph_name in glyph_order:
        if glyph_name == ".notdef":
            continue
        glyph = glyf[glyph_name]
        box = glyph_bbox(glyph)
        source_adv, source_lsb = original_hmtx.get(glyph_name, (0, 0))
        if box is None or getattr(glyph, "numberOfContours", 0) == 0:
            empty = TtGlyph()
            empty.numberOfContours = 0
            glyf[glyph_name] = empty
            hmtx[glyph_name] = (snap_x(source_adv, units_per_px_x), 0)
            emptied += 1
            continue

        x_min, _y_min, x_max, _y_max = box
        x_start_px = int(np.floor(min(0, x_min, source_lsb) / units_per_px_x))
        x_end_px = int(np.ceil(max(source_adv, x_max, source_lsb + source_adv) / units_per_px_x))
        cell_w = max(1, x_end_px - x_start_px)
        bitmap = render_glyph(glyph_set, glyph_name, cell_w, top_units,
                              units_per_px_x, units_per_px_y, x_start_px,
                              threshold)
        pixel_pen = emit_pixels(bitmap, asc_rows, x_start_px, scanline, px_y)
        if pixel_pen:
            glyf[glyph_name] = pixel_pen.glyph()
        else:
            empty = TtGlyph()
            empty.numberOfContours = 0
            glyf[glyph_name] = empty

        new_adv = snap_x(source_adv, units_per_px_x)
        if source_adv > 0:
            new_adv = max(PX_X, new_adv)
        new_box = coords_bbox(glyf[glyph_name])
        new_lsb = new_box[0] if new_box else 0
        hmtx[glyph_name] = (new_adv, new_lsb)
        processed += 1

    scale_gpos(tt, units_per_px_x, units_per_px_y, px_y)
    rewrite_name(
        tt,
        "K64 Arabic Sans Medium Pixel",
        "Regular",
        "K64 Arabic Sans Medium Pixel Regular",
        "K64ArabicSansMediumPixel-Regular",
        "K64 Arabic Sans Medium Pixel Regular 1.0",
    )
    tt["head"].xMin = min((coords_bbox(glyf[g]) or (0, 0, 0, 0))[0] for g in glyph_order)
    tt["head"].yMin = new_desc
    tt["head"].xMax = max((coords_bbox(glyf[g]) or (0, 0, 0, 0))[2] for g in glyph_order)
    tt["head"].yMax = new_asc
    tt.flavor = flavor
    output.parent.mkdir(parents=True, exist_ok=True)
    tt.save(str(output))
    print(f"wrote {output} ({processed} glyphs pixelated, {emptied} empty)")


def make_preview(font_path, out_path):
    sample_ar = (
        "\u0627\u0644\u0633\u064e\u0651\u0644\u064e\u0627\u0645\u064f "
        "\u0639\u064e\u0644\u064e\u064a\u0652\u0643\u064f\u0645\u0652   "
        "\u0645\u0631\u062d\u0628\u0627 \u0628\u0627\u0644\u0639\u0627\u0644\u0645 123"
    )
    lines = [
        ("K64 Arabic Sans Medium Pixel", font_path, sample_ar, "rtl", "ar"),
        ("source Noto Sans Arabic Medium", SRC, sample_ar, "rtl", "ar"),
    ]
    label = ImageFont.truetype("arial.ttf", 14)
    title = ImageFont.truetype("arial.ttf", 20)
    fonts = [ImageFont.truetype(str(path), 16, layout_engine=ImageFont.Layout.RAQM)
             for _name, path, _text, _dir, _lang in lines]
    width, row_h = 1220, 84
    img = Image.new("RGB", (width, 78 + row_h * len(lines)), "white")
    draw = ImageDraw.Draw(img)
    draw.text((24, 18), "K64 Arabic pixel preview", font=title, fill=(20, 20, 20))
    draw.text((24, 45), "Top is the generated game y1 font at 16px. Bottom is the source at the same size.", font=label, fill=(90, 90, 90))
    y = 78
    for idx, ((name, _path, text, direction, lang), font) in enumerate(zip(lines, fonts)):
        if idx % 2:
            draw.rectangle((16, y - 8, width - 16, y + row_h - 10), fill=(248, 248, 248))
        draw.text((24, y + 22), name, font=label, fill=(40, 40, 40))
        draw.text((width - 28, y + 10), text, font=font, fill=(0, 0, 0),
                  anchor="ra", direction=direction, language=lang)
        y += row_h
    img.save(out_path)
    print(f"wrote {out_path}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bake K64 Arabic pixel fonts.")
    parser.add_argument("--source", type=Path, default=SRC)
    parser.add_argument("--web-output", type=Path, default=WEB_OUT)
    parser.add_argument("--game-output", type=Path, default=GAME_OUT)
    parser.add_argument("--preview-output", type=Path, default=PREVIEW_OUT)
    parser.add_argument("--threshold", type=int, default=THRESHOLD)
    parser.add_argument("--top-units", type=int, default=DEFAULT_TOP_UNITS)
    parser.add_argument("--bottom-units", type=int, default=DEFAULT_BOTTOM_UNITS)
    parser.add_argument("--scanline", choices=["none", "erase-upper", "erase-lower"],
                        default="none")
    args = parser.parse_args(argv)

    if not args.source.exists():
        print(f"ERROR: source font not found: {args.source}", file=sys.stderr)
        return 2

    bake(args.source, args.web_output, flavor="woff2", threshold=args.threshold,
         scanline=args.scanline, top_units=args.top_units,
         bottom_units=args.bottom_units, px_y=PX_Y_WEB, upm_out=UPM_WEB)
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_y2x = Path(tmp_dir) / "k64-arabic-sans-medium-pixel-y2x.ttf"
        bake(args.source, tmp_y2x, flavor=None, threshold=args.threshold,
             scanline=args.scanline, top_units=args.top_units,
             bottom_units=args.bottom_units, px_y=PX_Y_WEB, upm_out=UPM_WEB)
        compress_y2x_to_y1(tmp_y2x, args.game_output)
        print(f"wrote {args.game_output} (compressed y2x -> game y1)")
    make_preview(args.game_output, args.preview_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
