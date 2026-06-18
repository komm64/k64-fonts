#!/usr/bin/env python3
"""Render README preview images for both monitor targets."""
from __future__ import annotations

import html
import subprocess
import sys
from pathlib import Path

import freetype
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SRC = ROOT / "src"
GAME = ROOT / "game"
WIN_FONTS = Path("C:/Windows/Fonts")
CHROME_CANDIDATES = [
    Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
    Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
    Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
]

sys.path.insert(0, str(ROOT / "tools"))
from bake_320x240_fonts import FT_FLAGS, bitmap_rows, shape_gids  # noqa: E402
from bake_web_fonts import apply_y2x_or_scanline_to_glyph  # noqa: E402

SAMPLES = {
    "latin": "HP 0123",
    "cjk_j": "日本語 ",
    "cjk_c": "你好 ",
    "cjk_k": "한국어",
    "thai": "กา กิ กี ก่ ก้",
    "arabic": "السلام ١٢٣",
}

LINE_SAMPLES = {
    "latin": "HP 0123",
    "cjk_j": "日本語 ",
    "cjk_c": "你好 ",
    "cjk_k": "한국어",
    "thai": "กา กิ",
    "arabic": "السلام",
}


def label_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(WIN_FONTS / "arial.ttf"), size)


def shaped_width(font_path: Path, text: str, size: int, x_scale=1, lang=None, direction=None) -> int:
    shaped = shape_gids(font_path, text, size, lang=lang, direction=direction)
    width = sum(pos.x_advance for _, pos in shaped) / 64.0
    return int(round(width * x_scale))


def draw_run(img: Image.Image, font_path: Path, text: str, x: int, baseline: int,
             size: int, *, x_scale=1, y_scale=1, lang=None, direction=None,
             load_flags=FT_FLAGS) -> int:
    face = freetype.Face(str(font_path))
    shaped = shape_gids(font_path, text, size, lang=lang, direction=direction)
    pen_x = float(x)
    pix = img.load()
    for info, pos in shaped:
        gid = info.codepoint
        face.set_pixel_sizes(0, size)
        face.load_glyph(gid, load_flags)
        glyph = face.glyph
        rows = bitmap_rows(glyph.bitmap)
        gx = int(round(pen_x + (pos.x_offset / 64.0 + glyph.bitmap_left) * x_scale))
        gy = int(round(baseline - (pos.y_offset / 64.0 + glyph.bitmap_top) * y_scale))
        for yy, row in enumerate(rows):
            py0 = gy + yy * y_scale
            for xx, ink in enumerate(row):
                if not ink:
                    continue
                px0 = gx + xx * x_scale
                for dy in range(y_scale):
                    py = py0 + dy
                    if not 0 <= py < img.height:
                        continue
                    for dx in range(x_scale):
                        px = px0 + dx
                        if 0 <= px < img.width:
                            pix[px, py] = (0, 0, 0)
        pen_x += (pos.x_advance / 64.0) * x_scale
    return int(round(pen_x))


def draw_sequence(img: Image.Image, runs: list[tuple[Path, str, int, int, int, str | None, int]],
                  x: int, baseline: int) -> int:
    pen_x = x
    for font_path, text, size, x_scale, y_scale, lang, load_flags in runs:
        pen_x = draw_run(
            img, font_path, text, pen_x, baseline, size,
            x_scale=x_scale, y_scale=y_scale, lang=lang, load_flags=load_flags,
        )
    return pen_x


def draw_inline(
    img: Image.Image,
    runs: list[tuple[Path, str, int, int, int, str | None, str | None, int]],
    x: int,
    baseline: int,
    separator_font: Path,
    separator_size: int,
) -> int:
    pen_x = x
    for index, (font_path, text, size, x_scale, y_scale, lang, direction, load_flags) in enumerate(runs):
        if index:
            pen_x = draw_run(img, separator_font, " / ", pen_x, baseline, separator_size)
        pen_x = draw_run(
            img,
            font_path,
            text,
            pen_x,
            baseline,
            size,
            x_scale=x_scale,
            y_scale=y_scale,
            lang=lang,
            direction=direction,
            load_flags=load_flags,
        )
    return pen_x


def draw_rtl(img: Image.Image, font_path: Path, text: str, right: int, baseline: int,
             size: int, *, x_scale=1, y_scale=1, lang="ar") -> int:
    width = shaped_width(font_path, text, size, x_scale=x_scale, lang=lang, direction="rtl")
    return draw_run(
        img, font_path, text, right - width, baseline, size,
        x_scale=x_scale, y_scale=y_scale, lang=lang, direction="rtl",
    )


