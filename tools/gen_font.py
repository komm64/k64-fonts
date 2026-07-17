#!/usr/bin/env python3
"""
gen_font.py — 16px TTF → 12px BitmapFont (.fnt + .png) for Godot 4

REECHO runs at 640×240 effective resolution with non-square pixels (1.5:1 tall).
16px fonts displayed as-is look too tall; this tool compresses 16→12px via 4→3 OR-merge.

OR-merge: each group of 4 source rows produces 3 output rows.
--or-pair selects which pair gets OR'd (same rule applied to all 4 groups):
  0: OR(row0,row1), row2, row3       ← merges top of each group
  1: row0, OR(row1,row2), row3       ← merges middle (default)
  2: row0, row1, OR(row2,row3)       ← merges bottom of each group

Dependencies: Pillow, numpy, fontTools, freetype-py
  pip install Pillow numpy fonttools freetype-py

Usage:
  python tools/gen_font.py tmp/fonts/JF-Dot-ShinonomeMin16.ttf --or-pair 1
  python tools/gen_font.py game/assets/fonts/ark-pixel-16px-monospaced-latin.ttf --or-pair 1
  python tools/gen_font.py tmp/fonts/JF-Dot-ShinonomeMin16.ttf game/assets/fonts/ark-pixel-16px-monospaced-latin.ttf --or-pair 2 --output-dir game/assets/fonts/gen
"""

import argparse
import io
import os
import sys
import math
import freetype
import numpy as np
from PIL import Image
from fontTools.ttLib import TTFont as TTLibFont

SRC_H = 16
DST_H = 12
SHEET_W = 1024

# Unhinted mono rendering: the pixel fonts this tool consumes are exactly
# grid-aligned, so hinting can only move ink. FreeType >= 2.14 (bundled in
# Pillow >= 12) autohints diacritics with a vertical-separation adjustment
# that splits grid-aligned marks and pushes them above the ascender.
FT_FLAGS = (freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_MONO |
            freetype.FT_LOAD_MONOCHROME | freetype.FT_LOAD_NO_HINTING |
            freetype.FT_LOAD_NO_AUTOHINT)


class PixelFont:
    """ImageFont-shaped facade over unhinted FreeType mono rendering."""

    def __init__(self, path, size):
        self._face = freetype.Face(path)
        self._face.set_pixel_sizes(0, size)

    def getmetrics(self):
        m = self._face.size
        return m.ascender >> 6, -(m.descender >> 6)

    def _load(self, char):
        self._face.load_char(char, FT_FLAGS)
        return self._face.glyph

    def getlength(self, char):
        return self._load(char).advance.x / 64.0

    def getbbox(self, char):
        """Ink bbox in cell coordinates (y=0 at ascender, downward). None if blank."""
        g = self._load(char)
        if g.bitmap.rows == 0 or g.bitmap.width == 0:
            return None
        ascent, _ = self.getmetrics()
        x0 = g.bitmap_left
        y0 = ascent - g.bitmap_top
        return (x0, y0, x0 + g.bitmap.width, y0 + g.bitmap.rows)

    def bitmap(self, char):
        """Glyph ink as a binary uint8 array (rows × width)."""
        bmp = self._load(char).bitmap
        if bmp.rows == 0 or bmp.width == 0:
            return np.zeros((0, 0), dtype=np.uint8)
        data = np.frombuffer(bytes(bmp.buffer), dtype=np.uint8).reshape(bmp.rows, abs(bmp.pitch))
        return np.unpackbits(data, axis=1)[:, :bmp.width]


def _or_merge(src, or_pair):
    """16-row numpy array → 12-row array via 4→3 OR-merge."""
    assert src.shape[0] == SRC_H
    dst = np.zeros((DST_H, src.shape[1]), dtype=np.uint8)
    for g in range(4):
        s = g * 4
        d = g * 3
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


