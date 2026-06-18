#!/usr/bin/env python3
"""Bake the final 12px font set for the 320x240 monitor target.

The existing flat game/web outputs are for the 640x240 Reecho path.  This
script writes the 320x240-specific square-dot fonts under:

  game/320x240/*.ttf
  web/320x240/*.woff2
  docs/320x240/preview.png

Final choices:
  - Japanese: Shinonome Mincho 12px, embedded bitmap baseline fixed to 12/0
  - CJK fallback: Unifont 16px -> 12px drop-bridge repair
  - Thai: Noto Sans Thai Light, 12px base glyphs with 16px upper/lower marks;
          upper marks use collision-aware max-up 2px per mark glyph
  - Arabic: Noto Sans Arabic Light, direct 12px mono pixel render
"""
from __future__ import annotations

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import freetype
import numpy as np
import uharfbuzz as hb
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import Glyph as TtGlyph
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
GAME = ROOT / "game" / "320x240"
WEB = ROOT / "web" / "320x240"
DOCS = ROOT / "docs" / "320x240"

PX = 100
UPM = 1200
FT_FLAGS = freetype.FT_LOAD_RENDER | freetype.FT_LOAD_TARGET_MONO | freetype.FT_LOAD_MONOCHROME

OUT = {
    "j": ("k64-320-j-shinonome-mincho-12px", "K64 320 J Shinonome Mincho 12px"),
    "cjk": ("k64-320-cjk-fallback-12px", "K64 320 CJK Fallback 12px"),
    "thai": (
        "k64-320-thai-light-12px-mark16-max2",
        "K64 320 Thai Light 12px Mark16 Max2",
    ),
    "arabic": ("k64-320-arabic-light-12px", "K64 320 Arabic Light 12px"),
}


def empty_glyph() -> TtGlyph:
    g = TtGlyph()
    g.numberOfContours = 0
    return g


def set_names(tt: TTFont, family: str, ps_name: str) -> None:
    name = tt["name"]
    name.names = [r for r in name.names if r.nameID not in (1, 2, 3, 4, 6, 16, 17)]
    for nid, text in [
        (1, family),
        (2, "Regular"),
        (3, ps_name),
        (4, f"{family} Regular"),
        (6, ps_name),
    ]:
        name.setName(text, nid, 3, 1, 0x409)


def set_line_metrics(tt: TTFont, ascent: int, descent: int) -> None:
    tt["hhea"].ascent = ascent
    tt["hhea"].descent = descent
    tt["hhea"].lineGap = 0
    if "OS/2" in tt:
        os2 = tt["OS/2"]
        os2.sTypoAscender = ascent
        os2.sTypoDescender = descent
        os2.sTypoLineGap = 0
        os2.usWinAscent = max(ascent, 0)
        os2.usWinDescent = max(-descent, 0)


def save_ttf_and_woff2(tt: TTFont, stem: str) -> tuple[Path, Path]:
    GAME.mkdir(parents=True, exist_ok=True)
    WEB.mkdir(parents=True, exist_ok=True)
    ttf_path = GAME / f"{stem}.ttf"
    woff_path = WEB / f"{stem}.woff2"
    tt.save(ttf_path)
    woff = TTFont(ttf_path)
    woff.flavor = "woff2"
    woff.save(woff_path)
    return ttf_path, woff_path


def fix_shinonome_bitmap_baseline() -> tuple[Path, Path]:
    source = SRC / "JF-Dot-ShinonomeMin12.ttf"
    if not source.exists():
        raise FileNotFoundError(source)
    tt = TTFont(source)
    upm = tt["head"].unitsPerEm
    set_line_metrics(tt, upm, 0)
    if "EBLC" in tt:
        for strike in tt["EBLC"].strikes:
            hori = strike.bitmapSizeTable.hori
            hori.ascender = 12
            hori.descender = 0
            hori.maxBeforeBL = 12
            hori.minAfterBL = 0
            for sub in strike.indexSubTables:
                metrics = getattr(sub, "metrics", None)
                if metrics is not None and getattr(metrics, "height", None) == 12:
                    metrics.horiBearingY = 12
    stem, family = OUT["j"]
    set_names(tt, family, "K64320JShinonomeMincho12px-Regular")
    return save_ttf_and_woff2(tt, stem)


