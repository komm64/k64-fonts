#!/usr/bin/env python3
"""
stretch_ttf_x2w.py — produce a horizontally-stretched (×2 width) variant
of a TTF, scaling glyph contours, advance widths, lsb, AND GPOS anchor
coordinates so HarfBuzz mark-to-base positioning still lands on target.

Why
---
Reecho's internal viewport is 640×240, displayed 4:3 inscribed → each
internal pixel is 1 wide × 2 tall on screen. To make font glyphs look
visually square, we either render glyphs 2x wider (k64F / ark-pixel-* do
this in gen_font.py's x2w mode) or 0.5x in height. The latter halves
visual size compared to other fonts, which doesn't match if you want
matching line heights.

Godot's FontVariation.variation_transform scales glyph SHAPES only — not
advance widths or GPOS anchors — so a runtime x=2 transform leaves
spacing too tight (overlap). The clean path is to bake x=2 into the TTF
itself: shape, advance, lsb, AND GPOS anchor x coords all scale together,
keeping mark-to-base positioning correct.

This script handles vector TTFs (Noto-style). It does NOT handle TTC,
CFF (PostScript outlines), or color tables — designed for Noto Sans Thai
which is glyf-based.

Usage:
    python tools/stretch_ttf_x2w.py game/assets/fonts/NotoSansThai-Regular.ttf

Output: writes <input_stem>_x2w.ttf in the same directory.

Dependencies: fontTools.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont


SCALE_X = 2


def scale_glyf(font: TTFont, scale_x: int) -> None:
    """Scale x coordinates in every glyph's contours and component offsets."""
    glyf = font["glyf"]
    for gname in glyf.keys():
        glyph = glyf[gname]
        if glyph.numberOfContours == 0:
            continue
        if glyph.numberOfContours > 0:  # simple glyph
            if hasattr(glyph, "coordinates"):
                glyph.coordinates = type(glyph.coordinates)(
                    [(x * scale_x, y) for (x, y) in glyph.coordinates]
                )
                glyph.recalcBounds(glyf)
        else:  # composite glyph: numberOfContours == -1
            for component in glyph.components:
                if hasattr(component, "x"):
                    component.x *= scale_x
            # Composite bbox is recalculated from components by recalcBounds
            glyph.recalcBounds(glyf)


def scale_hmtx(font: TTFont, scale_x: int) -> None:
    """Scale advance widths and lsb in horizontal metrics."""
    hmtx = font["hmtx"]
    for gname, (adv, lsb) in list(hmtx.metrics.items()):
        hmtx.metrics[gname] = (adv * scale_x, lsb * scale_x)
    # head table xMin/xMax also reflect the bbox after glyf changes — done by
    # individual glyph.recalcBounds + a separate head update could be needed;
    # for our purposes Godot doesn't read these for layout.


def scale_gpos_anchors(font: TTFont, scale_x: int) -> None:
    """Walk the GPOS table and scale every anchor's x coordinate.

    Mark-to-base / mark-to-mark positioning lookups attach marks to bases
    via Anchor records (XCoordinate, YCoordinate). Pair positioning also
    uses ValueRecords with XAdvance / XPlacement that need x-scaling.
    Cursive attachment uses Anchors too.
    """
    if "GPOS" not in font:
        return
    gpos = font["GPOS"].table

    def scale_anchor(anchor):
        if anchor is None:
            return
        if hasattr(anchor, "XCoordinate") and anchor.XCoordinate is not None:
            anchor.XCoordinate *= scale_x

    def scale_value_record(vr):
        if vr is None:
            return
        # Some attrs may be missing depending on ValueFormat; check before scaling.
        for attr in ("XPlacement", "XAdvance"):
            if hasattr(vr, attr):
                v = getattr(vr, attr)
                if v is not None:
                    setattr(vr, attr, v * scale_x)

    # fontTools class names: "MarkBasePos", "MarkMarkPos", "PairPos",
    # "SinglePos", etc — NOT the Format1/Format2 suffix that lives in the
    # sub.Format attribute. Earlier code keyed on "MarkBasePosFormat1" which
    # never matched anything, leaving GPOS anchors un-scaled — that's why the
    # x2w version had marks shifted left of their base consonants.
    def visit_subtable(sub):
        tname = sub.__class__.__name__
        if tname == "ExtensionPos":
            visit_subtable(sub.ExtSubTable)
            return
        if tname == "MarkBasePos":
            for mark in sub.MarkArray.MarkRecord:
                scale_anchor(mark.MarkAnchor)
            for base in sub.BaseArray.BaseRecord:
                for anchor in base.BaseAnchor:
                    scale_anchor(anchor)
        elif tname == "MarkMarkPos":
            for mark in sub.Mark1Array.MarkRecord:
                scale_anchor(mark.MarkAnchor)
            for mark2 in sub.Mark2Array.Mark2Record:
                for anchor in mark2.Mark2Anchor:
                    scale_anchor(anchor)
        elif tname == "MarkLigPos":
            for mark in sub.MarkArray.MarkRecord:
                scale_anchor(mark.MarkAnchor)
            for lig in sub.LigatureArray.LigatureAttach:
                for component in lig.ComponentRecord:
                    for anchor in component.LigatureAnchor:
                        scale_anchor(anchor)
        elif tname == "CursivePos":
            for entry_exit in sub.EntryExitRecord:
                scale_anchor(entry_exit.EntryAnchor)
                scale_anchor(entry_exit.ExitAnchor)
        elif tname == "PairPos":
            if sub.Format == 1:
                for pair_set in sub.PairSet:
                    for pair_value in pair_set.PairValueRecord:
                        scale_value_record(pair_value.Value1)
                        scale_value_record(pair_value.Value2)
            elif sub.Format == 2:
                for class1 in sub.Class1Record:
                    for class2 in class1.Class2Record:
                        scale_value_record(class2.Value1)
                        scale_value_record(class2.Value2)
        elif tname == "SinglePos":
            if sub.Format == 1:
                scale_value_record(sub.Value)
            elif sub.Format == 2:
                for vr in sub.Value:
                    scale_value_record(vr)
        # ChainContextPos (LookupType 8) chains to other lookups; no anchors
        # of its own, so nothing to scale here.

    for lookup in gpos.LookupList.Lookup:
        for sub in lookup.SubTable:
            visit_subtable(sub)


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: stretch_ttf_x2w.py <input.ttf>", file=sys.stderr)
        return 1
    in_path = Path(sys.argv[1])
    if not in_path.exists():
        print(f"missing: {in_path}", file=sys.stderr)
        return 1
    out_path = in_path.with_name(in_path.stem + "_x2w.ttf")

    font = TTFont(str(in_path))

    # Variable fonts: instantiate at default location to flatten gvar + STAT
    # before we scale glyphs. (Without instantiation, gvar deltas would
    # remain at unscaled coordinates and re-introduce squish at runtime.)
    if "fvar" in font:
        print("[stretch] variable font detected; instantiating at default master...")
        font = instantiateVariableFont(font, {})

    print(f"[stretch] scaling glyf coordinates by {SCALE_X}x in x...")
    scale_glyf(font, SCALE_X)

    print(f"[stretch] scaling hmtx (advance, lsb) by {SCALE_X}x...")
    scale_hmtx(font, SCALE_X)

    print(f"[stretch] scaling GPOS anchors and value records by {SCALE_X}x...")
    scale_gpos_anchors(font, SCALE_X)

    # head bbox reflects scaled glyf contents — recalc max advance.
    if "hhea" in font:
        font["hhea"].advanceWidthMax *= SCALE_X

    font.save(str(out_path))
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
