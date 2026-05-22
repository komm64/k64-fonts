"""
Render readability check PNGs: confusable pairs, all-glyphs grid, pixel sharpness.

Usage:
    python render_readcheck.py <font.ttf> [output_dir]

Defaults:
    output_dir = directory of the input font

Produces (next to font, prefixed with font base name):
    <name>_pairs_16.png       — confusable pairs at native 16px
    <name>_pairs_32.png       — at 32px (2x integer scale)
    <name>_allglyphs_16.png   — full glyph table at 16px
    <name>_allglyphs_32.png   — at 32px
    <name>_pixelsharp.png     — 16px text at 4x nearest-neighbor zoom

What to look for:
  - confusable pairs: Il1, O0, rn/m, cl/d, vv/w, B8, fi/fl, latin vs cyrillic
  - all-glyphs grid: rhythm uniformity, baseline alignment, outliers
  - pixelsharp: confirm no antialiasing artifacts at native scale

NOTE: Use integer-scale sizes only. Non-integer scales smear pixel fonts.
"""
import sys
import os
from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont

PAIRS = [
    ('Il1 / iI1',     'I l 1 i I 1 | I1l1Il'),
    ('O0 / o0',       'O 0 o 0 | O0o0O0'),
    ('rn vs m',       'rn m rn m rnrnm mmrn'),
    ('cl vs d',       'cl d cl d cldcld'),
    ('vv vs w',       'vv w vv w vvw wvv'),
    ('B8 / Bb8',      'B 8 b B8 B8b8B'),
    ('Gg6',           'G g 6 Gg6 6gG'),
    ('OQ / oc',       'O Q OQ oc oQ co'),
    ('nh',            'n h nh nhnhnh hnhn'),
    ('uv / yv',       'u v y uvy vyu'),
    ('5S',            '5 S 5S5S5S S5S5'),
    ('2Z / zZ',       '2 Z z zZ 2Z2Z'),
    ('fi / fl seq',   'fi fl ffi ffl fly fit'),
    ('punct close',   '. , : ; \' " ` ´  - _ ='),
    ('cyrillic conf', 'a а Aa Аа cc сс ee ее oo оо xx хх'),
    ('greek conf',    'AΑ BΒ EΕ HΗ KΚ MΜ NΝ OΟ PΡ TΤ XΧ ZΖ'),
]

def render_pairs(font_path, size, out_path):
    line_h = int(size * 1.6)
    W = 1100
    H = line_h * (len(PAIRS) + 2) + 30
    img = Image.new('RGB', (W, H), 'white')
    draw = ImageDraw.Draw(img)
    label_font = ImageFont.truetype('arial.ttf', max(11, size // 2))
    title_font = ImageFont.truetype('arial.ttf', 18)
    draw.text((10, 5), f'Confusable-pair check @ {size}px — {os.path.basename(font_path)}',
              font=title_font, fill='black')
    body_font = ImageFont.truetype(font_path, size)
    y = line_h
    for name, text in PAIRS:
        draw.text((10, y + size // 4), name, font=label_font, fill='gray')
        draw.text((220, y), text, font=body_font, fill='black')
        y += line_h
    img.save(out_path)
    print(f'wrote {out_path}')

def render_all_glyphs(font_path, size, out_path):
    f = TTFont(font_path)
    cmap = f.getBestCmap()
    chars = [chr(cp) for cp in sorted(cmap.keys()) if cp >= 0x20]

    cell = max(int(size * 1.4), size + 6)
    cols = max(30, 1200 // cell)
    W = cols * cell + 20
    rows = (len(chars) + cols - 1) // cols
    H = rows * cell + 40
    img = Image.new('RGB', (W, H), 'white')
    draw = ImageDraw.Draw(img)
    title_font = ImageFont.truetype('arial.ttf', 16)
    draw.text((10, 5), f'All {len(chars)} glyphs @ {size}px — {os.path.basename(font_path)}',
              font=title_font, fill='black')
    body_font = ImageFont.truetype(font_path, size)
    for i, ch in enumerate(chars):
        r, c = divmod(i, cols)
        x = 10 + c * cell
        y = 30 + r * cell
        draw.rectangle([x, y, x + cell - 2, y + cell - 2], outline=(230, 230, 230))
        draw.text((x + 3, y + 3), ch, font=body_font, fill='black')
    img.save(out_path)
    print(f'wrote {out_path}')

def render_pixelsharp(font_path, out_path):
    SAMPLE = 'The quick fox 0123 Αβγ Бвг ñöü áéí'
    body = ImageFont.truetype(font_path, 16)
    tmp = Image.new('RGB', (800, 24), 'white')
    ImageDraw.Draw(tmp).text((4, 2), SAMPLE, font=body, fill='black')
    zoomed = tmp.resize((tmp.width * 4, tmp.height * 4), Image.NEAREST)
    zoomed.save(out_path)
    print(f'wrote {out_path}')

def main(font_path, out_dir=None):
    sys.stdout.reconfigure(encoding='utf-8')
    if out_dir is None:
        out_dir = os.path.dirname(font_path) or '.'
    base = os.path.splitext(os.path.basename(font_path))[0]

    render_pairs(font_path, 16, os.path.join(out_dir, f'{base}_pairs_16.png'))
    render_pairs(font_path, 32, os.path.join(out_dir, f'{base}_pairs_32.png'))
    render_all_glyphs(font_path, 16, os.path.join(out_dir, f'{base}_allglyphs_16.png'))
    render_all_glyphs(font_path, 32, os.path.join(out_dir, f'{base}_allglyphs_32.png'))
    render_pixelsharp(font_path, os.path.join(out_dir, f'{base}_pixelsharp.png'))

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    font = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) >= 3 else None
    main(font, out_dir)