def make_cjk_fallback() -> tuple[Path, Path]:
    stem, family = OUT["cjk"]
    source = SRC / "k64-cjk-fallback-12px-drop-bridge-asc1200-trial.ttf"
    if not source.exists():
        import bake_unifont_12px_drop as drop

        source = GAME / "_tmp-k64-320-cjk-fallback-12px.ttf"
        # The generic lab script defaults to ASC=11.  The final 320x240 CJK
        # face is bottom-aligned: 12 ink rows above the baseline, no descent.
        drop.ASC = 12
        drop.bake(
            SRC / "unifont-16px.ttf",
            source,
            drop_bridge_repair=True,
        )
    tt = TTFont(source)
    set_line_metrics(tt, UPM, 0)
    if "head" in tt:
        tt["head"].unitsPerEm = UPM
    if "OS/2" in tt:
        tt["OS/2"].usWinAscent = UPM
        tt["OS/2"].usWinDescent = 0
    set_names(tt, family, "K64320CJKFallback12px-Regular")
    return save_ttf_and_woff2(tt, stem)


def bitmap_rows(bitmap) -> list[list[int]]:
    w, h, pitch = bitmap.width, bitmap.rows, bitmap.pitch
    if w == 0 or h == 0:
        return []
    buf = bytes(bitmap.buffer)
    rows: list[list[int]] = []
    if bitmap.pixel_mode == freetype.FT_PIXEL_MODE_MONO:
        ap = abs(pitch)
        for y in range(h):
            start = y * pitch if pitch >= 0 else (h - 1 - y) * ap
            rows.append([1 if (buf[start + x // 8] >> (7 - (x % 8))) & 1 else 0 for x in range(w)])
    else:
        for y in range(h):
            start = y * pitch if pitch >= 0 else (h - 1 - y) * abs(pitch)
            rows.append([1 if buf[start + x] >= 128 else 0 for x in range(w)])
    return rows


class RenderedGlyph:
    def __init__(self, rows, left, top, advance):
        self.rows = rows
        self.left = left
        self.top = top
        self.advance = advance
        self.width = len(rows[0]) if rows else 0
        self.height = len(rows)


def render_gid(face: freetype.Face, gid: int, size: int) -> RenderedGlyph:
    face.set_pixel_sizes(0, size)
    face.load_glyph(gid, FT_FLAGS)
    glyph = face.glyph
    return RenderedGlyph(
        bitmap_rows(glyph.bitmap),
        glyph.bitmap_left,
        glyph.bitmap_top,
        glyph.advance.x / 64.0,
    )


def emit_bitmap_glyph(r: RenderedGlyph, x_shift=0.0, y_shift=0.0) -> TtGlyph:
    pen = TTGlyphPen(None)
    has_ink = False
    for y, row in enumerate(r.rows):
        for x, ink in enumerate(row):
            if not ink:
                continue
            has_ink = True
            x0 = int(round((r.left + x + x_shift) * PX))
            x1 = int(round((r.left + x + 1 + x_shift) * PX))
            y_top = int(round((r.top - y + y_shift) * PX))
            y_bot = int(round((r.top - y - 1 + y_shift) * PX))
            pen.moveTo((x0, y_bot))
            pen.lineTo((x0, y_top))
            pen.lineTo((x1, y_top))
            pen.lineTo((x1, y_bot))
            pen.closePath()
    return pen.glyph() if has_ink else empty_glyph()


def glyph_bbox(glyph: TtGlyph) -> tuple[int, int, int, int] | None:
    coords = getattr(glyph, "coordinates", None)
    if not coords:
        return None
    xs = [pt[0] for pt in coords]
    ys = [pt[1] for pt in coords]
    return min(xs), min(ys), max(xs), max(ys)


THAI_MARK_CPS = set([0x0E31] + list(range(0x0E34, 0x0E3B)) + list(range(0x0E47, 0x0E4F)))
THAI_MARK_HEX = {f"{cp:04X}" for cp in THAI_MARK_CPS}
THAI_BELOW_HEX = {f"{cp:04X}" for cp in (0x0E38, 0x0E39, 0x0E3A)}


def glyph_name_marks(gname: str) -> tuple[bool, bool]:
    name = gname.upper()
    is_mark = any(h in name for h in THAI_MARK_HEX)
    is_below = any(h in name for h in THAI_BELOW_HEX)
    return is_mark, is_below


def scale_gpos(tt: TTFont, scale_x: float, scale_y: float) -> None:
    if "GPOS" not in tt:
        return

    def sx(v):
        return int(round(v * scale_x / PX)) * PX

    def sy(v):
        return int(round(v * scale_y / PX)) * PX

    def scale_anchor(anchor):
        if anchor is None:
            return
        if hasattr(anchor, "XCoordinate") and anchor.XCoordinate is not None:
            anchor.XCoordinate = sx(anchor.XCoordinate)
        if hasattr(anchor, "YCoordinate") and anchor.YCoordinate is not None:
            anchor.YCoordinate = sy(anchor.YCoordinate)

    def scale_value(vr):
        if vr is None:
            return
        for attr, fn in [
            ("XPlacement", sx),
            ("XAdvance", sx),
            ("YPlacement", sy),
            ("YAdvance", sy),
        ]:
            if hasattr(vr, attr):
                value = getattr(vr, attr)
                if value is not None:
                    setattr(vr, attr, fn(value))

    def visit(sub):
        cls = sub.__class__.__name__
        if cls == "ExtensionPos":
            visit(sub.ExtSubTable)
        elif cls == "MarkBasePos":
            for rec in sub.MarkArray.MarkRecord:
                scale_anchor(rec.MarkAnchor)
            for rec in sub.BaseArray.BaseRecord:
                for anchor in rec.BaseAnchor:
                    scale_anchor(anchor)
        elif cls == "MarkMarkPos":
            for rec in sub.Mark1Array.MarkRecord:
                scale_anchor(rec.MarkAnchor)
            for rec in sub.Mark2Array.Mark2Record:
                for anchor in rec.Mark2Anchor:
                    scale_anchor(anchor)
        elif cls == "MarkLigPos":
            for rec in sub.MarkArray.MarkRecord:
                scale_anchor(rec.MarkAnchor)
            for lig in sub.LigatureArray.LigatureAttach:
                for comp in lig.ComponentRecord:
                    for anchor in comp.LigatureAnchor:
                        scale_anchor(anchor)
        elif cls == "CursivePos":
            for rec in sub.EntryExitRecord:
                scale_anchor(rec.EntryAnchor)
                scale_anchor(rec.ExitAnchor)
        elif cls == "PairPos":
            if sub.Format == 1:
                for pair_set in sub.PairSet:
                    for pair in pair_set.PairValueRecord:
                        scale_value(pair.Value1)
                        scale_value(pair.Value2)
            elif sub.Format == 2:
                for c1 in sub.Class1Record:
                    for c2 in c1.Class2Record:
                        scale_value(c2.Value1)
                        scale_value(c2.Value2)
        elif cls == "SinglePos":
            if sub.Format == 1:
                scale_value(sub.Value)
            elif sub.Format == 2:
                for value in sub.Value:
                    scale_value(value)

    for lookup in tt["GPOS"].table.LookupList.Lookup:
        for subtable in lookup.SubTable:
            visit(subtable)


def shape_gids(font_path: Path, text: str, size: int, lang=None, direction=None):
    data = font_path.read_bytes()
    font = hb.Font(hb.Face(data))
    font.scale = (size * 64, size * 64)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    if lang:
        buf.language = lang
    if direction:
        buf.direction = direction
    hb.shape(font, buf, {})
    return list(zip(buf.glyph_infos, buf.glyph_positions))


def collision_score(x, y, r: RenderedGlyph, base_mask: set[tuple[int, int]], clearance=1) -> int:
    ix = int(round(x))
    iy = int(round(y))
    score = 0
    for yy, row in enumerate(r.rows):
        py = iy + yy
        for xx, ink in enumerate(row):
            if not ink:
                continue
            px = ix + xx
            for dy in range(clearance + 1):
                if (px, py + dy) in base_mask:
                    score += 1
                    break
    return score


def mark_aligned_shift(ref: RenderedGlyph, mark: RenderedGlyph, is_below: bool) -> tuple[float, float]:
    x_shift = (ref.left + ref.width / 2.0) - (mark.left + mark.width / 2.0)
    if is_below:
        y_shift = ref.top - mark.top
    else:
        ref_bottom = ref.top - ref.height
        y_shift = ref_bottom + mark.height - mark.top
    return x_shift, y_shift


def thai_collision_up_by_gid(font_path: Path, glyph_order: list[str], max_up: int = 2) -> dict[int, int]:
    face = freetype.Face(str(font_path))
    samples = [
        "ก่ ก้ ก๊ ก๋ ก์ กำ ก่ำ ก้ำ กิ กี กึ กื กุ กู เก แก",
        "กา กิ กี กึ กื กุ กู เก แก ก่ ก้ ก๊ ก๋ ก์ ก่ำ ก้ำ กึ่ กื้",
    ]
    up_by_gid: dict[int, int] = {}
    for text in samples:
        shaped = shape_gids(font_path, text, 12, lang="th")
        base_mask: set[tuple[int, int]] = set()
        pen_x = 0.0
        for info, pos in shaped:
            gid = info.codepoint
            gname = glyph_order[gid] if gid < len(glyph_order) else ""
            is_mark, is_below = glyph_name_marks(gname)
            if is_mark:
                ref = render_gid(face, gid, 12)
                mark = render_gid(face, gid, 16)
                x_shift, y_shift = mark_aligned_shift(ref, mark, is_below)
                gx = pen_x + pos.x_offset / 64.0 + mark.left + x_shift
                gy = -(pos.y_offset / 64.0) - mark.top - y_shift
                if not is_below:
                    best = collision_score(gx, gy, mark, base_mask, clearance=1)
                    best_up = 0
                    for up in range(1, max_up + 1):
                        score = collision_score(gx, gy - up, mark, base_mask, clearance=1)
                        if score < best:
                            best = score
                            best_up = up
                        if score == 0:
                            break
                    up_by_gid[gid] = max(up_by_gid.get(gid, 0), best_up)
            else:
                base = render_gid(face, gid, 12)
                gx = pen_x + pos.x_offset / 64.0 + base.left
                gy = -(pos.y_offset / 64.0) - base.top
                ix = int(round(gx))
                iy = int(round(gy))
                for yy, row in enumerate(base.rows):
                    for xx, ink in enumerate(row):
                        if ink:
                            base_mask.add((ix + xx, iy + yy))
            pen_x += pos.x_advance / 64.0
    return up_by_gid


def bake_pixel_outline_font(
    source: Path,
    stem: str,
    family: str,
    ps_name: str,
    *,
    thai_mark16=False,
    descent=-300,
) -> tuple[Path, Path]:
    tt = TTFont(source)
    glyph_order = tt.getGlyphOrder()
    face = freetype.Face(str(source))
    glyf = tt["glyf"]
    hmtx = tt["hmtx"]

    up_by_gid = thai_collision_up_by_gid(source, glyph_order, max_up=2) if thai_mark16 else {}

    for tbl in ["prep", "fpgm", "cvt ", "gasp", "EBDT", "EBLC", "CBDT", "CBLC", "sbix"]:
        if tbl in tt:
            del tt[tbl]

    for gid, gname in enumerate(glyph_order):
        source_adv = hmtx[gname][0] if gname in hmtx.metrics else 0
        is_mark, is_below = glyph_name_marks(gname) if thai_mark16 else (False, False)
        render_size = 16 if is_mark else 12
        rendered = render_gid(face, gid, render_size)
        if thai_mark16 and is_mark:
            ref = render_gid(face, gid, 12)
            x_shift, y_shift = mark_aligned_shift(ref, rendered, is_below)
            if not is_below:
                y_shift += up_by_gid.get(gid, 0)
        else:
            x_shift = y_shift = 0
        new_glyph = emit_bitmap_glyph(rendered, x_shift=x_shift, y_shift=y_shift)
        glyf[gname] = new_glyph
        if source_adv == 0:
            box = glyph_bbox(new_glyph)
            hmtx[gname] = (0, box[0] if box else 0)
        else:
            hmtx[gname] = (max(1, int(round(render_gid(face, gid, 12).advance * PX))), 0)

    tt["head"].unitsPerEm = UPM
    set_line_metrics(tt, UPM, descent)
    if "head" in tt:
        tt["head"].yMax = UPM
        tt["head"].yMin = descent
    if "maxp" in tt:
        tt["maxp"].maxZones = 1
    scale_gpos(tt, UPM / 1000.0, UPM / 1000.0)
    set_names(tt, family, ps_name)
    return save_ttf_and_woff2(tt, stem)


def bake_thai() -> tuple[Path, Path]:
    stem, family = OUT["thai"]
    return bake_pixel_outline_font(
        SRC / "NotoSansThai-Light.ttf",
        stem,
        family,
        "K64320ThaiLight12pxMark16Max2-Regular",
        thai_mark16=True,
        descent=-300,
    )


def bake_arabic() -> tuple[Path, Path]:
    stem, family = OUT["arabic"]
    return bake_pixel_outline_font(
        SRC / "NotoSansArabic-Light.ttf",
        stem,
        family,
        "K64320ArabicLight12px-Regular",
        thai_mark16=False,
        descent=-300,
    )


def draw_shaped_run(img: Image.Image, font_path: Path, text: str, x: int, baseline: int,
                    size: int, lang=None, direction=None) -> int:
    face = freetype.Face(str(font_path))
    shaped = shape_gids(font_path, text, size, lang=lang, direction=direction)
    pen_x = float(x)
    pix = img.load()
    for info, pos in shaped:
        gid = info.codepoint
        face.set_pixel_sizes(0, size)
        face.load_glyph(gid, FT_FLAGS)
        g = face.glyph
        rows = bitmap_rows(g.bitmap)
        gx = int(round(pen_x + pos.x_offset / 64.0 + g.bitmap_left))
        gy = int(round(baseline - pos.y_offset / 64.0 - g.bitmap_top))
        for yy, row in enumerate(rows):
            py = gy + yy
            for xx, ink in enumerate(row):
                if ink and 0 <= gx + xx < img.width and 0 <= py < img.height:
                    pix[gx + xx, py] = (0, 0, 0)
        pen_x += pos.x_advance / 64.0
    return int(round(pen_x))


def make_preview(paths: dict[str, Path]) -> Path:
    DOCS.mkdir(parents=True, exist_ok=True)
    out = DOCS / "preview.png"
    w, h = 1180, 190
    img = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(img)
    label = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 10)
    title = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 14)
    draw.text((10, 10), "K64 320x240 12px final font set", fill=(0, 0, 0), font=title)
    rows = [
        ("J/CJK", 52),
        ("Thai mark16 collision-aware max2", 94),
        ("Arabic Light 12px", 136),
    ]
    for name, base in rows:
        draw.text((10, base - 30), name, fill=(70, 70, 70), font=label)
        draw.line((10, base, w - 10, base), fill=(210, 235, 255))
    base = rows[0][1]
    x = 24
    x = draw_shaped_run(img, paths["j"], "日本語 いろはにほへと", x, base, 12) + 12
    x = draw_shaped_run(img, paths["cjk"], "中国語 敏捷的白狐跳过懒狗 한국어", x, base, 12) + 12
    base = rows[1][1]
    x = 24
    x = draw_shaped_run(img, paths["j"], "日本語", x, base, 12) + 12
    draw_shaped_run(
        img,
        paths["thai"],
        "กา กิ กี กึ กื กุ กู เก แก ก่ ก้ ก๊ ก๋ ก์ ก่ำ ก้ำ กึ่ กื้",
        x,
        base,
        12,
        lang="th",
    )
    base = rows[2][1]
    x = 24
    x = draw_shaped_run(img, paths["j"], "日本語", x, base, 12) + 12
    x = draw_shaped_run(img, paths["cjk"], "天地玄黄 宇宙洪荒", x, base, 12) + 12
    draw_shaped_run(img, paths["arabic"], "السلام عليكم مرحبا بالعالم ١٢٣٤", x, base, 12, lang="ar", direction="rtl")
    img = img.resize((w * 3, h * 3), Image.Resampling.NEAREST)
    img.save(out)
    return out


def main() -> int:
    outputs = {
        "j": fix_shinonome_bitmap_baseline()[0],
        "cjk": make_cjk_fallback()[0],
        "thai": bake_thai()[0],
        "arabic": bake_arabic()[0],
    }
    preview = make_preview(outputs)
    print("wrote 320x240 fonts:")
    for path in outputs.values():
        print(f"  {path.relative_to(ROOT)}")
    print(f"  {preview.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
