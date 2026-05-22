"""
komm64 font inspector — metrics, language coverage, centering rules.

Usage:
    python inspect.py <font.ttf>

Reports:
  [1] Font metrics (em, ascent/descent, cap/x-height, total glyphs)
  [2] Language coverage for 23 langs (Steam HW Survey minus CJK+Thai + Esperanto)
  [3] Common typography & UI symbols
  [4] Centering rule conformance per padding bucket
  [5] Greek tonos caps follow "base unchanged or extend LEFT" rule
  [6] Advance width distribution
"""
import sys
from collections import Counter
from fontTools.ttLib import TTFont

LANGS = {
    'en (English)':           'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
    'id (Indonesian)':        'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ',
    'de (German)':            'abcdefghijklmnopqrstuvwxyzäöüßABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÜẞ',
    'es (Spanish)':           'abcdefghijklmnñopqrstuvwxyzáéíóúüABCDEFGHIJKLMNÑOPQRSTUVWXYZÁÉÍÓÚÜ¿¡',
    'pt (Portuguese)':        'abcdefghijklmnopqrstuvwxyzáâãàçéêíóôõúABCDEFGHIJKLMNOPQRSTUVWXYZÁÂÃÀÇÉÊÍÓÔÕÚ',
    'fr (French)':            'abcdefghijklmnopqrstuvwxyzàâæçéèêëîïôœùûüÿABCDEFGHIJKLMNOPQRSTUVWXYZÀÂÆÇÉÈÊËÎÏÔŒÙÛÜŸ«»',
    'it (Italian)':           'abcdefghijklmnopqrstuvwxyzàèéìíîòóùúABCDEFGHIJKLMNOPQRSTUVWXYZÀÈÉÌÍÎÒÓÙÚ',
    'pl (Polish)':            'aąbcćdeęfghijklłmnńoóprsśtuwyzźżAĄBCĆDEĘFGHIJKLŁMNŃOÓPRSŚTUWYZŹŻ',
    'cs (Czech)':             'aábcčdďeéěfghiíjklmnňoópqrřsštťuúůvwxyýzžAÁBCČDĎEÉĚFGHIÍJKLMNŇOÓPQRŘSŠTŤUÚŮVWXYÝZŽ',
    'hu (Hungarian)':         'aábcdeéfghiíjklmnoóöőpqrstuúüűvwxyzAÁBCDEÉFGHIÍJKLMNOÓÖŐPQRSTUÚÜŰVWXYZ',
    'tr (Turkish)':           'abcçdefgğhıijklmnoöprsştuüvyzABCÇDEFGĞHIİJKLMNOÖPRSŞTUÜVYZ',
    'ro (Romanian)':          'aăâbcdefghiîjklmnopqrsștțuvwxyzAĂÂBCDEFGHIÎJKLMNOPQRSȘTȚUVWXYZ',
    'nl (Dutch)':             'abcdefghijklmnopqrstuvwxyzäëïöüáéíóúèàABCDEFGHIJKLMNOPQRSTUVWXYZÄËÏÖÜÁÉÍÓÚÈÀĳĲ',
    'sv (Swedish)':           'abcdefghijklmnopqrstuvwxyzåäöABCDEFGHIJKLMNOPQRSTUVWXYZÅÄÖ',
    'da (Danish)':            'abcdefghijklmnopqrstuvwxyzæøåéABCDEFGHIJKLMNOPQRSTUVWXYZÆØÅÉ',
    'no (Norwegian)':         'abcdefghijklmnopqrstuvwxyzæøåéàóABCDEFGHIJKLMNOPQRSTUVWXYZÆØÅÉÀÓ',
    'fi (Finnish)':           'abcdefghijklmnopqrstuvwxyzäöåšžABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÅŠŽ',
    'ru (Russian)':           'абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ',
    'uk (Ukrainian)':         'абвгґдеєжзиіїйклмнопрстуфхцчшщьюяАБВГҐДЕЄЖЗИІЇЙКЛМНОПРСТУФХЦЧШЩЬЮЯʼ',
    'bg (Bulgarian)':         'абвгдежзийклмнопрстуфхцчшщъьюяАБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЬЮЯ',
    'vi (Vietnamese)':        'aàáảãạăằắẳẵặâầấẩẫậđèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬĐÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴ',
    'el (Greek)':             'αβγδεζηθικλμνξοπρςστυφχψωΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩάέήίόύώϊϋΐΰΆΈΉΊΌΎΏΪΫ',
    'eo (Esperanto)':         'abcĉdefgĝhĥijĵklmnoprsŝtuŭvzABCĈDEFGĜHĤIJĴKLMNOPRSŜTUŬVZ',
}

