#!/usr/bin/env python3
"""Render the target-specific README preview images."""
from __future__ import annotations

import sys
import os
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
WEB = ROOT / "web"
GAME = ROOT / "game"

sys.path.insert(0, str(ROOT / "tools"))
from bake_320x240_fonts import draw_shaped_run, shape_gids  # noqa: E402


def label_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype("C:/Windows/Fonts/arial.ttf", size)


def shaped_width(font_path: Path, text: str, size: int, lang=None, direction=None) -> int:
    shaped = shape_gids(font_path, text, size, lang=lang, direction=direction)
    width = sum(pos.x_advance for _, pos in shaped) / 64.0
    return int(round(width))


def draw_rtl(img: Image.Image, font_path: Path, text: str, right: int, baseline: int,
             size: int, lang="ar") -> int:
    width = shaped_width(font_path, text, size, lang=lang, direction="rtl")
    return draw_shaped_run(img, font_path, text, right - width, baseline, size, lang=lang, direction="rtl")


def upscale_nearest(img: Image.Image, scale: int) -> Image.Image:
    return img.resize((img.width * scale, img.height * scale), Image.Resampling.NEAREST)


def find_chrome() -> Path:
    env_path = os.environ.get("CHROME_PATH")
    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path))
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    candidates.extend(sorted(local.glob("ms-playwright/chromium-*/chrome-win*/chrome.exe"), reverse=True))
    candidates.extend([
        Path(os.environ.get("PROGRAMFILES", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft/Edge/Application/msedge.exe",
    ])
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError("Chrome/Edge executable not found; set CHROME_PATH to render the 640x240 web preview")


def render_640() -> Path:
    out = DOCS / "640x240" / "preview.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    font_urls = {
        "k64f": (WEB / "k64-fantasy-2x.woff2").as_uri(),
        "jp": (WEB / "k64-JF-Dot-ShinonomeMin16-or12-y2x.woff2").as_uri(),
        "cjk": (WEB / "k64-unifont-16px-or12-y2x.woff2").as_uri(),
        "thai": (WEB / "k64-thai-pixel-12w-or12-y2x-prop.woff2").as_uri(),
        "arabic": (WEB / "k64-arabic-sans-medium-pixel-20px-thin-y2x.woff2").as_uri(),
    }
    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
@font-face {{ font-family: "K64F2X"; src: url("{font_urls['k64f']}") format("woff2"); }}
@font-face {{ font-family: "K64CJKJP"; src: url("{font_urls['jp']}") format("woff2"); }}
@font-face {{ font-family: "K64CJKFallback"; src: url("{font_urls['cjk']}") format("woff2"); }}
@font-face {{ font-family: "K64Thai12WProp"; src: url("{font_urls['thai']}") format("woff2"); }}
@font-face {{ font-family: "K64Arabic20Thin"; src: url("{font_urls['arabic']}") format("woff2"); }}
html, body {{
  width: 640px;
  height: 240px;
  margin: 0;
  overflow: hidden;
  background: #fff;
}}
body {{
  color: #000;
  font-family: Arial, sans-serif;
  -webkit-font-smoothing: none;
  text-rendering: geometricPrecision;
}}
.title {{ position: absolute; left: 8px; top: 6px; font: 11px Arial, sans-serif; }}
.label {{ position: absolute; left: 8px; color: #555; font: 8px Arial, sans-serif; }}
.rule {{ position: absolute; left: 8px; right: 8px; height: 1px; background: #d2ebff; }}
.run {{ position: absolute; left: 24px; font-size: 32px; line-height: 32px; white-space: nowrap; }}
.k64f {{ font-family: "K64F2X", monospace; }}
.jcjk {{ font-family: "K64F2X", "K64CJKJP", "K64CJKFallback", monospace; }}
.thai {{ font-family: "K64F2X", "K64Thai12WProp", monospace; }}
.arabic {{
  position: absolute;
  right: 24px;
  top: 198px;
  font-family: "K64Arabic20Thin", "K64F2X", monospace;
  font-size: 40px;
  line-height: 32px;
  direction: rtl;
  white-space: nowrap;
}}
</style>
</head>
<body>
  <div class="title">K64 640x240 32px tall-dot font set</div>
  <div class="label" style="top:30px">K64F 2x</div>
  <div class="run k64f" style="top:42px">HP 0123 / MENU / SCORE</div>
  <div class="rule" style="top:74px"></div>

  <div class="label" style="top:82px">J / CJK or12-y2x</div>
  <div class="run jcjk" style="top:94px">日本語 こんにちは世界　中国語 敏捷的白狐 한국어</div>
  <div class="rule" style="top:126px"></div>

  <div class="label" style="top:134px">Thai 12w-or12-y2x prop</div>
  <div class="run thai" lang="th" style="top:146px">กา กิ กี กึ กื กุ กู เก แก ก่ ก้ ก๊ ก๋ ก์ ก่ำ ก้ำ</div>
  <div class="rule" style="top:178px"></div>

  <div class="label" style="top:186px">Arabic 20px thin y2x</div>
  <div class="run k64f" style="top:198px">HP 0123</div>
  <div class="arabic" lang="ar" dir="rtl">السلام عليكم مرحبا بالعالم ١٢٣</div>
  <div class="rule" style="top:230px"></div>
</body>
</html>
"""
    chrome = find_chrome()
    with tempfile.TemporaryDirectory() as tmp:
        html_path = Path(tmp) / "k64-640-preview.html"
        html_path.write_text(html, encoding="utf-8")
        cmd = [
            str(chrome),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--force-device-scale-factor=2",
            "--window-size=640,240",
            "--virtual-time-budget=3000",
            f"--screenshot={out}",
            html_path.as_uri(),
        ]
        subprocess.run(cmd, check=True)
    return out


def render_320() -> Path:
    out = DOCS / "320x240" / "preview.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (320, 240), "white")
    draw = ImageDraw.Draw(img)
    title = label_font(9)
    label = label_font(7)
    draw.text((6, 5), "K64 320x240 12px square-dot font set", fill=(0, 0, 0), font=title)
    paths = {
        "j": GAME / "320x240" / "k64-320-j-shinonome-mincho-12px.ttf",
        "cjk": GAME / "320x240" / "k64-320-cjk-fallback-12px.ttf",
        "thai": GAME / "320x240" / "k64-320-thai-light-12px-mark16-max2.ttf",
        "arabic": GAME / "320x240" / "k64-320-arabic-light-12px.ttf",
    }
    rows = [
        ("J / CJK", 34),
        ("Chinese / Korean", 70),
        ("Thai mark16 max2", 112),
        ("Arabic Light", 158),
        ("Dense mixed line", 202),
    ]
    for name, base in rows:
        draw.text((6, base - 28), name, fill=(70, 70, 70), font=label)
        draw.line((6, base + 6, 314, base + 6), fill=(210, 235, 255))

    x = 12
    x = draw_shaped_run(img, paths["j"], "日本語 いろはにほへと", x, rows[0][1], 12) + 8
    draw_shaped_run(img, paths["cjk"], "漢字", x, rows[0][1], 12)

    x = 12
    x = draw_shaped_run(img, paths["cjk"], "中国語 敏捷的白狐", x, rows[1][1], 12) + 8
    draw_shaped_run(img, paths["cjk"], "한국어 안녕하세요", x, rows[1][1], 12)

    draw_shaped_run(
        img,
        paths["thai"],
        "กา กิ กี กึ กื กุ กู เก แก ก่ ก้ ก๊ ก๋ ก์ ก่ำ ก้ำ",
        12,
        rows[2][1],
        12,
        lang="th",
    )

    draw_rtl(img, paths["arabic"], "السلام عليكم مرحبا بالعالم ١٢٣٤", 308, rows[3][1], 12)

    x = 12
    x = draw_shaped_run(img, paths["j"], "日本語", x, rows[4][1], 12) + 6
    x = draw_shaped_run(img, paths["cjk"], "天地玄黄", x, rows[4][1], 12) + 6
    x = draw_shaped_run(img, paths["thai"], "น้ำ", x, rows[4][1], 12, lang="th") + 6
    draw_rtl(img, paths["arabic"], "سلام", 308, rows[4][1], 12)

    upscale_nearest(img, 4).save(out)
    return out


def main() -> int:
    preview_640 = render_640()
    preview_320 = render_320()
    print(f"wrote {preview_640.relative_to(ROOT)}")
    print(f"wrote {preview_320.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