def _rasterize(font, char, cell_w, src_h=None):
    """Rasterize one character into a src_h×cell_w binary uint8 array.

    Ink outside the cell is clipped in place — negative offsets crop the
    source instead of shifting the whole glyph into the cell."""
    if src_h is None:
        src_h = SRC_H
    cell = np.zeros((src_h, cell_w), dtype=np.uint8)
    try:
        bbox = font.getbbox(char)
        if bbox is None:
            return cell
        arr = font.bitmap(char)
        x0, y0 = bbox[0], bbox[1]
        sy, sx = max(0, -y0), max(0, -x0)
        dy, dx = max(0, y0), max(0, x0)
        h = min(src_h - dy, arr.shape[0] - sy)
        w = min(cell_w - dx, arr.shape[1] - sx)
        if h > 0 and w > 0:
            cell[dy:dy+h, dx:dx+w] = arr[sy:sy+h, sx:sx+w]
    except Exception:
        pass
    return cell


def _next_pow2(n):
    p = 1
    while p < n:
        p *= 2
    return p


def _nn_scale(src):
    """16-row numpy array → 12-row via nearest-neighbour downscale (no OR-merge)."""
    assert src.shape[0] == SRC_H
    dst = np.zeros((DST_H, src.shape[1]), dtype=np.uint8)
    for d in range(DST_H):
        s = int(d * SRC_H / DST_H)
        dst[d] = src[s]
    return dst


