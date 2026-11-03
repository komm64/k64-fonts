"""Check every target face against the cross-script alignment rules (tools/k64_alignment.py).

    python tools/check_alignment.py [--target 640x240] [--kind web]

Exits 1 when any rule fails.
"""

from __future__ import annotations

import argparse
import sys

from k64_alignment import check, load_faces


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", action="append")
    parser.add_argument("--kind", choices=("web", "game"), action="append")
    args = parser.parse_args()
    faces = load_faces(args.target, tuple(args.kind or ("web", "game")))
    findings = check(faces)
    for finding in findings:
        face = finding.face
        print(f"{face.target:8} {face.kind:4} {face.role:6} {finding.rule:15} {finding.message}  ({face.path.name})")
    print(f"{len(findings)} finding(s) in {len(faces)} face(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
