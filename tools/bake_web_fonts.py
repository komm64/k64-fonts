#!/usr/bin/env python3
"""bake_web_fonts.py — produce woff2 fonts for komm64/k64-fonts CDN distribution.

Outputs (to web/):
  k64-fantasy.woff2                          # K64F v1.37 source (8w x 16h monospace), woff2 only
  k64-fantasy-2x.woff2                       # K64F 2x bake (16w x 32h display, 2x2 square dots)
  k64-JF-Dot-ShinonomeMin16-y2x.woff2        # JF-Dot or-merge + y2x (16w x 24h display, 1x2 tall rect)
  k64-unifont-16px-y2x.woff2                 # unifont or-merge + y2x
  k64-thai-pixel-16w-y2x.woff2               # NotoSansThai fitted to 16px width, 1x2 dots
  k64-thai-pixel-12w-16h-y2x.woff2           # NotoSansThai fitted to 12px width, full 16px height
  k64-thai-pixel-12w-or12-y2x.woff2          # 12w tall source compressed by 4->3 OR merge

All baked fonts target font-size: 32px on the web, with em = 32 display px.
  - K64F 2x: 16w x 32h glyph fills the em (square dots 2x2 px)
  - or12+y2x: 16w x 24h glyph (tall rect dots 1x2 px), sits at top of 32px line with 8px gap below

Name table for OFL-derived fonts is rewritten to OFL-safe names (no 'Unifont'/'Noto' brand).
"""
from __future__ import annotations
import argparse
import io
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np
from fontTools.ttLib import TTFont, woff2
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib.tables._g_l_y_f import Glyph as TtGlyph
from PIL import Image, ImageDraw, ImageFont

# ---------- paths ----------
ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
OUT_DIR = ROOT / "web"

SRC_K64F = SRC_DIR / "komm64Fantasy.ttf"
# Already-OR-merged outputs from tools/gen_font.py.
# Using these as starting point means we ONLY need to apply Y-2x scale.
SRC_JFDOT_OR12 = SRC_DIR / "JF-Dot-ShinonomeMin16_12px_or1.ttf"
SRC_UNI_OR12 = SRC_DIR / "unifont-16px_12px_or1.ttf"
# Thai: x2w preserves tone mark positioning for the smooth fallback.
SRC_THAI_X2W = SRC_DIR / "NotoSansThai-Regular_x2w.ttf"

# ---------- constants ----------
SRC_H = 16          # source font px size for rasterization
DST_H_MERGE = 12    # OR-merge target height (rows)
OR_PAIR = 1         # which row pair to OR-merge (Reecho default)
SCANLINE_SUFFIX = {
    "none": "",
    "erase-upper": "scan-erase-upper",
    "erase-lower": "scan-erase-lower",
}

# Output metrics for "32px line" web display:
# - 1 display pixel = 64 font units (so UPM aligns with K64F's 1024 scale)
# - K64F 2x: glyph 32 disp px tall × 16 disp px wide, fills em (UPM=2048)
# - or12+y2x: glyph 24 disp px tall × 16 disp px wide, top-aligned in 32 px line box
PX_X = 64           # font units per X display pixel
PX_Y = 64           # font units per Y display pixel (square)
UPM_OUT = 2048      # 32 display px * 64 units/px


# ---------- OR-merge ----------
def or_merge(src: np.ndarray, or_pair: int = OR_PAIR) -> np.ndarray:
    """16-row bitmap → 12-row via 4→3 OR-merge (from Reecho gen_font.py)."""
    assert src.shape[0] == SRC_H
    dst = np.zeros((DST_H_MERGE, src.shape[1]), dtype=np.uint8)
    for g in range(4):
        s, d = g * 4, g * 3
        r = src[s:s+4]
        if or_pair == 0:
            dst[d]   = r[0] | r[1]
            dst[d+1] = r[2]
            dst[d+2] = r[3]
        elif or_pair == 1:
            dst[d]   = r[0]
            dst[d+1] = r[1] | r[2]
            dst[d+2] = r[3]
        else:
            dst[d]   = r[0]
            dst[d+1] = r[1]
            dst[d+2] = r[2] | r[3]
    return dst


