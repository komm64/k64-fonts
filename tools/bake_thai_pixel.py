#!/usr/bin/env python3
"""Bake NotoSansThai as pixel font, 縦横2倍 (square 2×2 dots like K64F).

Process:
  1. Rasterize NotoSansThai at 8px (so original metrics → small bitmap)
  2. Each source pixel → 2×2 design grid (= square dots when displayed at font-size 32px)
  3. UPM=1024 (matches K64F convention)
  4. Preserve GPOS anchors (rescaled) so HarfBuzz stacks tone marks correctly
"""
from __future__ import annotations
import io, sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import numpy as np
from fontTools.ttLib import TTFont
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib.tables._g_l_y_f import Glyph as TtGlyph
from fontTools.varLib.instancer import instantiateVariableFont
from PIL import Image, ImageDraw, ImageFont

SRC = Path(r"C:\Users\komm64\Projects\reecho\game\assets\fonts\NotoSansThai-Regular_x2w.ttf")
OUT = Path(r"C:\Users\komm64\Projects\chicken-climber-godot\tmp\k64-fonts-staging\k64-thai-pixel-y2x.woff2")

SRC_SIZE = 16       # rasterize at 16px (= ~20 wide × 25 tall cells with _x2w)
PX_X = 100          # font units per source pixel in X (1 disp px at font-size 32, UPM=3200)
PX_Y = 200          # font units per source pixel in Y (2 disp px at font-size 32, UPM=3200; = Y2X effect)
UPM_OUT = 3200      # matches CJK y2x bake UPM
SRC_UPM_ASSUMED = 1000  # NotoSansThai source UPM


def rasterize(pil_font, char, cell_w, cell_h):
    """Render char into binary bitmap. For combining marks (where PIL would
    add a U+25CC dotted-circle base), render 'NBSP + mark' instead and take
    the mark portion only (= image minus what NBSP alone produces)."""
    cell = np.zeros((cell_h, cell_w), dtype=np.uint8)
    try:
        # Detect combining mark: bbox negative-left or no advance
        is_combining = False
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
    return emit_pixels_as_contours_shifted(bitmap, cell_h, cell_w, asc_design, 0)

def emit_pixels_as_contours_shifted(bitmap, cell_h, cell_w, asc_design, x_shift_pixels):
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
            while y_end + 1 < cell_h and bitmap[y_end + 1, x]:
                y_end += 1
            has_ink = True
            x_off = x_shift_pixels
            x0, x1 = (x + x_off) * PX_X, (x + 1 + x_off) * PX_X
            y_top = (asc_design - y) * PX_Y
            y_bot = (asc_design - y_end - 1) * PX_Y
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


def main():
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

    pil_font = ImageFont.truetype(str(SRC), SRC_SIZE)
    pil_asc, pil_desc = pil_font.getmetrics()
    src_h = pil_asc + pil_desc   # raster canvas height
    print(f"  PIL @ {SRC_SIZE}px: asc={pil_asc} desc={pil_desc} (cell h={src_h})")

    asc_design = pil_asc  # rows above baseline in raster
    # Output metrics: Y2X with PX_Y units per source pixel
    # add 1 src-px margin top/bot to avoid FreeType edge clipping
    new_asc = pil_asc * PX_Y + PX_Y
    new_desc = -pil_desc * PX_Y - PX_Y
    line_total = new_asc - new_desc
    new_lineGap = max(0, UPM_OUT - line_total)

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
    cmap_glyphs = set(cmap.values())

    # Process cmap-mapped glyphs first (have a codepoint to render via PIL)
    processed = 0
    for cp, gname in cmap.items():
        try:
            char = chr(cp)
            advance = int(round(pil_font.getlength(char)))
            bbox = pil_font.getbbox(char)
            if bbox is None:
                continue
            is_combining = (advance == 0)
            if is_combining:
                cell_w = max(bbox[2] - min(0, bbox[0]), 1)
            else:
                if advance <= 0:
                    continue
                cell_w = max(advance, 1)

            bitmap = rasterize(pil_font, char, cell_w, src_h)
            # For combining marks: shift X so mark visually centers over previous base.
            # Cursor sits at right edge of base after base advances. We shift the
            # mark glyph left by ~half the typical base width so mark overlays base.
            x_shift = 0
            if is_combining:
                # Heuristic: shift left by half of source raster width (~ base width)
                # so the mark's center sits roughly over the base's center.
                # In PX_X units: -bbox-width/2 → snap to integer pixel
                if bbox[2] - bbox[0] > 0:
                    x_shift = -((bbox[2] - bbox[0]) // 2)
            pen = emit_pixels_as_contours_shifted(bitmap, src_h, cell_w, asc_design, x_shift)
            if pen:
                glyf[gname] = pen.glyph()
            else:
                empty = TtGlyph(); empty.numberOfContours = 0
                glyf[gname] = empty
            new_adv = 0 if is_combining else cell_w * PX_X
            hmtx[gname] = (new_adv, 0)
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
        pen = TTGlyphPen(None)
        coords = list(base_g.coordinates)
        ends = list(base_g.endPtsOfContours)
        start = 0
        for end in ends:
            pts = coords[start:end+1]
            if len(pts) >= 3:
                pen.moveTo(pts[0])
                for p in pts[1:]:
                    pen.lineTo(p)
                pen.closePath()
            start = end + 1
        glyf[gname] = pen.glyph()
        hmtx[gname] = (hmtx[base_gname][0], 0)
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
        anchor_scale_x = PX_X / (SRC_UPM_ASSUMED / SRC_SIZE)
        anchor_scale_y = PX_Y / (SRC_UPM_ASSUMED / SRC_SIZE)
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
        print(f"  GPOS: scaled {anchor_count[0]} anchors x*{anchor_scale_x:.3f} y*{anchor_scale_y:.3f} (snapped to grid {PX_X}/{PX_Y})")

    # Rewrite name
    name = tt['name']
    name.names = [r for r in name.names if r.nameID not in (1, 2, 3, 4, 6, 16, 17)]
    for nid, txt in [(1, "K64 Thai Pixel 2x2"), (2, "Regular"),
                     (3, "K64ThaiPixel2x2-Regular"), (4, "K64 Thai Pixel 2x2 Regular"),
                     (6, "K64ThaiPixel2x2-Regular")]:
        name.setName(txt, nid, 3, 1, 0x409)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix('.ttf')
    tt.save(str(tmp))
    tt2 = TTFont(str(tmp))
    tt2.flavor = "woff2"
    tt2.save(str(OUT))
    tmp.unlink()
    print(f"  → {OUT.name}")


if __name__ == "__main__":
    main()
