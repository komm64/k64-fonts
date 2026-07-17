#!/usr/bin/env python3
"""Capture the three 31-language locale specimens used by the README.

The screenshots come from ``web/sample.html`` capture mode, so the README and
live sample share the same locale data, font stacks, spacing, and layout.
"""
from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
WEB_SAMPLE = ROOT / "web" / "sample.html"
OUT_DIR = ROOT / "docs" / "locale-specimens"
CHROME_CANDIDATES = (
    Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
    Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
    Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
)


@dataclass(frozen=True)
class Specimen:
    target: str
    width: int
    height: int

    @property
    def output(self) -> Path:
        return OUT_DIR / f"{self.target}-31-languages.png"


SPECIMENS = (
    Specimen("320x240", 320, 512),
    Specimen("640x240", 640, 1104),
    Specimen("640x480", 640, 568),
)


def find_chrome() -> Path:
    for candidate in CHROME_CANDIDATES:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Chrome or Edge was not found")


def render(chrome: Path, specimen: Specimen, profile: Path) -> None:
    specimen.output.parent.mkdir(parents=True, exist_ok=True)
    url = f"{WEB_SAMPLE.resolve().as_uri()}?specimen={specimen.target}"
    result = subprocess.run(
        [
            str(chrome),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--allow-file-access-from-files",
            "--run-all-compositor-stages-before-draw",
            "--force-color-profile=srgb",
            "--force-device-scale-factor=1",
            "--virtual-time-budget=5000",
            f"--user-data-dir={profile}",
            f"--window-size={specimen.width},{specimen.height}",
            f"--screenshot={specimen.output.resolve()}",
            url,
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=120,
    )
    if result.returncode != 0 or not specimen.output.exists():
        raise RuntimeError(
            f"Failed to capture {specimen.target}:\n{result.stdout}\n{result.stderr}"
        )

    with Image.open(specimen.output) as image:
        if image.size != (specimen.width, specimen.height):
            raise ValueError(
                f"Unexpected {specimen.target} size: {image.size}; "
                f"expected {(specimen.width, specimen.height)}"
            )
    print(f"wrote {specimen.output.relative_to(ROOT)} ({specimen.width}x{specimen.height})")


def main() -> int:
    chrome = find_chrome()
    with tempfile.TemporaryDirectory(prefix="k64-locale-specimens-") as temp_dir:
        profile = Path(temp_dir) / "chrome-profile"
        for specimen in SPECIMENS:
            render(chrome, specimen, profile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
