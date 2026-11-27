"""Independent geometry audit for the frozen 20-case snapshots.

This module deliberately does not import production CAD proof code.  It reads
raw entity coordinates and computes counts, bounding boxes, arc sweeps, endpoint
gaps and turning angles with plain trigonometry.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

SNAPSHOTS = Path(r"C:\Users\29924\Codes\xikao\cad_e2e_generalization_live_01\geometry-snapshots")
OUTPUT = Path(r"C:\Users\29924\Codes\xikao\cad_core_generalization_02")


def _sweep(entity: dict) -> float:
    start, end = float(entity["start_deg"]), float(entity["end_deg"])
    delta = end - start
    if entity.get("direction") == "ccw" and delta < 0:
        delta += 360.0
    if entity.get("direction") == "cw" and delta > 0:
        delta -= 360.0
    return abs(delta)


def _turns(points: list[list[float]]) -> list[float]:
    values = []
    for index in range(len(points)):
        prev, current, nxt = points[index - 1], points[index], points[(index + 1) % len(points)]
        u = (current[0] - prev[0], current[1] - prev[1])
        v = (nxt[0] - current[0], nxt[1] - current[1])
        lengths = math.hypot(*u) * math.hypot(*v)
        if lengths <= 1e-12:
            continue
        cosine = max(-1.0, min(1.0, (u[0] * v[0] + u[1] * v[1]) / lengths))
        values.append(math.degrees(math.acos(cosine)))
    return values


def audit(case_id: str) -> dict:
    data = json.loads((SNAPSHOTS / f"{case_id}.json").read_text(encoding="utf-8"))
    entities = data["entities"]
    counts: dict[str, int] = {}
    for entity in entities:
        counts[entity["type"]] = counts.get(entity["type"], 0) + 1
    result = {"case_id": case_id, "entity_counts": counts}
    arcs = [item for item in entities if item["type"] == "arc"]
    if arcs:
        result["arc_sweeps_deg"] = [round(_sweep(item), 6) for item in arcs]
        result["arc_sweep_total_deg"] = round(sum(_sweep(item) for item in arcs), 6)
    circles = [item for item in entities if item["type"] == "circle"]
    if circles:
        result["circle_radii_mm"] = sorted(item["radius"] for item in circles)
        result["circle_centers_mm"] = [item["center"] for item in circles]
    for entity in entities:
        points = entity.get("vertices") or []
        if len(points) > 10:
            gap = math.dist(points[0], points[-1])
            edges = [math.dist(points[i], points[(i + 1) % len(points)])
                     for i in range(len(points))]
            turns = _turns(points)
            result.update({
                "polyline_vertices": len(points),
                "polyline_closed_flag": bool(entity.get("closed")),
                "endpoint_gap_mm": round(gap, 9),
                "median_edge_mm": round(sorted(edges)[len(edges) // 2], 9),
                "max_turn_deg": round(max(turns), 9),
                "max_turn_below_90deg": round(
                    max((value for value in turns if value < 90.0), default=0.0), 9
                ),
                "turns_over_5deg": sum(1 for value in turns if value > 5.0),
            })
    return result


def main() -> int:
    rows = [audit(case_id) for case_id in (
        "B04", "M01", "M02", "M03", "M04", "F01", "F03", "T01", "T02", "T04"
    )]
    by_case = {row["case_id"]: row for row in rows}
    f03 = by_case["F03"]
    t02 = by_case["T02"]
    assert abs(f03["endpoint_gap_mm"] - 95.28941682066456) < 1e-6
    assert abs(f03["max_turn_below_90deg"] - 7.014676539987212) < 1e-6
    assert f03["endpoint_gap_mm"] > 0.5
    assert f03["max_turn_below_90deg"] > 5.0
    assert t02["arc_sweep_total_deg"] == 360.0, t02
    checks = {
        "f03_endpoint_gap_exceeds_0_5mm": f03["endpoint_gap_mm"] > 0.5,
        "f03_smooth_turn_exceeds_5deg": f03["max_turn_below_90deg"] > 5.0,
        "t02_arc_total_is_360_not_600": t02["arc_sweep_total_deg"] == 360.0,
        "b04_single_arc": by_case["B04"]["entity_counts"].get("arc") == 1,
        "m01_three_circles": by_case["M01"]["entity_counts"].get("circle") == 3,
        "m03_eight_circles": by_case["M03"]["entity_counts"].get("circle") == 8,
    }
    payload = {
        "schema": "cad.generalization-02.independent-geometry-audit.v1",
        "production_code_imported": False,
        "checks": checks,
        "rows": rows,
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "independent_geometry_audit.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(checks, ensure_ascii=False))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
