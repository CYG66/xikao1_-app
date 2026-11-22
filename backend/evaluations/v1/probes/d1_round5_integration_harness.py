"""Round-5 D-line integration harness: wire B's real geometry judge into C's M3 gate.

Zero model calls, zero network. The production loop and classifier run for
real against the round5 combo tree; only the per-attempt model text outlet
(`_interpret_cad_construction_plan`) is stubbed with controlled
interpretations. B's ``trajectory_equivalent`` is injected through C's
public ``set_geometry_evaluator`` hook; no production file is modified.

Outputs a structured JSON snapshot. Relation-name translation between B
(``equivalent``) and C's internal gate vocabulary (``identical``) is recorded
explicitly as an adapter observation.

Usage:
    python d1_round5_integration_harness.py \
        --combo-backend <combo/backend> --combo-probes <combo probes dir> \
        --d-probes <D probes dir> --out <round5/integration_results.json>
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import pathlib
import sys
import tempfile
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

REF = "outline"
SOURCE = "新建CAD图纸，生成一个闭合轮廓，整体宽4米高4米，坐标单位米"


def _circle(cx, cy, r, n=120, t0=0.0, t1=2 * math.pi):
    return [(cx + r * math.cos(t0 + (t1 - t0) * k / n),
             cy + r * math.sin(t0 + (t1 - t0) * k / n)) for k in range(n + 1)]


def _geom(pts, closed=True):
    return [{"id": REF, "type": "polyline", "closed": closed, "points": pts}]


def _plan(t_start=0):
    return {"units": "m", "steps": [{
        "op": "add_parametric_curve", "step_id": "s1", "output_ref": REF,
        "x_expression": "2+2*sin(t)", "y_expression": "3+2*cos(t)",
        "t_start": t_start, "t_end": "2*pi",
        "semantic": {"label": REF, "object_id": REF, "assembly_id": "whole"},
    }], "assertions": [{"kind": "bounds_size", "assertion_id": "size",
                        "width": 4, "height": 4}]}


def _invalid(details, code="structure_requirement_failed", plan=None, geom=None,
             message="构造计划未通过验证"):
    result = {
        "schema": "cad.construction-interpretation-result.v1",
        "status": "invalid", "provider_attempted": True,
        "construction_error": {"code": code, "message": message,
                              "details": deepcopy(details)},
        "error": {"code": code, "message": message},
        "plan": deepcopy(plan or _plan()),
    }
    if geom is not None:
        result["trial_result"] = {"geometries": deepcopy(geom)}
    return result


def _ready(plan):
    return {"schema": "cad.construction-interpretation-result.v1",
            "status": "ready", "provider_attempted": True,
            "confidence": 0.95, "plan": deepcopy(plan)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--combo-backend", required=True)
    ap.add_argument("--combo-probes", required=True)
    ap.add_argument("--d-probes", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    combo_backend = pathlib.Path(args.combo_backend).resolve()
    combo_probes = pathlib.Path(args.combo_probes).resolve()
    d_probes = pathlib.Path(args.d_probes).resolve()

    # 1. Isolation env BEFORE any app module import / singleton construction.
    iso_root = pathlib.Path(tempfile.mkdtemp(prefix="xline-d1-round5-"))
    sys.path.insert(0, str(d_probes))
    from d1_round4_isolation_collector import prepare_isolation_env  # noqa: PLC0415
    env = prepare_isolation_env(iso_root, "INTEGRATION")

    sys.path.insert(0, str(combo_backend))
    sys.path.insert(0, str(combo_probes))

    from app import cad_generation_recovery as recovery  # noqa: PLC0415
    from app.agent_service import RobotAgentService  # noqa: PLC0415
    from app.creative_projects import CreativeProjectStore  # noqa: PLC0415
    import b_round5_geometry_contract as gc  # noqa: PLC0415

    # ---- B -> C adapter ---------------------------------------------------- #
    def _to_ns(spec):
        geoms = (spec or {}).get("geometries") or []
        pts = []
        closed = None
        for g in geoms:
            if not isinstance(g, dict):
                continue
            raw = g.get("points")
            if raw is None and g.get("vertices"):
                raw = [(v["x"], v["y"]) for v in g["vertices"]]
            if raw:
                pts += [tuple(p) for p in raw]
            closed = g.get("closed", closed)
        if not pts:
            return None
        return SimpleNamespace(points=pts, closed=closed)

    def b_adapter(spec_a, spec_b, tolerance):
        a, b = _to_ns(spec_a), _to_ns(spec_b)
        if a is None or b is None:
            return {"equivalent": None, "undetermined": True,
                    "relation": "missing_snapshot", "reversed": False,
                    "checks": {}, "fail_reasons": ["geometry snapshot unavailable"],
                    "raw_b_relation": "missing"}
        r = gc.trajectory_equivalent(a, b, tolerance or 1e-6)
        # B reports relation "equivalent"; C's gate vocabulary expects
        # "identical" for a determined-equivalent pair. Record both.
        mapped = "identical" if r.relation == "equivalent" else r.relation
        return {"equivalent": r.equivalent, "undetermined": r.undetermined,
                "relation": mapped, "raw_b_relation": r.relation,
                "reversed": r.reversed, "checks": r.checks,
                "fail_reasons": r.fail_reasons,
                "hausdorff_normalized": r.hausdorff_normalized}

    recovery.set_geometry_evaluator(b_adapter)

    report: dict[str, object] = {
        "schema": "cad.d1.round5.integration.v1",
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "isolation_root": str(iso_root),
        "env_targets_inside_root": env,
        "real_model_calls": 0,
        "network_probe": "none",
        "adapter": "B trajectory_equivalent injected via set_geometry_evaluator; no production file changed",
    }

    # ---- 2. Unit-level M3 judgement table (real B judge) -------------------- #
    circle_a = _circle(2, 3, 1.5)
    circle_b_domain = _circle(2, 3, 1.5, t0=-math.pi, t1=math.pi)
    circle_big = _circle(2, 3, 2.0)
    circle_rev = list(reversed(circle_a))
    circle_scaled = [(2 + (x - 2) * 1.2, 3 + (y - 3) * 1.2) for x, y in circle_a]

    def feat(failed, measured=None):
        return {"construction_error": {"code": "structure_requirement_failed",
                "details": {"check": "outline", "failed_features": failed,
                            "measured_features": measured or {f: False for f in failed}}}}

    unit_cases: list[dict[str, object]] = []

    def run_unit(name, before, after, expect_decision, expect_progress):
        outcome = recovery.evaluate_repair_progress(before, after)
        unit_cases.append({
            "case": name,
            "expected_decision": expect_decision,
            "expected_progress": expect_progress,
            "actual_decision": outcome["decision"],
            "actual_progress": outcome["progress"],
            "geometry": outcome["geometry"],
            "match": outcome["decision"] == expect_decision,
        })

    # Positive: same trajectory (parametric domain shift), unchanged vector -> block.
    run_unit("M3-POS-equiv-param-domain-shift-block",
             _invalid({"check": "outline", "failed_features": ["cusp"],
                       "measured_features": {"cusp": False}}, geom=_geom(circle_a)),
             _invalid({"check": "outline", "failed_features": ["cusp"],
                       "measured_features": {"cusp": False}}, plan=_plan(3),
                      geom=_geom(circle_b_domain)),
             "block", "stalled_equivalent")

    # Negative: geometry changed (radius) -> allow.
    run_unit("M3-NEG-geometry-changed-allow",
             _invalid({"failed_features": ["cusp"], "measured_features": {"cusp": False}},
                      geom=_geom(circle_a)),
             _invalid({"failed_features": ["cusp"], "measured_features": {"cusp": False}},
                      plan=_plan(3), geom=_geom(circle_big)),
             "allow", "geometry_changed")

    # Negative: previously failed feature improved -> allow.
    run_unit("M3-NEG-feature-improved-allow",
             feat(["cusp", "side"], {"cusp": True, "side": False}),
             feat(["side"], {"cusp": True, "side": False}),
             "allow", "feature_improved")

    # Negative: new failure surfaced -> allow.
    run_unit("M3-NEG-new-failure-allow",
             feat(["cusp"]), feat(["cusp", "side"]),
             "allow", "new_failure")

    # Negative: reversed traversal (same point set, opposite direction) -> allow.
    run_unit("M3-NEG-reversed-trajectory-allow",
             _invalid({"failed_features": ["cusp"], "measured_features": {"cusp": False}},
                      geom=_geom(circle_a)),
             _invalid({"failed_features": ["cusp"], "measured_features": {"cusp": False}},
                      plan=_plan(3), geom=_geom(circle_rev)),
             "allow", None)

    # Negative: similarity-transformed (scale) compliant change -> allow.
    run_unit("M3-NEG-similarity-transform-allow",
             _invalid({"failed_features": ["cusp"], "measured_features": {"cusp": False}},
                      geom=_geom(circle_a)),
             _invalid({"failed_features": ["cusp"], "measured_features": {"cusp": False}},
                      plan=_plan(3), geom=_geom(circle_scaled)),
             "allow", None)

    # Negative: missing geometry snapshot -> undetermined release.
    run_unit("M3-NEG-missing-snapshot-allow",
             _invalid({"failed_features": ["cusp"], "measured_features": {"cusp": False}}),
             _invalid({"failed_features": ["cusp"], "measured_features": {"cusp": False}},
                      plan=_plan(3)),
             "allow", "undetermined")

    # First repair always allowed.
    run_unit("M3-FIRST-repair-allowed", None, feat(["cusp"]),
             "allow", "first_repair")

    report["m3_unit_cases"] = unit_cases
    report["m3_unit_summary"] = {
        "total": len(unit_cases),
        "matched": sum(c["match"] for c in unit_cases),
        "blocked": sum(c["actual_decision"] == "block" for c in unit_cases),
        "allowed": sum(c["actual_decision"] == "allow" for c in unit_cases),
    }

    # ---- 3. Production-loop level: real loop, stubbed model outlet --------- #
    def run_loop(queue, tmp_path):
        service = RobotAgentService(restore_pending_actions=False)
        service.mode = "deepseek"
        store = CreativeProjectStore(tmp_path / "projects.json")
        project = store.create("轮廓", SOURCE,
            requirements={"shape": "generic_2d_cad", "dimensions": {"width_m": 4, "height_m": 4}},
            missing_parameters=[])
        calls = []

        def interpret(text, **kwargs):
            entry = queue.pop(0)
            calls.append({"text": text, "kwargs": kwargs, "result": deepcopy(entry)})
            return entry

        route = {"name": "drawing_design", "operation": "create",
                 "stage": "candidate_generation", "selected_project_id": project["id"]}
        with patch("app.agent_service.get_creative_project_store", return_value=store), \
             patch.object(service, "_interpret_cad_construction_plan", side_effect=interpret):
            result = service._formal_cad_construction(SOURCE, route, mode="advanced")
        return result, calls, store, project

    loop_cases: list[dict[str, object]] = []

    # Positive stall: identical trajectory + unchanged vector; third request avoided.
    details = {"check": "outline", "failed_features": ["cusp"],
               "measured_features": {"cusp": False}, "affected_output_refs": [REF]}
    a1 = _invalid(details, plan=_plan(0), geom=_geom(circle_a), message="失败轮次1")
    a2 = _invalid(details, plan=_plan(3), geom=_geom(circle_b_domain), message="失败轮次2")
    result, calls, store, project = run_loop([a1, a2], iso_root)
    interp = result.get("construction_interpretation") or {}
    loop_cases.append({
        "case": "M3-LOOP-positive-stall-blocks-third-request",
        "expected_calls": 2, "actual_calls": len(calls),
        "third_request_avoided": len(calls) == 2,
        "error_code": (interp.get("error") or {}).get("code"),
        "progress": interp.get("progress"),
        "variants": store.get(project["id"]).get("variants") or [],
        "match": len(calls) == 2 and (interp.get("error") or {}).get("code") == "no_progress",
    })

    # Missing snapshot: undetermined release; third request issued.
    b1 = _invalid(details, plan=_plan(0), message="失败轮次1")
    b2 = _invalid(details, plan=_plan(3), message="失败轮次2")
    b3 = _invalid(details, plan=_plan(6), message="失败轮次3")
    result, calls, store, project = run_loop([b1, b2, b3], iso_root)
    interp = result.get("construction_interpretation") or {}
    loop_cases.append({
        "case": "M3-LOOP-missing-snapshot-releases",
        "expected_calls": 3, "actual_calls": len(calls),
        "second_progress": (interp.get("recovery") or {}).get("progress_log", [{}])[0],
        "match": len(calls) == 3,
    })

    report["m3_loop_cases"] = loop_cases

    # ---- 4. M2 four-channel production-loop feedback ----------------------- #
    def channel_details(channel):
        common = {"affected_output_refs": [REF]}
        if channel == "parameter_repair":
            return {**common, "check": "explicit_center",
                    "measured_center_mm": [1.0, 1.0], "expected_center_mm": [2.0, 3.0],
                    "error_mm": 1.2, "tolerance_mm": 0.5,
                    "required_features": {"center": "center at (2,3)"},
                    "measured_features": {"center": False}, "failed_features": ["center"]}
        if channel == "connection_repair":
            return {**common, "reference_geometry_id": "outer", "check": "containment",
                    "required_features": {"inner": "inner part inside outer"},
                    "measured_features": {"inner": False}, "failed_features": ["inner"]}
        if channel == "feature_replan":
            return {**common, "required_features": {"cusp": "lower center cusp"},
                    "measured_features": {"cusp": False}, "failed_features": ["cusp"],
                    "geometry_ids": [REF]}
        return {**common, "endpoint_degrees": [1, 1, 2], "closed_region_count": 0,
                "expected_count": 2, "actual_count": 1, "geometry_ids": [REF],
                "measured_features": {"closed_region": False},
                "failed_features": ["closed_region"]}

    m2_cases: list[dict[str, object]] = []
    for channel, structural in [("parameter_repair", False), ("connection_repair", False),
                                ("feature_replan", True), ("topology_replan", True)]:
        details = channel_details(channel)
        code = "constraint_conflict" if channel == "topology_replan" else "structure_requirement_failed"
        first = _invalid(details, code=code)
        second = _invalid(details, code=code, plan=_plan(t_start=3))
        result, calls, store, project = run_loop([first, second], iso_root)
        prompt = calls[1]["text"] if len(calls) > 1 else ""
        block = None
        if "修复范围判定：" in prompt:
            raw = prompt.split("修复范围判定：", 1)[1]
            block = json.JSONDecoder().raw_decode(raw)[0]
        kwargs = calls[1]["kwargs"] if len(calls) > 1 else {}
        structural_bypass = ("component_repair_context" not in kwargs
                             and "repair_context" not in kwargs)
        m2_cases.append({
            "channel": channel,
            "expected_structural": structural,
            "calls": len(calls),
            "feedback_block": block,
            "four_elements_present": bool(block and block.get("expected_feature") is not None
                                         and block.get("measured_feature") is not None
                                         and "difference" in block and "repair_class" in block),
            "structural_bypasses_ref_merger": structural_bypass if structural else None,
            "non_structural_carries_component_context":
                (kwargs.get("component_repair_context") is not None) if not structural else None,
            "match": bool(block and block["repair_class"] == channel
                          and block["requires_structural_replan"] is structural),
        })

    report["m2_cases"] = m2_cases
    report["m2_summary"] = {
        "total": len(m2_cases),
        "matched": sum(c["match"] for c in m2_cases),
        "structural_channels": [c["channel"] for c in m2_cases if c["expected_structural"]],
        "non_structural_channels": [c["channel"] for c in m2_cases if not c["expected_structural"]],
    }

    # ---- 5. Classifier unit spot checks (four channels + degraded default) - #
    classifier_cases = []
    samples = [
        ({"measured_center_mm": [1.0, 1.0], "expected_center_mm": [2.0, 3.0],
          "error_mm": 1.2, "tolerance_mm": 0.5, "measured_features": {"center": False},
          "failed_features": ["center"]}, "structure_requirement_failed",
         "parameter_repair", False),
        ({"reference_geometry_id": "outer", "measured_features": {"inner": False},
          "failed_features": ["inner"]}, "structure_requirement_failed",
         "connection_repair", False),
        ({"required_features": {"cusp": "x"}, "measured_features": {"cusp": False},
          "failed_features": ["cusp"], "geometry_ids": [REF]},
         "structure_requirement_failed", "feature_replan", True),
        ({"endpoint_degrees": [1, 1, 2], "closed_region_count": 0,
          "expected_count": 2, "actual_count": 1, "geometry_ids": [REF]},
         "constraint_conflict", "topology_replan", True),
        ({}, "invalid_model_output", "parameter_repair", False),
    ]
    for details, code, expected_class, expected_struct in samples:
        out = recovery.classify_feature_failure(details, code)
        classifier_cases.append({
            "details_keys": sorted(details), "code": code,
            "outcome": out,
            "match": out["repair_class"] == expected_class
                     and out["requires_structural_replan"] is expected_struct,
        })
    report["m2_classifier_cases"] = classifier_cases

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                   encoding="utf-8")
    print(json.dumps({"out": str(out),
                      "m3_unit": report["m3_unit_summary"],
                      "m2": report["m2_summary"],
                      "loop": [ (c["case"], c["actual_calls"]) for c in loop_cases ]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