def upscale(img: Image.Image, scale: int) -> Image.Image:
    return img.resize((img.width * scale, img.height * scale), Image.Resampling.NEAREST)


def as_file_url(path: Path) -> str:
    return path.resolve().as_uri()


def find_chrome() -> Path | None:
    for candidate in CHROME_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def render_640_with_chrome(out: Path) -> bool:
    chrome = find_chrome()
    if chrome is None:
        return False

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp_html = ROOT / "tmp" / "readme-preview-640.html"
    tmp_html.parent.mkdir(parents=True, exist_ok=True)
    font = {
        "k64f": as_file_url(ROOT / "web" / "k64-fantasy-2x.woff2"),
        "j": as_file_url(ROOT / "web" / "k64-JF-Dot-ShinonomeMin16-or12-y2x.woff2"),
        "ck": as_file_url(ROOT / "web" / "k64-unifont-16px-or12-y2x.woff2"),
        "thai": as_file_url(ROOT / "web" / "k64-thai-pixel-12w-or12-y2x-prop.woff2"),
        "arabic": as_file_url(ROOT / "web" / "k64-arabic-sans-medium-pixel-20px-thin-y2x.woff2"),
    }

    def e(text: str) -> str:
        return html.escape(text, quote=True)

    tmp_html.write_text(f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
@font-face {{ font-family: "K64F2X"; src: url("{font['k64f']}") format("woff2"); }}
@font-face {{ font-family: "K64J"; src: url("{font['j']}") format("woff2"); }}
@font-face {{ font-family: "K64CK"; src: url("{font['ck']}") format("woff2"); }}
@font-face {{ font-family: "K64Thai"; src: url("{font['thai']}") format("woff2"); }}
@font-face {{ font-family: "K64Arabic"; src: url("{font['arabic']}") format("woff2"); }}
html, body {{
  margin: 0;
  width: 640px;
  height: 240px;
  overflow: hidden;
  background: white;
  color: black;
  -webkit-font-smoothing: none;
  font-smooth: never;
}}
.canvas {{ position: relative; width: 640px; height: 240px; background: white; }}
.title {{ position: absolute; left: 16px; top: 6px; font: 11px Arial, sans-serif; }}
.head {{ position: absolute; left: 16px; font: 8px Arial, sans-serif; color: rgb(70,70,70); }}
.guide {{ position: absolute; left: 16px; width: 608px; height: 1px; background: rgb(210,235,255); }}
.run {{ position: absolute; left: 16px; white-space: nowrap; }}
.default-line {{ font: 32px Arial, "Yu Gothic", "Malgun Gothic", Tahoma, sans-serif; }}
.k64-line {{ font: 32px K64F2X, K64J, K64CK, K64Thai, K64Arabic, monospace; }}
.sep {{ color: rgb(120,120,120); font-family: Arial, sans-serif; padding: 0 5px; }}
.k64-latin {{ font-family: K64F2X; }}
.k64-j {{ font-family: K64J; }}
.k64-ck {{ font-family: K64CK; }}
.k64-thai {{ font-family: K64Thai; }}
.k64-arabic {{ font: 40px/32px K64Arabic, K64F2X, K64CK, K64J, monospace; }}
</style>
</head>
<body>
<div class="canvas">
  <div class="title">K64 640x240 tall-dot target</div>
  <div class="head" style="top:32px">Default font</div>
  <div class="head" style="top:126px">K64 target stack</div>
  <div class="guide" style="top:112px"></div>
  <div class="guide" style="top:206px"></div>
  <div class="run default-line" style="top:52px">{e(LINE_SAMPLES['latin'])} / {e(LINE_SAMPLES['cjk_j'] + LINE_SAMPLES['cjk_c'] + LINE_SAMPLES['cjk_k'])} / {e(LINE_SAMPLES['thai'])} / <span lang="ar" dir="rtl">{e(LINE_SAMPLES['arabic'])}</span></div>
  <div class="run k64-line" style="top:146px"><span class="k64-latin">{e(LINE_SAMPLES['latin'])}</span><span class="sep">/</span><span class="k64-j">{e(LINE_SAMPLES['cjk_j'])}</span><span class="k64-ck">{e(LINE_SAMPLES['cjk_c'] + LINE_SAMPLES['cjk_k'])}</span><span class="sep">/</span><span class="k64-thai" lang="th">{e(LINE_SAMPLES['thai'])}</span><span class="sep">/</span><span class="k64-arabic" lang="ar" dir="rtl">{e(LINE_SAMPLES['arabic'])}</span></div>
</div>
</body>
</html>
""", encoding="utf-8")
    result = subprocess.run(
        [
            str(chrome),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--force-device-scale-factor=2",
            "--window-size=640,240",
            f"--screenshot={out.resolve()}",
            tmp_html.resolve().as_uri(),
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=120,
    )
    return result.returncode == 0 and out.exists()


def ensure_y2x_ttf(src: Path, stem: str) -> Path:
    cache = ROOT / "tmp" / "readme-preview-cache"
    cache.mkdir(parents=True, exist_ok=True)
    out = cache / f"{stem}.ttf"
    if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
        return out

    from fontTools.ttLib import TTFont

    tt = TTFont(str(src))
    src_upm = tt["head"].unitsPerEm
    new_upm = src_upm * 2
    dot_units = src_upm // 16
    glyf = tt["glyf"]
    for gname in glyf.keys():
        apply_y2x_or_scanline_to_glyph(glyf[gname], dot_units, "none")

    margin = 200
    new_asc = tt["hhea"].ascent * 2 + margin
    new_desc = tt["hhea"].descent * 2 - margin
    new_line_gap = max(0, new_upm - (new_asc - new_desc))

    tt["head"].unitsPerEm = new_upm
    tt["head"].yMin = tt["head"].yMin * 2
    tt["head"].yMax = tt["head"].yMax * 2
    tt["hhea"].ascent = new_asc
    tt["hhea"].descent = new_desc
    tt["hhea"].lineGap = new_line_gap
    if "OS/2" in tt:
        os2 = tt["OS/2"]
        os2.sTypoAscender = new_asc
        os2.sTypoDescender = new_desc
        os2.sTypoLineGap = new_line_gap
        os2.usWinAscent = new_asc
        os2.usWinDescent = max(0, -new_desc)
    tt.save(str(out))
    return out


def render_640() -> Path:
    out = DOCS / "640x240" / "preview.png"
    if render_640_with_chrome(out):
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (640, 240), "white")
    draw = ImageDraw.Draw(img)
    draw.text((16, 6), "K64 640x240 tall-dot target", fill=(0, 0, 0), font=label_font(11))
    draw.text((16, 32), "Default font", fill=(70, 70, 70), font=label_font(8))
    draw.text((16, 126), "K64 target stack", fill=(70, 70, 70), font=label_font(8))
    for y in (112, 206):
        draw.line((16, y, 624, y), fill=(210, 235, 255))
    defaults = {
        "latin": WIN_FONTS / "arial.ttf",
        "cjk_j": WIN_FONTS / "YuGothR.ttc",
        "cjk_k": WIN_FONTS / "malgun.ttf",
        "thai": WIN_FONTS / "tahoma.ttf",
        "arabic": WIN_FONTS / "tahoma.ttf",
    }
    k64 = {
        "latin": SRC / "komm64Fantasy.ttf",
        "j": ensure_y2x_ttf(SRC / "JF-Dot-ShinonomeMin16_12px_or1.ttf", "k64-JF-Dot-ShinonomeMin16-or12-y2x"),
        "ck": ensure_y2x_ttf(SRC / "unifont-16px_12px_or1.ttf", "k64-unifont-16px-or12-y2x"),
        "thai": GAME / "k64-thai-pixel-12w-or12-y1-prop.ttf",
        "arabic": GAME / "k64-arabic-sans-medium-pixel-20px-thin-y1.ttf",
    }
    draw_inline(
        img,
        [
            (defaults["latin"], LINE_SAMPLES["latin"], 32, 1, 1, None, None, FT_FLAGS),
            (defaults["cjk_j"], LINE_SAMPLES["cjk_j"], 32, 1, 1, None, None, FT_FLAGS),
            (defaults["cjk_j"], LINE_SAMPLES["cjk_c"], 32, 1, 1, None, None, FT_FLAGS),
            (defaults["cjk_k"], LINE_SAMPLES["cjk_k"], 32, 1, 1, "ko", None, FT_FLAGS),
            (defaults["thai"], LINE_SAMPLES["thai"], 32, 1, 1, "th", None, FT_FLAGS),
            (defaults["arabic"], LINE_SAMPLES["arabic"], 32, 1, 1, "ar", "rtl", FT_FLAGS),
        ],
        16,
        92,
        defaults["latin"],
        32,
    )
    draw_inline(
        img,
        [
            (k64["latin"], LINE_SAMPLES["latin"], 16, 2, 2, None, None, FT_FLAGS),
            (k64["j"], LINE_SAMPLES["cjk_j"], 32, 1, 1, None, None, FT_FLAGS),
            (k64["ck"], LINE_SAMPLES["cjk_c"], 32, 1, 1, None, None, FT_FLAGS),
            (k64["ck"], LINE_SAMPLES["cjk_k"], 32, 1, 1, "ko", None, FT_FLAGS),
            (k64["thai"], LINE_SAMPLES["thai"], 16, 1, 2, "th", None, FT_FLAGS),
            (k64["arabic"], LINE_SAMPLES["arabic"], 20, 1, 2, "ar", "rtl", FT_FLAGS),
        ],
        16,
        186,
        defaults["latin"],
        32,
    )

    upscale(img, 2).save(out)
    return out


def render_320() -> Path:
    out = DOCS / "320x240" / "preview.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (320, 240), "white")
    draw = ImageDraw.Draw(img)
    draw.text((8, 5), "K64 320x240 square-dot target", fill=(0, 0, 0), font=label_font(9))
    draw.text((8, 38), "Default font", fill=(70, 70, 70), font=label_font(6))
    draw.text((8, 108), "K64 target stack", fill=(70, 70, 70), font=label_font(6))
    for y in (86, 156):
        draw.line((8, y, 312, y), fill=(210, 235, 255))
    defaults = {
        "latin": WIN_FONTS / "arial.ttf",
        "cjk_j": WIN_FONTS / "YuGothR.ttc",
        "cjk_k": WIN_FONTS / "malgun.ttf",
        "thai": WIN_FONTS / "tahoma.ttf",
        "arabic": WIN_FONTS / "tahoma.ttf",
    }
    base = GAME / "320x240"
    k64 = {
        "latin": SRC / "komm64Fantasy.ttf",
        "j": base / "k64-320-j-shinonome-mincho-12px.ttf",
        "ck": base / "k64-320-ck-unifont-12px.ttf",
        "thai": base / "k64-320-thai-light-12px-mark16-max2.ttf",
        "arabic": base / "k64-320-arabic-light-12px.ttf",
    }
    draw_inline(
        img,
        [
            (defaults["latin"], LINE_SAMPLES["latin"], 12, 1, 1, None, None, FT_FLAGS),
            (defaults["cjk_j"], LINE_SAMPLES["cjk_j"], 12, 1, 1, None, None, FT_FLAGS),
            (defaults["cjk_j"], LINE_SAMPLES["cjk_c"], 12, 1, 1, None, None, FT_FLAGS),
            (defaults["cjk_k"], LINE_SAMPLES["cjk_k"], 12, 1, 1, "ko", None, FT_FLAGS),
            (defaults["thai"], LINE_SAMPLES["thai"], 12, 1, 1, "th", None, FT_FLAGS),
            (defaults["arabic"], LINE_SAMPLES["arabic"], 12, 1, 1, "ar", "rtl", FT_FLAGS),
        ],
        8,
        70,
        defaults["latin"],
        12,
    )
    draw_inline(
        img,
        [
            (k64["latin"], LINE_SAMPLES["latin"], 16, 1, 1, None, None, FT_FLAGS),
            (k64["j"], LINE_SAMPLES["cjk_j"], 12, 1, 1, None, None, FT_FLAGS),
            (k64["ck"], LINE_SAMPLES["cjk_c"], 12, 1, 1, None, None, FT_FLAGS),
            (k64["ck"], LINE_SAMPLES["cjk_k"], 12, 1, 1, "ko", None, FT_FLAGS),
            (k64["thai"], LINE_SAMPLES["thai"], 12, 1, 1, "th", None, FT_FLAGS),
            (k64["arabic"], LINE_SAMPLES["arabic"], 12, 1, 1, "ar", "rtl", FT_FLAGS),
        ],
        8,
        140,
        defaults["latin"],
        12,
    )

    upscale(img, 4).save(out)
    return out


def main() -> int:
    for renderer in (render_640, render_320):
        preview = renderer()
        print(f"wrote {preview.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
