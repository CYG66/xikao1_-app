from __future__ import annotations

import math
from typing import Any

from .mission_analysis import point_xy, segment_length_m


def _heading(segment: dict[str, Any]) -> float | None:
    points: list[tuple[float, float] | None] = []
    if str(segment.get("type", "")).lower() in {"polyline", "spline"}:
        raw = segment.get("vertices", segment.get("control_points", []))
        if isinstance(raw, list) and len(raw) >= 2:
            points = [point_xy(raw[0]), point_xy(raw[-1])]
    else:
        points = [point_xy(segment.get("start")), point_xy(segment.get("end"))]
    if len(points) != 2 or None in points:
        return None
    start, end = points
    assert start is not None and end is not None
    return math.atan2(end[1] - start[1], end[0] - start[0])


def score_planned_mission(segments: list[dict[str, Any]], summary: dict[str, Any],
                          validation: dict[str, Any]) -> dict[str, Any]:
    printing = float(summary.get("printing_length_m", 0) or 0)
    travel = float(summary.get("travel_length_m", 0) or 0)
    total = printing + travel
    travel_ratio = travel / total if total > 0 else 1.0
    short_segments = sum(1 for item in segments if (segment_length_m(item) or 0) < 0.02)
    headings = [value for value in (_heading(item) for item in segments) if value is not None]
    sharp_turns = 0
    for previous, current in zip(headings, headings[1:]):
        delta = abs((current - previous + math.pi) % (2 * math.pi) - math.pi)
        if delta > math.radians(120):
            sharp_turns += 1
    duplicates = int(summary.get("duplicate_ink_paths_filtered", 0) or 0)
    score = 100 - min(30, round(travel_ratio * 30)) - min(20, short_segments * 2)
    score -= min(20, sharp_turns * 4) + min(20, duplicates * 5)
    if validation.get("errors"):
        score = min(score, 40)
    score = max(0, int(score))
    grade = "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D" if score >= 60 else "E"
    warnings = list(validation.get("warnings", []))
    if travel_ratio > 0.4:
        warnings.append("转场路径占比较高")
    if sharp_turns:
        warnings.append(f"检测到 {sharp_turns} 处大角度换向")
    return {"score": score, "grade": grade, "metrics": {
        "travel_ratio": round(travel_ratio, 4), "sharp_turns": sharp_turns,
        "short_segments": short_segments, "duplicate_ink_paths": duplicates,
    }, "warnings": warnings}