def gen_font(input_path, or_pair, output_dir, max_chars=None, no_merge=False, hscale=1,
             cp_min=None, cp_max=None, output_name=None, font_size=SRC_H, cell_height=None):
    name = os.path.splitext(os.path.basename(input_path))[0]
    # glyph_h: actual raster rows stored for each glyph. An explicit cell height
    # also defines the raster height in no-merge mode, allowing a 12px face with
    # 12px ascent + 4px descent to retain its full 16px bitmap.
    cell_h = cell_height if cell_height is not None else SRC_H
    glyph_h = (
        cell_h if no_merge and cell_height is not None
        else font_size if no_merge
        else DST_H
    )
    raster_h = glyph_h if no_merge else font_size
    if not no_merge and font_size != SRC_H:
        print(f"\nERROR: OR-merge bitmap output expects --font-size {SRC_H}", file=sys.stderr)
        return
    yoffset = cell_h - glyph_h  # bottom-align compressed glyphs within the cell
    if output_name is None:
        hscale_tag = f"_x{hscale}w" if hscale != 1 else ""
        output_name = f"{name}_{glyph_h}px" + ("" if no_merge else f"_or{or_pair}") + hscale_tag
    print(f"[{name}] {'no-merge' if no_merge else 'or_pair=' + str(or_pair)}{' hscale=' + str(hscale) if hscale != 1 else ''}", end="", flush=True)

    tt = TTLibFont(input_path)
    cmap = tt.getBestCmap()
    if cmap is None:
        print(f"\nERROR: no cmap in {input_path}", file=sys.stderr)
        return
    codepoints = sorted(cmap.keys())
    if cp_min is not None:
        codepoints = [cp for cp in codepoints if cp >= cp_min]
    if cp_max is not None:
        codepoints = [cp for cp in codepoints if cp <= cp_max]
    if max_chars:
        codepoints = codepoints[:max_chars]
    print(f"  {len(codepoints)} glyphs", end="", flush=True)

    pil_font = PixelFont(input_path, font_size)
    ascent, _descent = pil_font.getmetrics()

    glyphs = []
    empty_glyphs = []
    for cp in codepoints:
        char = chr(cp)
        try:
            bbox = pil_font.getbbox(char)
            advance = int(round(pil_font.getlength(char)))
        except Exception:
            continue
        if advance <= 0:
            continue
        if bbox is None:
            empty_glyphs.append((cp, advance))
            continue
        cell_w = max(advance, 1)
        glyphs.append((cp, char, cell_w, advance))

    # pack rows using cell_h so atlas slot height is always 16px
    x, y = 0, 0
    positions = []
    for cp, char, cell_w, adv in glyphs:
        scaled_w = cell_w * hscale
        if x + scaled_w > SHEET_W:
            x = 0
            y += cell_h
        positions.append((cp, char, x, y, cell_w, adv))
        x += scaled_w
    sheet_h = _next_pow2(y + cell_h)

    # render: place glyph at bottom of its 16px cell slot
    sheet = np.zeros((sheet_h, SHEET_W), dtype=np.uint8)
    empty_position_cps = set()
    for cp, char, sx, sy, cell_w, _adv in positions:
        src = _rasterize(pil_font, char, cell_w, raster_h)
        dst = src if no_merge else _or_merge(src, or_pair)
        if not dst.any():
            empty_glyphs.append((cp, _adv))
            empty_position_cps.add(cp)
            continue
        if hscale != 1:
            dst = np.repeat(dst, hscale, axis=1)
        sheet[sy + yoffset:sy + yoffset + glyph_h, sx:sx + cell_w * hscale] = dst * 255

    os.makedirs(output_dir, exist_ok=True)
    png_name = f"{output_name}_0.png"
    png_path = os.path.join(output_dir, png_name)
    alpha_img = Image.fromarray(sheet, mode='L')
    white = Image.new('L', alpha_img.size, 255)
    rgba = Image.merge('RGBA', (white, white, white, alpha_img))
    rgba.save(png_path)

    fnt_path = os.path.join(output_dir, f"{output_name}.fnt")
    # base: distance from cell top to baseline; scale proportionally then add top padding
    base = ascent if no_merge else round(ascent * glyph_h / SRC_H) + yoffset
    with open(fnt_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(f'info face="{name}" size={font_size} bold=0 italic=0 charset="" unicode=1 stretchH=100 smooth=0 aa=0 padding=0,0,0,0 spacing=0,0\n')
        f.write(f'common lineHeight={cell_h} base={base} scaleW={SHEET_W} scaleH={sheet_h} pages=1 packed=0\n')
        f.write(f'page id=0 file="{png_name}"\n')
        f.write(f'chars count={len(positions) - len(empty_position_cps) + len(empty_glyphs)}\n')
        for cp, adv in empty_glyphs:
            f.write(f'char id={cp} x=0 y=0 width=0 height=0 xoffset=0 yoffset=0 xadvance={adv * hscale} page=0 chnl=15\n')
        for cp, _char, sx, sy, cell_w, adv in positions:
            if cp in empty_position_cps:
                continue
            f.write(f'char id={cp} x={sx} y={sy + yoffset} width={cell_w * hscale} height={glyph_h} xoffset=0 yoffset={yoffset} xadvance={adv * hscale} page=0 chnl=15\n')

    print(f"  → {output_name}.fnt + .png  (sheet {SHEET_W}×{sheet_h}, cell={cell_h}px glyph={glyph_h}px)")


def gen_font_ttf(input_path, or_pair, output_dir, max_chars=None, cp_min=None, cp_max=None, output_name=None, cp_exclude_ranges=None, no_merge=False, hscale=1):
    """Generate TTF with OR-merged pixel outlines. Shaping tables (GSUB/GPOS) preserved from source."""
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.ttLib.tables._g_l_y_f import Glyph as TtGlyph

    name = os.path.splitext(os.path.basename(input_path))[0]
    if output_name is None:
        suffix = f"_16px_x{hscale}w" if no_merge else f"_12px_or{or_pair}"
        output_name = f"{name}{suffix}"
    print(f"[{name}] TTF {'no-merge' if no_merge else f'or_pair={or_pair}'} hscale={hscale}", end="", flush=True)

    tt = TTLibFont(input_path)
    if 'glyf' not in tt:
        print(f"\nERROR: CFF fonts not supported, need TrueType glyf", file=sys.stderr)
        return
    cmap_tbl = tt.getBestCmap()
    if cmap_tbl is None:
        print(f"\nERROR: no cmap", file=sys.stderr)
        return

    codepoints = sorted(cmap_tbl.keys())
    if cp_min is not None: codepoints = [cp for cp in codepoints if cp >= cp_min]
    if cp_max is not None: codepoints = [cp for cp in codepoints if cp <= cp_max]
    if cp_exclude_ranges:
        codepoints = [cp for cp in codepoints if not any(lo <= cp <= hi for lo, hi in cp_exclude_ranges)]
    if max_chars: codepoints = codepoints[:max_chars]
    print(f"  {len(codepoints)} glyphs", end="", flush=True)

    pil_font = PixelFont(input_path, SRC_H)
    pil_ascent, _ = pil_font.getmetrics()

    # UPM=1600: 1 canvas pixel = 100 font units at font_size=16
    old_upm   = tt['head'].unitsPerEm
    UPM       = SRC_H * 100         # 1600
    PX        = 100                  # font units per canvas pixel
    glyph_h = SRC_H if no_merge else DST_H
    # Compact CJK keeps the shared 12/4 line metrics, but the 640x240
    # ideographic cell ends on the roman baseline: 12px above / 0px below.
    glyph_ascent = pil_ascent if no_merge else glyph_h
    line_ascent = pil_ascent if no_merge else 12
    line_descent = (pil_ascent - glyph_h) if no_merge else -4
    line_gap = 0
    upm_scale = UPM / old_upm

    # Clone font via serialize/reload — preserves all shaping tables intact.
    # Embedded bitmap strikes describe the original source glyphs, however,
    # and become stale as soon as the outlines are replaced below.  Leaving a
    # matching ppem strike in the generated TTF makes FreeType/Godot render the
    # old bitmap instead of the new OR-merged outlines.
    buf = io.BytesIO()
    tt.save(buf)
    buf.seek(0)
    new_tt = TTLibFont(buf)
    for table in ('EBDT', 'EBLC'):
        if table in new_tt:
            del new_tt[table]

    # Update font-level metrics
    new_tt['head'].unitsPerEm = UPM
    new_tt['hhea'].ascent = line_ascent * PX
    new_tt['hhea'].descent = line_descent * PX
    new_tt['hhea'].lineGap = line_gap * PX
    if 'OS/2' in new_tt:
        os2 = new_tt['OS/2']
        os2.sTypoAscender = line_ascent * PX
        os2.sTypoDescender = line_descent * PX
        os2.sTypoLineGap = line_gap * PX
        os2.usWinAscent = line_ascent * PX
        os2.usWinDescent = max(0, -line_descent) * PX

    glyf_tbl = new_tt['glyf']
    hmtx     = new_tt['hmtx'].metrics   # gname → (adv_fu, lsb)

    max_adv  = 0
    replaced = 0
    for cp in codepoints:
        gname = cmap_tbl.get(cp)
        if not gname:
            continue
        char = chr(cp)
        try:
            advance = int(round(pil_font.getlength(char)))
            bbox    = pil_font.getbbox(char)
        except Exception:
            continue
        if bbox is None:
            continue

        # Combining marks (advance=0): rasterize at bbox width but keep zero advance
        is_combining = (advance == 0)
        if is_combining:
            cell_w = max(bbox[2], 1)  # use bbox right edge as raster width
        else:
            if advance <= 0:
                continue
            cell_w = max(advance, 1)

        src    = _rasterize(pil_font, char, cell_w)
        bitmap = src if no_merge else _or_merge(src, or_pair)

        # Merge vertical runs of consecutive lit pixels per column into single
        # rectangles. Stacking 1×1 quads sharing edges causes FreeType raster
        # double-counting at shared edges (= extra row + downward 1-px shift).
        # 1 column N-tall = 1 rect of width PX × height N*PX, no shared edges.
        pen = TTGlyphPen(None)
        has_ink = False
        for x in range(cell_w):
            y = 0
            while y < glyph_h:
                if not bitmap[y, x]:
                    y += 1
                    continue
                # find run end
                y_end = y
                while y_end + 1 < glyph_h and bitmap[y_end + 1, x]:
                    y_end += 1
                has_ink = True
                x0, x1 = x * PX * hscale, (x + 1) * PX * hscale
                # Run spans bitmap rows [y, y_end]. In font units:
                # top (= top of row y) = (glyph_ascent - y) * PX
                # bot (= bottom of row y_end) = (glyph_ascent - y_end - 1) * PX
                y_top = (glyph_ascent - y) * PX
                y_bot = (glyph_ascent - y_end - 1) * PX
                pen.moveTo((x0, y_bot))
                pen.lineTo((x0, y_top))
                pen.lineTo((x1, y_top))
                pen.lineTo((x1, y_bot))
                pen.closePath()
                y = y_end + 1

        if has_ink:
            glyf_tbl[gname] = pen.glyph()
        else:
            empty = TtGlyph()
            empty.numberOfContours = 0
            glyf_tbl[gname] = empty

        adv_fu = 0 if is_combining else cell_w * PX * hscale
        hmtx[gname] = (adv_fu, 0)
        if not is_combining:
            max_adv = max(max_adv, adv_fu)
        replaced += 1

    new_tt['hhea'].advanceWidthMax = max_adv * hscale

    # Prune cmap: remove codepoints outside our processed range so Godot can
    # fall through to the next fallback font for those characters.
    if cp_min is not None or cp_max is not None or cp_exclude_ranges:
        processed_set = set(codepoints)
        for tbl in new_tt['cmap'].tables:
            for cp in list(tbl.cmap.keys()):
                if cp not in processed_set:
                    del tbl.cmap[cp]

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f"{output_name}.ttf")
    new_tt.save(out_path)
    print(f"  → {output_name}.ttf  ({replaced} glyphs, UPM={UPM})")


