"""Keep Thai *.narrow upper marks off the tall stems of ป ฝ ฟ ฬ in pixel-outline fonts.

The pixel marks are wider than the source marks, so a mark placed by the source
anchors can land on the stem. This shapes the baked font and moves each *.narrow
mark left one pixel at a time, only as far as needed: every extra pixel pushes it
towards the previous letter's marks.
"""
from __future__ import annotations

import io

import uharfbuzz as hb
from fontTools.ttLib import TTFont

THAI_ASCENDERS = "ปฝฟฬ"  # ป ฝ ฟ ฬ: stem rises into the mark zone
THAI_ABOVE_VOWELS = ("ั", "ิ", "ี", "ึ", "ื", "็")
THAI_TONES = ("่", "้", "๊", "๋", "์")
THAI_SARA_AM = "ำ"
SAMPLES = (
    [c + a + t for c in THAI_ASCENDERS for a in ("", *THAI_ABOVE_VOWELS) for t in ("", *THAI_TONES)]
    + [c + t + THAI_SARA_AM for c in THAI_ASCENDERS for t in ("", *THAI_TONES)]
)


def glyph_cells(glyph, px_x: int, px_y: int) -> set[tuple[int, int]]:
    """Pixel cells of a glyph made of axis-aligned rectangle contours."""
    if not getattr(glyph, "numberOfContours", 0):
        return set()
    cells, start = set(), 0
    for end in glyph.endPtsOfContours:
        pts = glyph.coordinates[start:end + 1]
        xs, ys = [x for x, _ in pts], [y for _, y in pts]
        for cx in range(min(xs) // px_x, max(xs) // px_x):
            for cy in range(min(ys) // px_y, max(ys) // px_y):
                cells.add((cx, cy))
        start = end + 1
    return cells


def clear_narrow_marks(tt: TTFont, px_x: int, px_y: int, max_left: int = 2) -> list[str]:
    """Shift overlapping *.narrow glyphs left; return the names that moved."""
    glyf, hmtx, order = tt["glyf"], tt["hmtx"], tt.getGlyphOrder()
    moved = []
    for _ in range(max_left):
        buf = io.BytesIO()
        tt.save(buf)
        font = hb.Font(hb.Face(buf.getvalue()))
        hits = set()
        for text in SAMPLES:
            b = hb.Buffer()
            b.add_str(text)
            b.guess_segment_properties()
            hb.shape(font, b)
            pen, base_cells = 0, set()
            for info, pos in zip(b.glyph_infos, b.glyph_positions):
                name = order[info.codepoint]
                glyph = glyf[name]
                # Renderers put the outline's xMin at the hmtx lsb.
                lsb_shift = hmtx[name][1] - glyph.xMin if glyph.numberOfContours else 0
                dx = round((pen + pos.x_offset + lsb_shift) / px_x)
                dy = round(pos.y_offset / px_y)
                cells = {(x + dx, y + dy) for x, y in glyph_cells(glyf[name], px_x, px_y)}
                if pos.x_advance:
                    base_cells |= cells
                elif name.endswith(".narrow") and cells & base_cells:
                    hits.add(name)
                pen += pos.x_advance
        if not hits:
            break
        for name in hits:
            glyph = glyf[name]
            glyph.coordinates.translate((-px_x, 0))
            glyph.recalcBounds(glyf)
            hmtx[name] = (hmtx[name][0], glyph.xMin)
        moved += sorted(hits)
    return moved
