"""D0 zero-cost geometry probes.

This script does not call a model and does not persist projects or candidates.
It builds reconstructions from repository-known A9/S1 data and prints JSON.
"""
from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.cad_construction import ConstructionPlanError, execute_construction_plan
from app.cad_plan_component_repair import merge_component_repair


def canonical_sha256(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def point(x: float, y: float) -> dict[str, float]:
    return {"x": x, "y": y}


def a9_plan() -> dict:
    """Reconstructed closed path using the known A9 segment 0 and segment 5.

    Segment 1 is a synthetic straight connector between the two known curve
    endpoints. It is not part of the unavailable historical plan; this is a
    reconstructed_fixture, not an exact A9 replay.
    """
    seg0 = [
        point(2.0, 3.1),
        point(2.15, 3.9),
        point(1.45, 4.55),
        point(0.65, 4.55),
    ]
    seg5 = [
        point(3.35, 4.55),
        point(2.55, 4.55),
        point(1.85, 3.9),
        point(2.0, 3.1),
    ]
    return {
        "schema_version": "cad.construction-plan.v1",
        "units": "m",
        "steps": [{
            "op": "add_composite_path",
            "step_id": "a9-reconstructed",
            "output_ref": "a9-heart",
            "layer_id": 1,
            "semantic": {"object_type": "drawing_part", "label": "A9 重建夹具"},
            "segments": [
                {"kind": "bezier", "control_points": seg0},
                {"kind": "line", "start": point(0.65, 4.55), "end": point(3.35, 4.55)},
                {"kind": "bezier", "control_points": seg5},
            ],
            "closed": True,
            "samples_per_curve": 64,
            "connection_tolerance": 0.000001,
            "continuity": "C0",
            "allow_self_intersection": False,
            "allow_duplicate_segments": False,
        }],
        "budgets": {"max_steps": 10, "max_entities": 20},
    }


def s1_plan() -> dict:
    """Three cubic Beziers through the frozen S1 anchors with C1 joints."""
    segments = [
        [
            point(0.0, 0.0),
            point(0.8, 0.6),
            point(1.4, 1.2),
            point(2.0, 1.0),
        ],
        [
            point(2.0, 1.0),
            point(2.2, 0.9333333333333333),
            point(3.6, -0.9),
            point(4.0, -1.0),
        ],
        [
            point(4.0, -1.0),
            point(4.4, -1.1),
            point(5.2, -0.6),
            point(6.0, 0.0),
        ],
    ]
    return {
        "schema_version": "cad.construction-plan.v1",
        "units": "m",
        "steps": [{
            "op": "add_composite_path",
            "step_id": "s1-reconstructed",
            "output_ref": "s1-s-curve",
            "layer_id": 1,
            "semantic": {"object_type": "drawing_part", "label": "S1 重建夹具"},
            "segments": [{"kind": "bezier", "control_points": item} for item in segments],
            "closed": False,
            "samples_per_curve": 64,
            "connection_tolerance": 0.000001,
            "continuity": "C1",
            "tangent_tolerance_deg": 0.01,
            "allow_self_intersection": False,
            "allow_duplicate_segments": False,
        }],
        "budgets": {"max_steps": 10, "max_entities": 20},
    }


def run_plan(plan: dict) -> dict:
    try:
        result = execute_construction_plan(plan)
        trial = result.get("trial_result") if isinstance(result, dict) else None
        geometries = (trial or {}).get("geometries") or result.get("geometries") or []
        return {
            "status": "passed",
            "error": None,
            "geometry_count": len(geometries),
            "geometry_hash": canonical_sha256(geometries),
            "curve_quality": (trial or {}).get("curve_quality") or result.get("curve_quality"),
            "feasibility": (trial or {}).get("feasibility") or result.get("feasibility"),
            "topology": (trial or {}).get("topology") or result.get("topology"),
        }
    except ConstructionPlanError as exc:
        return {
            "status": "failed",
            "error": exc.as_dict(),
            "geometry_count": 0,
            "geometry_hash": None,
        }
    except Exception as exc:  # keep the probe honest for unexpected schema errors
        return {
            "status": "error",
            "error": {"type": type(exc).__name__, "message": str(exc)},
            "geometry_count": 0,
            "geometry_hash": None,
        }


def junction_repair_probe() -> dict:
    plan = {
        "schema_version": "cad.construction-plan.v1",
        "units": "m",
        "steps": [{
            "op": "add_composite_path",
            "step_id": "junction-step",
            "output_ref": "junction-curve",
            "layer_id": 1,
            "semantic": {"object_type": "drawing_part", "label": "junction fixture"},
            "segments": [
                {"kind": "line", "start": point(0, 0), "end": point(1, 0)},
                {"kind": "line", "start": point(1, 0), "end": point(1, 1)},
            ],
            "closed": False,
            "junction_constraints": [{
                "left_segment_index": 0,
                "right_segment_index": 1,
                "required_continuity": "C1",
                "intent": "smooth_connection",
                "source_requirement_refs": ["req-c1"],
            }],
        }],
    }
    replacement = deepcopy(plan["steps"][0])
    replacement.pop("junction_constraints", None)
    context = {
        "plan": plan,
        "construction_error": {
            "assertion_id": None,
            "details": {"affected_output_refs": ["junction-curve"]},
        },
    }
    result = merge_component_repair(context, {"plan": {"units": "m", "steps": [replacement]}})
    merged_step = result["plan"]["steps"][0]
    return {
        "status": "reproduced" if "junction_constraints" not in merged_step else "not_reproduced",
        "before_keys": sorted(plan["steps"][0]),
        "after_keys": sorted(merged_step),
        "junction_constraints_preserved": "junction_constraints" in merged_step,
        "before_plan_sha256": canonical_sha256(plan),
        "after_plan_sha256": canonical_sha256(result["plan"]),
    }


def main() -> int:
    output = {
        "schema": "cad.d0.geometry-probe.v1",
        "real_model_calls": 0,
        "project_persistence": False,
        "a9_reconstructed": run_plan(a9_plan()),
        "s1_reconstructed": run_plan(s1_plan()),
        "a9_junction_constraints_merge": junction_repair_probe(),
        "plan_hashes": {
            "a9_reconstructed": canonical_sha256(a9_plan()),
            "s1_reconstructed": canonical_sha256(s1_plan()),
        },
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
