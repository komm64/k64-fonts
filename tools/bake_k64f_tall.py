#!/usr/bin/env python3
"""Bake the full-height K64F for the 640x480 target (PC-98 style 8x16 ANK cells).

The 16px K64F draws capitals 9 rows tall in a 16-row cell, small next to the
16x16 Shinonome/Unifont cells of the 640x480 set. This bake stretches it to
PC-98 proportions on the same cell and line box as those faces (ascent 14 /
descent 2): capitals 12 rows, x-height 9, descenders 2.

Each glyph is resampled per vertical zone (accents/ascender, cap part above
x-height, x-height part, descender; capitals, digits and symbols stretch their
whole cap height as one zone). Growing repeats the rows that are only vertical
stems (not the edge of a horizontal stroke), spreading repeats; shrinking
OR-merges the most similar adjacent pair, as Reecho's or12 bake does. A few
glyphs are hand-tuned in FIXES.

Outputs (all 8x16 cells, baseline under row 13):
    game/640x480/k64-640x480-k64f-tall-16px.fnt + _0.png   BMFont for Godot
    game/640x480/k64-640x480-k64f-tall-16px.ttf            pixel-outline TTF
    web/640x480/k64-640x480-k64f-tall-16px.woff2           same, for the web
    docs/640x480/k64f-tall-preview.png                     before/after preview
"""
from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "game" / "640x480" / "k64-640x480-k64f-16px.fnt"
STEM = "k64-640x480-k64f-tall-16px"
GAME = ROOT / "game" / "640x480"
WEB = ROOT / "web" / "640x480"
DOCS = ROOT / "docs" / "640x480"

ROWS = 16
SOURCE_BASE = 12  # first row below the baseline in the source cells
BASE = 14  # same: ascent 14 / descent 2, like the 640x480 CJK cells
UNITS_PER_PX = 100

# (source rows, target rows), top to bottom.
LOWERCASE_ZONES = [(range(0, 3), 2), (range(3, 5), 3), (range(5, 12), 9), (range(12, 16), 2)]
CAPITAL_ZONES = [(range(0, 3), 2), (range(3, 12), 12), (range(12, 16), 2)]

FIXES = {
    # K: stretch the straight stem/arm rows, not the knot where the arms meet.
    "K": "........ ........ .#....#. .##..##. .##..##. .##.##.. .####... .###.... .###.... .####... .##.##.. .##..##. .##..##. .#....## ........ ........",
    # g, y: as in PC-98 ANK fonts, the bowl/arms end 1px above the baseline so the
    # descender keeps its full 3-row hook (stem, left curl, closing bottom); the top
    # stays at x-height, so the bowl/arms are 1px shorter than the other lowercase.
    "g": "........ ........ ........ ........ ......#. ...####. ..#..##. .##..##. .##..##. .##..##. .##..##. .##.###. ..##.##. .....##. .##..#.. ..###...",
    "y": "........ ........ ........ ........ ..#...#. .##..##. .##..##. .##..##. .##..##. .##..##. .##..##. .##.###. ..##.##. .....##. .##..#.. ..###...",
}

Cell = list[list[int]]


def load_bmfont(path: Path) -> dict[int, Cell]:
    text = path.read_text(encoding="utf-8")
    page = Image.open(path.with_name(re.search(r'file="([^"]+)"', text).group(1))).convert("RGBA")
    cells = {}
    pattern = r"char id=(\d+) x=(\d+) y=(\d+) width=(\d+) height=(\d+) xoffset=(-?\d+) yoffset=(-?\d+) xadvance=(\d+)"
    for match in re.finditer(pattern, text):
        code, x, y, width, height, x_offset, y_offset, advance = map(int, match.groups())
        cell = [[0] * advance for _ in range(ROWS)]
        for j in range(height):
            for i in range(width):
                pixel = page.getpixel((x + i, y + j))
                row, col = y_offset + j, x_offset + i
                if pixel[3] and pixel[:3] != (0, 0, 0) and 0 <= row < ROWS and 0 <= col < advance:
                    cell[row][col] = 1
        cells[code] = cell
    return cells


