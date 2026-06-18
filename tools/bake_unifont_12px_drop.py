#!/usr/bin/env python3
"""Bake Unifont 16px into a 12px drop-balanced pixel-outline TTF.

This is the generation counterpart to the preview tool's
"Drop low-ink balanced ties" mode.  It rasterizes the 16px source glyphs, drops
rows/columns globally per glyph to reach the 12px rhythm, and emits rectangular
pixel contours.
"""
from __future__ import annotations

import argparse
from functools import lru_cache
import io
import math
import sys
from pathlib import Path

import numpy as np
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import Glyph as TtGlyph
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "src" / "unifont-16px.ttf"
DEFAULT_OUTPUT = ROOT / "tmp-k64-ck-unifont-12px-drop-balanced.ttf"
DEFAULT_PREVIEW = ROOT / "tmp-k64-ck-unifont-12px-drop-balanced-preview.png"

SRC_SIZE = 16
DST_SIZE = 12
PX = 100
ASC = 11
UPM = 1200
PIXEL_INSET = 1
DEFAULT_TIE_BIAS = 0.05

BLOCK_SRC = 4
BLOCK_DST = 3

SAMPLE_LINES = [
    "ABC abc 0123 Il1 O0 rn/m",
    "日本語かなカナ 漢字 東雲 龍 鬱",
    "简体中文 繁體中文 測試",
    "한글 테스트 가나다",
    "Ελληνικά Кириллица",
    "←↑→↓ ×÷±° €£¥ ©®™",
]


def rasterize(pil_font: ImageFont.FreeTypeFont, char: str, src_h: int = SRC_SIZE) -> tuple[np.ndarray, int]:
    try:
        bbox = pil_font.getbbox(char)
        advance = int(round(pil_font.getlength(char)))
    except Exception:
        return np.zeros((src_h, 1), dtype=np.uint8), 1

    if bbox is None:
        width = max(advance, 1)
        return np.zeros((src_h, width), dtype=np.uint8), width

    width = max(advance, bbox[2], 1)
    cell = np.zeros((src_h, width), dtype=np.uint8)
    try:
        mask = pil_font.getmask(char, mode="L")
        mw, mh = mask.size
        if mw and mh:
            arr = np.array(mask, dtype=np.uint8).reshape(mh, mw)
            arr = (arr > 127).astype(np.uint8)
            x0 = max(0, bbox[0])
            y0 = max(0, bbox[1])
            x1 = min(width, x0 + mw)
            y1 = min(src_h, y0 + mh)
            if x1 > x0 and y1 > y0:
                cell[y0:y1, x0:x1] = arr[: y1 - y0, : x1 - x0]
    except Exception:
        pass
    return cell, width


def target_width(src_width: int) -> int:
    return max(1, int(round(src_width * DST_SIZE / SRC_SIZE)))


def normalize_width_np(bitmap: np.ndarray, target_w: int) -> np.ndarray:
    h, w = bitmap.shape
    if w == target_w:
        return bitmap.copy()
    out = np.zeros((h, target_w), dtype=np.uint8)
    if w <= 0:
        return out
    for x in range(target_w):
        sx = min(w - 1, int(math.floor(x * w / target_w)))
        out[:, x] = bitmap[:, sx]
    return out


def connected_components_8(bitmap: np.ndarray) -> int:
    h, w = bitmap.shape
    seen = np.zeros((h, w), dtype=np.uint8)
    count = 0
    for y in range(h):
        for x in range(w):
            if not bitmap[y, x] or seen[y, x]:
                continue
            count += 1
            stack = [(x, y)]
            seen[y, x] = 1
            while stack:
                cx, cy = stack.pop()
                for yy in range(cy - 1, cy + 2):
                    for xx in range(cx - 1, cx + 2):
                        if xx == cx and yy == cy:
                            continue
                        if xx < 0 or xx >= w or yy < 0 or yy >= h:
                            continue
                        if bitmap[yy, xx] and not seen[yy, xx]:
                            seen[yy, xx] = 1
                            stack.append((xx, yy))
    return count


@lru_cache(maxsize=1)
def block_candidate_data() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    bits = np.zeros((1 << (BLOCK_DST * BLOCK_DST), BLOCK_DST * BLOCK_DST), dtype=np.uint8)
    expanded = np.zeros((1 << (BLOCK_DST * BLOCK_DST), BLOCK_SRC * BLOCK_SRC), dtype=np.float32)
    inks = np.zeros((1 << (BLOCK_DST * BLOCK_DST),), dtype=np.float32)
    components = np.zeros((1 << (BLOCK_DST * BLOCK_DST),), dtype=np.float32)
    for pattern in range(1 << (BLOCK_DST * BLOCK_DST)):
        candidate = np.zeros((BLOCK_DST, BLOCK_DST), dtype=np.uint8)
        for y in range(BLOCK_DST):
            for x in range(BLOCK_DST):
                bit = (pattern >> (y * BLOCK_DST + x)) & 1
                candidate[y, x] = bit
                bits[pattern, y * BLOCK_DST + x] = bit
        inks[pattern] = float(candidate.sum())
        components[pattern] = float(connected_components_8(candidate))
        for sy in range(BLOCK_SRC):
            sy0, sy1 = sy, sy + 1
            for sx in range(BLOCK_SRC):
                sx0, sx1 = sx, sx + 1
                coverage = 0.0
                for dy in range(BLOCK_DST):
                    dy0 = dy * BLOCK_SRC / BLOCK_DST
                    dy1 = (dy + 1) * BLOCK_SRC / BLOCK_DST
                    oy = max(0.0, min(sy1, dy1) - max(sy0, dy0))
                    if oy <= 0:
                        continue
                    for dx in range(BLOCK_DST):
                        if not candidate[dy, dx]:
                            continue
                        dx0 = dx * BLOCK_SRC / BLOCK_DST
                        dx1 = (dx + 1) * BLOCK_SRC / BLOCK_DST
                        ox = max(0.0, min(sx1, dx1) - max(sx0, dx0))
                        coverage += ox * oy
                expanded[pattern, sy * BLOCK_SRC + sx] = coverage
    return bits, expanded, inks, components


