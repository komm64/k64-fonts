#!/usr/bin/env python3
"""Apply deterministic native TrueType hints to final K64F web fonts."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from fontTools.ttLib import TTFont, woff2


def _ttfautohint_command() -> list[str]:
    override = os.environ.get("TTFAUTOHINT")
    if override:
        return [override]

    executable = shutil.which("ttfautohint")
    if executable:
        return [executable]

    if importlib.util.find_spec("ttfautohint") is not None:
        return [sys.executable, "-m", "ttfautohint"]

    raise RuntimeError(
        "ttfautohint is required for K64F web output; "
        "install ttfautohint-py==0.6.1 or set TTFAUTOHINT"
    )


def save_hinted_woff2(
    font: TTFont,
    output_path: Path,
    *,
    transform_tables: bool = True,
) -> None:
    """Hint a final-size K64F font, then write it as WOFF2.

    The K64F outlines already sit on the target pixel grid. ttfautohint's
    native TrueType programs keep that grid stable on rasterizers that would
    otherwise apply FreeType's runtime auto-hinter to detached marks.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="k64f-web-hint-") as temp_dir:
        temp_dir = Path(temp_dir)
        unhinted_path = temp_dir / "unhinted.ttf"
        hinted_path = temp_dir / "hinted.ttf"

        # Keep generated WOFF2 bytes reproducible even when the input TTFont
        # was freshly saved by another bake step.
        font["head"].modified = font["head"].created
        font.recalcTimestamp = False
        font.save(unhinted_path)
        subprocess.run(
            [
                *_ttfautohint_command(),
                "--no-info",
                "--increase-x-height=0",
                str(unhinted_path),
                str(hinted_path),
            ],
            check=True,
        )

        hinted = TTFont(hinted_path, recalcTimestamp=False)
        hinted["head"].modified = hinted["head"].created
        hinted.recalcTimestamp = False
        if transform_tables:
            hinted.flavor = "woff2"
            hinted.save(output_path)
        else:
            normalized_path = temp_dir / "hinted-normalized.ttf"
            hinted.save(normalized_path)
            woff2.compress(
                str(normalized_path),
                str(output_path),
                transform_tables=set(),
            )