def rasterize(pil_font: ImageFont.FreeTypeFont, char: str, cell_w: int,
              src_h: int = SRC_H) -> np.ndarray:
    """Rasterize one char into (src_h, cell_w) binary uint8 array."""
    cell = np.zeros((src_h, cell_w), dtype=np.uint8)
    try:
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
        y1 = min(src_h, y0 + mh)
        x1 = min(cell_w, x0 + mw)
        if y1 > y0 and x1 > x0:
            cell[y0:y1, x0:x1] = arr[:y1-y0, :x1-x0]
    except Exception:
        pass
    return cell


# ---------- pixel-to-contour ----------
def emit_pixels_as_contours(bitmap: np.ndarray, cell_w: int, glyph_h: int,
                            px_x: int, px_y: int, asc_design: int):
    """For each col, merge vertical runs of lit pixels into rectangle contours.
    Returns a TTGlyphPen with the glyph drawn (or None if no ink)."""
    pen = TTGlyphPen(None)
    has_ink = False
    for x in range(cell_w):
        y = 0
        while y < glyph_h:
            if not bitmap[y, x]:
                y += 1
                continue
            y_end = y
            while y_end + 1 < glyph_h and bitmap[y_end + 1, x]:
                y_end += 1
            has_ink = True
            x0, x1 = x * px_x, (x + 1) * px_x
            # top of row y, bottom of row y_end (y is from-top, baseline at row asc_design)
            y_top = (asc_design - y) * px_y
            y_bot = (asc_design - y_end - 1) * px_y
            pen.moveTo((x0, y_bot))
            pen.lineTo((x0, y_top))
            pen.lineTo((x1, y_top))
            pen.lineTo((x1, y_bot))
            pen.closePath()
            y = y_end + 1
    return pen if has_ink else None


def scanline_y_bounds(y_min: int, y_max: int, dot_units: int, scanline: str):
    if scanline == "erase-upper":
        return y_min * 2, y_min * 2 + dot_units
    if scanline == "erase-lower":
        return y_max * 2 - dot_units, y_max * 2
    return y_min * 2, y_max * 2


def apply_y2x_or_scanline_to_glyph(glyph, dot_units: int, scanline: str):
    coords = getattr(glyph, "coordinates", None)
    if not coords:
        return
    if scanline == "none":
        for i, (x, y) in enumerate(coords):
            coords[i] = (x, y * 2)
        return

    ends = list(glyph.endPtsOfContours)
    start = 0
    for end in ends:
        contour = list(range(start, end + 1))
        ys = [coords[i][1] for i in contour]
        y_min, y_max = min(ys), max(ys)
        if y_min == y_max:
            for i in contour:
                x, y = coords[i]
                coords[i] = (x, y * 2)
        else:
            new_min, new_max = scanline_y_bounds(y_min, y_max, dot_units, scanline)
            midpoint = (y_min + y_max) / 2
            for i in contour:
                x, y = coords[i]
                coords[i] = (x, new_min if y <= midpoint else new_max)
        start = end + 1


