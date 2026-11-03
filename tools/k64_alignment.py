"""Cross-script alignment rules for the k64-fonts monitor targets.

K64F is the reference face of every target. Its baseline, cap height and
x-height (measured from H and x) and its line box (ascent/descent) define where
the other roles must sit, so a fallback chain mixes scripts without manual,
per-target offsets:

- metrics: every role exposes the K64F line box (ascent/descent) at its role size,
  so a fallback glyph never changes the line height.
- cjk (J, CK): ideographs and kana are centred on the middle of the cap height,
  and their ink is centred in the advance. The whole cell moves, so punctuation
  keeps its designed position inside the cell.
- thai: low consonants (ก) reach x-height..cap height, tall ones (ป) cap height.
- arabic: alef (ا) reaches cap height.
- every reference glyph stays inside the line box.

Sizes come from k64-locale.json: targets.<t>.fontSizePx, optionally overridden
per role by roleFontSizePx. Web faces are measured at that CSS size; game faces
at the game size (gameFontSizePx, else fontSizePx). Vertical rules are judged in
rows: a tall-dot (y2x) web face draws one source row as 2px.
"""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "k64-locale.json"

CJK_VERTICAL = "日中国漢字あいアカ한국"
CJK_HORIZONTAL = "国漢字あアカ한"  # wide glyphs only: narrow ones (日) say nothing about the cell
THAI_LOW, THAI_TALL = "ก", "ป"
ARABIC_ALEF = "ا"
# A row is 2px on tall-dot web faces (y2x), 1px everywhere else.
CJK_TOLERANCE_ROWS = 0.5
CJK_TOLERANCE_PX = 1.0
HEIGHT_TOLERANCE_ROWS = 1.0
METRIC_TOLERANCE_PX = 0.5


@dataclass
class Box:
    x0: float
    y0: float
    x1: float
    y1: float
    advance: float


@dataclass
class Face:
    target: str
    kind: str  # web | game
    role: str
    path: Path
    size: float  # px the face is used at
    row_px: float
    ascent: float = 0.0  # px above the baseline
    descent: float = 0.0  # px below (positive)
    boxes: dict[str, Box] = field(default_factory=dict)


def manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def role_size(target: dict, role: str, kind: str) -> float:
    if kind == "game":
        return float(target.get("roleGameFontSizePx", {}).get(role, target.get("gameFontSizePx", target["fontSizePx"])))
    return float(target.get("roleFontSizePx", {}).get(role, target["fontSizePx"]))


def row_px(target: dict, kind: str) -> float:
    return 2.0 if kind == "web" and target.get("display") == "tall-dot" else 1.0


def _measure_ttf(face: Face, chars: str) -> None:
    font = TTFont(face.path)
    scale = face.size / font["head"].unitsPerEm
    face.ascent = font["hhea"].ascent * scale
    face.descent = -font["hhea"].descent * scale
    glyphs = font.getGlyphSet()
    cmap = font.getBestCmap()
    for char in chars:
        name = cmap.get(ord(char))
        if name is None:
            continue
        pen = BoundsPen(glyphs)
        glyphs[name].draw(pen)
        if pen.bounds is None:
            continue
        x0, y0, x1, y1 = (value * scale for value in pen.bounds)
        face.boxes[char] = Box(x0, y0, x1, y1, font["hmtx"][name][0] * scale)


def _measure_fnt(face: Face, chars: str) -> None:
    """BMFont: pixel rows above the baseline from the page image."""
    from PIL import Image

    text = face.path.read_text(encoding="utf-8")
    common = re.search(r"lineHeight=(\d+) base=(\d+)", text)
    line_height, base = int(common.group(1)), int(common.group(2))
    face.ascent, face.descent = float(base), float(line_height - base)
    page = Image.open(face.path.with_name(re.search(r'file="([^"]+)"', text).group(1))).convert("RGBA")
    for char in chars:
        match = re.search(
            rf"char id={ord(char)} x=(\d+) y=(\d+) width=(\d+) height=(\d+) xoffset=(-?\d+) yoffset=(-?\d+) xadvance=(\d+)", text
        )
        if not match:
            continue
        x, y, width, height, x_offset, y_offset, advance = map(int, match.groups())
        ink = [
            (i, j)
            for i in range(width)
            for j in range(height)
            if page.getpixel((x + i, y + j))[3] > 0 and page.getpixel((x + i, y + j))[:3] != (0, 0, 0)
        ]
        if not ink:
            continue
        xs = [i + x_offset for i, _ in ink]
        tops = [base - (j + y_offset) for _, j in ink]  # pixel row j spans (base-j-1, base-j)
        face.boxes[char] = Box(min(xs), min(tops) - 1, max(xs) + 1, max(tops), advance)


