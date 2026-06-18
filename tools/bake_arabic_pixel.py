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


def shift_glyph_y(glyph, dy):
    if dy == 0 or getattr(glyph, "numberOfContours", 0) <= 0:
        return
    coords = getattr(glyph, "coordinates", None)
    if coords is None:
        return
    glyph.coordinates = type(coords)((x, y + dy) for x, y in coords)


def compact_hamza_below_glyph(px_y=PX_Y_WEB):
    pen = TTGlyphPen(None)
    for x, y in ((3, -2), (4, -2), (2, -3), (2, -4), (3, -4)):
        x0 = x * PX_X
        x1 = (x + 1) * PX_X
        y0 = y * px_y
        y1 = (y + 1) * px_y
        pen.moveTo((x0, y0))
        pen.lineTo((x0, y1))
        pen.lineTo((x1, y1))
        pen.lineTo((x1, y0))
        pen.closePath()
    return pen.glyph()


def below_baseline_correction(source_box, output_box, src_upm, src_rows, px_y):
    if source_box is None or output_box is None:
        return 0
    _sx0, sy_min, _sx1, sy_max = source_box
    _ox0, oy_min, _ox1, oy_max = output_box
    source_units_per_row = src_upm / src_rows
    source_min = sy_min / source_units_per_row
    source_max = sy_max / source_units_per_row
    output_min = oy_min / px_y
    if source_min >= -0.25 or source_max > 0.5 or output_min < 3:
        return 0
    source_center = (sy_min + sy_max) / (2 * source_units_per_row)
    output_center = (oy_min + oy_max) / (2 * px_y)
    return int(round(source_center - output_center)) * px_y


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
                 x_shift_px, threshold, src_rows=SRC_ROWS, render_scale=1,
                 coverage_any=False, pre_skeleton_strokes=False,
                 centerline_downsample=False, coverage_downsample=False,
                 coverage_cell_threshold=0.25):
    pen = FreeTypePen(glyph_set)
    glyph_set[glyph_name].draw(pen)
    render_scale = max(1, int(render_scale))
    render_w = cell_w * render_scale
    render_rows = src_rows * render_scale
    render_units_per_px_x = units_per_px_x / render_scale
    render_units_per_px_y = units_per_px_y / render_scale
    scale_x = 1.0 / render_units_per_px_x
    scale_y = 1.0 / render_units_per_px_y
    transform = Transform(scale_x, 0, 0, -scale_y, -x_shift_px * render_scale,
                          top_units * scale_y)
    arr = pen.array(width=render_w, height=render_rows, transform=transform)
    # FreeTypePen returns rows in the opposite vertical order from the
    # top-to-bottom bitmap convention used by emit_pixels().
    arr = np.flipud(arr)
    if coverage_downsample and render_scale > 1:
        coverage = arr.reshape(src_rows, render_scale, cell_w, render_scale)
        coverage = coverage.mean(axis=(1, 3))
        return (coverage >= coverage_cell_threshold).astype(np.uint8)
    bitmap = (arr > (threshold / 255.0)).astype(np.uint8)
    if pre_skeleton_strokes:
        bitmap = thin_bitmap(bitmap)
    if centerline_downsample and render_scale > 1:
        bitmap = downsample_points_nearest(bitmap, src_rows, cell_w)
    if coverage_any and render_scale > 1:
        bitmap = bitmap.reshape(src_rows, render_scale, cell_w, render_scale)
        bitmap = bitmap.max(axis=(1, 3))
    return bitmap


def thin_bitmap(bitmap):
    """Zhang-Suen thinning. Reduces thickened coverage to a 1px skeleton."""
    img = (bitmap > 0).astype(np.uint8).copy()
    if img.shape[0] < 3 or img.shape[1] < 3:
        return img
    changed = True
    while changed:
        changed = False
        for step in (0, 1):
            remove = []
            for y in range(1, img.shape[0] - 1):
                for x in range(1, img.shape[1] - 1):
                    if img[y, x] == 0:
                        continue
                    p2 = img[y - 1, x]
                    p3 = img[y - 1, x + 1]
                    p4 = img[y, x + 1]
                    p5 = img[y + 1, x + 1]
                    p6 = img[y + 1, x]
                    p7 = img[y + 1, x - 1]
                    p8 = img[y, x - 1]
                    p9 = img[y - 1, x - 1]
                    neighbors = [p2, p3, p4, p5, p6, p7, p8, p9]
                    count = sum(neighbors)
                    if count < 2 or count > 6:
                        continue
                    transitions = sum(
                        1 for a, b in zip(neighbors, neighbors[1:] + neighbors[:1])
                        if a == 0 and b == 1
                    )
                    if transitions != 1:
                        continue
                    if step == 0:
                        if p2 * p4 * p6 != 0 or p4 * p6 * p8 != 0:
                            continue
                    else:
                        if p2 * p4 * p8 != 0 or p2 * p6 * p8 != 0:
                            continue
                    remove.append((y, x))
            if remove:
                changed = True
                for y, x in remove:
                    img[y, x] = 0
    return img


