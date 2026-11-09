#!/usr/bin/env python3
"""Bake the 16px Taiwan-form TC faces of the 640x480 and 640x240 targets.

    python tools/bake_tc_16px.py

Each face is that target's CK face cut down to the CJK Unified Ideographs block, with
the glyphs of src/unifont-tw-16px.txt redrawn on CK's dot grid. The zh-Hant stack puts
it right before CK, so kana, Hangul, punctuation and the rest come from CK. 640x240
draws the same 16 rows or-merged to 12, the way its CK face is made.

The whole block is kept because Godot counts a face as supporting Han only when it
covers that block, and sorts one that does not behind every face that does: a face
with just the redrawn glyphs would never be reached.

A modified Unifont 9.0.06 (src/unifont-16px.ttf): GPL v2 or later with the GNU font
embedding exception, as that font states. The replacement glyphs' source is
src/unifont-tw-16px.txt and this script.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import numpy as np
from fontTools import subset
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import Glyph as TtGlyph

from bake_320x240_fonts import set_names
from gen_font import _or_merge

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "unifont-tw-16px.txt"
CJK_UNIFIED = range(0x4E00, 0xA000)
LICENSE_NOTE = (
    "GPL v2 or later with the GNU font embedding exception; modified by k64-fonts (Taiwan glyph "
    "forms from src/unifont-tw-16px.txt). See LICENSE/GPL-2.0-font-exception.txt."
)


@dataclass(frozen=True)
class Face:
    ck: str  # the target's CK face: metrics, names and advances come from it
    out: str
    family: str
    postscript: str
    merged: bool  # the 16 rows or-merged to 12
    dot_w: int  # font units per dot
    dot_h: int
    left: int  # x of column 0's left edge
    top: int  # y of row 0's top edge


_640X480 = dict(merged=False, dot_w=64, dot_h=64, left=0, top=896)
_640X240 = dict(merged=True, dot_w=100, left=100)
FACES = (
    Face("game/640x480/k64-640x480-ck-unifont-16px.ttf", "game/640x480/k64-640x480-tc-unifont-tw-16px.ttf",
         "K64 640x480 TC Unifont TW 16px", "K64640x480TCUnifontTW16px-Regular", **_640X480),
    Face("web/640x480/k64-640x480-ck-unifont-16px.woff2", "web/640x480/k64-640x480-tc-unifont-tw-16px.woff2",
         "K64 640x480 TC Unifont TW 16px", "K64640x480TCUnifontTW16px-Regular", **_640X480),
    Face("game/640x240/k64-640x240-ck-unifont-16px-or12.ttf", "game/640x240/k64-640x240-tc-unifont-tw-16px-or12.ttf",
         "K64 640x240 TC Unifont TW 16px OR12", "K64640x240TCUnifontTW16pxOR12-Regular", dot_h=100, top=1100, **_640X240),
    # Web 640x240 is used at font-size 32px: each dot 1 wide by 2 tall.
    Face("web/k64-unifont-16px-or12-y2x.woff2", "web/k64-unifont-tw-16px-or12-y2x.woff2",
         "K64 TC", "K64TC-Regular", dot_h=200, top=2200, **_640X240),
)


def parse_rows(rows: list[str]) -> np.ndarray:
    return np.array([[(int(h, 16) >> (15 - x)) & 1 for x in range(16)] for h in rows], np.uint8)


def read_glyphs() -> dict[int, np.ndarray]:
    """src/unifont-tw-16px.txt: code point -> 16x16 dots."""
    out = {}
    for line in SOURCE.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            cp, _char, *rows = line.split()
            assert len(rows) == 16, cp
            out[int(cp[2:], 16)] = parse_rows(rows)
    return out


def dot_glyph(dots: np.ndarray, face: Face) -> TtGlyph:
    """One rectangle per horizontal run of dots."""
    pen = TTGlyphPen(None)
    for r, row in enumerate(dots):
        y1 = face.top - r * face.dot_h
        y0 = y1 - face.dot_h
        c = 0
        while c < len(row):
            if not row[c]:
                c += 1
                continue
            s = c
            while c < len(row) and row[c]:
                c += 1
            x0, x1 = face.left + s * face.dot_w, face.left + c * face.dot_w
            pen.moveTo((x0, y0))
            pen.lineTo((x0, y1))
            pen.lineTo((x1, y1))
            pen.lineTo((x1, y0))
            pen.closePath()
    return pen.glyph()


def make_tc_face(face: Face, glyphs: dict[int, np.ndarray]) -> TTFont:
    tt = TTFont(ROOT / face.ck, recalcTimestamp=False)
    options = subset.Options(notdef_outline=True, name_IDs=["*"], name_languages=["*"], hinting=False, layout_features=[])
    options.drop_tables.append("FFTM")
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=CJK_UNIFIED)
    subsetter.subset(tt)
    cmap, glyf, hmtx = tt.getBestCmap(), tt["glyf"], tt["hmtx"]
    for cp, dots in glyphs.items():
        glyph = dot_glyph(_or_merge(dots, 1) if face.merged else dots, face)
        glyph.recalcBounds(glyf)
        glyf[cmap[cp]] = glyph
        hmtx[cmap[cp]] = (hmtx[cmap[cp]][0], glyph.xMin)
    set_names(tt, face.family, face.postscript)
    tt["name"].setName(LICENSE_NOTE, 13, 3, 1, 0x409)
    return tt


def save(tt: TTFont, path: Path) -> None:
    # Through a plain sfnt first: the WOFF2 glyf transform needs freshly compiled tables.
    buffer = BytesIO()
    tt.flavor = None
    tt.save(buffer)
    buffer.seek(0)
    out = TTFont(buffer, recalcTimestamp=False)
    out.flavor = "woff2" if path.suffix == ".woff2" else None
    out.save(path)


def main() -> int:
    glyphs = read_glyphs()
    for face in FACES:
        save(make_tc_face(face, glyphs), ROOT / face.out)
        print(f"wrote {face.out} ({len(glyphs)} glyphs redrawn)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
