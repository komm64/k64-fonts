"""Structure-preserving 16->12 reduction for the 12px CK face (used for Hangul).

The default CK reduction (bake_unifont_12px_drop.py, drop-bridge) removes the
lowest-ink line of every 4-line block. That keeps sweeps smooth but can close the
counters of dense Hangul syllables. This "joint" reduction instead:

1. ranks every way of removing 4 of 16 rows (or columns) that keeps the removals
   spread out (within one line of the uniform 4->3 rate) and never removes two
   adjacent lines, by a local stroke cost: a 1px stroke that would vanish, two
   strokes made to touch, a merge that thickens a stroke. Each removed line is
   dropped or OR-merged into the cheaper neighbour.
2. tries the best TOP row sets with the best TOP column sets, plus the
   drop-bridge result, and keeps the lowest score() among those that close no
   more counters (overall, and roomy ones) than drop-bridge does.

score(), lower is better (weights from komm64's review, 2026-11-04):
  a roomy counter (>=2px in both directions in the 16px source) closing   10
  a tight counter (1px deep) closing                                         1
  a counter appearing                                                        3
  an ink part appearing or disappearing                                      3
  a stroke a scan line no longer crosses (lost, or merged into another)      1
  two horizontal strokes touching as one 2-dot bar (scanlines split them) 0.2
  an L-shaped corner (a doubled diagonal step) beyond the source's share   0.5
"""

from __future__ import annotations

import itertools
from functools import lru_cache

import numpy as np
from scipy import ndimage

LOST, TOUCH, THICKEN = 3.0, 2.0, 1.0
TOP = 12
ROOMY_LOST, TIGHT_LOST, HOLE_GAINED, PART, STROKE, THICK_BAR, JAG = 10.0, 1.0, 3.0, 3.0, 1.0, 0.2, 0.5
EIGHT = np.ones((3, 3), dtype=int)

HANGUL_RANGES = ((0x1100, 0x11FF), (0x3130, 0x318F), (0xA960, 0xA97F), (0xAC00, 0xD7A3), (0xD7B0, 0xD7FF))


def is_hangul(codepoint: int) -> bool:
    return any(lo <= codepoint <= hi for lo, hi in HANGUL_RANGES)


# ---------------------------------------------------------------- score


def counters(cell: np.ndarray) -> tuple[int, int]:
    """(roomy, tight) enclosed background regions; roomy = at least 2px tall and wide."""
    labels, _ = ndimage.label(np.pad(cell, 1) == 0)  # 4-connected background
    outside = labels[0, 0]
    roomy = tight = 0
    for index, region in enumerate(ndimage.find_objects(labels), start=1):
        if index == outside or region is None:
            continue
        if region[0].stop - region[0].start >= 2 and region[1].stop - region[1].start >= 2:
            roomy += 1
        else:
            tight += 1
    return roomy, tight


def strokes_down(line: np.ndarray) -> tuple[int, int]:
    """Horizontal strokes a vertical scan line crosses, with 2-dot runs counted as two
    touching strokes; also returns how many such runs there are."""
    padded = np.concatenate(([0], line, [0]))
    lengths = np.flatnonzero(np.diff(padded) == -1) - np.flatnonzero(np.diff(padded) == 1)
    thick = int(np.count_nonzero(lengths == 2))
    return int(len(lengths)) + thick, thick


def strokes_across(line: np.ndarray) -> int:
    return int(np.count_nonzero(np.diff(np.concatenate(([0], line, [0]))) == 1))


def jags(cell: np.ndarray) -> int:
    if cell.shape[0] < 2 or cell.shape[1] < 2:
        return 0
    windows = cell[:-1, :-1].astype(int) + cell[1:, :-1] + cell[:-1, 1:] + cell[1:, 1:]
    return int(np.count_nonzero(windows == 3))


def features(cell: np.ndarray, size: int = 12):
    _, parts = ndimage.label(cell, structure=EIGHT)
    h, w = cell.shape
    # Scan lines at the same relative positions whatever the glyph size.
    down = [strokes_down(cell[:, min(w - 1, int((j + 0.5) * w / size))]) for j in range(size)]
    across = [strokes_across(cell[min(h - 1, int((i + 0.5) * h / size)), :]) for i in range(size)]
    return counters(cell), parts, down, across, jags(cell)


