# K64F social specimens

Pixel-exact language specimens intended for readability feedback on social
media. Generate them from the repository root with:

```powershell
python tools/render_social_specimens.py
```

## Current files

- `k64f-320x240-after-descender-fix.png`: native 320x240 target using the
  12px-role K64F BMFont from `k64-locale.json`; fourteen languages selected for
  locale priority and glyph diversity.
- `k64f-640x480-after-descender-fix.png`: native 640x480 target using the 16px
  K64F BMFont; all 23 unique K64F languages from `tools/render_pangrams.py`.
- `*-social-*.png`: 1280x960 nearest-neighbor copies for upload. These preserve
  the original dot grid while avoiding arbitrary non-integer scaling by a
  social platform.

The equivalent untagged PNG files are the pre-autohint-fix references, and the
`after-autohint-fix` files preserve the intermediate version whose 320x240
glyphs still clipped descenders. Keep both sets for before/after comparison;
the generator deliberately writes only the current tagged filenames above.

The CJK, Japanese, Korean, Thai, and Arabic k64-locale targets are intentionally
excluded because their glyphs come from the `ck`, `j`, `thai`, and `arabic`
fallback roles rather than K64F.