def apply_k64f_2x_or_scanline_to_glyph(glyph, scale: float, dot_units: int,
                                       scanline: str):
    coords = getattr(glyph, "coordinates", None)
    if not coords:
        return
    if scanline == "none":
        for i, (x, y) in enumerate(coords):
            coords[i] = (int(x * scale), int(y * scale))
        return

    contours = []
    start = 0
    for end in glyph.endPtsOfContours:
        contours.append(list(coords[start:end + 1]))
        start = end + 1

    def inside_polygon(px, py, contour):
        inside = False
        prev_x, prev_y = contour[-1]
        for cur_x, cur_y in contour:
            if (cur_y > py) != (prev_y > py):
                cross_x = (prev_x - cur_x) * (py - cur_y) / (prev_y - cur_y) + cur_x
                if px < cross_x:
                    inside = not inside
            prev_x, prev_y = cur_x, cur_y
        return inside

    def inside_glyph(px, py):
        # K64F source outlines are orthogonal bitmap paths. Even-odd fill gives
        # the intended source-pixel occupancy including counters/holes.
        return sum(1 for contour in contours if inside_polygon(px, py, contour)) % 2 == 1

    x_min = (glyph.xMin // dot_units) * dot_units
    x_max = ((glyph.xMax + dot_units - 1) // dot_units) * dot_units
    y_min = (glyph.yMin // dot_units) * dot_units
    y_max = ((glyph.yMax + dot_units - 1) // dot_units) * dot_units

    pen = TTGlyphPen(None)
    has_ink = False
    for y in range(y_min, y_max, dot_units):
        for x in range(x_min, x_max, dot_units):
            if not inside_glyph(x + dot_units / 2, y + dot_units / 2):
                continue
            has_ink = True
            x0 = int(x * scale)
            x1 = int((x + dot_units) * scale)
            out_y0, out_y1 = scanline_y_bounds(y, y + dot_units, dot_units, scanline)
            pen.moveTo((x0, out_y0))
            pen.lineTo((x0, out_y1))
            pen.lineTo((x1, out_y1))
            pen.lineTo((x1, out_y0))
            pen.closePath()

    new_glyph = pen.glyph() if has_ink else TtGlyph()
    if not has_ink:
        new_glyph.numberOfContours = 0
    glyph.__dict__.clear()
    glyph.__dict__.update(new_glyph.__dict__)


# ---------- bake: K64F 2x ----------
def bake_k64f_2x(src_path: Path, out_path: Path, scanline: str = "none"):
    """K64F source (UPM=1024, 8w x 16h) → 2x bake (UPM=2048, 16w x 32h display).
    Each source pixel becomes 2x2 square dots when displayed at font-size 32px."""
    print(f"[k64f-2x] reading {src_path.name}")
    src_tt = TTFont(str(src_path))
    src_upm = src_tt['head'].unitsPerEm
    src_asc = src_tt['hhea'].ascent     # in source units
    src_desc = src_tt['hhea'].descent
    print(f"  source: UPM={src_upm}  asc={src_asc}  desc={src_desc}")
    print(f"  scanline: {scanline}")

    # K64F: each source design pixel = src_upm/16 units in source.
    # We want each source design pixel → 2 display pixels in output.
    # Output: 1 display pixel = PX_X units (square dots, so PX_X=PX_Y=64).
    # So each source design pixel = 2*PX_X = 128 units in output.
    SRC_PX_TO_OUT = (2 * PX_X) // (src_upm // 16)   # 128/64 = 2 (scale factor)
    scale = (2 * PX_X) * 16 / src_upm   # = 2.0 (multiplier from source units → output units)
    dot_units = src_upm // 16

    # Clone via serialize
    buf = io.BytesIO()
    src_tt.save(buf); buf.seek(0)
    new_tt = TTFont(buf)

    # Scale all glyph contours by 2x (= scale factor in font units)
    glyf = new_tt['glyf']
    hmtx = new_tt['hmtx'].metrics
    new_tt['head'].unitsPerEm = UPM_OUT  # 2048
    new_tt['hhea'].ascent  = int(src_asc * scale)
    new_tt['hhea'].descent = int(src_desc * scale)
    new_tt['hhea'].lineGap = 0
    if 'OS/2' in new_tt:
        os2 = new_tt['OS/2']
        os2.sTypoAscender  = int(src_asc * scale)
        os2.sTypoDescender = int(src_desc * scale)
        os2.sTypoLineGap   = 0
        os2.usWinAscent    = int(src_asc * scale)
        os2.usWinDescent   = max(0, int(-src_desc * scale))

    for gname in glyf.keys():
        apply_k64f_2x_or_scanline_to_glyph(glyf[gname], scale, dot_units, scanline)
        # advance also scales
        adv, lsb = hmtx[gname]
        hmtx[gname] = (int(adv * scale), int(lsb * scale))

    # Rename: optional but consistent — use "K64 Fantasy 2X" as family
    scan_suffix = SCANLINE_SUFFIX[scanline]
    family = "K64 Fantasy 2X" if scanline == "none" else f"K64 Fantasy 2X {scan_suffix}"
    ps_suffix = "" if scanline == "none" else scan_suffix.replace("-", "").title()
    rewrite_name(new_tt, family=family, style="Regular",
                 full=f"{family} Regular", postscript=f"K64Fantasy2X{ps_suffix}-Regular",
                 unique=f"K64Fantasy2X{ps_suffix}-{src_upm}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Save TTF → reload → save woff2 to avoid woff2 glyf corruption after mutation
    tmp_ttf = out_path.with_suffix(".ttf")
    new_tt.save(str(tmp_ttf))
    if scanline == "none":
        tt2 = TTFont(str(tmp_ttf))
        tt2.flavor = "woff2"
        tt2.save(str(out_path))
    else:
        # The glyf transform is very slow for large bitmap-outline fonts
        # such as Unifont. WOFF2 without table transforms is still valid and
        # keeps scanline variants practical to generate.
        woff2.compress(str(tmp_ttf), str(out_path), transform_tables=set())
    tmp_ttf.unlink()
    print(f"  → {out_path.name}")


# ---------- bake: Thai pass-through from Reecho _x2w ----------
def bake_thai_from_reecho_x2w(src_path: Path, out_path: Path,
                              family: str, postscript: str):
    """Take Reecho's _x2w Thai (horizontal stretched, shaping preserved).
    No glyph changes, just rename for OFL safety + woff2 compress."""
    print(f"[thai-x2w-passthrough] reading {src_path.name}")
    tt = TTFont(str(src_path))
    rewrite_name(tt, family=family, style="Regular",
                 full=f"{family} Regular", postscript=postscript, unique=postscript)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tt.flavor = "woff2"
    tt.save(str(out_path))
    print(f"  → {out_path.name}")


# ---------- bake: K64F source-as-woff2 (1x, no transformation) ----------
def bake_k64f_1x(src_path: Path, out_path: Path):
    """Just compress K64F source to woff2, no glyph changes."""
    print(f"[k64f-1x] reading {src_path.name}")
    tt = TTFont(str(src_path))
    rewrite_name(tt, family="K64 Fantasy", style="Regular",
                 full="K64 Fantasy Regular", postscript="K64Fantasy-Regular",
                 unique="K64Fantasy-1x")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tt.flavor = "woff2"
    tt.save(str(out_path))
    print(f"  → {out_path.name}")


# ---------- bake: y2x from Reecho-pre-merged TTF ----------
def bake_y2x_from_reecho_merged(src_path: Path, out_path: Path,
                                family: str, postscript: str,
                                scanline: str = "none"):
    """Take Reecho's already-OR-merged TTF (UPM=1600, 12 tall glyph, 100 units/design-px)
    and apply Y-2x scaling. Result: 1 source design pixel becomes 1 disp px wide × 2 disp px tall.

    Math:
      - Source: UPM=1600, asc=1100, desc=-100, lineGap=400. 100 units = 1 design pixel.
      - At target font-size 32px, target line = 32 disp px.
      - To make X stay at 1 disp px per source design px AND Y at 2 disp px per source design px:
        - Y2X scale: multiply all Y coords by 2
        - UPM doubles: 1600 → 3200 (so 100 units still = 1 disp px in X at font-size 32 since 3200/32=100)
        - asc/desc/lineGap also doubled (= preserves baseline at design y=0)
      - Width unchanged: glyph 16 design X px = 1600 units = 16 disp px (matches K64F x2 width).
    """
    print(f"[y2x-from-reecho] reading {src_path.name}")
    tt = TTFont(str(src_path))
    src_upm = tt['head'].unitsPerEm
    print(f"  source: UPM={src_upm}  asc={tt['hhea'].ascent}  desc={tt['hhea'].descent}  lineGap={tt['hhea'].lineGap}")
    print(f"  scanline: {scanline}")

    # Scale Y only. UPM doubles to preserve X-per-disp-px at font-size 32.
    new_upm = src_upm * 2   # 1600 → 3200

    # Scale all glyph contour Y coords by 2 (X unchanged). In scanline mode,
    # each 1x2 output dot keeps only one 1px half.
    glyf = tt['glyf']
    dot_units = src_upm // 16
    for gname in glyf.keys():
        apply_y2x_or_scanline_to_glyph(glyf[gname], dot_units, scanline)

    # Update metrics: add 2-disp-px margin between glyph edges and asc/desc.
    # Without margin (asc == glyph yMax), FreeType anti-aliases the top edge,
    # rendering it as a 1-disp-px row instead of the full 2-disp-px-tall dot.
    # This breaks the "1×2 tall rect dot" invariant.
    # Source: asc=1100, desc=-100 (glyph top/bot at edges). After y2x without margin
    # would be asc=2200, desc=-200. With +200 margin each side: asc=2400, desc=-400.
    MARGIN = 200   # 2 disp px = 200 units (in UPM=3200, font-size=32 → 100 u/px)
    new_asc  = tt['hhea'].ascent  * 2 + MARGIN     # e.g. 1100*2 + 200 = 2400
    new_desc = tt['hhea'].descent * 2 - MARGIN     # e.g. -100*2 - 200 = -400
    # lineGap pads to total line height of UPM (= K64F 2x line at font-size 32)
    new_lineGap = new_upm - (new_asc - new_desc)   # e.g. 3200 - 2400 - 400 = 400
    if new_lineGap < 0:
        new_lineGap = 0

    tt['head'].unitsPerEm = new_upm
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

    # head.yMin / yMax: glyph bbox (NOT line metrics). Scale glyph extents.
    tt['head'].yMin = tt['head'].yMin * 2
    tt['head'].yMax = tt['head'].yMax * 2

    rewrite_name(tt, family=family, style="Regular",
                 full=f"{family} Regular", postscript=postscript, unique=postscript)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Save as TTF first, then reload + convert to woff2 (direct woff2 save
    # corrupts the glyf stream when contours were mutated in memory).
    tmp_ttf = out_path.with_suffix(".ttf")
    tt.save(str(tmp_ttf))
    tt2 = TTFont(str(tmp_ttf))
    tt2.flavor = "woff2"
    tt2.save(str(out_path))
    tmp_ttf.unlink()
    print(f"  → {out_path.name}  (new UPM={new_upm})")


# ---------- DEPRECATED: bake: or-merge + y2x from raw source ----------
def bake_or12_y2x(src_path: Path, out_path: Path, family: str, postscript: str,
                  cp_min: int = None, cp_max: int = None,
                  cp_exclude_ranges: list = None,
                  preserve_shaping: bool = False):
    """OR-merge source (16→12 tall) + emit with each source pixel as 1 wide × 2 tall.
    Result: glyph design 16w × 24h display (= tall rect dots when rendered at font-size 32px).
    """
    print(f"[or12-y2x] reading {src_path.name}")
    tt = TTFont(str(src_path))
    cmap_tbl = tt.getBestCmap()
    if cmap_tbl is None:
        print("  ERROR: no cmap", file=sys.stderr); return

    codepoints = sorted(cmap_tbl.keys())
    if cp_min is not None: codepoints = [cp for cp in codepoints if cp >= cp_min]
    if cp_max is not None: codepoints = [cp for cp in codepoints if cp <= cp_max]
    if cp_exclude_ranges:
        codepoints = [cp for cp in codepoints if not any(lo <= cp <= hi for lo, hi in cp_exclude_ranges)]
    print(f"  {len(codepoints)} codepoints in range")

    pil_font = ImageFont.truetype(str(src_path), SRC_H)

    # Output metrics (Reecho-compatible baseline convention):
    # - UPM = 2048 (= 32 display px @ font-size 32px)
    # - Each source pixel: PX_X wide × (PX_Y * 2) tall in font units (= 1 display px × 2 display px)
    # - asc_design = glyph_h - 1 = 11 (Reecho convention)
    #     bitmap row 0  → design y=+11 (= top of ascent)
    #     bitmap row 11 → design y=-1 (= 1 design px below baseline = descender)
    # - hhea.ascent  = 11 * 128 = 1408 (= 22 display px above baseline)
    # - hhea.descent = -1 * 128 = -128 (= 2 display px below baseline)
    # - Glyph ink: 24 display px tall total (= K64F 2x line padded with lineGap 8 display px)
    px_y_out = PX_Y * 2     # 128 = 2 display pixels tall per source pixel
    glyph_h_design = DST_H_MERGE   # 12 source rows
    asc_design = glyph_h_design - 1  # 11 — Reecho baseline-aware convention
    ascent_units  = asc_design * px_y_out                 # 1408
    descent_units = (asc_design - glyph_h_design) * px_y_out   # -128
    lineGap_units = UPM_OUT - (ascent_units - descent_units)   # 2048 - 1536 = 512

    # Clone
    buf = io.BytesIO()
    tt.save(buf); buf.seek(0)
    new_tt = TTFont(buf)
    new_tt['head'].unitsPerEm = UPM_OUT
    new_tt['hhea'].ascent  = ascent_units
    new_tt['hhea'].descent = descent_units
    new_tt['hhea'].lineGap = lineGap_units
    if 'OS/2' in new_tt:
        os2 = new_tt['OS/2']
        os2.sTypoAscender  = ascent_units
        os2.sTypoDescender = descent_units
        os2.sTypoLineGap   = lineGap_units
        os2.usWinAscent    = ascent_units
        os2.usWinDescent   = max(0, -descent_units)

    glyf_tbl = new_tt['glyf']
    hmtx     = new_tt['hmtx'].metrics
    max_adv  = 0
    replaced = 0

    for cp in codepoints:
        gname = cmap_tbl.get(cp)
        if not gname: continue
        char = chr(cp)
        try:
            advance = int(round(pil_font.getlength(char)))
            bbox    = pil_font.getbbox(char)
        except Exception:
            continue
        if bbox is None: continue

        is_combining = (advance == 0)
        if is_combining:
            cell_w = max(bbox[2], 1)
        else:
            if advance <= 0: continue
            cell_w = max(advance, 1)

        src = rasterize(pil_font, char, cell_w)
        bitmap = or_merge(src)   # 12 rows

        pen = emit_pixels_as_contours(bitmap, cell_w, glyph_h_design,
                                       PX_X, px_y_out, asc_design)
        # asc_design=11 means glyph extends 1 design px below baseline for
        # source content in bitmap row 11 (= source row 15 via or_pair=1).
        if pen:
            glyf_tbl[gname] = pen.glyph()
        else:
            empty = TtGlyph(); empty.numberOfContours = 0
            glyf_tbl[gname] = empty

        adv_fu = 0 if is_combining else cell_w * PX_X
        hmtx[gname] = (adv_fu, 0)
        if not is_combining:
            max_adv = max(max_adv, adv_fu)
        replaced += 1

    new_tt['hhea'].advanceWidthMax = max_adv

    # Prune cmap
    if cp_min is not None or cp_max is not None or cp_exclude_ranges:
        processed = set(codepoints)
        for tbl in new_tt['cmap'].tables:
            for cp in list(tbl.cmap.keys()):
                if cp not in processed:
                    del tbl.cmap[cp]

    rewrite_name(new_tt, family=family, style="Regular",
                 full=f"{family} Regular", postscript=postscript,
                 unique=postscript)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    new_tt.flavor = "woff2"
    new_tt.save(str(out_path))
    print(f"  → {out_path.name}  ({replaced} glyphs)")


# ---------- Name table rewrite ----------
def rewrite_name(tt: TTFont, family: str, style: str, full: str,
                 postscript: str, unique: str):
    """Rewrite name table so the font identifies as `family`, not its original brand.
    Required for OFL Reserved Font Name compliance on derivative works.
    """
    if 'name' not in tt:
        return
    name = tt['name']
    # NameID 1 = family, 2 = style, 3 = unique ID, 4 = full, 6 = postscript
    # 16 = preferred family, 17 = preferred style
    # We set in Mac Roman (platform 1) and Windows (platform 3)
    PLATFORMS = [(3, 1, 0x409)]   # Win/Unicode/en-US is what browsers actually consult
    # Remove existing records for the IDs we're rewriting
    new_records = [r for r in name.names if r.nameID not in (1, 2, 3, 4, 6, 16, 17)]
    name.names = new_records

    def add(nameID, text):
        for platformID, platEncID, langID in PLATFORMS:
            name.setName(text, nameID, platformID, platEncID, langID)

    add(1, family)
    add(2, style)
    add(3, unique)
    add(4, full)
    add(6, postscript)


# ---------- main ----------
def main(argv=None):
    parser = argparse.ArgumentParser(description="Bake k64 web fonts into web/.")
    parser.add_argument(
        "--include-unifont",
        action="store_true",
        help="also regenerate the large Unifont WOFF2; slow because it has ~57k glyphs",
    )
    parser.add_argument(
        "--scanline",
        choices=list(SCANLINE_SUFFIX),
        default="none",
        help="erase one half of each 1x2 y2x dot for generated y2x fonts",
    )
    args = parser.parse_args(argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # K64F: 1x source + 2x bake
    bake_k64f_1x(SRC_K64F, OUT_DIR / "k64-fantasy.woff2")
    scan_suffix = SCANLINE_SUFFIX[args.scanline]
    k64f_2x_name = "k64-fantasy-2x.woff2" if not scan_suffix else f"k64-fantasy-2x-{scan_suffix}.woff2"
    bake_k64f_2x(SRC_K64F, OUT_DIR / k64f_2x_name, scanline=args.scanline)

    # JF-Dot: Reecho's pre-merged TTF + Y2X scale only (= or-merged 12 rows + Y 2x)
    cjk_suffix = f"-{scan_suffix}" if scan_suffix else ""
    bake_y2x_from_reecho_merged(SRC_JFDOT_OR12,
        OUT_DIR / f"k64-JF-Dot-ShinonomeMin16-or12-y2x{cjk_suffix}.woff2",
        family="K64 CJK JP", postscript=f"K64CJKJP-OR12-Y2X{scan_suffix}",
        scanline=args.scanline)

    # unifont: Reecho's pre-merged TTF + Y2X scale only (= or-merged 12 rows + Y 2x).
    # This font has ~57k glyphs and fontTools WOFF2 compression is very slow, so
    # the normal bake keeps the checked-in web file unless explicitly requested.
    if args.include_unifont:
        bake_y2x_from_reecho_merged(SRC_UNI_OR12,
            OUT_DIR / f"k64-unifont-16px-or12-y2x{cjk_suffix}.woff2",
            family="K64 CJK Fallback", postscript=f"K64CJKFallback-OR12-Y2X{scan_suffix}",
            scanline=args.scanline)
    else:
        print("[unifont] skipped; pass --include-unifont to regenerate the large fallback")

    # Thai: rasterize the x2w source into 1x2 pixel outlines while preserving
    # GSUB/GPOS so tone marks still stack above base consonants.
    from bake_thai_pixel import main as bake_thai_pixel_main
    scan_args = [] if args.scanline == "none" else ["--scanline", args.scanline]
    bake_thai_pixel_main(["--target-width", "16", *scan_args])
    bake_thai_pixel_main(["--target-width", "12", "--height-mode", "full", *scan_args])
    bake_thai_pixel_main(["--target-width", "12", "--height-mode", "or12", *scan_args])
    if args.scanline == "none":
        bake_thai_pixel_main([
            "--target-width", "12",
            "--height-mode", "or12",
            "--advance-mode", "noto-proportional",
            "--min-right-bearing-px", "1",
        ])
        bake_thai_pixel_main([
            "--fit-mode", "native",
            "--raster-size", "12",
            "--height-mode", "full",
            "--advance-mode", "noto-proportional",
            "--min-right-bearing-px", "1",
        ])

    print(f"\n[done] all files written to {OUT_DIR}")


if __name__ == "__main__":
    main()
