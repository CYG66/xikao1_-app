"""Advisory raster scoring for already geometry-validated CAD candidates.

This module never decides whether a drawing is valid or executable.  It only
provides deterministic visual diagnostics and a tie-break score after the
authoritative geometry checks have passed.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from PIL import Image, ImageDraw

from .drawing_store import preview_paths


def score_candidate_visuals(
    geometries: list[dict[str, Any]], *, canvas_size: int = 256,
) -> dict[str, Any]:
    paths = preview_paths({"lines": geometries})
    usable = [
        [(float(point[0]), float(point[1])) for point in path]
        for path in paths
        if isinstance(path, list) and len(path) >= 2
    ]
    if not usable:
        return _report(
            score=0.0,
            path_count=0,
            segment_count=0,
            ink_ratio=0.0,
            canvas_utilization=0.0,
            tiny_segment_ratio=1.0,
            retraced_segment_ratio=0.0,
            warnings=["没有可渲染路径"],
        )

    all_points = [point for path in usable for point in path]
    min_x = min(point[0] for point in all_points)
    max_x = max(point[0] for point in all_points)
    min_y = min(point[1] for point in all_points)
    max_y = max(point[1] for point in all_points)
    width = max_x - min_x
    height = max_y - min_y
    span = max(width, height)
    if not math.isfinite(span) or span <= 1e-9:
        return _report(
            score=0.0,
            path_count=len(usable),
            segment_count=0,
            ink_ratio=0.0,
            canvas_utilization=0.0,
            tiny_segment_ratio=1.0,
            retraced_segment_ratio=0.0,
            warnings=["图形范围退化，无法形成稳定预览"],
        )

    padding = max(8, canvas_size // 16)
    drawable = canvas_size - padding * 2
    scale = drawable / span
    offset_x = padding + (drawable - width * scale) / 2.0
    offset_y = padding + (drawable - height * scale) / 2.0

    image = Image.new("L", (canvas_size, canvas_size), 0)
    draw = ImageDraw.Draw(image)
    segment_lengths: list[float] = []
    segment_keys: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for path in usable:
        pixels = [
            (
                offset_x + (x - min_x) * scale,
                canvas_size - (offset_y + (y - min_y) * scale),
            )
            for x, y in path
        ]
        draw.line(pixels, fill=255, width=2, joint="curve")
        for left, right in zip(path, path[1:]):
            length = math.hypot(right[0] - left[0], right[1] - left[1])
            segment_lengths.append(length)
            a = (round(left[0] * 1000), round(left[1] * 1000))
            b = (round(right[0] * 1000), round(right[1] * 1000))
            segment_keys.append(tuple(sorted((a, b))))

    histogram = image.histogram()
    ink_pixels = sum(histogram[1:])
    total_pixels = canvas_size * canvas_size
    bbox = image.getbbox()
    if bbox is None:
        utilization = 0.0
    else:
        utilization = ((bbox[2] - bbox[0]) * (bbox[3] - bbox[1])) / total_pixels
    ink_ratio = ink_pixels / total_pixels
    tiny_threshold = max(span * 0.0005, 1e-9)
    tiny_ratio = (
        sum(length <= tiny_threshold for length in segment_lengths) / len(segment_lengths)
        if segment_lengths else 1.0
    )
    counts = Counter(segment_keys)
    retraced = sum(count - 1 for count in counts.values() if count > 1)
    retraced_ratio = retraced / len(segment_keys) if segment_keys else 0.0

    # These terms measure preview legibility only. They do not express CAD
    # correctness, dimensions, topology, or construction feasibility.
    visibility = min(1.0, ink_ratio / 0.02)
    utilization_quality = min(1.0, utilization / 0.55)
    score = 100.0 * (
        0.45 * visibility
        + 0.35 * utilization_quality
        + 0.20 * (1.0 - min(1.0, tiny_ratio + retraced_ratio))
    )
    warnings: list[str] = []
    if tiny_ratio > 0.1:
        warnings.append("预览中存在较多极短线段")
    if retraced_ratio > 0.1:
        warnings.append("预览中存在较多重复描画线段")
    if utilization < 0.1:
        warnings.append("图形在预览画布中的占比较小")
    return _report(
        score=score,
        path_count=len(usable),
        segment_count=len(segment_lengths),
        ink_ratio=ink_ratio,
        canvas_utilization=utilization,
        tiny_segment_ratio=tiny_ratio,
        retraced_segment_ratio=retraced_ratio,
        warnings=warnings,
    )


def _report(
    *, score: float, path_count: int, segment_count: int, ink_ratio: float,
    canvas_utilization: float, tiny_segment_ratio: float,
    retraced_segment_ratio: float, warnings: list[str],
) -> dict[str, Any]:
    return {
        "schema": "cad.visual-score.v1",
        "score": round(max(0.0, min(100.0, score)), 3),
        "authoritative": False,
        "used_for_gate": False,
        "role": "geometry_score_tie_break_only",
        "path_count": path_count,
        "segment_count": segment_count,
        "ink_ratio": round(ink_ratio, 6),
        "canvas_utilization": round(canvas_utilization, 6),
        "tiny_segment_ratio": round(tiny_segment_ratio, 6),
        "retraced_segment_ratio": round(retraced_segment_ratio, 6),
        "warnings": warnings,
    }