REFERENCE_CHARS = {
    "k64f": "Hx",
    "j": CJK_VERTICAL,
    "ck": CJK_VERTICAL,
    "thai": THAI_LOW + THAI_TALL,
    "arabic": ARABIC_ALEF,
}


def load_faces(targets: list[str] | None = None, kinds: tuple[str, ...] = ("web", "game")) -> list[Face]:
    data = manifest()
    faces = []
    for name, target in data["targets"].items():
        if targets and name not in targets:
            continue
        for kind in kinds:
            for role, relative in target.get(kind, {}).items():
                face = Face(name, kind, role, ROOT / relative, role_size(target, role, kind), row_px(target, kind))
                (_measure_fnt if relative.endswith(".fnt") else _measure_ttf)(face, REFERENCE_CHARS.get(role, ""))
                faces.append(face)
    return faces


@dataclass
class Reference:
    cap: float
    x_height: float
    ascent: float
    descent: float


def reference(faces: list[Face], target: str, kind: str) -> Reference:
    k64f = next(face for face in faces if face.target == target and face.kind == kind and face.role == "k64f")
    return Reference(k64f.boxes["H"].y1, k64f.boxes["x"].y1, k64f.ascent, k64f.descent)


def cjk_center(face: Face) -> float:
    return statistics.median((box.y0 + box.y1) / 2 for char, box in face.boxes.items() if char in CJK_VERTICAL)


def cjk_imbalance(face: Face) -> float:
    """Right side bearing minus left side bearing / 2: how far the ink must move right to be centred."""
    return statistics.median(
        ((box.advance - box.x1) - box.x0) / 2 for char, box in face.boxes.items() if char in CJK_HORIZONTAL
    )


@dataclass
class Finding:
    face: Face
    rule: str
    message: str


def check(faces: list[Face]) -> list[Finding]:
    findings = []
    for face in faces:
        if face.role == "k64f":
            continue
        ref = reference(faces, face.target, face.kind)
        rows = face.row_px

        def fail(rule: str, message: str) -> None:
            findings.append(Finding(face, rule, message))

        if abs(face.ascent - ref.ascent) > METRIC_TOLERANCE_PX or abs(face.descent - ref.descent) > METRIC_TOLERANCE_PX:
            fail("metrics", f"line box {face.ascent:g}/{face.descent:g}px, K64F {ref.ascent:g}/{ref.descent:g}px")
        for char, box in face.boxes.items():
            if box.y1 > ref.ascent + 0.01 or -box.y0 > ref.descent + 0.01:
                fail("inside", f"{char} ink {box.y0:g}..{box.y1:g}px leaves the K64F line box")
        if face.role in ("j", "ck") and face.boxes:
            offset = (cjk_center(face) - ref.cap / 2) / rows
            if abs(offset) > CJK_TOLERANCE_ROWS:
                fail("cjk-vertical", f"ideograph centre {offset:+.1f} rows from the cap-height centre")
            imbalance = cjk_imbalance(face)
            if abs(imbalance) > CJK_TOLERANCE_PX:
                fail("cjk-horizontal", f"ink sits {imbalance:.1f}px left of the cell centre")
        if face.role == "thai" and THAI_LOW in face.boxes and THAI_TALL in face.boxes:
            low, tall = face.boxes[THAI_LOW].y1 / rows, face.boxes[THAI_TALL].y1 / rows
            x_rows, cap_rows = ref.x_height / rows, ref.cap / rows
            if not (x_rows - HEIGHT_TOLERANCE_ROWS <= low <= cap_rows + HEIGHT_TOLERANCE_ROWS):
                fail("thai-height", f"ก top {low:g} rows, K64F x-height {x_rows:g} / cap {cap_rows:g}")
            if abs(tall - cap_rows) > HEIGHT_TOLERANCE_ROWS:
                fail("thai-height", f"ป top {tall:g} rows, K64F cap {cap_rows:g}")
        if face.role == "arabic" and ARABIC_ALEF in face.boxes:
            alef, cap_rows = face.boxes[ARABIC_ALEF].y1 / rows, ref.cap / rows
            if abs(alef - cap_rows) > HEIGHT_TOLERANCE_ROWS:
                fail("arabic-height", f"ا top {alef:g} rows, K64F cap {cap_rows:g}")
    return findings
