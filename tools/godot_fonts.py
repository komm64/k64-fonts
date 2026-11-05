#!/usr/bin/env python3
"""Godot font stacks from k64-locale.json, and a sync into a game project.

    python tools/godot_fonts.py stacks
        Writes game/<target>/k64-<target>-<stack>.tres for every target with
        `game` files and every stack in k64-locale.json.

    python tools/godot_fonts.py sync <target> <dest_dir>
        Copies one target's game fonts, its stack .tres files and the licenses
        they need into <dest_dir> (a folder inside a Godot project), with
        .import files that keep the fonts dot-sharp.

A stack .tres is a FontVariation whose base font is the stack's first role
(K64F) and whose fallbacks are the other roles in stack order, so a game can
use it directly:

    theme.default_font = load("res://<dest>/k64-640x240-ja.tres")

The .tres refer to the fonts by path relative to the .tres itself, and the
written .import files carry only the importer and its settings. Nothing in
either depends on where the folder sits in the host project, and no uid is
written, so a copy can live anywhere and be re-synced.

<dest_dir> is owned by the sync: files in it that the sync did not write are
removed (with their .import files).
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "k64-locale.json"

# Import settings for dot-sharp pixel fonts.
# Dynamic fonts: no antialiasing / hinting / subpixel positioning, no system
# fallback, so every glyph comes from the k64 chain.
# BMFont: no scaling of the fixed-size strike (load_bitmap_font behaviour).
_IMPORT = {
    ".ttf": ("font_data_dynamic", "FontFile", {
        "antialiasing": 0,
        "generate_mipmaps": False,
        "disable_embedded_bitmaps": True,
        "multichannel_signed_distance_field": False,
        "allow_system_fallback": False,
        "force_autohinter": False,
        "hinting": 0,
        "subpixel_positioning": 0,
        "keep_rounding_remainders": True,
        "oversampling": 0.0,
    }),
    ".fnt": ("font_data_bmfont", "FontFile", {
        "compress": True,
        "scaling_mode": 0,
    }),
}

# License text per role. K64F is the only role under CC-BY-NC.
_LICENSE = {
    "k64f": "CC-BY-NC-4.0.txt",
    "j": "PDS-JF-Dot.txt",
    "ck": "OFL-1.1.txt",
    "thai": "OFL-1.1.txt",
    "arabic": "OFL-1.1.txt",
}


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _targets(m: dict) -> dict:
    return {name: t for name, t in m["targets"].items() if t.get("game")}


def stack_name(target: str, stack: str) -> str:
    return f"k64-{target}-{stack}.tres"


def stack_tres(game: dict, roles: list[str]) -> str:
    """FontVariation text: base = roles[0], fallbacks = roles[1:]."""
    lines = [f'[gd_resource type="FontVariation" load_steps={len(roles) + 1} format=3]', ""]
    for i, role in enumerate(roles, 1):
        lines.append(f'[ext_resource type="FontFile" path="{Path(game[role]).name}" id="{i}_{role}"]')
    lines += ["", "[resource]", f'base_font = ExtResource("1_{roles[0]}")']
    fb = ", ".join(f'ExtResource("{i}_{r}")' for i, r in enumerate(roles[1:], 2))
    lines.append(f"fallbacks = Array[Font]([{fb}])")
    return "\n".join(lines) + "\n"


def _import_text(path: Path) -> str | None:
    spec = _IMPORT.get(path.suffix.lower())
    if spec is None:
        return None
    importer, rtype, params = spec
    out = ["[remap]", "", f'importer="{importer}"', f'type="{rtype}"', "", "[params]", ""]
    for k, v in params.items():
        out.append(f"{k}={str(v).lower() if isinstance(v, bool) else v}")
    return "\n".join(out) + "\n"


def cmd_stacks() -> int:
    m = _manifest()
    for target, t in _targets(m).items():
        for stack, roles in m["stacks"].items():
            out = ROOT / Path(t["game"][roles[0]]).parent / stack_name(target, stack)
            out.write_text(stack_tres(t["game"], roles), encoding="utf-8", newline="\n")
            print(f"wrote {out.relative_to(ROOT).as_posix()}")
    return 0


def _role_files(rel: str) -> list[Path]:
    """The font file plus its BMFont page images."""
    src = ROOT / rel
    files = [src]
    if src.suffix.lower() == ".fnt":
        files += sorted(src.parent.glob(src.stem + "_*.png"))
    return files


def cmd_sync(target: str, dest: Path) -> int:
    m = _manifest()
    t = _targets(m).get(target)
    if t is None:
        print(f"unknown target {target!r}; have {sorted(_targets(m))}", file=sys.stderr)
        return 2
    if not (dest.parent.exists()):
        print(f"parent of {dest} does not exist", file=sys.stderr)
        return 2
    dest.mkdir(exist_ok=True)
    written: set[str] = set()

    def put(name: str, data: bytes) -> None:
        (dest / name).write_bytes(data)
        written.add(name)

    for role, rel in t["game"].items():
        for f in _role_files(rel):
            put(f.name, f.read_bytes())
            imp = _import_text(f)
            if imp is not None:
                put(f.name + ".import", imp.encode("utf-8"))
    for stack, roles in m["stacks"].items():
        put(stack_name(target, stack), stack_tres(t["game"], roles).encode("utf-8"))
    licenses = sorted({_LICENSE[r] for r in t["game"]})
    for lic in licenses:
        put(lic, (ROOT / "LICENSE" / lic).read_bytes())
    notice = [f"k64-fonts {target} game fonts, synced by tools/godot_fonts.py.",
              "https://github.com/komm64/k64-fonts", "", "File -> license:"]
    for role, rel in t["game"].items():
        notice.append(f"  {Path(rel).name} -> {_LICENSE[role]}")
    put("NOTICE.txt", ("\n".join(notice) + "\n").encode("utf-8"))

    for f in dest.iterdir():
        if f.is_file() and f.name not in written and not (
                f.name.endswith(".import") and f.name[:-7] in written):
            f.unlink()
            print(f"removed {f.name}")
    print(f"synced {target} -> {dest} ({len(written)} files)")
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["stacks"]:
        return cmd_stacks()
    if argv[:1] == ["sync"] and len(argv) == 3:
        return cmd_sync(argv[1], Path(argv[2]))
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