def block_pattern(block: np.ndarray) -> int:
    pattern = 0
    for y in range(BLOCK_SRC):
        for x in range(BLOCK_SRC):
            if block[y, x]:
                pattern |= 1 << (y * BLOCK_SRC + x)
    return pattern


def pattern3_to_bitmap(pattern: int) -> np.ndarray:
    out = np.zeros((BLOCK_DST, BLOCK_DST), dtype=np.uint8)
    for y in range(BLOCK_DST):
        for x in range(BLOCK_DST):
            out[y, x] = (pattern >> (y * BLOCK_DST + x)) & 1
    return out


def pattern3_from_points(points: list[tuple[int, int]]) -> int:
    pattern = 0
    for x, y in points:
        pattern |= 1 << (y * BLOCK_DST + x)
    return pattern


@lru_cache(maxsize=1)
def axis_merge_maps_4_to_3() -> tuple[tuple[int, int, tuple[int, int, int, int]], ...]:
    maps: list[tuple[int, int, tuple[int, int, int, int]]] = []
    for drop in range(BLOCK_SRC):
        for target in (drop - 1, drop + 1):
            if target < 0 or target >= BLOCK_SRC:
                continue
            keep = [i for i in range(BLOCK_SRC) if i != drop]
            index = {src: dst for dst, src in enumerate(keep)}
            mapped = []
            for src in range(BLOCK_SRC):
                mapped.append(index[target] if src == drop else index[src])
            maps.append((drop, target, tuple(mapped)))
    return tuple(maps)


@lru_cache(maxsize=1 << (BLOCK_SRC * BLOCK_SRC))
def block_merge_candidates(pattern: int) -> tuple[tuple[int, tuple[int, ...], tuple[int, ...]], ...]:
    source_pixels = [
        (x, y)
        for y in range(BLOCK_SRC)
        for x in range(BLOCK_SRC)
        if (pattern >> (y * BLOCK_SRC + x)) & 1
    ]
    candidates: dict[int, tuple[tuple[int, ...], tuple[int, ...]]] = {}
    for _drop_x, _target_x, x_map in axis_merge_maps_4_to_3():
        for _drop_y, _target_y, y_map in axis_merge_maps_4_to_3():
            out_pattern = 0
            for x, y in source_pixels:
                ox = x_map[x]
                oy = y_map[y]
                out_pattern |= 1 << (oy * BLOCK_DST + ox)
            candidates.setdefault(out_pattern, (x_map, y_map))
    return tuple((out_pattern, x_map, y_map) for out_pattern, (x_map, y_map) in candidates.items())


MAIN_DIAG_4 = sum(1 << (i * BLOCK_SRC + i) for i in range(BLOCK_SRC))
ANTI_DIAG_4 = sum(1 << (i * BLOCK_SRC + (BLOCK_SRC - 1 - i)) for i in range(BLOCK_SRC))
MAIN_DIAG_3 = pattern3_from_points([(0, 0), (1, 1), (2, 2)])
ANTI_DIAG_3 = pattern3_from_points([(2, 0), (1, 1), (0, 2)])


@lru_cache(maxsize=1 << (BLOCK_SRC * BLOCK_SRC))
def lut_4x4_to_3x3_pattern(pattern: int) -> int:
    if pattern == 0:
        return 0
    if pattern == MAIN_DIAG_4:
        return MAIN_DIAG_3
    if pattern == ANTI_DIAG_4:
        return ANTI_DIAG_3

    source = np.array([(pattern >> i) & 1 for i in range(BLOCK_SRC * BLOCK_SRC)], dtype=np.float32)
    source_2d = source.reshape(BLOCK_SRC, BLOCK_SRC).astype(np.uint8)
    source_ink = float(source.sum())
    source_components = float(connected_components_8(source_2d))
    _bits, expanded, inks, components = block_candidate_data()
    density_target = source_ink * (BLOCK_DST * BLOCK_DST) / (BLOCK_SRC * BLOCK_SRC)
    thin_target = source_ink * BLOCK_DST / BLOCK_SRC
    target_ink = max(density_target, thin_target if source_ink <= 6 else density_target)

    source_points = [
        (x, y)
        for y in range(BLOCK_SRC)
        for x in range(BLOCK_SRC)
        if (pattern >> (y * BLOCK_SRC + x)) & 1
    ]
    best_pattern = 0
    best_loss: tuple[float, float, float, int] | None = None
    for out_pattern, x_map, y_map in block_merge_candidates(pattern):
        fn = float((source * (1.0 - expanded[out_pattern])).sum())
        fp = float(((1.0 - source) * expanded[out_pattern]).sum())
        ink_loss = abs(float(inks[out_pattern]) - target_ink)
        component_loss = abs(float(components[out_pattern]) - source_components)

        movement = 0.0
        for x, y in source_points:
            sx = (x + 0.5) / BLOCK_SRC
            sy = (y + 0.5) / BLOCK_SRC
            ox = (x_map[x] + 0.5) / BLOCK_DST
            oy = (y_map[y] + 0.5) / BLOCK_DST
            movement += (sx - ox) * (sx - ox) + (sy - oy) * (sy - oy)

        loss = fn * 1.8 + fp * 1.0 + ink_loss * 0.35 + component_loss * 0.45 + movement * 2.2
        key = (loss, movement, float(inks[out_pattern]), out_pattern)
        if best_loss is None or key < best_loss:
            best_loss = key
            best_pattern = out_pattern

    return best_pattern


