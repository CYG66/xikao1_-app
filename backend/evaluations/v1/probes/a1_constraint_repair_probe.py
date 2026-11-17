"""Zero-cost A1 evidence probe: generic constraint inheritance at the merge boundary."""
from copy import deepcopy
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.cad_plan_component_repair import (
    ComponentRepairError,
    merge_component_repair,
)


def point(x, y):
    return {"x": x, "y": y}


def canonical_sha256(value):
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def fixture():
    return {
        "schema_version": "cad.construction-plan.v1",
        "units": "m",
        "steps": [{
            "op": "add_composite_path",
            "step_id": "a1-junction-step",
            "output_ref": "a1-junction-curve",
            "layer_id": 1,
            "semantic": {"object_type": "drawing_part", "label": "A1 generic junction fixture"},
            "segments": [
                {"kind": "line", "start": point(0, 0), "end": point(1, 0)},
                {"kind": "line", "start": point(1, 0), "end": point(1, 1)},
            ],
            "closed": False,
            "samples_per_curve": 64,
            "connection_tolerance": 0.000001,
            "continuity": "C1",
            "tangent_tolerance_deg": 0.01,
            "allow_self_intersection": False,
            "allow_duplicate_segments": False,
            "junction_constraints": [{
                "junction_index": 0,
                "left_segment_index": 0,
                "right_segment_index": 1,
                "intent": "smooth",
                "required_continuity": "C1",
                "tangent_tolerance_deg": 0.01,
                "source_requirement_refs": ["user:0"],
            }],
        }],
    }


def context(plan):
    return {
        "plan": plan,
        "construction_error": {"details": {"affected_output_refs": ["a1-junction-curve"]}},
    }


def payload(step):
    return {"plan": {"units": "m", "steps": [step]}}


def main():
    plan = fixture()
    replacement = deepcopy(plan["steps"][0])
    for key in ("junction_constraints", "continuity", "tangent_tolerance_deg"):
        replacement.pop(key, None)

    merged = merge_component_repair(context(plan), payload(replacement))
    merged_step = merged["plan"]["steps"][0]

    clear = deepcopy(plan["steps"][0])
    clear["junction_constraints"] = []
    clear_code = None
    try:
        merge_component_repair(context(plan), payload(clear))
    except ComponentRepairError as exc:
        clear_code = exc.code

    reorder = deepcopy(plan["steps"][0])
    reorder["segments"] = list(reversed(reorder["segments"]))
    for key in ("junction_constraints", "continuity", "tangent_tolerance_deg"):
        reorder.pop(key, None)
    reorder_code = None
    try:
        merge_component_repair(context(plan), payload(reorder))
    except ComponentRepairError as exc:
        reorder_code = exc.code

    print(json.dumps({
        "schema": "cad.a1-constraint-repair-probe.v1",
        "before_plan_sha256": canonical_sha256(plan),
        "replacement_without_constraints_sha256": canonical_sha256(payload(replacement)),
        "after_plan_sha256": canonical_sha256(merged["plan"]),
        "junction_constraints_preserved": merged_step.get("junction_constraints") == plan["steps"][0]["junction_constraints"],
        "continuity_preserved": merged_step.get("continuity") == "C1",
        "tangent_tolerance_preserved": merged_step.get("tangent_tolerance_deg") == 0.01,
        "explicit_clear_error_code": clear_code,
        "segment_reorder_error_code": reorder_code,
        "real_model_calls": 0,
        "project_persistence": False,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
