#!/usr/bin/env python3
"""Render native-resolution K64F language specimens for social review.

The native images are drawn directly from the BMFont atlases selected by
``k64-locale.json``.  This avoids FreeType hinting or antialiasing differences
and makes every output pixel match the game-facing bitmap font.

Outputs:
    docs/social-specimens/k64f-320x240.png
    docs/social-specimens/k64f-320x240-social-4x.png
    docs/social-specimens/k64f-640x480.png
    docs/social-specimens/k64f-640x480-social-2x.png
"""
from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from render_pangrams import PANGRAMS


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "social-specimens"
SPECIMEN_TAG = "after-descender-fix"

BACKGROUND = (7, 16, 29)
TEXT = (239, 243, 232)
LABEL = (84, 214, 192)
HEADING = (255, 207, 92)
RULE = (35, 67, 82)


# The 320x240 target has fifteen native 16-dot rows.  These fourteen compact
# lines prioritize k64-locale order plus glyph diversity: Western/extended
# Latin, Vietnamese, monotonic Greek, Russian, and Ukrainian Cyrillic.
COMPACT_SAMPLES = [
    ("eo", "Ĉu vi ŝatas ĵaŭdojn aŭ vendrojn?"),
    ("en", "Quick fox jumps over the lazy dog."),
    ("ru", "Съешь ещё булок, выпей чаю."),
    ("es", "El murciélago hindú comía kiwi."),
    ("pt", "Luís põe chá e açúcar no café."),
    ("de", "Übung quält jeden größeren Zwerg."),
    ("fr", "Le vieux château brille à Noël."),
    ("pl", "Pchnąć w tę łódź jeża i ośm fig."),
    ("tr", "Yağız şoföre çabucak güvendi."),
    ("uk", "Пʼять філософів біля ґанку."),
    ("cs", "Žluťoučký kůň úpěl ďábelské ódy."),
    ("hu", "Árvíztűrő tükörfúrógép."),
    ("vi", "Tôi yêu tiếng nước tôi từ nhỏ."),
    ("el", "Ξεσκεπάζω ψυχοφθόρα βδελυγμία."),
]


@dataclass(frozen=True)
class Glyph:
    x: int
    y: int
    width: int
    height: int
    xoffset: int
    yoffset: int
    xadvance: int


def parse_fields(line: str) -> tuple[str, dict[str, str]]:
    parts = shlex.split(line, posix=True)
    kind = parts[0]
    fields = {}
    for part in parts[1:]:
        if "=" in part:
            key, value = part.split("=", 1)
            fields[key] = value
    return kind, fields


class BitmapFont:
    def __init__(self, descriptor: Path) -> None:
        self.descriptor = descriptor
        self.glyphs: dict[int, Glyph] = {}
        self.kernings: dict[tuple[int, int], int] = {}
        self.line_height = 0
        page_name = None

        for line in descriptor.read_text(encoding="utf-8").splitlines():
            kind, fields = parse_fields(line)
            if kind == "common":
                self.line_height = int(fields["lineHeight"])
            elif kind == "page" and fields.get("id") == "0":
                page_name = fields["file"]
            elif kind == "char":
                codepoint = int(fields["id"])
                self.glyphs[codepoint] = Glyph(
                    x=int(fields["x"]),
                    y=int(fields["y"]),
                    width=int(fields["width"]),
                    height=int(fields["height"]),
                    xoffset=int(fields["xoffset"]),
                    yoffset=int(fields["yoffset"]),
                    xadvance=int(fields["xadvance"]),
                )
            elif kind == "kerning":
                pair = (int(fields["first"]), int(fields["second"]))
                self.kernings[pair] = int(fields["amount"])

        if not page_name or not self.line_height:
            raise ValueError(f"Incomplete BMFont descriptor: {descriptor}")
        self.atlas = Image.open(descriptor.with_name(page_name)).convert("RGBA")

    def validate(self, text: str) -> None:
        missing = sorted({f"U+{ord(char):04X} {char!r}" for char in text if ord(char) not in self.glyphs})
        if missing:
            raise ValueError(f"{self.descriptor.name} lacks: {', '.join(missing)}")

    def measure(self, text: str) -> int:
        self.validate(text)
        width = 0
        previous = None
        for char in text:
            codepoint = ord(char)
            if previous is not None:
                width += self.kernings.get((previous, codepoint), 0)
            width += self.glyphs[codepoint].xadvance
            previous = codepoint
        return width

    def draw(self, image: Image.Image, text: str, x: int, y: int, color: tuple[int, int, int]) -> int:
        self.validate(text)
        pen_x = x
        previous = None
        for char in text:
            codepoint = ord(char)
            glyph = self.glyphs[codepoint]
            if previous is not None:
                pen_x += self.kernings.get((previous, codepoint), 0)
            if glyph.width and glyph.height:
                box = (glyph.x, glyph.y, glyph.x + glyph.width, glyph.y + glyph.height)
                mask = self.atlas.getchannel("A").crop(box)
                ink = Image.new("RGB", (glyph.width, glyph.height), color)
                image.paste(ink, (pen_x + glyph.xoffset, y + glyph.yoffset), mask)
            pen_x += glyph.xadvance
            previous = codepoint
        return pen_x


