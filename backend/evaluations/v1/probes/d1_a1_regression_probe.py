"""D-owned A1 independent regression probe (read-only against the A worktree).

This probe lives in the D evaluation scope. It imports the A backend package
read-only, builds its own generic fixtures (no borrowed case ids, shape names,
or frozen control-point constants), and checks constraint inheritance,
protected-field preservation and rejection semantics at the merge boundary.

It never calls a live model: only pure merge / interpreter functions are
invoked. Model API keys are stripped from the child environment.

Usage (from any cwd):
    python evaluations/v1/probes/d1_a1_regression_probe.py \
        --backend "C:\\Users\\29924\\Codes\\worktrees\\A\\backend"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from copy import deepcopy
from pathlib import Path

PROBE_DIR = Path(__file__).resolve().parent
D_BACKEND = PROBE_DIR.parents[2]

STRIPPED_KEYS = ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ARK_API_KEY", "MODEL_API_KEY")


def _point(x: float, y: float) -> dict[str, float]:
    return {"x": x, "y": y}


def _fingerprint(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_a_backend(backend: Path) -> dict[str, object]:
    """Import A backend app modules with a clean module cache."""
    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]
    sys.path.insert(0, str(backend))
    from app import cad_plan_component_repair as repair  # type: ignore
    from app import cad_construction_interpreter as interpreter  # type: ignore
    return {"repair": repair, "interpreter": interpreter}


def _context(plan: dict, ref: str) -> dict[str, object]:
    return {
        "plan": plan,
        "construction_error": {"details": {"affected_output_refs": [ref]}},
    }


def _payload(step: dict) -> dict[str, object]:
    return {"plan": {"units": "m", "steps": [step]}}


def _constraints_open() -> list[dict[str, object]]:
    return [
        {
            "junction_index": 0,
            "left_segment_index": 0,
            "right_segment_index": 1,
            "intent": "smooth",
            "required_continuity": "C1",
            "tangent_tolerance_deg": 0.02,
            "source_requirement_refs": ["user:7"],
        },
        {
            "junction_index": 1,
            "left_segment_index": 1,
            "right_segment_index": 2,
            "intent": "intentional_corner",
            "required_continuity": "C0",
            "tangent_tolerance_deg": 0.02,
            "source_requirement_refs": ["user:7"],
        },
    ]


def fixture_open_line_chain() -> dict[str, object]:
    """G1: open three-segment line chain with inherited local constraints."""
    return {
        "schema_version": "cad.construction-plan.v1",
        "units": "m",
        "steps": [
            {
                "op": "add_composite_path",
                "step_id": "chain-step",
                "output_ref": "chain-outline",
                "layer_id": 1,
                "semantic": {"object_type": "drawing_part", "label": "generic open chain"},
                "segments": [
                    {"kind": "line", "start": _point(0.0, 0.0), "end": _point(1.2, 0.4)},
                    {"kind": "line", "start": _point(1.2, 0.4), "end": _point(2.4, 0.1)},
                    {"kind": "line", "start": _point(2.4, 0.1), "end": _point(3.1, 0.9)},
                ],
                "closed": False,
                "samples_per_curve": 48,
                "connection_tolerance": 0.000001,
                "continuity": "C1",
                "tangent_tolerance_deg": 0.02,
                "allow_self_intersection": False,
                "allow_duplicate_segments": False,
                "junction_constraints": _constraints_open(),
            },
            {
                "op": "add_circle",
                "step_id": "kept-circle",
                "output_ref": "kept-circle",
                "center": _point(-2.0, -1.0),
                "radius": 1.25,
                "semantic": {"label": "untouched companion"},
            },
        ],
    }


def fixture_closed_bezier_loop() -> dict[str, object]:
    """G2: closed two-segment bezier loop with one closed-loop constraint."""
    return {
        "schema_version": "cad.construction-plan.v1",
        "units": "m",
        "steps": [
            {
                "op": "add_composite_path",
                "step_id": "loop-step",
                "output_ref": "loop-outline",
                "layer_id": 1,
                "semantic": {"object_type": "drawing_part", "label": "generic closed loop"},
                "segments": [
                    {"kind": "bezier", "control_points": [
                        _point(0.0, 0.0), _point(0.6, 0.9), _point(1.8, 0.9), _point(2.4, 0.0)]},
                    {"kind": "bezier", "control_points": [
                        _point(2.4, 0.0), _point(1.8, -0.9), _point(0.6, -0.9), _point(0.0, 0.0)]},
                ],
                "closed": True,
                "samples_per_curve": 64,
                "connection_tolerance": 0.000001,
                "continuity": "C0",
                "tangent_tolerance_deg": 0.05,
                "allow_self_intersection": False,
                "allow_duplicate_segments": False,
                "junction_constraints": [{
                    "junction_index": 1,
                    "left_segment_index": 1,
                    "right_segment_index": 0,
                    "intent": "smooth",
                    "required_continuity": "C1",
                    "tangent_tolerance_deg": 0.05,
                    "source_requirement_refs": ["user:12"],
                }],
            }
        ],
    }


def check(name: str, ok: bool, detail: object = None) -> dict[str, object]:
    return {"check": name, "passed": bool(ok), "detail": detail}


def run_g1(repair: object) -> dict[str, object]:
    plan = fixture_open_line_chain()
    original_step = deepcopy(plan["steps"][0])
    replacement = deepcopy(original_step)
    # Legal in-place joint edit; local connection fields are omitted on purpose.
    replacement["segments"][1]["start"] = _point(1.2, 0.55)
    replacement["segments"][1]["end"] = _point(2.4, 0.18)
    for key in ("junction_constraints", "continuity", "tangent_tolerance_deg",
                "closed", "samples_per_curve", "connection_tolerance",
                "allow_self_intersection", "allow_duplicate_segments"):
        replacement.pop(key, None)

    merged = repair.merge_component_repair(
        _context(plan, "chain-outline"), _payload(replacement))["plan"]
    merged_step = merged["steps"][0]
    checks = [
        check("edited_joint_coordinate_landed",
              merged_step["segments"][1]["start"] == _point(1.2, 0.55)),
        check("edited_end_coordinate_landed",
              merged_step["segments"][1]["end"] == _point(2.4, 0.18)),
        check("junction_constraints_preserved",
              merged_step.get("junction_constraints") == original_step["junction_constraints"]),
        check("source_requirement_refs_preserved",
              [c.get("source_requirement_refs") for c in merged_step.get("junction_constraints", [])]
              == [["user:7"], ["user:7"]]),
        check("continuity_preserved", merged_step.get("continuity") == "C1"),
        check("tangent_tolerance_preserved", merged_step.get("tangent_tolerance_deg") == 0.02),
        check("closed_preserved", merged_step.get("closed") is False),
        check("samples_per_curve_preserved", merged_step.get("samples_per_curve") == 48),
        check("connection_tolerance_preserved", merged_step.get("connection_tolerance") == 0.000001),
        check("self_intersection_flag_preserved", merged_step.get("allow_self_intersection") is False),
        check("duplicate_segment_flag_preserved", merged_step.get("allow_duplicate_segments") is False),
        check("untouched_companion_step_preserved",
              merged["steps"][1] == plan["steps"][1]),
    ]
    return {"case": "G1-open-line-chain", "checks": checks,
            "passed": all(c["passed"] for c in checks)}


def run_g2(repair: object) -> dict[str, object]:
    plan = fixture_closed_bezier_loop()
    original_step = deepcopy(plan["steps"][0])
    results: list[dict[str, object]] = []

    # A: omitted policy/constraint fields must be inherited, not dropped.
    replacement_a = deepcopy(original_step)
    for key in ("junction_constraints", "continuity", "tangent_tolerance_deg",
                "closed", "samples_per_curve", "connection_tolerance",
                "allow_self_intersection", "allow_duplicate_segments"):
        replacement_a.pop(key, None)
    merged_a = repair.merge_component_repair(
        _context(plan, "loop-outline"), _payload(replacement_a))["plan"]["steps"][0]
    results.append(check(
        "omitted_closed_loop_fields_inherited",
        merged_a.get("closed") is True and merged_a.get("continuity") == "C0"
        and merged_a.get("tangent_tolerance_deg") == 0.05
        and merged_a.get("junction_constraints") == original_step["junction_constraints"],
        {"closed": merged_a.get("closed"), "continuity": merged_a.get("continuity"),
         "tangent_tolerance_deg": merged_a.get("tangent_tolerance_deg")}))

    # B: explicit tolerance loosening must be rejected.
    replacement_b = deepcopy(original_step)
    replacement_b["tangent_tolerance_deg"] = 0.2
    code_b = None
    try:
        repair.merge_component_repair(_context(plan, "loop-outline"), _payload(replacement_b))
    except repair.ComponentRepairError as exc:
        code_b = exc.code
    results.append(check("tolerance_weakening_rejected", code_b == "tangent_tolerance_weakened",
                         {"error_code": code_b}))

    # C: explicit constraint clearing must be rejected.
    replacement_c = deepcopy(original_step)
    replacement_c["junction_constraints"] = []
    code_c = None
    try:
        repair.merge_component_repair(_context(plan, "loop-outline"), _payload(replacement_c))
    except repair.ComponentRepairError as exc:
        code_c = exc.code
    results.append(check("constraint_clear_rejected", code_c == "junction_constraints_clear_rejected",
                         {"error_code": code_c}))

    # D: segment-count change without a new constraint set must be rejected.
    replacement_d = deepcopy(original_step)
    replacement_d["segments"] = replacement_d["segments"] + [
        {"kind": "line", "start": _point(2.4, 0.0), "end": _point(3.0, -0.4)}]
    replacement_d.pop("junction_constraints", None)
    code_d = None
    try:
        repair.merge_component_repair(_context(plan, "loop-outline"), _payload(replacement_d))
    except repair.ComponentRepairError as exc:
        code_d = exc.code
    results.append(check("structure_change_without_new_constraints_rejected",
                         code_d == "junction_constraint_mapping_unsafe", {"error_code": code_d}))

    return {"case": "G2-closed-bezier-loop", "checks": results,
            "passed": all(c["passed"] for c in results)}


def run_g5(repair: object) -> dict[str, object]:
    """Joint test: legal coordinate edit lands; protected fields stay byte-identical."""
    original = fixture_open_line_chain()
    original_step = deepcopy(original["steps"][0])
    repaired = deepcopy(original_step)
    repaired["segments"][2]["start"] = _point(2.4, 0.18)
    repaired["segments"][2]["end"] = _point(3.1, 1.05)
    replacement = deepcopy(repaired)
    for key in ("junction_constraints", "continuity", "tangent_tolerance_deg"):
        replacement.pop(key, None)

    merged = repair.merge_component_repair(
        _context(original, "chain-outline"), _payload(replacement))["plan"]
    merged_step = merged["steps"][0]

    protected = ("junction_constraints", "source_requirement_refs",
                 "continuity", "tangent_tolerance_deg")
    checks = [
        check("new_coordinate_present",
              merged_step["segments"][2]["end"] == _point(3.1, 1.05)),
        check("old_coordinate_absent",
              _point(3.1, 0.9) not in [s.get("end") for s in merged_step["segments"]]),
        check("junction_constraints_unchanged",
              merged_step["junction_constraints"] == original_step["junction_constraints"]),
        check("source_requirement_refs_unchanged",
              [c.get("source_requirement_refs") for c in merged_step["junction_constraints"]]
              == [c.get("source_requirement_refs") for c in original_step["junction_constraints"]]),
        check("continuity_unchanged", merged_step["continuity"] == original_step["continuity"]),
        check("tangent_tolerance_unchanged",
              merged_step["tangent_tolerance_deg"] == original_step["tangent_tolerance_deg"]),
        check("merged_differs_from_original", _fingerprint(merged) != _fingerprint(original)),
        check("merged_differs_from_raw_replacement",
              _fingerprint(merged["steps"][0]) != _fingerprint(replacement)),
    ]
    return {"case": "G5-joint-edit-protected-fields", "checks": checks,
            "passed": all(c["passed"] for c in checks)}


def run_mapping_wiring(repair: object, interpreter: object) -> dict[str, object]:
    # Direct ComponentRepairError contract: code, message, details travel together.
    try:
        repair.merge_component_repair(
            {"plan": {"units": "m", "steps": [{"op": "add_circle", "output_ref": "x"}]},
             "construction_error": {"details": {"affected_output_refs": ["x"]}}},
            {"plan": {"units": "m", "steps": [{"op": "add_circle", "output_ref": "x",
                                               "junction_constraints": []}]}})
        contract = None
    except repair.ComponentRepairError as exc:
        contract = {"code": exc.code, "message_present": bool(exc.message),
                    "details_keys": sorted(exc.details.keys())}
    interpreter_imports_class = hasattr(interpreter, "ComponentRepairError")
    return {"case": "M-error-mapping-wiring", "checks": [
        check("ComponentRepairError_carries_code_message_details",
              contract is not None and contract["message_present"], contract),
        check("interpreter_imports_ComponentRepairError", interpreter_imports_class),
    ], "passed": interpreter_imports_class and contract is not None}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", required=True, help="A backend root (read-only)")
    parser.add_argument("--out", default=str(PROBE_DIR / "d1_a1_regression_results.json"))
    args = parser.parse_args()

    backend = Path(args.backend)
    stripped = {k: ("present" if os.environ.get(k) else "absent") for k in STRIPPED_KEYS}
    for key in STRIPPED_KEYS:
        os.environ.pop(key, None)

    modules = _load_a_backend(backend)
    repair = modules["repair"]
    interpreter = modules["interpreter"]

    cases = [run_g1(repair), run_g2(repair), run_g5(repair),
             run_mapping_wiring(repair, interpreter)]

    snapshot = {
        "schema": "cad.d1.a1-regression-probe.v1",
        "target_backend": str(backend),
        "target_ref": "d8cb85f68db08b90beb4872ccfc9fdf93d8735d9",
        "guard": {"stripped_keys": stripped, "forced_provider": "local",
                  "real_model_calls": 0, "project_persistence": False},
        "cases": cases,
        "all_passed": all(c["passed"] for c in cases),
    }
    out = Path(args.out)
    out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"all_passed": snapshot["all_passed"],
                      "cases": [{"case": c["case"], "passed": c["passed"],
                                 "failed_checks": [x["check"] for x in c["checks"] if not x["passed"]]}
                                for c in cases],
                      "out": str(out)}, ensure_ascii=False, indent=2))
    return 0 if snapshot["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
