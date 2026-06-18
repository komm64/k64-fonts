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
.head {{ position: absolute; top: 24px; font: 8px Arial, sans-serif; color: rgb(70,70,70); }}
.left {{ left: 16px; }}
.right {{ left: 330px; }}
.guide {{ position: absolute; left: 16px; width: 608px; height: 1px; background: rgb(210,235,255); }}
.run {{ position: absolute; white-space: nowrap; }}
.default-latin {{ font: 32px Arial, sans-serif; }}
.default-cjk {{ font: 32px "Yu Gothic", "Malgun Gothic", sans-serif; }}
.default-thai {{ font: 32px Tahoma, sans-serif; }}
.default-arabic {{ font: 32px Tahoma, sans-serif; direction: rtl; text-align: right; }}
.k64-latin {{ font: 32px K64F2X, monospace; }}
.k64-cjk {{ font: 32px K64F2X, K64J, K64CK, monospace; }}
.k64-j {{ font-family: K64J; }}
.k64-ck {{ font-family: K64CK; }}
.k64-thai {{ font: 32px K64Thai, monospace; }}
.k64-arabic {{ font: 40px/32px K64Arabic, K64F2X, K64CK, K64J, monospace; direction: rtl; text-align: right; }}
</style>
</head>
<body>
<div class="canvas">
  <div class="title">K64 640x240 tall-dot target</div>
  <div class="head left">Default font</div>
  <div class="head right">K64 target stack</div>
  <div class="guide" style="top:78px"></div>
  <div class="guide" style="top:124px"></div>
  <div class="guide" style="top:168px"></div>
  <div class="guide" style="top:224px"></div>
  <div class="run default-latin left" style="top:33px">{e(SAMPLES['latin'])}</div>
  <div class="run k64-latin right" style="top:36px">{e(SAMPLES['latin'])}</div>
  <div class="run default-cjk left" style="top:79px">{e(SAMPLES['cjk_j'] + SAMPLES['cjk_c'] + SAMPLES['cjk_k'])}</div>
  <div class="run k64-cjk right" style="top:84px"><span class="k64-j">{e(SAMPLES['cjk_j'])}</span><span class="k64-ck">{e(SAMPLES['cjk_c'] + SAMPLES['cjk_k'])}</span></div>
  <div class="run default-thai left" lang="th" style="top:132px">{e(SAMPLES['thai'])}</div>
  <div class="run k64-thai right" lang="th" style="top:130px">{e(SAMPLES['thai'])}</div>
  <div class="run default-arabic" lang="ar" dir="rtl" style="top:174px; left:16px; width:294px">{e(SAMPLES['arabic'])}</div>
  <div class="run k64-arabic" lang="ar" dir="rtl" style="top:178px; left:330px; width:294px">{e(SAMPLES['arabic'])}</div>
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


def draw_frame(img: Image.Image, title: str, left_x: int, right_x: int,
               header_y: int, label_size: int) -> ImageDraw.ImageDraw:
    draw = ImageDraw.Draw(img)
    draw.text((left_x, 6 if img.width == 640 else 5), title, fill=(0, 0, 0), font=label_font(label_size + 3))
    draw.text((left_x, header_y), "Default font", fill=(70, 70, 70), font=label_font(label_size))
    draw.text((right_x, header_y), "K64 target stack", fill=(70, 70, 70), font=label_font(label_size))
    return draw


def render_640() -> Path:
    out = DOCS / "640x240" / "preview.png"
    if render_640_with_chrome(out):
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (640, 240), "white")
    draw = draw_frame(img, "K64 640x240 tall-dot target", 16, 330, 24, 8)
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
    rows = [("Latin", 64), ("J / CK", 110), ("Thai", 154), ("Arabic", 210)]
    for _label, baseline in rows:
        draw.line((16, baseline + 14, 624, baseline + 14), fill=(210, 235, 255))

    draw_run(img, defaults["latin"], SAMPLES["latin"], 16, rows[0][1], 32)
    draw_run(img, k64["latin"], SAMPLES["latin"], 330, rows[0][1], 16, x_scale=2, y_scale=2)

    draw_sequence(
        img,
        [
            (defaults["cjk_j"], SAMPLES["cjk_j"], 32, 1, 1, None, FT_FLAGS),
            (defaults["cjk_j"], SAMPLES["cjk_c"], 32, 1, 1, None, FT_FLAGS),
            (defaults["cjk_k"], SAMPLES["cjk_k"], 32, 1, 1, "ko", FT_FLAGS),
        ],
        16,
        rows[1][1],
    )
    draw_sequence(
        img,
        [
            (k64["j"], SAMPLES["cjk_j"], 32, 1, 1, None, FT_FLAGS),
            (k64["ck"], SAMPLES["cjk_c"], 32, 1, 1, None, FT_FLAGS),
            (k64["ck"], SAMPLES["cjk_k"], 32, 1, 1, "ko", FT_FLAGS),
        ],
        330,
        rows[1][1],
    )

    draw_run(img, defaults["thai"], SAMPLES["thai"], 16, rows[2][1], 32, lang="th")
    draw_run(img, k64["thai"], SAMPLES["thai"], 330, rows[2][1], 16, y_scale=2, lang="th")

    draw_rtl(img, defaults["arabic"], SAMPLES["arabic"], 310, rows[3][1], 32)
    draw_rtl(img, k64["arabic"], SAMPLES["arabic"], 624, rows[3][1], 20, y_scale=2)

    upscale(img, 2).save(out)
    return out


def render_320() -> Path:
    out = DOCS / "320x240" / "preview.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (320, 240), "white")
    draw = draw_frame(img, "K64 320x240 square-dot target", 8, 168, 24, 6)
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
    rows = [("Latin", 56), ("J / CK", 100), ("Thai", 144), ("Arabic", 198)]
    for _label, baseline in rows:
        draw.line((8, baseline + 12, 312, baseline + 12), fill=(210, 235, 255))

    draw_run(img, defaults["latin"], SAMPLES["latin"], 8, rows[0][1], 12)
    draw_run(img, k64["latin"], SAMPLES["latin"], 168, rows[0][1], 16)

    draw_sequence(
        img,
        [
            (defaults["cjk_j"], SAMPLES["cjk_j"], 12, 1, 1, None, FT_FLAGS),
            (defaults["cjk_j"], SAMPLES["cjk_c"], 12, 1, 1, None, FT_FLAGS),
            (defaults["cjk_k"], SAMPLES["cjk_k"], 12, 1, 1, "ko", FT_FLAGS),
        ],
        8,
        rows[1][1],
    )
    draw_sequence(
        img,
        [
            (k64["j"], SAMPLES["cjk_j"], 12, 1, 1, None, FT_FLAGS),
            (k64["ck"], SAMPLES["cjk_c"], 12, 1, 1, None, FT_FLAGS),
            (k64["ck"], SAMPLES["cjk_k"], 12, 1, 1, "ko", FT_FLAGS),
        ],
        168,
        rows[1][1],
    )

    draw_run(img, defaults["thai"], SAMPLES["thai"], 8, rows[2][1], 12, lang="th")
    draw_run(img, k64["thai"], SAMPLES["thai"], 168, rows[2][1], 12, lang="th")

    draw_rtl(img, defaults["arabic"], SAMPLES["arabic"], 152, rows[3][1], 12)
    draw_rtl(img, k64["arabic"], SAMPLES["arabic"], 312, rows[3][1], 12)

    upscale(img, 4).save(out)
    return out


def main() -> int:
    for renderer in (render_640, render_320):
        preview = renderer()
        print(f"wrote {preview.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
