#!/usr/bin/env python3
"""Bake NotoSansThai as pixel font with 1x2 tall rectangular dots.

Process:
  1. Rasterize NotoSansThai_x2w at 16px
  2. Horizontally fit the typical Thai base advance to 16px
  3. Each fitted source pixel → 1×2 display pixels, matching CJK y2x dots
  4. UPM=3200 (matches CJK y2x line metrics at font-size 32px)
  5. Preserve GPOS anchors (rescaled) so HarfBuzz stacks tone marks correctly
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
from fontTools.ttLib import TTFont
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib.tables._g_l_y_f import Glyph as TtGlyph
from fontTools.varLib.instancer import instantiateVariableFont
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "NotoSansThai-Regular_x2w.ttf"

SRC_SIZE = 16       # rasterize at 16px
PX_X = 100          # font units per fitted source pixel in X (1 disp px at font-size 32)
PX_Y = 200          # font units per source pixel in Y (2 disp px at font-size 32)
UPM_OUT = 3200      # matches CJK y2x bake UPM
SRC_UPM_ASSUMED = 1000  # NotoSansThai source UPM
MARK_LEFT_SHIFT_PX = 0
MARK_RAISE_ROWS = 0
MARK_WIDTH_FOR_SMALL_FONTS = 16
ADVANCE_MODE_SUFFIX = {
    "pixel-snap": "",
    "noto-proportional": "prop",
    "noto-proportional-half-px": "prop-half",
}
SCANLINE_SUFFIX = {
    "none": "",
    "erase-upper": "scan-erase-upper",
    "erase-lower": "scan-erase-lower",
}


def source_units_per_raster_pixel(source_upm, raster_size):
    return source_upm / raster_size


def glyph_bbox(font, glyph_name):
    glyph = font["glyf"][glyph_name]
    if not hasattr(glyph, "xMin"):
        return None
    return glyph.xMin, glyph.yMin, glyph.xMax, glyph.yMax


def coords_bbox(coords):
    if not coords:
        return None
    xs = [p[0] for p in coords]
    ys = [p[1] for p in coords]
    return min(xs), min(ys), max(xs), max(ys)


def glyph_coord_bbox(glyph):
    coords = getattr(glyph, "coordinates", None)
    if coords is None:
        return None
    return coords_bbox(list(coords))


def fit_width(n, width_scale):
    return max(1, int(round(n * width_scale)))


def fitted_advance(source_adv, fitted_w, source_to_out_x, advance_mode):
    if source_adv == 0:
        return 0
    if advance_mode == "pixel-snap":
        return fitted_w * PX_X

    adv = source_adv * source_to_out_x
    if advance_mode == "noto-proportional-half-px":
        quantum = PX_X / 2
        adv = round(adv / quantum) * quantum
    return max(1, int(round(adv)))


def scale_bitmap_x(bitmap, out_w):
    """Nearest-neighbor horizontal fit, preserving hard pixel edges."""
    in_w = bitmap.shape[1]
    if in_w == out_w:
        return bitmap
    xs = np.floor(np.arange(out_w) * in_w / out_w).astype(np.int32)
    return bitmap[:, xs]


def scale_bitmap_y(bitmap, out_h):
    """Nearest-neighbor vertical fit, preserving hard pixel edges."""
    in_h = bitmap.shape[0]
    if in_h == out_h:
        return bitmap
    ys = np.floor(np.arange(out_h) * in_h / out_h).astype(np.int32)
    return bitmap[ys, :]


def or_merge_4to3(bitmap, or_pair=1):
    """Compress rows by 4->3 OR merge, preserving thin horizontal strokes."""
    rows = []
    full_groups = bitmap.shape[0] // 4
    for g in range(full_groups):
        r = bitmap[g * 4:g * 4 + 4]
        if or_pair == 0:
            rows.extend([r[0] | r[1], r[2], r[3]])
        elif or_pair == 1:
            rows.extend([r[0], r[1] | r[2], r[3]])
        else:
            rows.extend([r[0], r[1], r[2] | r[3]])
    rem = bitmap[full_groups * 4:]
    if rem.size:
        rows.append(np.bitwise_or.reduce(rem, axis=0))
    return np.stack(rows, axis=0).astype(np.uint8)


def shift_bitmap_y(bitmap, rows_up):
    if rows_up <= 0:
        return bitmap
    out = np.zeros_like(bitmap)
    if rows_up < bitmap.shape[0]:
        out[:-rows_up, :] = bitmap[rows_up:, :]
    return out


def shift_bitmap_y_down(bitmap, rows_down):
    if rows_down <= 0:
        return bitmap
    out = np.zeros_like(bitmap)
    if rows_down < bitmap.shape[0]:
        out[rows_down:, :] = bitmap[:-rows_down, :]
    return out


def clear_top_ink_rows(bitmap, rows):
    """Remove the highest occupied raster rows while preserving glyph placement."""
    if rows <= 0:
        return bitmap
    out = bitmap.copy()
    occupied = np.where(out.any(axis=1))[0]
    if occupied.size:
        out[occupied[:rows], :] = 0
    return out


def center_mark_shift(target_width, mark_width):
    return int(round((target_width - mark_width) / 2)) - target_width


def is_centered_top_mark(cp):
    return 0x0E48 <= cp <= 0x0E4D


def is_above_mark(cp):
    return cp == 0x0E31 or 0x0E34 <= cp <= 0x0E37 or 0x0E47 <= cp <= 0x0E4E


def snap_to_grid(value, grid):
    return int(round(value / grid)) * grid


def scanline_bounds(row, y_end, asc_design, scanline):
    y_top = (asc_design - row) * PX_Y
    y_bot = (asc_design - y_end - 1) * PX_Y
    if scanline == "erase-upper":
        return y_bot, y_bot + PX_X
    if scanline == "erase-lower":
        return y_top - PX_X, y_top
    return y_bot, y_top


def thin_bitmap(bitmap):
    """Zhang-Suen thinning. Turns variable-width raster strokes into 1px skeletons."""
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


def normalize_vertical_stems(bitmap):
    """Trim duplicated adjacent columns only when they form a vertical stem."""
    img = (bitmap > 0).astype(np.uint8).copy()
    if img.shape[1] < 2:
        return img

    remove = np.zeros_like(img)
    protected = set()
    src = img.copy()
    for x in range(src.shape[1] - 1):
        left = src[:, x]
        right = src[:, x + 1]
        left_count = int(left.sum())
        right_count = int(right.sum())
        if left_count < 4 or right_count < 4:
            continue
        overlap = (left & right).astype(np.uint8)
        overlap_count = int(overlap.sum())
        if overlap_count < 5:
            continue
        if overlap_count / min(left_count, right_count) < 0.80:
            continue

        left_extra = left_count - overlap_count
        right_extra = right_count - overlap_count
        if right_extra > left_extra:
            keep_x, drop_x = x + 1, x
        else:
            keep_x, drop_x = x, x + 1
        if drop_x in protected:
            continue
        protected.add(keep_x)
        remove[:, drop_x] |= overlap
    img[remove == 1] = 0
    return img


def rasterize(pil_font, char, cell_w, cell_h, force_combining=False):
    """Render char into binary bitmap. For combining marks (where PIL would
    add a U+25CC dotted-circle base), render 'NBSP + mark' instead and take
    the mark portion only (= image minus what NBSP alone produces)."""
    cell = np.zeros((cell_h, cell_w), dtype=np.uint8)
    try:
        # Detect combining mark: bbox negative-left or no advance
        is_combining = force_combining
        try:
            adv = pil_font.getlength(char)
            if adv == 0:
                is_combining = True
        except Exception: pass

        if is_combining:
            # Render with NBSP base, then subtract NBSP-alone result
            from PIL import Image as _I, ImageDraw as _D
            w = cell_w + 8
            h = cell_h + 4
            img_both = _I.new("L", (w, h), 255)
            _D.Draw(img_both).text((4, 0), ' ' + char, fill=0, font=pil_font)
            img_both = img_both.point(lambda p: 0 if p < 128 else 255, mode="L")
            img_base = _I.new("L", (w, h), 255)
            _D.Draw(img_base).text((4, 0), ' ', fill=0, font=pil_font)
            img_base = img_base.point(lambda p: 0 if p < 128 else 255, mode="L")
            arr_both = (np.array(img_both) < 128).astype(np.uint8)
            arr_base = (np.array(img_base) < 128).astype(np.uint8)
            arr = arr_both & ~arr_base  # only pixels in both-render not in base-alone
            # Find bbox of mark
            ys, xs = np.where(arr)
            if len(xs) == 0:
                return cell
            mx0, mx1 = xs.min(), xs.max() + 1
            my0, my1 = ys.min(), ys.max() + 1
            cropped = arr[my0:my1, mx0:mx1]
            # Place at top-left of cell, preserving Y offset from canvas top
            mh, mw = cropped.shape
            y_dst = max(0, my0)  # keep original Y in cell (= position above baseline)
            x_dst = 0
            y_end = min(cell_h, y_dst + mh)
            x_end = min(cell_w, x_dst + mw)
            if y_end > y_dst and x_end > x_dst:
                cell[y_dst:y_end, x_dst:x_end] = cropped[:y_end-y_dst, :x_end-x_dst]
            return cell

        # Normal base char: use getmask
        mask = pil_font.getmask(char, mode='L')
        mw, mh = mask.size
        if mw == 0 or mh == 0:
            return cell
        arr = (np.array(mask, dtype=np.uint8).reshape(mh, mw) > 127).astype(np.uint8)
        bbox = pil_font.getbbox(char)
        if bbox is None:
            return cell
        x0 = max(0, bbox[0])
        y0 = max(0, bbox[1])
        y1 = min(cell_h, y0 + mh)
        x1 = min(cell_w, x0 + mw)
        if y1 > y0 and x1 > x0:
            cell[y0:y1, x0:x1] = arr[:y1-y0, :x1-x0]
        return cell
    except Exception:
        return cell


def emit_pixels_as_contours(bitmap, cell_h, cell_w, asc_design):
    return emit_pixels_as_contours_shifted(bitmap, cell_h, cell_w, asc_design, 0, "none")

def emit_pixels_as_contours_shifted(bitmap, cell_h, cell_w, asc_design, x_shift_pixels,
                                    scanline):
    """Emit per Reecho convention. x_shift_pixels shifts the entire contour
    horizontally by N source pixels (negative = left, for marks)."""
    pen = TTGlyphPen(None)
    has_ink = False
    for x in range(cell_w):
        y = 0
        while y < cell_h:
            if not bitmap[y, x]:
                y += 1
                continue
            y_end = y
            while scanline == "none" and y_end + 1 < cell_h and bitmap[y_end + 1, x]:
                y_end += 1
            has_ink = True
            x_off = x_shift_pixels
            x0, x1 = (x + x_off) * PX_X, (x + 1 + x_off) * PX_X
            y_bot, y_top = scanline_bounds(y, y_end, asc_design, scanline)
            pen.moveTo((x0, y_bot))
            pen.lineTo((x0, y_top))
            pen.lineTo((x1, y_top))
            pen.lineTo((x1, y_bot))
            pen.closePath()
            y = y_end + 1
    return pen if has_ink else None


def scale_gpos_anchors(gpos_table, scale):
    """Walk GPOS, scale all Anchor X/YCoordinate by `scale`."""
    visited = set()
    def walk(obj):
        if obj is None or id(obj) in visited:
            return
        visited.add(id(obj))
        if hasattr(obj, 'XCoordinate') and hasattr(obj, 'YCoordinate'):
            obj.XCoordinate = int(round(obj.XCoordinate * scale))
            obj.YCoordinate = int(round(obj.YCoordinate * scale))
        for attr in dir(obj):
            if attr.startswith('_') or attr in ('xPlacement', 'yPlacement',
                'xAdvance', 'yAdvance', 'xPlaDevice', 'yPlaDevice'):
                # value records: scale those too
                if attr == 'xPlacement' or attr == 'yPlacement' or attr == 'xAdvance' or attr == 'yAdvance':
                    try:
                        v = getattr(obj, attr)
                        if v is not None and isinstance(v, int):
                            setattr(obj, attr, int(round(v * scale)))
                    except Exception:
                        pass
                continue
            try:
                val = getattr(obj, attr)
            except Exception:
                continue
            if isinstance(val, list):
                for item in val:
                    if hasattr(item, '__class__') and hasattr(item, '__dict__') and item.__class__.__module__.startswith('fontTools'):
                        walk(item)
            elif hasattr(val, '__class__') and hasattr(val, '__dict__'):
                if val.__class__.__module__.startswith('fontTools'):
                    walk(val)
    walk(gpos_table)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bake pixel Thai WOFF2.")
    parser.add_argument(
        "--target-width",
        type=int,
        default=16,
        help="fit U+0E01 ก advance to this many display pixels (default: 16)",
    )
    parser.add_argument(
        "--raster-size",
        type=int,
        default=SRC_SIZE,
        help="FreeType/Pillow raster size used as the source bitmap (default: 16)",
    )
    parser.add_argument(
        "--fit-mode",
        choices=["fit-base", "native"],
        default="fit-base",
        help="fit-base scales widths to --target-width; native preserves the rasterized pixel width",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="output path. TTF/WOFF2 outputs are y2x; run compress_y2x_to_y1.py for Reecho game TTFs",
    )
    parser.add_argument(
        "--height-mode",
        choices=["full", "scaled", "or12"],
        default="full",
        help="full keeps source height; scaled shrinks by scale; or12 uses 4->3 OR row merge",
    )
    parser.add_argument(
        "--advance-mode",
        choices=list(ADVANCE_MODE_SUFFIX),
        default="pixel-snap",
        help="pixel-snap keeps current integer-pixel advances; noto-proportional preserves source hmtx proportions",
    )
    parser.add_argument(
        "--scanline",
        choices=list(SCANLINE_SUFFIX),
        default="none",
        help="erase one half of each 1x2 dot: erase-upper keeps the lower pixel, erase-lower keeps the upper pixel",
    )
    parser.add_argument(
        "--min-right-bearing-px",
        type=int,
        default=0,
        help="ensure non-combining glyph advances leave at least this many fitted pixels after xMax",
    )
    parser.add_argument(
        "--normalize-vertical-stems",
        action="store_true",
        help="try to trim duplicated adjacent vertical stem columns",
    )
    parser.add_argument(
        "--skeleton-strokes",
        action="store_true",
        help="use full 1px skeleton thinning after raster fit",
    )
    parser.add_argument(
        "--mark-left-shift",
        type=int,
        default=MARK_LEFT_SHIFT_PX,
        help="extra left shift in fitted pixels for zero-width Thai marks",
    )
    parser.add_argument(
        "--mark-raise-rows",
        type=int,
        default=MARK_RAISE_ROWS,
        help="extra upward shift in source rows for zero-width Thai marks",
    )
    args = parser.parse_args(argv)
    mark_left_shift = args.mark_left_shift
    if args.output:
        out_path = args.output
    elif args.fit_mode == "native":
        suffix = f"native{args.raster_size}px-y2x"
        if ADVANCE_MODE_SUFFIX[args.advance_mode]:
            suffix = f"{suffix}-{ADVANCE_MODE_SUFFIX[args.advance_mode]}"
        if SCANLINE_SUFFIX[args.scanline]:
            suffix = f"{suffix}-{SCANLINE_SUFFIX[args.scanline]}"
        out_path = ROOT / "web" / f"k64-thai-pixel-{suffix}.woff2"
    elif args.height_mode == "full":
        suffix = f"{args.target_width}w-y2x" if args.target_width == 16 else f"{args.target_width}w-16h-y2x"
        if ADVANCE_MODE_SUFFIX[args.advance_mode]:
            suffix = f"{suffix}-{ADVANCE_MODE_SUFFIX[args.advance_mode]}"
        if SCANLINE_SUFFIX[args.scanline]:
            suffix = f"{suffix}-{SCANLINE_SUFFIX[args.scanline]}"
        out_path = ROOT / "web" / f"k64-thai-pixel-{suffix}.woff2"
    elif args.height_mode == "or12":
        suffix = f"{args.target_width}w-or12-y2x"
        if ADVANCE_MODE_SUFFIX[args.advance_mode]:
            suffix = f"{suffix}-{ADVANCE_MODE_SUFFIX[args.advance_mode]}"
        if SCANLINE_SUFFIX[args.scanline]:
            suffix = f"{suffix}-{SCANLINE_SUFFIX[args.scanline]}"
        out_path = ROOT / "web" / f"k64-thai-pixel-{suffix}.woff2"
    else:
        suffix = f"{args.target_width}w-scaled-y2x"
        if ADVANCE_MODE_SUFFIX[args.advance_mode]:
            suffix = f"{suffix}-{ADVANCE_MODE_SUFFIX[args.advance_mode]}"
        if SCANLINE_SUFFIX[args.scanline]:
            suffix = f"{suffix}-{SCANLINE_SUFFIX[args.scanline]}"
        out_path = ROOT / "web" / f"k64-thai-pixel-{suffix}.woff2"

    print(f"reading {SRC.name}")
    tt = TTFont(str(SRC))
    src_upm = tt['head'].unitsPerEm
    print(f"  source UPM={src_upm}")

    # Flatten variable font first (NotoSansThai is variable). Without this,
    # gvar/HVAR/STAT/prep tables would reference original glyph outlines and
    # apply deltas to our pixelated outlines, breaking shaping.
    if 'fvar' in tt:
        print("  variable font detected → instantiating at default master")
        tt = instantiateVariableFont(tt, {})
    # Also drop hinting code (prep/fpgm/cvt) which assumes original outlines
    for tbl in ['prep', 'fpgm', 'cvt ']:
        if tbl in tt:
            del tt[tbl]
            print(f"  removed {tbl} table")

    pil_font = ImageFont.truetype(str(SRC), args.raster_size)
    pil_asc, pil_desc = pil_font.getmetrics()
    src_h = pil_asc + pil_desc   # raster canvas height
    print(f"  PIL @ {args.raster_size}px: asc={pil_asc} desc={pil_desc} (cell h={src_h})")

    if args.fit_mode == "native":
        vertical_scale = 1.0
        fitted_h = src_h
        asc_design = pil_asc
    elif args.height_mode == "full":
        vertical_scale = 1.0
        fitted_h = src_h
        asc_design = pil_asc
    elif args.height_mode == "or12":
        vertical_scale = 0.75
        fitted_h = (src_h // 4) * 3 + (1 if src_h % 4 else 0)
        asc_design = (pil_asc // 4) * 3 + (1 if pil_asc % 4 else 0)
    else:
        vertical_scale = args.target_width / 16
        fitted_h = max(1, int(round(src_h * vertical_scale)))
        asc_design = max(1, int(round(pil_asc * vertical_scale)))
    if args.height_mode in ("full", "or12"):
        # Thai stacked marks need the top of the em. Descender margin remains
        # below the baseline; lineGap stays zero to keep browser layout simple.
        new_asc = 3200
        new_desc = -400
        new_lineGap = 0
    else:
        # Narrow variants scale height with width. 12w lands on the same
        # 24px ink height / 32px line rhythm as CJK or12+y2x.
        new_asc = 2400
        new_desc = -400
        new_lineGap = UPM_OUT - (new_asc - new_desc)

    tt['head'].unitsPerEm = UPM_OUT
    tt['hhea'].ascent  = new_asc
    tt['hhea'].descent = new_desc
    tt['hhea'].lineGap = new_lineGap
    if 'OS/2' in tt:
        os2 = tt['OS/2']
        os2.sTypoAscender  = new_asc
        os2.sTypoDescender = new_desc
        os2.sTypoLineGap   = new_lineGap
        os2.usWinAscent    = new_asc
        os2.usWinDescent   = max(0, -new_desc)

    tt['head'].yMin = new_desc
    tt['head'].yMax = new_asc

    cmap = tt.getBestCmap()
    glyf = tt['glyf']
    hmtx = tt['hmtx'].metrics
    glyph_order = tt.getGlyphOrder()
    source_hmtx = dict(hmtx)
    source_bboxes = {gname: glyph_bbox(tt, gname) for gname in glyph_order}
    units_per_px = source_units_per_raster_pixel(src_upm, args.raster_size)
    cmap_glyphs = set(cmap.values())
    base_adv_px = pil_font.getlength("ก")
    width_scale = 1.0 if args.fit_mode == "native" else args.target_width / base_adv_px
    source_to_out_x = PX_X / units_per_px * width_scale
    source_to_out_y = PX_Y / units_per_px * vertical_scale
    source_to_out_mark_y = PX_Y / units_per_px
    mark_target_width = base_adv_px if args.fit_mode == "native" else max(args.target_width, MARK_WIDTH_FOR_SMALL_FONTS)
    mark_width_scale = 1.0 if args.fit_mode == "native" else mark_target_width / base_adv_px
    source_to_out_mark_x = PX_X / units_per_px * mark_width_scale
    if args.fit_mode == "native":
        print(f"  horizontal fit: native raster advance ก={base_adv_px:.2f}px (x*1.000)")
    else:
        print(f"  horizontal fit: ก advance {base_adv_px:.2f}px -> {args.target_width}px (x*{width_scale:.3f})")
    print(f"  vertical fit: {src_h}px canvas -> {fitted_h}px canvas ({args.height_mode}, y*{vertical_scale:.3f})")
    print(f"  advance mode: {args.advance_mode}")
    print(f"  scanline: {args.scanline}")

    # Process cmap-mapped glyphs first (have a codepoint to render via PIL)
    processed = 0
    for cp, gname in cmap.items():
        try:
            char = chr(cp)
            advance = int(round(pil_font.getlength(char)))
            bbox = pil_font.getbbox(char)
            if bbox is None:
                continue
            source_adv = source_hmtx.get(gname, (0, 0))[0]
            is_combining = (source_adv == 0)
            if is_combining:
                source_box = source_bboxes.get(gname)
                if source_box:
                    x_min, _y_min, x_max, _y_max = source_box
                    cell_w = max(int(round((x_max - x_min) / units_per_px)), 1)
                else:
                    cell_w = max(bbox[2] - min(0, bbox[0]), 1)
            else:
                if advance <= 0:
                    continue
                cell_w = max(advance, 1)

            bitmap = rasterize(pil_font, char, cell_w, src_h, force_combining=is_combining)
            glyph_width_scale = mark_width_scale if is_combining else width_scale
            fitted_w = fit_width(cell_w, glyph_width_scale)
            bitmap = scale_bitmap_x(bitmap, fitted_w)
            if args.height_mode == "or12":
                # OR merge is good for base glyphs because it preserves thin
                # horizontal strokes. Thai tone/mark glyphs lose distinctions
                # under OR merge, so keep them at the original 16px-tall raster.
                if is_combining:
                    emit_h = src_h
                    emit_asc = pil_asc
                else:
                    bitmap = or_merge_4to3(bitmap)
                    emit_h = fitted_h
                    emit_asc = asc_design
            else:
                bitmap = scale_bitmap_y(bitmap, fitted_h)
                emit_h = fitted_h
                emit_asc = asc_design
            if args.skeleton_strokes:
                bitmap = thin_bitmap(bitmap)
            elif args.normalize_vertical_stems:
                bitmap = normalize_vertical_stems(bitmap)
            x_shift = 0
            if is_combining:
                # Preserve the original zero-width glyph origin. Thai mark glyphs
                # in Noto sit at negative X relative to the current cursor; forcing
                # leftmost ink to x=0 turns them into inline spacing glyphs.
                source_box = source_bboxes.get(gname)
                if source_box:
                    x_shift = int(round((source_box[0] / units_per_px) * glyph_width_scale))
                if args.fit_mode != "native" and is_centered_top_mark(cp):
                    x_shift = center_mark_shift(args.target_width, fitted_w)
                x_shift -= mark_left_shift
                mark_raise_rows = args.mark_raise_rows
                if (args.fit_mode != "native" and args.height_mode == "or12"
                        and is_above_mark(cp)):
                    mark_raise_rows -= 2
                if mark_raise_rows > 0:
                    bitmap = shift_bitmap_y(bitmap, mark_raise_rows)
                elif mark_raise_rows < 0:
                    bitmap = shift_bitmap_y_down(bitmap, -mark_raise_rows)
                if args.fit_mode != "native" and cp == 0x0E4D:
                    # Nikhahit is the lower part of a two-storey mark stack.
                    # Clearing its top row prevents it from merging with the
                    # upper *.small tone mark while keeping a gap from the base.
                    bitmap = clear_top_ink_rows(bitmap, 1)
            pen = emit_pixels_as_contours_shifted(bitmap, emit_h, fitted_w, emit_asc,
                                                  x_shift, args.scanline)
            if pen:
                new_glyph = pen.glyph()
                glyf[gname] = new_glyph
            else:
                empty = TtGlyph(); empty.numberOfContours = 0
                new_glyph = empty
                glyf[gname] = new_glyph
            new_adv = fitted_advance(source_adv, fitted_w, source_to_out_x, args.advance_mode)
            new_box = glyph_coord_bbox(new_glyph)
            if not is_combining and new_box and args.min_right_bearing_px > 0:
                new_adv = max(new_adv, new_box[2] + args.min_right_bearing_px * PX_X)
            new_lsb = new_box[0] if is_combining and new_box else 0
            hmtx[gname] = (new_adv, new_lsb)
            processed += 1
        except Exception:
            pass
    print(f"  processed {processed} cmap glyphs")

    # Non-cmap glyphs (= variants/composed marks reached via GSUB substitution).
    # For variants like "uni0E35.narrow" or "uni0E49.small", strip the suffix
    # and copy the base glyph's pixelation. For composed marks, use the FIRST
    # component's pixelation as approximation.
    cmap_gname_to_cp = {gn: cp for cp, gn in cmap.items()}
    name_to_base = {}
    for gname in glyph_order:
        if gname in cmap_glyphs or gname == '.notdef':
            continue
        # Try suffix-stripping: uni0E35.narrow → uni0E35
        if '.' in gname:
            base = gname.split('.')[0]
            if base in cmap_glyphs:
                name_to_base[gname] = base
                continue
        # Composed marks like nikhahit_maiChattawathai_X → use first part as fallback
        if '_' in gname:
            first = gname.split('_')[0]
            # try uni-prefixed variant
            for candidate in [first, 'uni' + first[0:4] if len(first) >= 4 else None]:
                if candidate and candidate in cmap_glyphs:
                    name_to_base[gname] = candidate
                    break

    non_cmap_count = 0
    for gname, base_gname in name_to_base.items():
        # Re-trace base glyph's outline via TTGlyphPen to clone properly
        base_g = glyf[base_gname]
        if not hasattr(base_g, 'coordinates') or not base_g.coordinates:
            continue
        coords = list(base_g.coordinates)
        base_out_box = coords_bbox(coords)
        base_box = source_bboxes.get(base_gname)
        variant_box = source_bboxes.get(gname)
        is_mark_variant = source_hmtx.get(base_gname, (1, 0))[0] == 0
        dx = dy = 0
        sx = sy = 1.0
        if base_box and variant_box:
            dx = int(round((variant_box[0] - base_box[0]) * source_to_out_x))
            y_scale = source_to_out_mark_y if is_mark_variant else source_to_out_y
            dy = int(round((variant_box[1] - base_box[1]) * y_scale))
            if is_mark_variant:
                base_w = max(1, base_box[2] - base_box[0])
                base_h = max(1, base_box[3] - base_box[1])
                sx = max(0.5, min(1.0, (variant_box[2] - variant_box[0]) / base_w))
                sy = max(0.5, min(1.0, (variant_box[3] - variant_box[1]) / base_h))
                if args.target_width < MARK_WIDTH_FOR_SMALL_FONTS:
                    sx = min(1.0, sx * (MARK_WIDTH_FOR_SMALL_FONTS / args.target_width))
                dx = int(round((variant_box[0] - base_box[0]) * source_to_out_mark_x))
                # Keep upper stacked variants high enough to avoid merging
                # into the lower mark. Base/cmap marks are shifted above.
                # Mark variants such as *.small are raised/nudged in the source
                # font. Preserve that relation, but keep the copied pixel glyph
                # inside the current zero-advance mark slot and inside the line.
                if base_out_box:
                    dx = min(dx, -base_out_box[2])
                    scaled_h = int(round((base_out_box[3] - base_out_box[1]) * sy))
                    dy = min(dy, new_asc - base_out_box[1] - scaled_h)
        pen = TTGlyphPen(None)
        ends = list(base_g.endPtsOfContours)
        start = 0
        y_snap_grid = PX_X if args.scanline != "none" else PX_Y
        for end in ends:
            pts = coords[start:end+1]
            if len(pts) >= 3:
                def transform(p):
                    if is_mark_variant and base_out_box:
                        x_anchor = base_out_box[2]
                        y_anchor = base_out_box[1]
                        x = x_anchor + dx + int(round((p[0] - x_anchor) * sx))
                        y = y_anchor + dy + int(round((p[1] - y_anchor) * sy))
                        return snap_to_grid(x, PX_X), snap_to_grid(y, y_snap_grid)
                    return snap_to_grid(p[0] + dx, PX_X), snap_to_grid(p[1] + dy, y_snap_grid)

                pen.moveTo(transform(pts[0]))
                for p in pts[1:]:
                    pen.lineTo(transform(p))
                pen.closePath()
            start = end + 1
        new_glyph = pen.glyph()
        glyf[gname] = new_glyph
        new_box = glyph_coord_bbox(new_glyph)
        new_lsb = new_box[0] if is_mark_variant and new_box else 0
        hmtx[gname] = (hmtx[base_gname][0], new_lsb)
        non_cmap_count += 1
    print(f"  copied {non_cmap_count} non-cmap variants from base glyphs")

    # Remaining non-cmap glyphs (no obvious base): empty them out so they
    # at least don't render as smooth vectors
    other_empty = 0
    for gname in glyph_order:
        if gname in cmap_glyphs or gname == '.notdef' or gname in name_to_base:
            continue
        g = glyf[gname]
        if hasattr(g, 'coordinates') and len(g.coordinates) > 0:
            empty = TtGlyph(); empty.numberOfContours = 0
            glyf[gname] = empty
            hmtx[gname] = (0, 0)
            other_empty += 1
    print(f"  emptied {other_empty} other non-cmap glyphs")

    # GPOS rescale: source UPM=1000, target UPM=1024, plus pixel snap to PX boundaries
    # Anchor scale = (1 source unit in source UPM) → (1 source unit in our PX scheme)
    # Source 1000 units = 1 em. At 8px rasterization, 1 source pixel = 1000/8 = 125 source units.
    # In our bake: 1 source pixel = PX = 64 font units.
    # So GPOS anchor scale = 64/125 = 0.512.
    if 'GPOS' in tt:
        anchor_scale_x = (PX_X / (SRC_UPM_ASSUMED / args.raster_size)) * width_scale
        anchor_scale_y = (PX_Y / (SRC_UPM_ASSUMED / args.raster_size)) * vertical_scale
        if args.fit_mode == "native":
            def snap_x(v): return int(round(v))
            def snap_y(v): return int(round(v))
        else:
            def snap_x(v): return int(round(v / PX_X)) * PX_X
            def snap_y(v): return int(round(v / PX_Y)) * PX_Y
        anchor_count = [0]

        def scale_anchor(anchor):
            if anchor is None: return
            if hasattr(anchor, 'XCoordinate') and anchor.XCoordinate is not None:
                anchor.XCoordinate = snap_x(anchor.XCoordinate * anchor_scale_x)
            if hasattr(anchor, 'YCoordinate') and anchor.YCoordinate is not None:
                anchor.YCoordinate = snap_y(anchor.YCoordinate * anchor_scale_y)
            anchor_count[0] += 1

        def scale_value_record(vr):
            if vr is None: return
            for attr_name, scale_fn in [('XPlacement', lambda v: snap_x(v * anchor_scale_x)),
                                        ('XAdvance', lambda v: snap_x(v * anchor_scale_x)),
                                        ('YPlacement', lambda v: snap_y(v * anchor_scale_y)),
                                        ('YAdvance', lambda v: snap_y(v * anchor_scale_y))]:
                if hasattr(vr, attr_name):
                    v = getattr(vr, attr_name)
                    if v is not None:
                        setattr(vr, attr_name, scale_fn(v))

        def visit_subtable(sub):
            tname = sub.__class__.__name__
            if tname == "ExtensionPos":
                visit_subtable(sub.ExtSubTable); return
            if tname == "MarkBasePos":
                for mark in sub.MarkArray.MarkRecord:
                    scale_anchor(mark.MarkAnchor)
                for base in sub.BaseArray.BaseRecord:
                    for anchor in base.BaseAnchor:
                        scale_anchor(anchor)
            elif tname == "MarkMarkPos":
                for mark in sub.Mark1Array.MarkRecord:
                    scale_anchor(mark.MarkAnchor)
                for m2 in sub.Mark2Array.Mark2Record:
                    for anchor in m2.Mark2Anchor:
                        scale_anchor(anchor)
            elif tname == "MarkLigPos":
                for mark in sub.MarkArray.MarkRecord:
                    scale_anchor(mark.MarkAnchor)
                for lig in sub.LigatureArray.LigatureAttach:
                    for comp in lig.ComponentRecord:
                        for anchor in comp.LigatureAnchor:
                            scale_anchor(anchor)
            elif tname == "CursivePos":
                for ee in sub.EntryExitRecord:
                    scale_anchor(ee.EntryAnchor)
                    scale_anchor(ee.ExitAnchor)
            elif tname == "PairPos":
                if sub.Format == 1:
                    for ps in sub.PairSet:
                        for pv in ps.PairValueRecord:
                            scale_value_record(pv.Value1)
                            scale_value_record(pv.Value2)
                elif sub.Format == 2:
                    for c1 in sub.Class1Record:
                        for c2 in c1.Class2Record:
                            scale_value_record(c2.Value1)
                            scale_value_record(c2.Value2)
            elif tname == "SinglePos":
                if sub.Format == 1:
                    scale_value_record(sub.Value)
                elif sub.Format == 2:
                    for vr in sub.Value:
                        scale_value_record(vr)
        for lookup in tt['GPOS'].table.LookupList.Lookup:
            for sub in lookup.SubTable:
                visit_subtable(sub)
        snap_note = "unsnapped" if args.fit_mode == "native" else f"snapped to grid {PX_X}/{PX_Y}"
        print(f"  GPOS: scaled {anchor_count[0]} anchors x*{anchor_scale_x:.3f} y*{anchor_scale_y:.3f} ({snap_note})")

    # Rewrite name
    name = tt['name']
    name.names = [r for r in name.names if r.nameID not in (1, 2, 3, 4, 6, 16, 17)]
    ps_suffix = ADVANCE_MODE_SUFFIX[args.advance_mode].replace("-", "").title()
    ps_name = f"K64ThaiPixel{args.target_width}W{ps_suffix}-Y2X-Regular"
    for nid, txt in [(1, "K64 Thai"), (2, "Regular"),
                     (3, ps_name), (4, "K64 Thai Regular"),
                     (6, ps_name)]:
        name.setName(txt, nid, 3, 1, 0x409)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.suffix.lower() == ".ttf":
        tt.save(str(out_path))
    else:
        tmp = out_path.with_suffix('.ttf')
        tt.save(str(tmp))
        tt2 = TTFont(str(tmp))
        tt2.flavor = "woff2"
        tt2.save(str(out_path))
        tmp.unlink()
    print(f"  → {out_path.name}")


if __name__ == "__main__":
    main()
