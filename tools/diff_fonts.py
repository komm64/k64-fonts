"""
Diff two font files — list added/removed glyphs and per-glyph metric changes.

Usage:
    python diff_fonts.py <old.ttf> <new.ttf>

Reports:
  - cmap diff (added/removed codepoints)
  - per-glyph diff for common codepoints (advance, xMin/xMax, yMin/yMax, lsb/rsb)
"""
import sys
import unicodedata
from fontTools.ttLib import TTFont

def load(path):
    f = TTFont(path)
    cmap = f.getBestCmap()
    hmtx = f['hmtx']
    glyf = f['glyf']
    data = {}
    for cp, gn in cmap.items():
        adv, _ = hmtx[gn]
        g = glyf[gn]
        if not hasattr(g, 'xMin'):
            data[cp] = (gn, adv, None, None, None, None, None, None)
            continue
        data[cp] = (gn, adv, g.xMin, g.xMax, g.yMin, g.yMax, g.xMin, adv - g.xMax)
    return data

def main(old_path, new_path):
    sys.stdout.reconfigure(encoding='utf-8')
    a = load(old_path)
    b = load(new_path)
    print(f'{old_path}: {len(a)} codepoints')
    print(f'{new_path}: {len(b)} codepoints')

    added = set(b) - set(a)
    removed = set(a) - set(b)
    common = set(a) & set(b)

    if added:
        print(f'\nAdded ({len(added)}):')
        for cp in sorted(added):
            try:
                ch = chr(cp); name = unicodedata.name(ch, '?')
            except: ch = '?'; name = '?'
            print(f'  U+{cp:04X} {ch}  {name}')
    if removed:
        print(f'\nRemoved ({len(removed)}):')
        for cp in sorted(removed):
            try:
                ch = chr(cp); name = unicodedata.name(ch, '?')
            except: ch = '?'; name = '?'
            print(f'  U+{cp:04X} {ch}  {name}')

    changed = [cp for cp in common if a[cp][1:] != b[cp][1:]]
    print(f'\nChanged metrics ({len(changed)}):')
    for cp in sorted(changed):
        try:
            ch = chr(cp); name = unicodedata.name(ch, '?')
        except: ch = '?'; name = '?'
        ad, bd = a[cp], b[cp]
        print(f'  U+{cp:04X} {ch:2s}  {name}')
        if ad[1] != bd[1]:
            print(f'      advance: {ad[1]} -> {bd[1]}')
        if ad[2] != bd[2] or ad[3] != bd[3]:
            print(f'      x: [{ad[2]},{ad[3]}] -> [{bd[2]},{bd[3]}]')
        if ad[4] != bd[4] or ad[5] != bd[5]:
            print(f'      y: [{ad[4]},{ad[5]}] -> [{bd[4]},{bd[5]}]')
        if ad[6] != bd[6] or ad[7] != bd[7]:
            print(f'      lsb/rsb: {ad[6]}/{ad[7]} -> {bd[6]}/{bd[7]}')

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