def block_lut_4x4_to_3x3(bitmap: np.ndarray, target_w: int) -> np.ndarray:
    h, w = bitmap.shape
    blocks_x = max(1, int(math.ceil(w / BLOCK_SRC)))
    out = np.zeros((DST_SIZE, blocks_x * BLOCK_DST), dtype=np.uint8)
    for by in range(SRC_SIZE // BLOCK_SRC):
        for bx in range(blocks_x):
            block = np.zeros((BLOCK_SRC, BLOCK_SRC), dtype=np.uint8)
            y0 = by * BLOCK_SRC
            x0 = bx * BLOCK_SRC
            src = bitmap[y0 : min(y0 + BLOCK_SRC, h), x0 : min(x0 + BLOCK_SRC, w)]
            block[: src.shape[0], : src.shape[1]] = src
            out[
                by * BLOCK_DST : by * BLOCK_DST + BLOCK_DST,
                bx * BLOCK_DST : bx * BLOCK_DST + BLOCK_DST,
            ] = pattern3_to_bitmap(lut_4x4_to_3x3_pattern(block_pattern(block)))
    return normalize_width_np(out, target_w).astype(np.uint8)


def choose_drop_line(bitmap: np.ndarray, block_start: int, count: int, tie_bias: float) -> int:
    best_x = block_start
    best_score = None
    center = (count - 1) / 2
    for i in range(count):
        x = block_start + i
        ink = int(bitmap[:, x].sum())
        score = ink + abs(i - center) * tie_bias
        if best_score is None or score < best_score:
            best_score = score
            best_x = x
    return best_x


def choose_drop_specs(bitmap: np.ndarray, target_w: int, tie_bias: float) -> list[tuple[int, int, int]]:
    _, w = bitmap.shape
    remove_count = w - target_w
    specs: list[tuple[int, int, int]] = []
    for r in range(remove_count):
        start = round(r * w / remove_count)
        end = round((r + 1) * w / remove_count)
        block_start = max(0, min(w - 1, start))
        count = max(1, min(w, end) - block_start)
        drop_x = choose_drop_line(bitmap, block_start, count, tie_bias)
        specs.append((drop_x, block_start, count))
    return specs


def candidate_merge_targets(drop_x: int, block_start: int, count: int, width: int) -> list[int]:
    targets: list[int] = []
    if drop_x - 1 >= block_start:
        targets.append(drop_x - 1)
    if drop_x + 1 < block_start + count and drop_x + 1 < width:
        targets.append(drop_x + 1)
    return targets


def local_merge_score(
    bitmap: np.ndarray,
    drop_x: int,
    target_x: int,
    block_start: int,
    count: int,
    *,
    diagonal_aware: bool,
) -> tuple[int, float]:
    direction = -1 if target_x < drop_x else 1
    outer_x = target_x + direction
    opposite_x = drop_x - direction
    added = 0
    bridge = 0
    diagonal_collapse = 0
    diagonal_preserve = 0
    for y in range(bitmap.shape[0]):
        if not bitmap[y, drop_x] or bitmap[y, target_x]:
            continue
        added += 1
        if block_start <= outer_x < block_start + count and bitmap[y, outer_x]:
            bridge += 1
        if diagonal_aware:
            source_vertical = (
                (y > 0 and bitmap[y - 1, drop_x])
                or (y + 1 < bitmap.shape[0] and bitmap[y + 1, drop_x])
            )
            target_diagonal = (
                (y > 0 and bitmap[y - 1, target_x])
                or (y + 1 < bitmap.shape[0] and bitmap[y + 1, target_x])
            )
            opposite_diagonal = (
                block_start <= opposite_x < block_start + count
                and (
                    (y > 0 and bitmap[y - 1, opposite_x])
                    or (y + 1 < bitmap.shape[0] and bitmap[y + 1, opposite_x])
                )
            )
            if not source_vertical and target_diagonal:
                diagonal_collapse += 1
            if not source_vertical and opposite_diagonal:
                diagonal_preserve += 1
    shape_penalty = bridge + diagonal_collapse * 2 - diagonal_preserve * 0.25
    return added, shape_penalty


def choose_merge_cost_specs(
    bitmap: np.ndarray,
    target_w: int,
    tie_bias: float,
    *,
    diagonal_aware: bool = False,
) -> list[tuple[int, int, int, int | None]]:
    _, w = bitmap.shape
    remove_count = w - target_w
    specs: list[tuple[int, int, int, int | None]] = []
    for r in range(remove_count):
        start = round(r * w / remove_count)
        end = round((r + 1) * w / remove_count)
        block_start = max(0, min(w - 1, start))
        count = max(1, min(w, end) - block_start)
        center = block_start + (count - 1) / 2
        best: tuple[float, float, float, float, int, int | None] | None = None
        for i in range(count):
            drop_x = block_start + i
            targets = candidate_merge_targets(drop_x, block_start, count, w)
            if not targets:
                ink = int(bitmap[:, drop_x].sum())
                key = (float(ink), 0.0, abs(drop_x - center), 0.0, drop_x, None)
                if best is None or key < best:
                    best = key
                continue
            for target_x in targets:
                added, shape_penalty = local_merge_score(
                    bitmap,
                    drop_x,
                    target_x,
                    block_start,
                    count,
                    diagonal_aware=diagonal_aware,
                )
                key = (
                    float(added),
                    shape_penalty,
                    abs(drop_x - center) * tie_bias,
                    abs(target_x - center) * tie_bias,
                    drop_x,
                    target_x,
                )
                if best is None or key < best:
                    best = key
        if best is None:
            specs.append((block_start, block_start, count, None))
        else:
            specs.append((best[4], block_start, count, best[5]))
    return specs


def choose_similar_pair_specs(
    bitmap: np.ndarray,
    target_w: int,
    tie_bias: float,
) -> list[tuple[int, int, int, int | None]]:
    _, w = bitmap.shape
    remove_count = w - target_w
    specs: list[tuple[int, int, int, int | None]] = []
    for r in range(remove_count):
        start = round(r * w / remove_count)
        end = round((r + 1) * w / remove_count)
        block_start = max(0, min(w - 1, start))
        count = max(1, min(w, end) - block_start)
        center = block_start + (count - 1) / 2
        best: tuple[float, float, float, float, int, int | None] | None = None
        if count <= 1:
            specs.append((block_start, block_start, count, None))
            continue

        for i in range(count - 1):
            left = block_start + i
            right = left + 1
            xor = int(np.count_nonzero(bitmap[:, left] != bitmap[:, right]))
            pair_center = (left + right) / 2
            for drop_x, target_x in ((left, right), (right, left)):
                added, shape_penalty = local_merge_score(
                    bitmap,
                    drop_x,
                    target_x,
                    block_start,
                    count,
                    diagonal_aware=False,
                )
                key = (
                    float(xor),
                    float(added),
                    shape_penalty,
                    abs(pair_center - center) * tie_bias + abs(target_x - center) * tie_bias,
                    drop_x,
                    target_x,
                )
                if best is None or key < best:
                    best = key

        if best is None:
            specs.append((block_start, block_start, count, None))
        else:
            specs.append((best[4], block_start, count, best[5]))
    return specs


def merge_dropped_line_to_target(bitmap: np.ndarray, drop_x: int, target_x: int | None) -> None:
    if target_x is not None:
        bitmap[:, target_x] |= bitmap[:, drop_x]


def drop_axis_with_merge_specs(
    bitmap: np.ndarray,
    target_w: int,
    specs: list[tuple[int, int, int, int | None]],
    *,
    apply_merges: bool = True,
) -> np.ndarray:
    h, w = bitmap.shape
    if w <= target_w:
        if w == target_w:
            return bitmap.copy()
        out = np.zeros((h, target_w), dtype=np.uint8)
        out[:, :w] = bitmap
        return out

    drops: set[int] = set()
    for drop_x, _block_start, _count, target_x in specs:
        if drop_x < 0 or drop_x >= w:
            continue
        if apply_merges and target_x is not None and 0 <= target_x < w:
            merge_dropped_line_to_target(bitmap, drop_x, target_x)
        drops.add(drop_x)

    keep = [x for x in range(w) if x not in drops]
    if len(keep) > target_w:
        keep = keep[:target_w]
    elif len(keep) < target_w:
        keep.extend([keep[-1] if keep else 0] * (target_w - len(keep)))
    return bitmap[:, keep].astype(np.uint8)


def axis_projection_from_drop_specs(
    width: int,
    target_w: int,
    specs: list[tuple[int, int, int]],
) -> list[tuple[int, ...]]:
    drops = {drop_x for drop_x, _block_start, _count in specs}
    keep = [x for x in range(width) if x not in drops]
    if len(keep) > target_w:
        keep = keep[:target_w]
    elif len(keep) < target_w:
        keep.extend([keep[-1] if keep else 0] * (target_w - len(keep)))

    keep_pos = {src: i for i, src in enumerate(keep)}
    projections: list[tuple[int, ...]] = []
    for src in range(width):
        if src in keep_pos:
            projections.append((keep_pos[src],))
            continue

        candidates: list[int] = []
        left = src - 1
        while left >= 0:
            if left in keep_pos:
                candidates.append(keep_pos[left])
                break
            left -= 1
        right = src + 1
        while right < width:
            if right in keep_pos:
                candidates.append(keep_pos[right])
                break
            right += 1
        if not candidates:
            candidates.append(max(0, min(target_w - 1, int(round(src * target_w / width)))))
        projections.append(tuple(dict.fromkeys(candidates)))
    return projections


def local_neighbor_component_count(bitmap: np.ndarray, x: int, y: int) -> tuple[int, int]:
    h, w = bitmap.shape
    coords: list[tuple[int, int]] = []
    for yy in range(max(0, y - 1), min(h, y + 2)):
        for xx in range(max(0, x - 1), min(w, x + 2)):
            if xx == x and yy == y:
                continue
            if bitmap[yy, xx]:
                coords.append((xx, yy))

    if not coords:
        return 0, 0

    coord_set = set(coords)
    seen: set[tuple[int, int]] = set()
    components = 0
    for coord in coords:
        if coord in seen:
            continue
        components += 1
        stack = [coord]
        seen.add(coord)
        while stack:
            cx, cy = stack.pop()
            for yy in range(cy - 1, cy + 2):
                for xx in range(cx - 1, cx + 2):
                    if xx == cx and yy == cy:
                        continue
                    nxt = (xx, yy)
                    if nxt in coord_set and nxt not in seen:
                        seen.add(nxt)
                        stack.append(nxt)
    return len(coords), components


def merge_specs_to_drop_specs(
    specs: list[tuple[int, int, int, int | None]],
) -> list[tuple[int, int, int]]:
    return [(drop_x, block_start, count) for drop_x, block_start, count, _target_x in specs]


def drop_axis_bridge_repair(
    bitmap: np.ndarray,
    target_w: int,
    specs: list[tuple[int, int, int, int | None]],
    *,
    max_neighbors: int = 5,
) -> np.ndarray:
    base = drop_axis_with_merge_specs(bitmap.copy(), target_w, specs, apply_merges=False)
    projection = axis_projection_from_drop_specs(
        bitmap.shape[1],
        target_w,
        merge_specs_to_drop_specs(specs),
    )
    projected = np.zeros(base.shape, dtype=np.uint16)

    for y in range(bitmap.shape[0]):
        for sx in range(bitmap.shape[1]):
            if not bitmap[y, sx]:
                continue
            for ox in projection[sx]:
                if 0 <= ox < projected.shape[1]:
                    projected[y, ox] += 1

    repaired = base.copy()
    for y in range(repaired.shape[0]):
        for x in range(repaired.shape[1]):
            if repaired[y, x] or not projected[y, x]:
                continue
            neighbors, components = local_neighbor_component_count(base, x, y)
            if components >= 2 and 2 <= neighbors <= max_neighbors:
                repaired[y, x] = 1
    return repaired.astype(np.uint8)


def drop_balanced_bridge_repair_12(
    bitmap: np.ndarray,
    target_w: int,
    tie_bias: float,
    *,
    max_neighbors: int = 5,
) -> np.ndarray:
    x_specs = choose_drop_specs(bitmap, target_w, tie_bias)
    x_dropped = drop_axis_to(bitmap.copy(), target_w, tie_bias)
    y_specs = choose_drop_specs(x_dropped.T, DST_SIZE, tie_bias)
    base = drop_axis_to(x_dropped.T, DST_SIZE, tie_bias).T.astype(np.uint8)

    x_projection = axis_projection_from_drop_specs(bitmap.shape[1], target_w, x_specs)
    y_projection = axis_projection_from_drop_specs(bitmap.shape[0], DST_SIZE, y_specs)
    projected = np.zeros(base.shape, dtype=np.uint16)

    for sy in range(bitmap.shape[0]):
        for sx in range(bitmap.shape[1]):
            if not bitmap[sy, sx]:
                continue
            for oy in y_projection[sy]:
                if oy < 0 or oy >= projected.shape[0]:
                    continue
                for ox in x_projection[sx]:
                    if 0 <= ox < projected.shape[1]:
                        projected[oy, ox] += 1

    repaired = base.copy()
    for y in range(repaired.shape[0]):
        for x in range(repaired.shape[1]):
            if repaired[y, x] or not projected[y, x]:
                continue
            neighbors, components = local_neighbor_component_count(base, x, y)
            if components >= 2 and 2 <= neighbors <= max_neighbors:
                repaired[y, x] = 1
    return repaired.astype(np.uint8)


def drop_similar_pair_bridge_repair_12(
    bitmap: np.ndarray,
    target_w: int,
    tie_bias: float,
    *,
    max_neighbors: int = 5,
) -> np.ndarray:
    x_merge_specs = choose_similar_pair_specs(bitmap, target_w, tie_bias)
    y_merge_specs = choose_similar_pair_specs(bitmap.T, DST_SIZE, tie_bias)
    x_drop_specs = [(drop_x, block_start, count) for drop_x, block_start, count, _target_x in x_merge_specs]
    y_drop_specs = [(drop_y, block_start, count) for drop_y, block_start, count, _target_y in y_merge_specs]

    x_dropped = drop_axis_with_merge_specs(bitmap.copy(), target_w, x_merge_specs, apply_merges=False)
    base = drop_axis_with_merge_specs(x_dropped.T, DST_SIZE, y_merge_specs, apply_merges=False).T

    x_projection = axis_projection_from_drop_specs(bitmap.shape[1], target_w, x_drop_specs)
    y_projection = axis_projection_from_drop_specs(bitmap.shape[0], DST_SIZE, y_drop_specs)
    projected = np.zeros(base.shape, dtype=np.uint16)

    for sy in range(bitmap.shape[0]):
        for sx in range(bitmap.shape[1]):
            if not bitmap[sy, sx]:
                continue
            for oy in y_projection[sy]:
                if oy < 0 or oy >= projected.shape[0]:
                    continue
                for ox in x_projection[sx]:
                    if 0 <= ox < projected.shape[1]:
                        projected[oy, ox] += 1

    repaired = base.copy()
    for y in range(repaired.shape[0]):
        for x in range(repaired.shape[1]):
            if repaired[y, x] or not projected[y, x]:
                continue
            neighbors, components = local_neighbor_component_count(base, x, y)
            if components >= 2 and 2 <= neighbors <= max_neighbors:
                repaired[y, x] = 1
    return repaired.astype(np.uint8)


def drop_merge_cost_bridge_repair_1234_12(
    bitmap: np.ndarray,
    target_w: int,
    tie_bias: float,
    *,
    max_neighbors: int = 5,
    diagonal_aware: bool = False,
) -> np.ndarray:
    x_specs = choose_merge_cost_specs(
        bitmap,
        target_w,
        tie_bias,
        diagonal_aware=diagonal_aware,
    )
    x_repaired = drop_axis_bridge_repair(
        bitmap,
        target_w,
        x_specs,
        max_neighbors=max_neighbors,
    )
    y_specs = choose_merge_cost_specs(
        x_repaired.T,
        DST_SIZE,
        tie_bias,
        diagonal_aware=diagonal_aware,
    )
    y_repaired_t = drop_axis_bridge_repair(
        x_repaired.T,
        DST_SIZE,
        y_specs,
        max_neighbors=max_neighbors,
    )
    return y_repaired_t.T.astype(np.uint8)


def merge_dropped_line_local(
    bitmap: np.ndarray,
    drop_x: int,
    block_start: int,
    count: int,
    *,
    diagonal_aware: bool = False,
) -> None:
    _, w = bitmap.shape
    candidates = candidate_merge_targets(drop_x, block_start, count, w)
    if not candidates:
        return

    center = block_start + (count - 1) / 2
    best_target = candidates[0]
    best_key: tuple[int, float, float] | None = None
    for target_x in candidates:
        added, shape_penalty = local_merge_score(
            bitmap,
            drop_x,
            target_x,
            block_start,
            count,
            diagonal_aware=diagonal_aware,
        )
        key = (added, shape_penalty, abs(target_x - center))
        if best_key is None or key < best_key:
            best_key = key
            best_target = target_x

    bitmap[:, best_target] |= bitmap[:, drop_x]


def drop_axis_to(
    bitmap: np.ndarray,
    target_w: int,
    tie_bias: float,
    *,
    similar_pair_local: bool = False,
    merge_lost_local: bool = False,
    merge_lost_local_diagonal: bool = False,
    merge_cost_local: bool = False,
    merge_cost_local_diagonal: bool = False,
    reference_bitmap: np.ndarray | None = None,
    apply_merges: bool = True,
) -> np.ndarray:
    h, w = bitmap.shape
    if w <= target_w:
        if w == target_w:
            return bitmap.copy()
        out = np.zeros((h, target_w), dtype=np.uint8)
        out[:, :w] = bitmap
        return out

    reference = bitmap if reference_bitmap is None else reference_bitmap
    if reference.shape != bitmap.shape:
        raise ValueError("reference bitmap must have the same shape as bitmap")

    drops: set[int] = set()
    if similar_pair_local:
        merge_specs = choose_similar_pair_specs(reference, target_w, tie_bias)
        for drop_x, _block_start, _count, target_x in merge_specs:
            if apply_merges:
                merge_dropped_line_to_target(bitmap, drop_x, target_x)
            drops.add(drop_x)
    elif merge_cost_local or merge_cost_local_diagonal:
        merge_specs = choose_merge_cost_specs(
            reference,
            target_w,
            tie_bias,
            diagonal_aware=merge_cost_local_diagonal,
        )
        for drop_x, _block_start, _count, target_x in merge_specs:
            if apply_merges:
                merge_dropped_line_to_target(bitmap, drop_x, target_x)
            drops.add(drop_x)
    else:
        drop_specs = choose_drop_specs(reference, target_w, tie_bias)
        for drop_x, block_start, count in drop_specs:
            if apply_merges and (merge_lost_local or merge_lost_local_diagonal):
                merge_dropped_line_local(
                    bitmap,
                    drop_x,
                    block_start,
                    count,
                    diagonal_aware=merge_lost_local_diagonal,
                )
            drops.add(drop_x)

    keep = [x for x in range(w) if x not in drops]
    if len(keep) > target_w:
        keep = keep[:target_w]
    elif len(keep) < target_w:
        keep.extend([keep[-1] if keep else 0] * (target_w - len(keep)))
    return bitmap[:, keep].astype(np.uint8)


def drop_balanced_12(
    bitmap: np.ndarray,
    target_w: int,
    tie_bias: float,
    *,
    similar_pair_local: bool = False,
    merge_lost_local: bool = False,
    merge_lost_local_diagonal: bool = False,
    merge_cost_local: bool = False,
    merge_cost_local_diagonal: bool = False,
) -> np.ndarray:
    if (
        not similar_pair_local
        and not merge_lost_local
        and not merge_lost_local_diagonal
        and not merge_cost_local
        and not merge_cost_local_diagonal
    ):
        x_dropped = drop_axis_to(bitmap.copy(), target_w, tie_bias)
        y_dropped_t = drop_axis_to(x_dropped.T, DST_SIZE, tie_bias)
        return y_dropped_t.T.astype(np.uint8)

    if similar_pair_local:
        base_x = drop_axis_to(
            bitmap.copy(),
            target_w,
            tie_bias,
            similar_pair_local=True,
            reference_bitmap=bitmap,
            apply_merges=False,
        )
    elif merge_cost_local or merge_cost_local_diagonal:
        base_x = drop_axis_to(
            bitmap.copy(),
            target_w,
            tie_bias,
            merge_cost_local=True,
            merge_cost_local_diagonal=merge_cost_local_diagonal,
            reference_bitmap=bitmap,
            apply_merges=False,
        )
    else:
        base_x = drop_axis_to(bitmap.copy(), target_w, tie_bias)
    x_dropped = drop_axis_to(
        bitmap.copy(),
        target_w,
        tie_bias,
        similar_pair_local=similar_pair_local,
        merge_lost_local=merge_lost_local,
        merge_lost_local_diagonal=merge_lost_local_diagonal,
        merge_cost_local=merge_cost_local,
        merge_cost_local_diagonal=merge_cost_local_diagonal,
        reference_bitmap=bitmap,
    )
    y_dropped_t = drop_axis_to(
        x_dropped.T,
        DST_SIZE,
        tie_bias,
        similar_pair_local=similar_pair_local,
        merge_lost_local=merge_lost_local,
        merge_lost_local_diagonal=merge_lost_local_diagonal,
        merge_cost_local=merge_cost_local,
        merge_cost_local_diagonal=merge_cost_local_diagonal,
        reference_bitmap=base_x.T,
    )
    return y_dropped_t.T.astype(np.uint8)


def drop_balanced_local_merge_12(bitmap: np.ndarray, target_w: int, tie_bias: float) -> np.ndarray:
    return drop_balanced_12(bitmap, target_w, tie_bias, merge_lost_local=True)


def drop_balanced_local_merge_diagonal_12(bitmap: np.ndarray, target_w: int, tie_bias: float) -> np.ndarray:
    return drop_balanced_12(bitmap, target_w, tie_bias, merge_lost_local_diagonal=True)


def drop_balanced_local_merge_add_only_12(bitmap: np.ndarray, target_w: int, tie_bias: float) -> np.ndarray:
    base = drop_balanced_12(bitmap, target_w, tie_bias, merge_lost_local=False)
    merged = drop_balanced_local_merge_12(bitmap, target_w, tie_bias)
    return (base | merged).astype(np.uint8)


def drop_similar_pair_local_12(bitmap: np.ndarray, target_w: int, tie_bias: float) -> np.ndarray:
    return drop_balanced_12(bitmap, target_w, tie_bias, similar_pair_local=True)


def drop_merge_cost_local_12(bitmap: np.ndarray, target_w: int, tie_bias: float) -> np.ndarray:
    return drop_balanced_12(bitmap, target_w, tie_bias, merge_cost_local=True)


def drop_merge_cost_local_diagonal_12(bitmap: np.ndarray, target_w: int, tie_bias: float) -> np.ndarray:
    return drop_balanced_12(bitmap, target_w, tie_bias, merge_cost_local_diagonal=True)


def drop_merge_cost_preselect_axes_12(
    bitmap: np.ndarray,
    target_w: int,
    tie_bias: float,
    *,
    diagonal_aware: bool = False,
) -> np.ndarray:
    x_specs = choose_merge_cost_specs(
        bitmap,
        target_w,
        tie_bias,
        diagonal_aware=diagonal_aware,
    )
    y_specs = choose_merge_cost_specs(
        bitmap.T,
        DST_SIZE,
        tie_bias,
        diagonal_aware=diagonal_aware,
    )
    x_dropped = drop_axis_with_merge_specs(bitmap.copy(), target_w, x_specs)
    y_dropped_t = drop_axis_with_merge_specs(x_dropped.T, DST_SIZE, y_specs)
    return y_dropped_t.T.astype(np.uint8)


def drop_merge_cost_preselect_rows_first_12(
    bitmap: np.ndarray,
    target_w: int,
    tie_bias: float,
    *,
    diagonal_aware: bool = False,
) -> np.ndarray:
    y_specs = choose_merge_cost_specs(
        bitmap.T,
        DST_SIZE,
        tie_bias,
        diagonal_aware=diagonal_aware,
    )
    x_specs = choose_merge_cost_specs(
        bitmap,
        target_w,
        tie_bias,
        diagonal_aware=diagonal_aware,
    )
    y_dropped_t = drop_axis_with_merge_specs(bitmap.T.copy(), DST_SIZE, y_specs)
    y_dropped = y_dropped_t.T
    x_dropped = drop_axis_with_merge_specs(y_dropped, target_w, x_specs)
    return x_dropped.astype(np.uint8)


def bitmap_to_glyph(bitmap: np.ndarray) -> TtGlyph:
    h, w = bitmap.shape
    pen = TTGlyphPen(None)
    has_ink = False
    for x in range(w):
        y = 0
        while y < h:
            if not bitmap[y, x]:
                y += 1
                continue
            y_end = y
            while y_end + 1 < h and bitmap[y_end + 1, x]:
                y_end += 1
            has_ink = True
            x0, x1 = x * PX + PIXEL_INSET, (x + 1) * PX - PIXEL_INSET
            y_top = (ASC - y) * PX - PIXEL_INSET
            y_bot = (ASC - y_end - 1) * PX + PIXEL_INSET
            pen.moveTo((x0, y_bot))
            pen.lineTo((x0, y_top))
            pen.lineTo((x1, y_top))
            pen.lineTo((x1, y_bot))
            pen.closePath()
            y = y_end + 1
    if has_ink:
        return pen.glyph()
    empty = TtGlyph()
    empty.numberOfContours = 0
    return empty


def rewrite_name(font: TTFont) -> None:
    if "name" not in font:
        return
    name = font["name"]
    name.names = [r for r in name.names if r.nameID not in (1, 2, 3, 4, 6, 16, 17)]

    def add(name_id: int, value: str) -> None:
        name.setName(value, name_id, 3, 1, 0x409)

    family = "K64 CK Unifont 12px Drop Balanced Trial"
    style = "Regular"
    add(1, family)
    add(2, style)
    add(3, "K64 CK Unifont 12px Drop Balanced Trial 2026-06-17")
    add(4, f"{family} {style}")
    add(6, "K64CKUnifont12pxDropBalancedTrial-Regular")
    add(16, family)
    add(17, style)


def update_metrics(font: TTFont, advance_width_max: int) -> None:
    font["head"].unitsPerEm = UPM
    font["hhea"].ascent = 1100
    font["hhea"].descent = -100
    font["hhea"].lineGap = 0
    font["hhea"].advanceWidthMax = advance_width_max
    if "OS/2" in font:
        os2 = font["OS/2"]
        os2.sTypoAscender = 1100
        os2.sTypoDescender = -100
        os2.sTypoLineGap = 0
        os2.usWinAscent = 1100
        os2.usWinDescent = 100
        if hasattr(os2, "sxHeight"):
            os2.sxHeight = 0
        if hasattr(os2, "sCapHeight"):
            os2.sCapHeight = 0


def update_bbox(font: TTFont) -> None:
    glyf = font["glyf"]
    x_mins: list[int] = []
    y_mins: list[int] = []
    x_maxs: list[int] = []
    y_maxs: list[int] = []
    for glyph_name in font.getGlyphOrder():
        glyph = glyf[glyph_name]
        if glyph.numberOfContours == 0:
            continue
        glyph.recalcBounds(glyf)
        x_mins.append(glyph.xMin)
        y_mins.append(glyph.yMin)
        x_maxs.append(glyph.xMax)
        y_maxs.append(glyph.yMax)
    if not x_mins:
        return
    head = font["head"]
    head.xMin = min(x_mins)
    head.yMin = min(y_mins)
    head.xMax = max(x_maxs)
    head.yMax = max(y_maxs)


def bake(
    source: Path,
    output: Path,
    *,
    tie_bias: float,
    block_lut_4x4: bool,
    similar_pair_local: bool,
    drop_bridge_repair: bool,
    merge_cost_bridge_repair: bool,
    similar_pair_bridge_repair: bool,
    merge_lost_local: bool,
    merge_lost_local_diagonal: bool,
    merge_lost_local_add_only: bool,
    merge_cost_preselect_axes: bool,
    merge_cost_preselect_rows_first: bool,
    merge_cost_local: bool,
    merge_cost_local_diagonal: bool,
    max_chars: int | None = None,
) -> None:
    src_font = TTFont(str(source))
    if "glyf" not in src_font:
        raise RuntimeError("source must be a TrueType glyf font")
    cmap = src_font.getBestCmap()
    if not cmap:
        raise RuntimeError("source has no cmap")

    buf = io.BytesIO()
    src_font.save(buf)
    buf.seek(0)
    out_font = TTFont(buf, recalcBBoxes=True, recalcTimestamp=False)
    glyf = out_font["glyf"]
    hmtx = out_font["hmtx"].metrics
    pil_font = ImageFont.truetype(str(source), SRC_SIZE)

    items = sorted(cmap.items())
    if max_chars is not None:
        items = items[:max_chars]

    processed_glyphs: set[str] = set()
    max_advance = 0
    for index, (cp, glyph_name) in enumerate(items, 1):
        if glyph_name in processed_glyphs:
            continue
        bitmap, src_width = rasterize(pil_font, chr(cp))
        old_advance = hmtx.get(glyph_name, (src_width * PX, 0))[0]
        is_zero_advance = old_advance == 0
        dst_w = target_width(src_width)
        if block_lut_4x4:
            dst = block_lut_4x4_to_3x3(bitmap, dst_w)
        elif similar_pair_local:
            dst = drop_similar_pair_local_12(bitmap, dst_w, tie_bias)
        elif drop_bridge_repair:
            dst = drop_balanced_bridge_repair_12(bitmap, dst_w, tie_bias)
        elif merge_cost_bridge_repair:
            dst = drop_merge_cost_bridge_repair_1234_12(bitmap, dst_w, tie_bias)
        elif similar_pair_bridge_repair:
            dst = drop_similar_pair_bridge_repair_12(bitmap, dst_w, tie_bias)
        elif merge_lost_local_add_only:
            dst = drop_balanced_local_merge_add_only_12(bitmap, dst_w, tie_bias)
        elif merge_cost_preselect_rows_first:
            dst = drop_merge_cost_preselect_rows_first_12(bitmap, dst_w, tie_bias)
        elif merge_cost_preselect_axes:
            dst = drop_merge_cost_preselect_axes_12(bitmap, dst_w, tie_bias)
        elif merge_cost_local_diagonal:
            dst = drop_merge_cost_local_diagonal_12(bitmap, dst_w, tie_bias)
        elif merge_cost_local:
            dst = drop_merge_cost_local_12(bitmap, dst_w, tie_bias)
        elif merge_lost_local_diagonal:
            dst = drop_balanced_local_merge_diagonal_12(bitmap, dst_w, tie_bias)
        elif merge_lost_local:
            dst = drop_balanced_local_merge_12(bitmap, dst_w, tie_bias)
        else:
            dst = drop_balanced_12(bitmap, dst_w, tie_bias)
        glyph = bitmap_to_glyph(dst)
        glyf[glyph_name] = glyph
        advance = 0 if is_zero_advance else dst_w * PX
        lsb = 0
        if glyph.numberOfContours:
            glyph.recalcBounds(glyf)
            lsb = glyph.xMin
        hmtx[glyph_name] = (advance, lsb)
        max_advance = max(max_advance, advance)
        processed_glyphs.add(glyph_name)
        if index % 5000 == 0:
            print(f"  processed {index}/{len(items)} cmap entries", flush=True)

    update_metrics(out_font, max_advance)
    rewrite_name(out_font)
    update_bbox(out_font)
    output.parent.mkdir(parents=True, exist_ok=True)
    out_font.save(str(output))
    print(f"wrote {output} ({len(processed_glyphs)} glyphs, UPM={UPM})")


def make_preview(font_path: Path, out_path: Path, scale: int = 4) -> None:
    font = ImageFont.truetype(str(font_path), DST_SIZE)
    pad = 6
    gap = 2
    dummy = Image.new("L", (1, 1), 255)
    draw = ImageDraw.Draw(dummy)
    widths = []
    for line in SAMPLE_LINES:
        bbox = draw.textbbox((0, 0), line, font=font)
        widths.append(bbox[2] - bbox[0])
    width = max(widths + [1]) + pad * 2
    height = pad * 2 + len(SAMPLE_LINES) * DST_SIZE + (len(SAMPLE_LINES) - 1) * gap
    image = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(image)
    draw.fontmode = "1"
    y = pad
    for line in SAMPLE_LINES:
        draw.text((pad, y), line, font=font, fill=0)
        y += DST_SIZE + gap
    image = image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
    rgb = Image.merge("RGB", (image, image, image))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rgb.save(out_path)
    print(f"wrote {out_path}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Bake a 12px drop-balanced Unifont trial TTF.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--preview-output", type=Path, default=DEFAULT_PREVIEW)
    parser.add_argument("--tie-bias", type=float, default=DEFAULT_TIE_BIAS)
    parser.add_argument(
        "--merge-lost-local",
        action="store_true",
        help="OR lost pixels into the lower-impact neighbor inside each drop block before dropping.",
    )
    parser.add_argument(
        "--merge-lost-local-diagonal",
        action="store_true",
        help="Use local merge with an additional penalty for collapsing diagonal strokes.",
    )
    parser.add_argument(
        "--merge-lost-local-add-only",
        action="store_true",
        help="Use local merge as an add-only overlay on the plain drop-balanced result.",
    )
    parser.add_argument(
        "--merge-cost-local",
        action="store_true",
        help="Choose dropped rows/columns by lowest same-block OR-merge cost instead of lowest ink.",
    )
    parser.add_argument(
        "--merge-cost-local-diagonal",
        action="store_true",
        help="Choose dropped rows/columns by OR-merge cost with an added diagonal-collapse penalty.",
    )
    parser.add_argument(
        "--merge-cost-preselect-axes",
        action="store_true",
        help="Choose merge-cost columns and rows from the original bitmap before applying either axis.",
    )
    parser.add_argument(
        "--merge-cost-preselect-rows-first",
        action="store_true",
        help="Choose merge-cost rows first, then columns, both from the original bitmap; apply rows then columns.",
    )
    parser.add_argument(
        "--block-lut-4x4",
        action="store_true",
        help="Convert each 4x4 source domain to 3x3 by choosing the best local OR-merge candidate.",
    )
    parser.add_argument(
        "--similar-pair-local",
        action="store_true",
        help="Choose the most similar adjacent row/column pair in each drop block, OR-merge it, then drop one line.",
    )
    parser.add_argument(
        "--drop-bridge-repair",
        action="store_true",
        help="Start from plain drop-balanced and add projected lost pixels only when they bridge separated neighbors.",
    )
    parser.add_argument(
        "--merge-cost-bridge-repair",
        action="store_true",
        help="Use old merge-cost 1-2-3-4 selection, but replace OR merge with bridge-repair-only filling.",
    )
    parser.add_argument(
        "--similar-pair-bridge-repair",
        action="store_true",
        help="Drop lines chosen by similar adjacent pairs without merging, then add bridge-repair pixels.",
    )
    parser.add_argument("--max-chars", type=int, default=None)
    parser.add_argument("--no-preview", action="store_true")
    args = parser.parse_args(argv)

    bake(
        args.source,
        args.output,
        tie_bias=args.tie_bias,
        block_lut_4x4=args.block_lut_4x4,
        similar_pair_local=args.similar_pair_local,
        drop_bridge_repair=args.drop_bridge_repair,
        merge_cost_bridge_repair=args.merge_cost_bridge_repair,
        similar_pair_bridge_repair=args.similar_pair_bridge_repair,
        merge_lost_local=args.merge_lost_local,
        merge_lost_local_diagonal=args.merge_lost_local_diagonal,
        merge_lost_local_add_only=args.merge_lost_local_add_only,
        merge_cost_preselect_axes=args.merge_cost_preselect_axes,
        merge_cost_preselect_rows_first=args.merge_cost_preselect_rows_first,
        merge_cost_local=args.merge_cost_local,
        merge_cost_local_diagonal=args.merge_cost_local_diagonal,
        max_chars=args.max_chars,
    )
    if not args.no_preview:
        make_preview(args.output, args.preview_output)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