def score(result: np.ndarray, source_features) -> float:
    (roomy, tight), parts, down, across, jag = features(result)
    (s_roomy, s_tight), s_parts, s_down, s_across, s_jag = source_features
    # Which counters closed is not tracked; assume the tight ones closed first.
    lost = max(0, (s_roomy + s_tight) - (roomy + tight))
    tight_lost = min(lost, s_tight)
    cost = TIGHT_LOST * tight_lost + ROOMY_LOST * (lost - tight_lost)
    cost += HOLE_GAINED * max(0, (roomy + tight) - (s_roomy + s_tight))
    cost += PART * abs(parts - s_parts)
    cost += sum(STROKE * abs(n - s_n) + THICK_BAR * thick for (n, thick), (s_n, _) in zip(down, s_down))
    cost += sum(STROKE * abs(n - s_n) for n, s_n in zip(across, s_across))
    # The source is 16px: compare with its corner count scaled to the 12px area.
    cost += JAG * max(0.0, jag - s_jag * 9 / 16)
    return cost


# ---------------------------------------------------------------- reduction


def line_option(m: np.ndarray, i: int) -> tuple[float, str]:
    """Cheapest way to remove line i of m: 'drop', or merge 'up' / 'down' into a neighbour."""
    n = m.shape[0]
    zero = np.zeros_like(m[0])
    row = m[i]
    a = m[i - 1] if i > 0 else zero
    b = m[i + 1] if i < n - 1 else zero
    a2 = m[i - 2] if i > 1 else zero
    b2 = m[i + 2] if i < n - 2 else zero
    options = [(LOST * int((row & ~a & ~b & 1).sum()) + TOUCH * int((a & b & ~row & 1).sum()), "drop")]
    if i > 0:
        options.append((TOUCH * int(((a | row) & b & ~row & 1).sum()) + THICKEN * int((row & ~a & a2 & 1).sum()) + 0.1, "up"))
    if i < n - 1:
        options.append((TOUCH * int(((b | row) & a & ~row & 1).sum()) + THICKEN * int((row & ~b & b2 & 1).sum()) + 0.1, "down"))
    return min(options)


@lru_cache(maxsize=None)
def valid_removals(n: int, remove: int) -> tuple[tuple[int, ...], ...]:
    out = []
    for combo in itertools.combinations(range(n), remove):
        if any(b - a < 2 for a, b in zip(combo, combo[1:])):
            continue
        k, ok = 0, True
        for i in range(n):
            k += i in combo
            if abs(k - (i + 1) * remove / n) > 1.0 + 1e-9:
                ok = False
                break
        if ok:
            out.append(combo)
    return tuple(out)


def removal_sets(m: np.ndarray, remove: int, top: int):
    if remove <= 0:
        return [((), {})]
    costs = [line_option(m, i) for i in range(m.shape[0])]
    ranked = sorted((sum(costs[i][0] for i in combo), combo) for combo in valid_removals(m.shape[0], remove))
    return [(combo, {i: costs[i][1] for i in combo}) for _, combo in ranked[:top]]


def apply_rows(m: np.ndarray, ops: dict[int, str]) -> np.ndarray:
    out = m.copy()
    for i, op in ops.items():
        if op == "up":
            out[i - 1] |= m[i]
        elif op == "down":
            out[i + 1] |= m[i]
    return out[[i for i in range(m.shape[0]) if i not in ops]]


def reduce(src: np.ndarray, target_w: int, baseline: np.ndarray, target_h: int = 12) -> np.ndarray:
    """Reduce a 16-row source glyph to target_h x target_w; baseline (the drop-bridge
    result) is a candidate and sets how many counters may close at most."""
    src = src.astype(np.uint8)
    h, w = src.shape
    feats = features(src)
    roomy_floor = min(counters(baseline)[0], feats[0][0])
    total_floor = min(sum(counters(baseline)), sum(feats[0]))
    best = (score(baseline, feats), baseline)
    col_sets = removal_sets(src.T, w - target_w, TOP)
    for _, row_ops in removal_sets(src, h - target_h, TOP):
        rows = apply_rows(src, row_ops)
        for col_combo, _ in col_sets:
            # Merge directions re-decided on the row-reduced glyph.
            col_ops = {i: line_option(rows.T, i)[1] for i in col_combo}
            result = apply_rows(rows.T, col_ops).T
            roomy, tight = counters(result)
            if roomy < roomy_floor or roomy + tight < total_floor:
                continue
            s = score(result, feats)
            if s < best[0]:
                best = (s, result)
    return best[1].astype(np.uint8)
