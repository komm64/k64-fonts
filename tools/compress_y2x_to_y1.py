#!/usr/bin/env python3
"""Compress a y2x pixel-outline font into a Reecho game y1 font.

Web fonts in this repo bake each authored pixel as 1px wide x 2px tall at
font-size 32. Reecho renders into a 640x240 surface whose output pixels are
already vertically tall in the final display path, so game TTFs keep the same
X coordinates and advances but halve Y coordinates, vertical metrics, and
GPOS Y values.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fontTools.ttLib import TTFont

SCALE_Y = 0.5


def scale_y(value: int) -> int:
    return int(round(value * SCALE_Y))


def scale_glyf_y(font: TTFont) -> None:
    glyf = font["glyf"]
    for glyph_name in glyf.keys():
        glyph = glyf[glyph_name]
        if glyph.numberOfContours == 0:
            continue
        if glyph.numberOfContours > 0:
            if hasattr(glyph, "coordinates"):
                glyph.coordinates = type(glyph.coordinates)(
                    [(x, scale_y(y)) for (x, y) in glyph.coordinates]
                )
                glyph.recalcBounds(glyf)
            continue
        for component in glyph.components:
            if hasattr(component, "y"):
                component.y = scale_y(component.y)
        glyph.recalcBounds(glyf)


def scale_gpos_y(font: TTFont) -> None:
    if "GPOS" not in font:
        return
    gpos = font["GPOS"].table

    def scale_anchor(anchor) -> None:
        if anchor is None:
            return
        if hasattr(anchor, "YCoordinate") and anchor.YCoordinate is not None:
            anchor.YCoordinate = scale_y(anchor.YCoordinate)

    def scale_value_record(record) -> None:
        if record is None:
            return
        for attr in ("YPlacement", "YAdvance"):
            if hasattr(record, attr):
                value = getattr(record, attr)
                if value is not None:
                    setattr(record, attr, scale_y(value))

    def visit_subtable(subtable) -> None:
        name = subtable.__class__.__name__
        if name == "ExtensionPos":
            visit_subtable(subtable.ExtSubTable)
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
                for component in lig.ComponentRecord:
                    for anchor in component.LigatureAnchor:
                        scale_anchor(anchor)
        elif name == "CursivePos":
            for entry_exit in subtable.EntryExitRecord:
                scale_anchor(entry_exit.EntryAnchor)
                scale_anchor(entry_exit.ExitAnchor)
        elif name == "PairPos":
            if subtable.Format == 1:
                for pair_set in subtable.PairSet:
                    for pair_value in pair_set.PairValueRecord:
                        scale_value_record(pair_value.Value1)
                        scale_value_record(pair_value.Value2)
            elif subtable.Format == 2:
                for class1 in subtable.Class1Record:
                    for class2 in class1.Class2Record:
                        scale_value_record(class2.Value1)
                        scale_value_record(class2.Value2)
        elif name == "SinglePos":
            if subtable.Format == 1:
                scale_value_record(subtable.Value)
            elif subtable.Format == 2:
                for record in subtable.Value:
                    scale_value_record(record)

    if not gpos.LookupList:
        return
    for lookup in gpos.LookupList.Lookup:
        for subtable in lookup.SubTable:
            visit_subtable(subtable)


def scale_vertical_metrics(font: TTFont) -> None:
    font["head"].unitsPerEm = scale_y(font["head"].unitsPerEm)
    if "hhea" in font:
        hhea = font["hhea"]
        hhea.ascent = scale_y(hhea.ascent)
        hhea.descent = scale_y(hhea.descent)
        hhea.lineGap = scale_y(hhea.lineGap)
    if "OS/2" in font:
        os2 = font["OS/2"]
        for attr in (
            "sTypoAscender",
            "sTypoDescender",
            "sTypoLineGap",
            "usWinAscent",
            "usWinDescent",
            "ySubscriptYSize",
            "ySubscriptYOffset",
            "ySuperscriptYSize",
            "ySuperscriptYOffset",
            "yStrikeoutSize",
            "yStrikeoutPosition",
        ):
            if hasattr(os2, attr):
                setattr(os2, attr, scale_y(getattr(os2, attr)))
    if "post" in font:
        post = font["post"]
        post.underlinePosition = scale_y(post.underlinePosition)
        post.underlineThickness = scale_y(post.underlineThickness)


def update_head_bbox(font: TTFont) -> None:
    glyf = font["glyf"]
    x_mins: list[int] = []
    y_mins: list[int] = []
    x_maxs: list[int] = []
    y_maxs: list[int] = []
    for glyph_name in font.getGlyphOrder():
        glyph = glyf[glyph_name]
        if glyph.numberOfContours == 0:
            continue
        glyph.recalcBounds(glyf)
        x_mins.append(glyph.xMin)
        y_mins.append(glyph.yMin)
        x_maxs.append(glyph.xMax)
        y_maxs.append(glyph.yMax)
    if not x_mins:
        return
    head = font["head"]
    head.xMin = min(x_mins)
    head.yMin = min(y_mins)
    head.xMax = max(x_maxs)
    head.yMax = max(y_maxs)


def compress(source: Path, output: Path) -> None:
    font = TTFont(str(source), recalcBBoxes=True, recalcTimestamp=False)
    scale_glyf_y(font)
    scale_gpos_y(font)
    scale_vertical_metrics(font)
    update_head_bbox(font)
    output.parent.mkdir(parents=True, exist_ok=True)
    font.save(str(output))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Compress a y2x TTF into a Reecho game y1 TTF.")
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)

    if not args.source.exists():
        print(f"missing source: {args.source}", file=sys.stderr)
        return 1

    compress(args.source, args.output)
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