EXTRAS = {
    'curly quotes':         '‘’“”',
    'low quotes':           '„‚',
    'guillemets':           '«»‹›',
    'dashes':               '–—',
    'ellipsis':             '…',
    'bullet':               '•',
    'arrows':               '←↑→↓',
    'math':                 '×÷±°',
    'currency':             '€£¥¢$',
    'copyright/tm':         '©®™',
    'inverted ?!':          '¿¡',
    'middle dot':           '·',
    'NBSP':                 ' ',
    'apostrophe (uk)':      'ʼ',
}

GREEK_TONOS_PAIRS = [('Α','Ά'),('Ε','Έ'),('Η','Ή'),('Ι','Ί'),('Ο','Ό'),('Υ','Ύ'),('Ω','Ώ')]

def main(font_path):
    sys.stdout.reconfigure(encoding='utf-8')
    f = TTFont(font_path)
    cmap = f.getBestCmap()
    hmtx = f['hmtx']
    glyf = f['glyf']
    head = f['head']
    hhea = f['hhea']
    os2 = f['OS/2']
    codes = set(cmap.keys())

    print('=' * 72)
    print(f'komm64 font inspection: {font_path}')
    print('=' * 72)

    print('\n[1] Font metrics')
    print('-' * 72)
    print(f'  units/em       : {head.unitsPerEm}')
    print(f'  ascent/descent : hhea {hhea.ascent}/{hhea.descent} (gap {hhea.lineGap})')
    print(f'                   typo {os2.sTypoAscender}/{os2.sTypoDescender}')
    print(f'                   win  {os2.usWinAscent}/-{os2.usWinDescent}')
    print(f'  xHeight        : {getattr(os2, "sxHeight", "n/a")}')
    print(f'  capHeight      : {getattr(os2, "sCapHeight", "n/a")}')
    print(f'  total glyphs   : {len(cmap)}')

    print('\n[2] Language coverage (23 langs)')
    print('-' * 72)
    ok = 0
    for lang, chars in LANGS.items():
        missing = sorted(set(c for c in chars if ord(c) not in codes), key=lambda c: ord(c))
        if missing:
            miss_str = ' '.join(f'{c}(U+{ord(c):04X})' for c in missing)
            print(f'  [NG] {lang:25s} {miss_str}')
        else:
            print(f'  [OK] {lang:25s} all glyphs present')
            ok += 1
    print(f'\n  Result: {ok}/{len(LANGS)} languages fully covered')

    print('\n[3] Typography & UI symbols')
    print('-' * 72)
    for name, chars in EXTRAS.items():
        missing = [c for c in chars if ord(c) not in codes]
        if missing:
            miss_str = ' '.join(f'{c}(U+{ord(c):04X})' for c in missing)
            print(f'  [-]  {name:20s} missing: {miss_str}')
        else:
            print(f'  [OK] {name:20s} all present')

    print('\n[4] Centering rule conformance')
    print('-' * 72)
    by_pad = {}
    for cp, gn in cmap.items():
        adv, _ = hmtx[gn]
        g = glyf[gn]
        if not hasattr(g, 'xMin') or g.numberOfContours == 0:
            continue
        pad = adv - (g.xMax - g.xMin)
        by_pad.setdefault(pad, []).append((cp, gn, g.xMin, adv - g.xMax))
    canonical = {pad: Counter((x[2], x[3]) for x in items).most_common(1)[0][0]
                 for pad, items in by_pad.items()}
    for pad in sorted(canonical):
        canon = canonical[pad]
        items = by_pad[pad]
        matching = sum(1 for x in items if (x[2], x[3]) == canon)
        print(f'  pad={pad:4d}u ({pad//64:+d}px) canonical lsb/rsb={canon}  conform: {matching}/{len(items)} ({100*matching//len(items)}%)')

    print('\n[5] Greek tonos caps — base-stays-put rule')
    print('-' * 72)
    def info(ch):
        gn = cmap[ord(ch)]
        adv, _ = hmtx[gn]
        g = glyf[gn]
        return g.xMin, g.xMax, adv
    for base, deriv in GREEK_TONOS_PAIRS:
        if ord(base) not in codes or ord(deriv) not in codes:
            print(f'  {base} -> {deriv}  one or both missing')
            continue
        b = info(base); d = info(deriv)
        if b[:2] == d[:2]:
            status = 'base unchanged'
        elif d[0] < b[0] and d[1] == b[1]:
            status = 'extended LEFT'
        elif d[0] == b[0] and d[1] > b[1]:
            status = 'extended RIGHT (irregular)'
        else:
            status = 'IRREGULAR'
        print(f'  {base} -> {deriv}  base:({b[0]},{b[1]}) deriv:({d[0]},{d[1]})  [{status}]')

    print('\n[6] Advance width distribution')
    print('-' * 72)
    advs = Counter()
    for cp, gn in cmap.items():
        adv, _ = hmtx[gn]
        advs[adv] += 1
    for a, c in advs.most_common():
        print(f'  adv={a:4d}u : {c} glyphs')

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1])