def _diff(a: list[int], b: list[int]) -> int:
    return sum(x != y for x, y in zip(a, b))


def resample(rows: Cell, count: int) -> Cell:
    """Grow by repeating stem-only rows; shrink by OR-merging the most similar adjacent pair."""
    rows = [list(row) for row in rows]
    repeats = [0] * len(rows)
    while len(rows) < count:
        def cost(i: int):
            if not any(rows[i]):
                return (-1, repeats[i], 0)
            # Pixels on the edge of a horizontal stroke (not continued both above and below).
            edges = sum(
                1
                for c, on in enumerate(rows[i])
                if on and not (0 < i < len(rows) - 1 and rows[i - 1][c] and rows[i + 1][c])
            )
            boundary = 0 if 0 < i < len(rows) - 1 else 2
            return (edges + boundary + repeats[i] * 2, repeats[i], abs(i - (len(rows) - 1) / 2))

        i = min(range(len(rows)), key=cost)
        rows.insert(i, list(rows[i]))
        repeats[i] += 1
        repeats.insert(i, repeats[i])
    while len(rows) > count:
        blank = [i for i, row in enumerate(rows) if not any(row)]
        if blank:
            rows.pop(blank[-1])
            repeats.pop(blank[-1])
            continue
        i = min(range(len(rows) - 1), key=lambda i: _diff(rows[i], rows[i + 1]))
        rows[i] = [a | b for a, b in zip(rows[i], rows[i + 1])]
        rows.pop(i + 1)
        repeats.pop(i + 1)
    return rows


def stretch(cell: Cell, char: str) -> Cell:
    zones = LOWERCASE_ZONES if unicodedata.category(char) == "Ll" else CAPITAL_ZONES
    out: Cell = []
    for source_rows, count in zones:
        out += resample([cell[r] for r in source_rows], count)
    return out


def parse(rows: str) -> Cell:
    return [[1 if c == "#" else 0 for c in row] for row in rows.split()]


def bake_cells() -> dict[int, Cell]:
    cells = {code: stretch(cell, chr(code)) for code, cell in load_bmfont(SOURCE).items()}
    cells.update({ord(char): parse(rows) for char, rows in FIXES.items()})
    return cells