def assert_fits(font: BitmapFont, text: str, x: int, right: int) -> None:
    end = x + font.measure(text)
    if end > right:
        raise ValueError(f"Line exceeds target by {end - right}px: {text}")


def render_320() -> Image.Image:
    font = BitmapFont(ROOT / "game" / "320x240" / "k64-320-k64f-visual16-12px.fnt")
    if font.line_height != 16:
        raise ValueError(f"Unexpected 320x240 line height: {font.line_height}")

    image = Image.new("RGB", (320, 240), BACKGROUND)
    heading = "K64F / 320x240 / 14 LANGUAGES"
    assert_fits(font, heading, 8, 312)
    font.draw(image, heading, 8, 0, HEADING)

    for row, (code, text) in enumerate(COMPACT_SAMPLES, start=1):
        y = row * font.line_height
        label = code.upper()
        assert_fits(font, label, 8, 24)
        assert_fits(font, text, 32, 312)
        font.draw(image, label, 8, y, LABEL)
        font.draw(image, text, 32, y, TEXT)
    return image


def render_640() -> Image.Image:
    font = BitmapFont(ROOT / "game" / "640x480" / "k64-640x480-k64f-tall-16px.fnt")
    if font.line_height != 16:
        raise ValueError(f"Unexpected 640x480 line height: {font.line_height}")

    image = Image.new("RGB", (640, 480), BACKGROUND)
    heading = "K64F / 640x480 / ALL 23 K64F LANGUAGES"
    assert_fits(font, heading, 8, 632)
    font.draw(image, heading, 8, 8, HEADING)
    image.paste(RULE, (8, 31, 632, 32))

    for row, (code, text) in enumerate(PANGRAMS):
        y = 40 + row * font.line_height
        label = code.upper()
        assert_fits(font, label, 8, 24)
        assert_fits(font, text, 40, 632)
        font.draw(image, label, 8, y, LABEL)
        font.draw(image, text, 40, y, TEXT)

    footer = "LATIN + GREEK + CYRILLIC / NATIVE BITMAP GLYPHS"
    assert_fits(font, footer, 8, 632)
    font.draw(image, footer, 8, 448, HEADING)
    return image


def save_native_and_social(image: Image.Image, stem: str, scale: int) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    native = OUT_DIR / f"{stem}.png"
    social = OUT_DIR / f"{stem}-social-{scale}x.png"
    image.save(native)
    image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST).save(social)
    print(f"wrote {native.relative_to(ROOT)} ({image.width}x{image.height})")
    print(f"wrote {social.relative_to(ROOT)} ({image.width * scale}x{image.height * scale})")


def main() -> None:
    save_native_and_social(render_320(), f"k64f-320x240-{SPECIMEN_TAG}", 4)
    save_native_and_social(render_640(), f"k64f-640x480-{SPECIMEN_TAG}", 2)


if __name__ == "__main__":
    main()
