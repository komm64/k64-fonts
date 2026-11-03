"""Move every target face onto the cross-script alignment rules (tools/k64_alignment.py).

Run after the bake scripts:

    python tools/align_targets.py [--target 640x240] [--dry-run]

Each non-K64F face gets the K64F line box (hhea / OS/2 ascent and descent at its
role size). J and CK faces are also translated as a whole, so their ideographs
sit on the cap-height centre and in the middle of the advance. Shifts are
whole rows (2px on tall-dot web faces) and whole pixels, so the pixel grid is
kept. The step is idempotent: shifts are computed from the current outlines,
so an aligned face gets none.
"""

from __future__ import annotations

import argparse
import math
import sys

from fontTools.ttLib import TTFont

from k64_alignment import (
    CJK_TOLERANCE_PX,
    grid_offset,
    CJK_TOLERANCE_ROWS,
    Face,
    cjk_center,
    cjk_imbalance,
    load_faces,
    reference,
)


def vertical_shift_rows(face: Face, cap: float, ascent: float, descent: float) -> int:
    """Whole-row shift that centres the ideographs on cap/2 and keeps their ink in the line box."""
    offset = (cjk_center(face) - cap / 2) / face.row_px
    # The nearest whole rows, plus one either side for a tall cell that only fits off-centre.
    candidates = range(-math.ceil(offset) - 1, -math.floor(offset) + 2)

    def overflow(rows: int) -> float:
        dy = rows * face.row_px
        return sum(
            max(0.0, box.y1 + dy - ascent) + max(0.0, -(box.y0 + dy) - descent) for box in face.boxes.values()
        )

    def residual(rows: int) -> float:
        # Inside the tolerance counts as centred, so an aligned face is left alone.
        return max(0.0, abs(offset + rows) - CJK_TOLERANCE_ROWS)

    return min(candidates, key=lambda rows: (overflow(rows), residual(rows), abs(rows)))


def horizontal_shift_px(face: Face) -> int:
    imbalance = cjk_imbalance(face)
    return 0 if abs(imbalance) <= CJK_TOLERANCE_PX else math.ceil(imbalance)


def apply(face: Face, ascent_px: float, descent_px: float, dx_px: int, dy_px: float) -> None:
    font = TTFont(face.path)
    units = font["head"].unitsPerEm / face.size
    if dx_px or dy_px:
        dx, dy = round(dx_px * units), round(dy_px * units)
        glyf, hmtx = font["glyf"], font["hmtx"]
        for name in font.getGlyphOrder():
            glyph = glyf[name]
            # Composites follow their (already moved) components.
            if glyph.numberOfContours > 0:
                glyph.coordinates.translate((dx, dy))
                glyph.recalcBounds(glyf)
                # Rasterizers place the outline by its left side bearing, which some
                # bakes leave different from xMin: move it by dx rather than reset it.
                advance, lsb = hmtx[name]
                hmtx[name] = (advance, lsb + dx)
    if "EBLC" in font and (dx_px or dy_px):
        shift_bitmaps(font, face.size, dx_px, dy_px, ascent_px, descent_px)
    ascent, descent = round(ascent_px * units), round(descent_px * units)
    hhea, os2 = font["hhea"], font["OS/2"]
    hhea.ascent, hhea.descent, hhea.lineGap = ascent, -descent, 0
    os2.sTypoAscender, os2.sTypoDescender, os2.sTypoLineGap = ascent, -descent, 0
    os2.usWinAscent, os2.usWinDescent = ascent, descent
    font.save(face.path)


def shift_bitmaps(font: TTFont, size: float, dx_px: float, dy_px: float, ascent_px: float, descent_px: float) -> None:
    """Move every embedded bitmap strike with the outlines (rounded to its own pixels)."""
    for strike in font["EBLC"].strikes:
        table = strike.bitmapSizeTable
        scale = table.ppemY / size
        dx, dy = round(dx_px * scale), round(dy_px * scale)
        table.hori.ascender, table.hori.descender = round(ascent_px * scale), -round(descent_px * scale)
        for sub in strike.indexSubTables:
            shared = getattr(sub, "metrics", None)
            if shared is not None:  # index formats 2 and 5 share one metrics record
                shared.horiBearingX += dx
                shared.horiBearingY += dy
    # Per-glyph metrics: big (horiBearing*) or small (Bearing*). The strikes in these faces
    # are all at the role size, so the pixel shift applies as is.
    for strike_data in font["EBDT"].strikeData:
        for glyph in strike_data.values():
            metrics = getattr(glyph, "metrics", None)
            if metrics is None:
                continue
            if hasattr(metrics, "horiBearingY"):
                metrics.horiBearingX += round(dx_px)
                metrics.horiBearingY += round(dy_px)
            else:
                metrics.BearingX += round(dx_px)
                metrics.BearingY += round(dy_px)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", action="append")
    parser.add_argument("--kind", choices=("web", "game"), action="append")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    faces = load_faces(args.target, tuple(args.kind or ("web", "game")))
    for face in faces:
        if face.role == "k64f" or face.path.suffix == ".fnt":
            continue
        ref = reference(faces, face.target, face.kind)
        dx = dy = 0
        if face.role in ("j", "ck") and face.boxes:
            # Snap to whole pixels first (some game bakes sit a fraction off), then move whole rows.
            snap = 0.0 if face.bitmaps else -grid_offset(face)
            snap = 0.0 if abs(snap) < 0.05 else snap  # unit rounding, not a real offset
            for box in face.boxes.values():
                box.y0, box.y1 = box.y0 + snap, box.y1 + snap
            dy = vertical_shift_rows(face, ref.cap, ref.ascent, ref.descent) * face.row_px + snap
            dx = horizontal_shift_px(face)
        metrics_ok = abs(face.ascent - ref.ascent) < 0.01 and abs(face.descent - ref.descent) < 0.01
        if not dx and abs(dy) < 0.005 and metrics_ok:
            continue
        print(
            f"{face.target:8} {face.kind:4} {face.role:6} dx {dx:+d}px dy {dy:+.2f}px "
            f"line box {face.ascent:g}/{face.descent:g} -> {ref.ascent:g}/{ref.descent:g}px  ({face.path.name})",
            flush=True,
        )
        if not args.dry_run:
            apply(face, ref.ascent, ref.descent, dx, dy)
    return 0


if __name__ == "__main__":
    sys.exit(main())