def write_bmfont(cells: dict[int, Cell]) -> Path:
    per_row = 64
    codes = sorted(cells)
    page = Image.new("RGBA", (per_row * 8, ROWS * ((len(codes) + per_row - 1) // per_row)), (0, 0, 0, 0))
    lines = [
        'info face="komm64Fantasy Tall" size=16 bold=0 italic=0 charset="" unicode=1 stretchH=100 smooth=0 aa=0 padding=0,0,0,0 spacing=0,0',
        f"common lineHeight={ROWS} base={BASE} scaleW={page.width} scaleH={page.height} pages=1 packed=0",
        f'page id=0 file="{STEM}_0.png"',
        f"chars count={len(codes)}",
    ]
    for index, code in enumerate(codes):
        cell = cells[code]
        advance = len(cell[0])
        x, y = (index % per_row) * 8, (index // per_row) * ROWS
        for r, row in enumerate(cell):
            for c, on in enumerate(row):
                if on:
                    page.putpixel((x + c, y + r), (255, 255, 255, 255))
        lines.append(
            f"char id={code} x={x} y={y} width={advance} height={ROWS} xoffset=0 yoffset=0 xadvance={advance} page=0 chnl=15"
        )
    page.save(GAME / f"{STEM}_0.png")
    fnt = GAME / f"{STEM}.fnt"
    fnt.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return fnt


def write_outline_fonts(cells: dict[int, Cell]) -> tuple[Path, Path]:
    """Pixel-square outlines (one rectangle per horizontal run) on a 1600-unit em, 14/2 line box."""
    names = [".notdef"] + [f"uni{code:04X}" for code in sorted(cells)]
    glyphs, metrics = {}, {}
    empty = TTGlyphPen(None)
    glyphs[".notdef"], metrics[".notdef"] = empty.glyph(), (8 * UNITS_PER_PX, 0)
    for code in sorted(cells):
        cell, pen = cells[code], TTGlyphPen(None)
        for r, row in enumerate(cell):
            top = (BASE - r) * UNITS_PER_PX
            c = 0
            while c < len(row):
                if not row[c]:
                    c += 1
                    continue
                start = c
                while c < len(row) and row[c]:
                    c += 1
                x0, x1 = start * UNITS_PER_PX, c * UNITS_PER_PX
                pen.moveTo((x0, top - UNITS_PER_PX))
                pen.lineTo((x0, top))
                pen.lineTo((x1, top))
                pen.lineTo((x1, top - UNITS_PER_PX))
                pen.closePath()
        name = f"uni{code:04X}"
        glyphs[name] = pen.glyph()
        metrics[name] = (len(cell[0]) * UNITS_PER_PX, 0)

    builder = FontBuilder(ROWS * UNITS_PER_PX, isTTF=True)
    builder.setupGlyphOrder(names)
    builder.setupCharacterMap({code: f"uni{code:04X}" for code in cells})
    builder.setupGlyf(glyphs)
    for name, glyph in glyphs.items():
        glyph.recalcBounds(builder.font["glyf"])
        metrics[name] = (metrics[name][0], getattr(glyph, "xMin", 0))
    builder.setupHorizontalMetrics(metrics)
    ascent, descent = BASE * UNITS_PER_PX, (ROWS - BASE) * UNITS_PER_PX
    builder.setupHorizontalHeader(ascent=ascent, descent=-descent)
    builder.setupNameTable({"familyName": "K64 640x480 K64F Tall 16px", "styleName": "Regular", "psName": "K64640x480K64FTall16px-Regular"})
    builder.setupOS2(
        sTypoAscender=ascent, sTypoDescender=-descent, sTypoLineGap=0, usWinAscent=ascent, usWinDescent=descent
    )
    builder.setupPost()
    ttf = GAME / f"{STEM}.ttf"
    builder.save(ttf)
    builder.font.flavor = "woff2"
    woff2 = WEB / f"{STEM}.woff2"
    builder.font.save(woff2)
    return ttf, woff2


def write_preview(before: dict[int, Cell], after: dict[int, Cell]) -> Path:
    text = [
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ 0123456789",
        "abcdefghijklmnopqrstuvwxyz !?&%#@()[]",
        "The quick brown fox jumps over 13 lazy dogs.",
        "Àéîõü Çñ Ærøß gjpqy Il1 O0 rn/m KkGgYy",
    ]
    scale, gap = 3, 4
    width = max(len(t) for t in text) * 8 * scale + 32
    height = 2 * (len(text) * (ROWS * scale + gap)) + 48
    image = Image.new("RGB", (width, height), (11, 15, 20))
    draw = ImageDraw.Draw(image)
    y = 16
    for cells, shift in ((before, BASE - SOURCE_BASE), (after, 0)):
        for line in text:
            draw.rectangle([16, y, width - 16, y + ROWS * scale - 1], outline=(32, 43, 54))
            x = 16
            for char in line:
                cell = cells.get(ord(char))
                if cell is None:
                    x += 8 * scale
                    continue
                for r, row in enumerate(cell):
                    for c, on in enumerate(row):
                        if on and 0 <= r + shift < ROWS:
                            draw.rectangle(
                                [x + c * scale, y + (r + shift) * scale, x + (c + 1) * scale - 1, y + (r + shift + 1) * scale - 1],
                                fill=(232, 237, 242),
                            )
                x += len(cell[0]) * scale
            y += ROWS * scale + gap
        y += 16
    out = DOCS / "k64f-tall-preview.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)
    return out


def main() -> int:
    cells = bake_cells()
    outputs = [write_bmfont(cells), *write_outline_fonts(cells), write_preview(load_bmfont(SOURCE), cells)]
    print("wrote:")
    for path in outputs:
        print(f"  {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