def downsample_points_nearest(bitmap, out_h, out_w):
    """Map ink pixels to the nearest output cell instead of OR-ing bin coverage."""
    in_h, in_w = bitmap.shape
    out = np.zeros((out_h, out_w), dtype=bitmap.dtype)
    ys, xs = np.where(bitmap > 0)
    if len(xs) == 0:
        return out
    tx = np.rint((xs + 0.5) * out_w / in_w - 0.5).astype(np.int32)
    ty = np.rint((ys + 0.5) * out_h / in_h - 0.5).astype(np.int32)
    tx = np.clip(tx, 0, out_w - 1)
    ty = np.clip(ty, 0, out_h - 1)
    out[ty, tx] = 1
    return out


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


def source_weight_name(source):
    stem = Path(source).stem
    prefix = "NotoSansArabic-"
    if stem.startswith(prefix):
        return stem[len(prefix):]
    return "Medium"


def bake(source, output, *, flavor=None, threshold=THRESHOLD, scanline="none",
         top_units=DEFAULT_TOP_UNITS, bottom_units=DEFAULT_BOTTOM_UNITS,
         src_rows=SRC_ROWS, px_y=PX_Y_WEB, upm_out=None,
         metric_rows=None, metric_ascent_rows=None, name_suffix="",
         render_scale=1, coverage_any=False, skeleton_strokes=False,
         pre_skeleton_strokes=False, centerline_downsample=False,
         coverage_downsample=False, coverage_cell_threshold=0.25,
         x_scale=1.0):
    tt = TTFont(str(source))
    src_upm = tt["head"].unitsPerEm
    if x_scale <= 0:
        raise ValueError("--x-scale must be positive")
    units_per_px_x = (src_upm / src_rows) / x_scale
    units_per_px_y = (top_units - bottom_units) / src_rows
    asc_rows = int(round(top_units / units_per_px_y))
    desc_rows = src_rows - asc_rows
    metric_rows = src_rows if metric_rows is None else metric_rows
    metric_asc_rows = (
        int(round(metric_rows * asc_rows / src_rows))
        if metric_ascent_rows is None
        else int(metric_ascent_rows)
    )
    if metric_asc_rows < 0 or metric_asc_rows > metric_rows:
        raise ValueError("--metric-ascent-rows must be within --metric-rows")
    metric_desc_rows = metric_rows - metric_asc_rows
    if upm_out is None:
        upm_out = src_rows * px_y

    for table in ("prep", "fpgm", "cvt ", "gasp", "hdmx", "LTSH", "VDMX"):
        if table in tt:
            del tt[table]

    glyph_asc = asc_rows * px_y
    glyph_desc = -desc_rows * px_y
    new_asc = metric_asc_rows * px_y
    new_desc = -metric_desc_rows * px_y
    tt["head"].unitsPerEm = upm_out
    tt["hhea"].ascent = new_asc
    tt["hhea"].descent = new_desc
    tt["hhea"].lineGap = 0
    if "OS/2" in tt:
        os2 = tt["OS/2"]
        os2.sTypoAscender = new_asc
        os2.sTypoDescender = new_desc
        os2.sTypoLineGap = 0
        os2.usWinAscent = max(new_asc, glyph_asc)
        os2.usWinDescent = max(-new_desc, -glyph_desc)
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
                              threshold, src_rows, render_scale, coverage_any,
                              pre_skeleton_strokes, centerline_downsample,
                              coverage_downsample, coverage_cell_threshold)
        if skeleton_strokes:
            bitmap = thin_bitmap(bitmap)
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
        dy = below_baseline_correction(box, new_box, src_upm, src_rows, px_y)
        if dy:
            shift_glyph_y(glyf[glyph_name], dy)
            glyf[glyph_name].recalcBounds(glyf)
            new_box = coords_bbox(glyf[glyph_name])
        if glyph_name == "uni0655":
            glyf[glyph_name] = compact_hamza_below_glyph(px_y)
            glyf[glyph_name].recalcBounds(glyf)
            new_box = coords_bbox(glyf[glyph_name])
        new_lsb = new_box[0] if new_box else 0
        hmtx[glyph_name] = (new_adv, new_lsb)
        processed += 1

    scale_gpos(tt, units_per_px_x, units_per_px_y, px_y)
    size_suffix = "" if src_rows == SRC_ROWS else f" {src_rows}px"
    variant_suffix = f" {name_suffix.strip()}" if name_suffix.strip() else ""
    postscript_size_suffix = "" if src_rows == SRC_ROWS else f"{src_rows}px"
    postscript_variant_suffix = "".join(
        ch for ch in name_suffix.title() if ch.isalnum()
    )
    weight_name = source_weight_name(source)
    postscript_weight_name = "".join(ch for ch in weight_name.title() if ch.isalnum())
    family = f"K64 Arabic Sans {weight_name} Pixel{size_suffix}{variant_suffix}"
    rewrite_name(
        tt,
        family,
        "Regular",
        f"{family} Regular",
        f"K64ArabicSans{postscript_weight_name}Pixel{postscript_size_suffix}{postscript_variant_suffix}-Regular",
        f"{family} Regular 1.0",
    )
    tt["head"].xMin = min((coords_bbox(glyf[g]) or (0, 0, 0, 0))[0] for g in glyph_order)
    tt["head"].yMin = min((coords_bbox(glyf[g]) or (0, 0, 0, 0))[1] for g in glyph_order)
    tt["head"].xMax = max((coords_bbox(glyf[g]) or (0, 0, 0, 0))[2] for g in glyph_order)
    tt["head"].yMax = max((coords_bbox(glyf[g]) or (0, 0, 0, 0))[3] for g in glyph_order)
    tt.flavor = flavor
    output.parent.mkdir(parents=True, exist_ok=True)
    tt.save(str(output))
    print(f"wrote {output} ({processed} glyphs pixelated, {emptied} empty)")


