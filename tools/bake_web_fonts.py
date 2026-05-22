#!/usr/bin/env python3
"""bake_web_fonts.py — produce woff2 fonts for komm64/k64-fonts CDN distribution.

Outputs (to tmp/k64-fonts-staging/):
  k64-fantasy.woff2                          # K64F v1.37 source (8w x 16h monospace), woff2 only
  k64-fantasy-2x.woff2                       # K64F 2x bake (16w x 32h display, 2x2 square dots)
  k64-JF-Dot-ShinonomeMin16-y2x.woff2        # JF-Dot or-merge + y2x (16w x 24h display, 1x2 tall rect)
  k64-unifont-16px-y2x.woff2                 # unifont or-merge + y2x
  k64-NotoSansThai-Regular-y2x.woff2         # NotoSansThai or-merge + y2x

All baked fonts target font-size: 32px on the web, with em = 32 display px.
  - K64F 2x: 16w x 32h glyph fills the em (square dots 2x2 px)
  - or12+y2x: 16w x 24h glyph (tall rect dots 1x2 px), sits at top of 32px line with 8px gap below

Name table for OFL-derived fonts is rewritten to OFL-safe names (no 'Unifont'/'Noto' brand).
"""
from __future__ import annotations
import io
import os
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import numpy as np
from fontTools.ttLib import TTFont
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib.tables._g_l_y_f import Glyph as TtGlyph
from PIL import Image, ImageDraw, ImageFont

# ---------- paths ----------
ROOT = Path(r"C:\Users\komm64\Projects\chicken-climber-godot")
SRC_K64F   = Path(r"K:\fonts\komm64Fantasy_v1.37.ttf")
# Reecho's already-OR-merged outputs (= tested, baseline-aware, correct glyphs).
# Using these as starting point means we ONLY need to apply Y-2x scale.
REECHO_FONTS_GEN = Path(r"C:\Users\komm64\Projects\reecho\game\assets\fonts\gen")
SRC_JFDOT_OR12 = REECHO_FONTS_GEN / "JF-Dot-ShinonomeMin16_12px_or1.ttf"
SRC_UNI_OR12   = REECHO_FONTS_GEN / "unifont-16px_12px_or1.ttf"
# Thai: Reecho uses x2w (horizontal stretch), NOT or-merge. Need separate treatment.
SRC_THAI_RAW   = Path(r"C:\Users\komm64\Projects\reecho\game\assets\fonts\NotoSansThai-Regular.ttf")
SRC_THAI_X2W   = Path(r"C:\Users\komm64\Projects\reecho\game\assets\fonts\NotoSansThai-Regular_x2w.ttf")
OUT_DIR    = ROOT / "tmp" / "k64-fonts-staging"

# ---------- constants ----------
SRC_H = 16          # source font px size for rasterization
DST_H_MERGE = 12    # OR-merge target height (rows)
OR_PAIR = 1         # which row pair to OR-merge (Reecho default)

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


# ---------- bake: K64F 2x ----------
def bake_k64f_2x(src_path: Path, out_path: Path):
    """K64F source (UPM=1024, 8w x 16h) → 2x bake (UPM=2048, 16w x 32h display).
    Each source pixel becomes 2x2 square dots when displayed at font-size 32px."""
    print(f"[k64f-2x] reading {src_path.name}")
    src_tt = TTFont(str(src_path))
    src_upm = src_tt['head'].unitsPerEm
    src_asc = src_tt['hhea'].ascent     # in source units
    src_desc = src_tt['hhea'].descent
    print(f"  source: UPM={src_upm}  asc={src_asc}  desc={src_desc}")

    # K64F: each source design pixel = src_upm/16 units in source.
    # We want each source design pixel → 2 display pixels in output.
    # Output: 1 display pixel = PX_X units (square dots, so PX_X=PX_Y=64).
    # So each source design pixel = 2*PX_X = 128 units in output.
    SRC_PX_TO_OUT = (2 * PX_X) // (src_upm // 16)   # 128/64 = 2 (scale factor)
    scale = (2 * PX_X) * 16 / src_upm   # = 2.0 (multiplier from source units → output units)

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
        g = glyf[gname]
        if hasattr(g, 'coordinates') and g.coordinates:
            for i, (x, y) in enumerate(g.coordinates):
                g.coordinates[i] = (int(x * scale), int(y * scale))
        # advance also scales
        adv, lsb = hmtx[gname]
        hmtx[gname] = (int(adv * scale), int(lsb * scale))

    # Rename: optional but consistent — use "K64 Fantasy 2X" as family
    rewrite_name(new_tt, family="K64 Fantasy 2X", style="Regular",
                 full="K64 Fantasy 2X Regular", postscript="K64Fantasy2X-Regular",
                 unique=f"K64Fantasy2X-{src_upm}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Save TTF → reload → save woff2 to avoid woff2 glyf corruption after mutation
    tmp_ttf = out_path.with_suffix(".ttf")
    new_tt.save(str(tmp_ttf))
    tt2 = TTFont(str(tmp_ttf))
    tt2.flavor = "woff2"
    tt2.save(str(out_path))
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
                                family: str, postscript: str):
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

    # Scale Y only. UPM doubles to preserve X-per-disp-px at font-size 32.
    new_upm = src_upm * 2   # 1600 → 3200

    # Scale all glyph contour Y coords by 2 (X unchanged)
    glyf = tt['glyf']
    for gname in glyf.keys():
        g = glyf[gname]
        if hasattr(g, 'coordinates') and g.coordinates:
            for i, (x, y) in enumerate(g.coordinates):
                g.coordinates[i] = (x, y * 2)

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
def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # K64F: 1x source + 2x bake
    bake_k64f_1x(SRC_K64F, OUT_DIR / "k64-fantasy.woff2")
    bake_k64f_2x(SRC_K64F, OUT_DIR / "k64-fantasy-2x.woff2")

    # JF-Dot: Reecho's pre-merged TTF + Y2X scale only (= or-merged 12 rows + Y 2x)
    bake_y2x_from_reecho_merged(SRC_JFDOT_OR12,
        OUT_DIR / "k64-JF-Dot-ShinonomeMin16-or12-y2x.woff2",
        family="K64 CJK JP", postscript="K64CJKJP-OR12-Y2X")

    # unifont: Reecho's pre-merged TTF + Y2X scale only (= or-merged 12 rows + Y 2x)
    bake_y2x_from_reecho_merged(SRC_UNI_OR12,
        OUT_DIR / "k64-unifont-16px-or12-y2x.woff2",
        family="K64 CJK Fallback", postscript="K64CJKFallback-OR12-Y2X")

    # Thai: Reecho's _x2w version (horizontal 2x, preserves GPOS shaping).
    # NOTE: Reecho does NOT or-merge Thai. We pass through as-is + rename + woff2 compress.
    # This gives Thai a different aesthetic than CJK (2×1 wide vs 1×2 tall rect dots)
    # but preserves the tone mark positioning Reecho went to trouble to maintain.
    bake_thai_from_reecho_x2w(SRC_THAI_X2W,
        OUT_DIR / "k64-NotoSansThai-Regular-x2w.woff2",
        family="K64 Thai", postscript="K64Thai-X2W")

    print(f"\n[done] all files written to {OUT_DIR}")


if __name__ == "__main__":
    main()