def main():
    ap = argparse.ArgumentParser(
        description='Generate 12px BitmapFont from 16px TTF via 4→3 OR-merge',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split('Usage:')[1] if 'Usage:' in __doc__ else ''
    )
    ap.add_argument('input', nargs='+', help='TTF font file(s)')
    ap.add_argument('--or-pair', type=int, default=1, choices=[0, 1, 2],
                    help='which row pair to OR-merge in each 4-group (0/1/2, default 1)')
    ap.add_argument('--output-dir', default='game/assets/fonts/gen',
                    help='output directory (default: game/assets/fonts/gen)')
    ap.add_argument('--max-chars', type=int, default=None,
                    help='limit glyph count (for quick testing)')
    ap.add_argument('--no-merge', action='store_true',
                    help='render directly at 16px (no OR-merge); use for fonts without 歯抜けライン (e.g. komm64Fantasy)')
    ap.add_argument('--hscale', type=int, default=1,
                    help='horizontal pixel scale factor (default 1); use 2 for komm64Fantasy to compensate non-square pixels')
    ap.add_argument('--cp-min', type=lambda x: int(x, 0), default=None,
                    help='filter: minimum codepoint (hex ok, e.g. 0x0E00)')
    ap.add_argument('--cp-max', type=lambda x: int(x, 0), default=None,
                    help='filter: maximum codepoint (hex ok, e.g. 0x0E7F)')
    ap.add_argument('--format', choices=['bitmap', 'ttf'], default='bitmap',
                    help='output format: bitmap (.fnt+.png) or ttf (OR-merged pixel outlines, shaping tables preserved)')
    ap.add_argument('--output-name', default=None,
                    help='override output filename stem')
    ap.add_argument('--font-size', type=int, default=SRC_H,
                    help='FreeType pixel size for bitmap output')
    ap.add_argument('--cell-height', type=int, default=None,
                    help='line/atlas height; with --no-merge, also preserves this many raster rows')
    ap.add_argument('--cp-exclude-ranges', default=None,
                    help='comma-separated ranges to strip from cmap (e.g. 0x3000-0x303F,0xFF00-0xFFEF)')
    ap.add_argument('--no-merge-ttf', action='store_true',
                    help='ttf format: skip OR-merge, keep 16px glyph height (like --no-merge for bitmap)')
    ap.add_argument('--hscale-ttf', type=int, default=1,
                    help='ttf format: horizontal pixel scale factor (default 1)')
    args = ap.parse_args()

    exclude_ranges = None
    if args.cp_exclude_ranges:
        exclude_ranges = []
        for part in args.cp_exclude_ranges.split(','):
            lo_s, hi_s = part.strip().split('-')
            exclude_ranges.append((int(lo_s, 0), int(hi_s, 0)))

    for path in args.input:
        if not os.path.exists(path):
            print(f"ERROR: not found: {path}", file=sys.stderr)
            continue
        if args.format == 'ttf':
            gen_font_ttf(path, args.or_pair, args.output_dir, args.max_chars,
                         cp_min=args.cp_min, cp_max=args.cp_max, output_name=args.output_name,
                         cp_exclude_ranges=exclude_ranges,
                         no_merge=args.no_merge_ttf, hscale=args.hscale_ttf)
        else:
            gen_font(path, args.or_pair, args.output_dir, args.max_chars, no_merge=args.no_merge, hscale=args.hscale,
                     cp_min=args.cp_min, cp_max=args.cp_max, output_name=args.output_name,
                     font_size=args.font_size, cell_height=args.cell_height)


if __name__ == '__main__':
    main()