def make_preview(font_path, out_path, font_size=16):
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
    fonts = [ImageFont.truetype(str(path), font_size, layout_engine=ImageFont.Layout.RAQM)
             for _name, path, _text, _dir, _lang in lines]
    width, row_h = 1220, 84
    img = Image.new("RGB", (width, 78 + row_h * len(lines)), "white")
    draw = ImageDraw.Draw(img)
    draw.text((24, 18), "K64 Arabic pixel preview", font=title, fill=(20, 20, 20))
    draw.text((24, 45), f"Top is the generated game y1 font at {font_size}px. Bottom is the source at the same size.", font=label, fill=(90, 90, 90))
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
    parser.add_argument("--rows", type=int, default=SRC_ROWS,
                        help="source raster rows; 16 for the default game 16px font, 24 for a larger trial")
    parser.add_argument("--metric-rows", type=int, default=None,
                        help="vertical metrics rows; defaults to --rows. Use 16 with --rows 20 to keep line spacing on the 16px rhythm")
    parser.add_argument("--metric-ascent-rows", type=int, default=None,
                        help="baseline row within --metric-rows; use 12 with --metric-rows 16 to match K64F's 12/4 line metrics")
    parser.add_argument("--name-suffix", default="",
                        help="extra family/PostScript suffix for variants such as Thin")
    parser.add_argument("--scanline", choices=["none", "erase-upper", "erase-lower"],
                        default="none")
    parser.add_argument("--render-scale", type=int, default=1,
                        help="supersample outlines by this factor before optional OR downsample")
    parser.add_argument("--coverage-any", action="store_true",
                        help="OR supersampled pixels into the target grid so any covered cell becomes ink")
    parser.add_argument("--skeleton-strokes", action="store_true",
                        help="thin the OR coverage bitmap to a 1px skeleton before outline emission")
    parser.add_argument("--pre-skeleton-strokes", action="store_true",
                        help="thin the supersampled bitmap before OR downsampling into the target grid")
    parser.add_argument(
        "--centerline-downsample",
        action="store_true",
        help="after high-resolution skeletonization, map centerline pixels to nearest target cells instead of OR downsampling",
    )
    parser.add_argument(
        "--coverage-downsample",
        action="store_true",
        help="downsample supersampled grayscale coverage by averaging each target cell, then threshold it",
    )
    parser.add_argument(
        "--coverage-cell-threshold",
        type=float,
        default=0.25,
        help="minimum average cell coverage for --coverage-downsample, from 0.0 to 1.0",
    )
    parser.add_argument(
        "--x-scale",
        type=float,
        default=1.0,
        help="horizontal scale for glyph outlines, advances, and GPOS X values",
    )
    parser.add_argument(
        "--square12",
        action="store_true",
        help="emit a 12px square-dot trial font using UPM=1200, asc=1100, desc=-100",
    )
    parser.add_argument(
        "--square16-thin",
        action="store_true",
        help="emit a 16px square-dot thin trial font from the original source",
    )
    args = parser.parse_args(argv)
    if args.square12 and args.square16_thin:
        parser.error("--square12 and --square16-thin are mutually exclusive")

    if not args.source.exists():
        print(f"ERROR: source font not found: {args.source}", file=sys.stderr)
        return 2

    px_y = PX_Y_WEB
    upm_out = None
    preview_size = args.rows
    if args.square12:
        if args.web_output == WEB_OUT:
            args.web_output = ROOT / "web" / "k64-arabic-sans-medium-pixel-12px-square-trial.woff2"
        if args.game_output == GAME_OUT:
            args.game_output = ROOT / "game" / "k64-arabic-sans-medium-pixel-12px-square-trial.ttf"
        if args.preview_output == PREVIEW_OUT:
            args.preview_output = ROOT / "game" / "k64-arabic-sans-medium-pixel-12px-square-trial.preview.png"
        if args.top_units == DEFAULT_TOP_UNITS:
            args.top_units = 900
        if args.bottom_units == DEFAULT_BOTTOM_UNITS:
            args.bottom_units = -100
        args.rows = 12
        args.metric_rows = 12
        args.metric_ascent_rows = 11
        if not args.name_suffix:
            args.name_suffix = "Square Trial"
        px_y = 100
        upm_out = 1200
        preview_size = 12
    elif args.square16_thin:
        if args.web_output == WEB_OUT:
            args.web_output = ROOT / "web" / "k64-arabic-sans-medium-pixel-16px-thin-square-trial.woff2"
        if args.game_output == GAME_OUT:
            args.game_output = ROOT / "game" / "k64-arabic-sans-medium-pixel-16px-thin-square-trial.ttf"
        if args.preview_output == PREVIEW_OUT:
            args.preview_output = ROOT / "game" / "k64-arabic-sans-medium-pixel-16px-thin-square-trial.preview.png"
        args.top_units = DEFAULT_TOP_UNITS
        args.bottom_units = DEFAULT_BOTTOM_UNITS
        args.rows = 16
        args.metric_rows = 16
        args.metric_ascent_rows = 12
        if args.threshold == THRESHOLD:
            args.threshold = 160
        if not args.name_suffix:
            args.name_suffix = "16px Thin Square Trial"
        px_y = 100
        upm_out = 1600
        preview_size = 16

    bake(args.source, args.web_output, flavor="woff2", threshold=args.threshold,
         scanline=args.scanline, top_units=args.top_units,
         bottom_units=args.bottom_units, src_rows=args.rows, px_y=px_y,
         upm_out=upm_out,
         metric_rows=args.metric_rows,
         metric_ascent_rows=args.metric_ascent_rows,
         name_suffix=args.name_suffix,
         render_scale=args.render_scale,
         coverage_any=args.coverage_any,
         skeleton_strokes=args.skeleton_strokes,
         pre_skeleton_strokes=args.pre_skeleton_strokes,
         centerline_downsample=args.centerline_downsample,
         coverage_downsample=args.coverage_downsample,
         coverage_cell_threshold=args.coverage_cell_threshold,
         x_scale=args.x_scale)
    if args.square12 or args.square16_thin:
        bake(args.source, args.game_output, flavor=None, threshold=args.threshold,
             scanline=args.scanline, top_units=args.top_units,
             bottom_units=args.bottom_units, src_rows=args.rows, px_y=px_y,
             upm_out=upm_out,
             metric_rows=args.metric_rows,
             metric_ascent_rows=args.metric_ascent_rows,
             name_suffix=args.name_suffix,
             render_scale=args.render_scale,
             coverage_any=args.coverage_any,
             skeleton_strokes=args.skeleton_strokes,
             pre_skeleton_strokes=args.pre_skeleton_strokes,
             centerline_downsample=args.centerline_downsample,
             coverage_downsample=args.coverage_downsample,
             coverage_cell_threshold=args.coverage_cell_threshold,
             x_scale=args.x_scale)
    else:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_y2x = Path(tmp_dir) / "k64-arabic-sans-medium-pixel-y2x.ttf"
            bake(args.source, tmp_y2x, flavor=None, threshold=args.threshold,
                 scanline=args.scanline, top_units=args.top_units,
                 bottom_units=args.bottom_units, src_rows=args.rows, px_y=px_y,
                 upm_out=upm_out,
                 metric_rows=args.metric_rows,
                 metric_ascent_rows=args.metric_ascent_rows,
                 name_suffix=args.name_suffix,
                 render_scale=args.render_scale,
                 coverage_any=args.coverage_any,
                 skeleton_strokes=args.skeleton_strokes,
                 pre_skeleton_strokes=args.pre_skeleton_strokes,
                 centerline_downsample=args.centerline_downsample,
                 coverage_downsample=args.coverage_downsample,
                 coverage_cell_threshold=args.coverage_cell_threshold,
                 x_scale=args.x_scale)
            compress_y2x_to_y1(tmp_y2x, args.game_output)
            print(f"wrote {args.game_output} (compressed y2x -> game y1)")
    make_preview(args.game_output, args.preview_output, preview_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
