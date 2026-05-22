"""
Render multi-language pangrams as PNG for visual inspection.

Usage:
    python render_pangrams.py <font.ttf> [size] [output.png]

Defaults:
    size       = 32
    output.png = <font_name>_pangrams_<size>.png  (next to font)

Renders 23 lines (one per supported language) so you can spot:
  - missing glyphs (tofu boxes)
  - rhythm/baseline issues
  - script consistency across Latin/Cyrillic/Greek/Vietnamese

The Greek line uses MONOTONIC Greek only (modern, post-1982 orthography).
For polytonic Greek (classical/scholarly) the font needs the U+1F00-1FFF block.
"""
import sys
import os
from PIL import Image, ImageDraw, ImageFont

PANGRAMS = [
    ('en',  'The quick brown fox jumps over the lazy dog.'),
    ('de',  'Falsches Üben von Xylophonmusik quält jeden größeren Zwerg.'),
    ('fr',  'Portez ce vieux whisky au juge blond qui fume.'),
    ('es',  'El veloz murciélago hindú comía feliz cardillo y kiwi.'),
    ('pt',  'Luís argüia à Júlia que «brações, fé, chá, óxido, pôr» eram do português.'),
    ('it',  'Ma la volpe, col suo balzo, ha raggiunto il quieto Fido.'),
    ('pl',  'Pchnąć w tę łódź jeża lub ośm skrzyń fig.'),
    ('cs',  'Příliš žluťoučký kůň úpěl ďábelské ódy.'),
    ('hu',  'Árvíztűrő tükörfúrógép.'),
    ('tr',  'Pijamalı hasta yağız şoföre çabucak güvendi.'),
    ('ro',  'Muzicologă în bej vând whisky și tequila, preț fix.'),
    ('nl',  'Pa\'s wijze lynx bezag vroom het fikse aquaduct.'),
    ('sv',  'Flygande bäckasiner söka hwila på mjuka tuvor.'),
    ('da',  'Quizdeltagerne spiste jordbær med fløde, mens cirkusklovnen.'),
    ('no',  'Vår sære Zulu fra badeøya spilte jo whist og quickstep.'),
    ('fi',  'Albert osti fagotin ja töräytti puhkuvan melodian.'),
    ('id',  'Saya makan nasi goreng dengan ayam dan sambal pedas.'),
    ('vi',  'Tôi yêu tiếng nước tôi từ khi mới ra đời người ơi.'),
    ('ru',  'Съешь же ещё этих мягких французских булок, да выпей чаю.'),
    ('uk',  'Жебракують філософи при ґанку церкви — пʼять років.'),
    ('bg',  'За миг бях в чужд скърбен ден на изгрев слънце.'),
    # Modern Greek (monotonic) — for polytonic see docstring
    ('el',  'Ξεσκεπάζω την ψυχοφθόρα βδελυγμία — Άά Έέ Ήή Ίί Όό Ύύ Ώώ.'),
    ('eo',  'Eĥoŝanĝo ĉiuĵaŭde — ĉu vi ŝatas pli ĵaŭdojn aŭ vendrojn?'),
]

def main(font_path, size=32, out_path=None):
    sys.stdout.reconfigure(encoding='utf-8')
    if out_path is None:
        base = os.path.splitext(os.path.basename(font_path))[0]
        out_path = os.path.join(os.path.dirname(font_path), f'{base}_pangrams_{size}.png')

    line_h = int(size * 1.7)
    W = max(1500, int(size * 50))
    H = line_h * (len(PANGRAMS) + 2) + 30
    img = Image.new('RGB', (W, H), 'white')
    draw = ImageDraw.Draw(img)
    label_font = ImageFont.truetype('arial.ttf', max(11, size // 2))
    title_font = ImageFont.truetype('arial.ttf', 18)
    draw.text((10, 5), f'23-language pangrams @ {size}px — {os.path.basename(font_path)}',
              font=title_font, fill='black')
    body_font = ImageFont.truetype(font_path, size)
    y = line_h
    for code, text in PANGRAMS:
        draw.text((10, y + size // 4), code, font=label_font, fill='gray')
        draw.text((60, y), text, font=body_font, fill='black')
        y += line_h
    img.save(out_path)
    print(f'wrote {out_path}')

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    font = sys.argv[1]
    size = int(sys.argv[2]) if len(sys.argv) >= 3 else 32
    out = sys.argv[3] if len(sys.argv) >= 4 else None
    main(font, size, out)
