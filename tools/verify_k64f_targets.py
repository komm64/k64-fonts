#!/usr/bin/env python3
"""Verify every K64F glyph for all three game and web targets."""

from __future__ import annotations

import shlex
import tempfile
from pathlib import Path

import numpy as np
from fontTools.ttLib import woff2
from PIL import Image, ImageDraw, ImageFont, features


ROOT = Path(__file__).resolve().parents[1]
BASE_FNT = ROOT / "game/640x480/k64-640x480-k64f-16px.fnt"

GAME_TARGETS = (
    (
        "320x240 game",
        ROOT / "game/320x240/k64-320-k64f-visual16-12px.fnt",
        1,
    ),
    (
        "640x480 game",
        BASE_FNT,
        1,
    ),
    (
        "640x240 game",
        ROOT / "game/640x240/k64-640x240-k64f-16px-x2w.fnt",
        2,
    ),
)

WEB_TARGETS = (
    (
        "320x240 web",
        ROOT / "web/320x240/k64-320-k64f-visual16-12px.woff2",
        12,
        8,
        16,
        12,
        (12, 4),
        1,
    ),
    (
        "640x480 web",
        ROOT / "web/k64-fantasy.woff2",
        16,
        8,
        16,
        12,
        (12, 4),
        1,
    ),
    (
        "640x240 web",
        ROOT / "web/k64-fantasy-2x.woff2",
        32,
        16,
        32,
        24,
        (24, 8),
        2,
    ),
)

WEB_SCAN_TARGETS = (
    (
        "640x240 web scan erase-upper",
        ROOT / "web/k64-fantasy-2x-scan-erase-upper.woff2",
        1,
    ),
    (
        "640x240 web scan erase-lower",
        ROOT / "web/k64-fantasy-2x-scan-erase-lower.woff2",
        0,
    ),
)


def fields(line: str) -> tuple[str, dict[str, str]]:
    parts = shlex.split(line, posix=True)
    return parts[0], dict(part.split("=", 1) for part in parts[1:] if "=" in part)


def read_bmfont(path: Path) -> tuple[dict[str, int], dict[int, np.ndarray]]:
    common: dict[str, int] = {}
    page_name = ""
    glyphs: dict[int, dict[str, int]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        kind, values = fields(line)
        if kind == "common":
            common = {key: int(values[key]) for key in ("lineHeight", "base")}
        elif kind == "page" and values.get("id") == "0":
            page_name = values["file"]
        elif kind == "char":
            glyphs[int(values["id"])] = {
                key: int(values[key])
                for key in ("x", "y", "width", "height", "xoffset", "yoffset", "xadvance")
            }

    if not common or not page_name or not glyphs:
        raise AssertionError(f"incomplete BMFont: {path}")
    atlas = np.asarray(Image.open(path.with_name(page_name)).convert("RGBA"))[:, :, 3] > 127
    cells: dict[int, np.ndarray] = {}
    for codepoint, glyph in glyphs.items():
        cell = np.zeros((common["lineHeight"], glyph["xadvance"]), dtype=bool)
        width, height = glyph["width"], glyph["height"]
        if width and height:
            source = atlas[
                glyph["y"] : glyph["y"] + height,
                glyph["x"] : glyph["x"] + width,
            ]
            y, x = glyph["yoffset"], glyph["xoffset"]
            cell[y : y + height, x : x + width] = source
        cells[codepoint] = cell
    return common, cells


def assert_cells(label: str, actual: dict[int, np.ndarray], expected: dict[int, np.ndarray]) -> None:
    if actual.keys() != expected.keys():
        raise AssertionError(f"{label}: codepoint set differs")
    different = [codepoint for codepoint in expected if not np.array_equal(actual[codepoint], expected[codepoint])]
    if different:
        examples = ", ".join(f"U+{codepoint:04X}" for codepoint in different[:8])
        raise AssertionError(f"{label}: {len(different)} glyphs differ ({examples})")


def render_web_font(
    path: Path,
    size: int,
    width: int,
    height: int,
    baseline: int,
    codepoints: set[int],
) -> tuple[tuple[int, int], dict[int, np.ndarray]]:
    with tempfile.TemporaryDirectory(prefix="verify-k64f-") as temp_dir:
        ttf_path = Path(temp_dir) / "font.ttf"
        woff2.decompress(str(path), str(ttf_path))
        font = ImageFont.truetype(str(ttf_path), size)
        rendered = {}
        for codepoint in codepoints:
            image = Image.new("L", (width, height))
            ImageDraw.Draw(image).text(
                (0, baseline), chr(codepoint), font=font, fill=255, anchor="ls"
            )
            rendered[codepoint] = np.asarray(image) > 127
        return font.getmetrics(), rendered


def main() -> None:
    common, base_cells = read_bmfont(BASE_FNT)
    if common != {"lineHeight": 16, "base": 12} or len(base_cells) != 606:
        raise AssertionError(f"unexpected canonical atlas: {common}, {len(base_cells)} glyphs")

    for label, path, x_scale in GAME_TARGETS:
        metrics, cells = read_bmfont(path)
        if metrics != common:
            raise AssertionError(f"{label}: expected metrics {common}, got {metrics}")
        expected = {
            codepoint: np.repeat(cell, x_scale, axis=1)
            for codepoint, cell in base_cells.items()
        }
        assert_cells(label, cells, expected)
        print(f"PASS {label}: 606 glyphs, lineHeight=16, base=12")

    for label, path, size, width, height, baseline, expected_metrics, scale in WEB_TARGETS:
        metrics, cells = render_web_font(
            path, size, width, height, baseline, set(base_cells)
        )
        if metrics != expected_metrics:
            raise AssertionError(f"{label}: expected metrics {expected_metrics}, got {metrics}")
        expected = {
            codepoint: np.repeat(np.repeat(cell, scale, axis=0), scale, axis=1)
            for codepoint, cell in base_cells.items()
        }
        assert_cells(label, cells, expected)
        print(f"PASS {label}: 606 glyphs, ascent/descent={metrics}")

    for label, path, kept_display_row in WEB_SCAN_TARGETS:
        metrics, cells = render_web_font(path, 32, 16, 32, 24, set(base_cells))
        if metrics != (24, 8):
            raise AssertionError(f"{label}: expected metrics (24, 8), got {metrics}")
        expected = {}
        for codepoint, cell in base_cells.items():
            scan_cell = np.zeros((32, 16), dtype=bool)
            scan_cell[kept_display_row::2] = np.repeat(cell, 2, axis=1)
            expected[codepoint] = scan_cell
        assert_cells(label, cells, expected)
        print(f"PASS {label}: 606 glyphs, ascent/descent={metrics}")

    print(f"Pillow FreeType {features.version('freetype2')}: all K64F targets match")


if __name__ == "__main__":
    main()
