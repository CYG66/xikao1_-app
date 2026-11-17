"""C1.3 M2 feature-contract classification + M3 stalled-progress gate.

Production entry under test: ``RobotAgentService._formal_cad_construction``.
The repair loop, failure capture, context routing, classifier, progress gate,
recovery record and isolated persistence all run for real.

Mock boundary: the per-attempt producer ``_interpret_cad_construction_plan``
is stubbed to return controlled interpretations (the model text outlet and
executor are not exercised here). The loop itself is NOT replaced, no real
DeepSeek/network request is made, and no acceptance criterion is lowered.

M3 judgement table (stalled_equivalent requires BOTH conditions together):
  - identical executed geometry AND unchanged failure vector -> block;
  - feature improved / new failure / geometry changed / undetermined /
    missing snapshot -> allow;
  - the first repair is always allowed.

M2 classifier contract (aligned with A proposals/feature_contract_fields):
  classify_feature_failure(details, code) ->
    {repair_class, requires_structural_replan, reason, missing_fields}
  Classes: parameter_repair / connection_repair / feature_replan /
  topology_replan. Only structured fields are read; there is no feature-name
  or request-string branch.
"""
from __future__ import annotations

import json
from copy import deepcopy
from unittest.mock import patch

import pytest

from app.agent_service import RobotAgentService
from app.creative_projects import CreativeProjectStore
from app.cad_generation_recovery import (
    classify_feature_failure, evaluate_repair_progress,
    set_geometry_evaluator,
)


SOURCE = "新建CAD图纸，生成一个闭合轮廓，整体宽4米高4米，坐标单位米"
REF = "outline"

GEOM = [{"id": REF, "type": "polyline", "closed": True,
         "vertices": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}]}]
GEOM_OTHER = [{"id": REF, "type": "polyline", "closed": True,
               "vertices": [{"x": 0.0, "y": 0.0}, {"x": 2.0, "y": 2.0}]}]


def _stub_evaluator(relation="identical", equivalent=True, undetermined=False,
                    reversed_flag=False):
    """B-semantics test double (NOT the real B judge). Mirrors
    ``trajectory_equivalent`` result fields: relation / equivalent /
    undetermined / reversed / checks / fail_reasons. Real judgement is left
    to the D-run A+B+C combo tree.
    """
    def _fn(spec_a, spec_b, tolerance):
        return {"equivalent": equivalent, "undetermined": undetermined,
                "relation": relation, "reversed": reversed_flag,
                "checks": {"geometry": "pass", "orientation": "pass",
                           "endpoints": "pass", "closed": "pass",
                           "topology": "pass", "transformation": "n/a"},
                "fail_reasons": []}
    return _fn


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


def _feedback_block(prompt):
    raw = prompt.split("修复范围判定：", 1)[1]
    return json.JSONDecoder().raw_decode(raw)[0]


def _run(queue, tmp_path):
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


# ---------------------------------------------------------------------------
# M2 classifier: four channels, no string feature-name matching
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("details,code,expected_class,structural", [
    ({"check": "explicit_center", "measured_center_mm": [1.0, 1.0],
      "expected_center_mm": [2.0, 3.0], "error_mm": 1.2, "tolerance_mm": 0.5,
      "measured_features": {"center": False}, "failed_features": ["center"]},
     "structure_requirement_failed", "parameter_repair", False),
    ({"reference_geometry_id": "outer", "check": "containment",
      "measured_features": {"inner": False}, "failed_features": ["inner"]},
     "structure_requirement_failed", "connection_repair", False),
    ({"required_features": {"cusp": "lower center cusp"},
      "measured_features": {"cusp": False}, "failed_features": ["cusp"],
      "geometry_ids": [REF]},
     "structure_requirement_failed", "feature_replan", True),
    ({"endpoint_degrees": [1, 1, 2], "closed_region_count": 0,
      "expected_count": 2, "actual_count": 1, "geometry_ids": [REF]},
     "constraint_conflict", "topology_replan", True),
])
def test_m2_classifier_four_channels(details, code, expected_class, structural):
    outcome = classify_feature_failure(details, code)
    assert outcome["repair_class"] == expected_class
    assert outcome["requires_structural_replan"] is structural
    assert outcome["reason"]
    assert set(outcome) >= {"repair_class", "requires_structural_replan", "reason", "missing_fields"}


def test_m2_degraded_default_never_escalates_to_structural():
    outcome = classify_feature_failure({}, "invalid_model_output")
    assert outcome["repair_class"] == "parameter_repair"
    assert outcome["requires_structural_replan"] is False
    assert outcome["missing_fields"]


# ---------------------------------------------------------------------------
# M2 production-loop wiring: four-element feedback and channel routing
# ---------------------------------------------------------------------------

def _channel_details(channel):
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
            "measured_features": {"closed_region": False}, "failed_features": ["closed_region"]}


@pytest.mark.parametrize("channel,structural_channel", [
    ("parameter_repair", False), ("connection_repair", False),
    ("feature_replan", True), ("topology_replan", True),
])
def test_m2_loop_feedback_four_elements_and_channel(tmp_path, channel, structural_channel):
    details = _channel_details(channel)
    code = "constraint_conflict" if channel == "topology_replan" else "structure_requirement_failed"
    first = _invalid(details, code=code)
    second = _invalid(details, code=code, plan=_plan(t_start=3))
    result, calls, store, project = _run([first, second], tmp_path)

    assert len(calls) == 2
    prompt = calls[1]["text"]
    assert "修复范围判定" in prompt
    block = _feedback_block(prompt)
    assert block["repair_class"] == channel
    assert block["requires_structural_replan"] is structural_channel
    # Four-element feedback: expected / measured / difference / marker.
    assert block["expected_feature"]
    assert block["measured_feature"] is not None
    assert block["difference"] == details["failed_features"]

    kwargs = calls[1]["kwargs"]
    if structural_channel:
        # Replan channel bypasses the component merger context; the whole
        # plan is recompiled, not patched through the ref-scoped merger.
        assert "component_repair_context" not in kwargs
        assert "repair_context" not in kwargs
        assert "重新编译" in prompt or "结构" in prompt
    else:
        assert kwargs.get("component_repair_context") is not None


def _two_step_plan():
    outline = _plan()
    outline["steps"][0]["source_requirement_refs"] = ["R1"]
    outline["steps"][0]["junction_constraints"] = [
        {"left_segment_index": 0, "right_segment_index": 1,
         "source_requirement_refs": ["R3"]}]
    outline["steps"].append({
        "op": "add_line", "step_id": "keep", "output_ref": "keep",
        "semantic": {"label": "keep", "object_id": "keep", "assembly_id": "whole"},
        "start": {"x": 0.0, "y": 0.0}, "end": {"x": 0.0, "y": 1.0},
        "source_requirement_refs": ["R2"],
        "junction_constraints": [
            {"left_segment_index": 1, "right_segment_index": 0,
             "source_requirement_refs": ["R3"]}]})
    return outline


def test_m2_replan_preserves_source_dimensions_part_and_closure(tmp_path):
    """Structural replan rebuilds the failing part while preserving: source
    requirement refs, user dimensions, the non-target part, and the dependency
    closure. Acceptance is not lowered."""
    outline = _two_step_plan()
    fail_details = {"required_features": {"cusp": "lower center cusp"},
                     "measured_features": {"cusp": False}, "failed_features": ["cusp"],
                     "geometry_ids": [REF], "affected_output_refs": [REF]}
    first = _invalid(fail_details, plan=outline)

    # Replan: target expression rebuilt; source refs and junction closure kept;
    # keep step carried over verbatim.
    replan_plan = deepcopy(outline)
    replan_plan["steps"][0]["y_expression"] = "3+2*cos(t)+abs(sin(t))"
    replan = _ready(replan_plan)
    result, calls, store, project = _run([first, replan], tmp_path)

    assert len(calls) == 2
    # Structural channel bypasses the ref-scoped component merger context.
    assert "component_repair_context" not in calls[1]["kwargs"]
    assert "repair_context" not in calls[1]["kwargs"]

    before_steps = {s["output_ref"]: s for s in outline["steps"]}
    after_steps = {s["output_ref"]: s for s in replan["plan"]["steps"]}
    # Non-target part preserved verbatim (identity, coordinates).
    assert set(after_steps) == {REF, "keep"}
    assert after_steps["keep"] == before_steps["keep"]
    # Source requirement refs preserved on both target and non-target.
    assert after_steps[REF]["source_requirement_refs"] == ["R1"]
    assert after_steps["keep"]["source_requirement_refs"] == ["R2"]
    # User dimensions preserved; acceptance assertions unchanged.
    assert outline["assertions"] == replan["plan"]["assertions"]
    assert after_steps["keep"]["start"] == before_steps["keep"]["start"]
    assert after_steps["keep"]["end"] == before_steps["keep"]["end"]
    # Dependency closure (junction constraints + their source refs) preserved.
    assert after_steps[REF]["junction_constraints"] == before_steps[REF]["junction_constraints"]
    assert after_steps["keep"]["junction_constraints"] == before_steps["keep"]["junction_constraints"]


# ---------------------------------------------------------------------------
# M3 judgement table (unit level)
# ---------------------------------------------------------------------------

def _feat(failed, measured=None):
    return {"construction_error": {"code": "structure_requirement_failed",
            "details": {"check": "outline", "failed_features": failed,
                        "measured_features": measured or {f: False for f in failed}}}}


def test_m3_first_repair_is_always_allowed():
    outcome = evaluate_repair_progress(None, _feat(["cusp"]))
    assert outcome["decision"] == "allow"
    assert outcome["progress"] == "first_repair"


def test_m3_blocks_identical_geometry_and_unchanged_failure_vector(monkeypatch):
    monkeypatch.setattr("app.cad_generation_recovery._GEOMETRY_EVALUATOR",
                        _stub_evaluator("identical", equivalent=True))
    a = _invalid({"check": "outline", "failed_features": ["cusp"],
                  "measured_features": {"cusp": False}}, geom=GEOM)
    b = _invalid({"check": "outline", "failed_features": ["cusp"],
                  "measured_features": {"cusp": False}}, plan=_plan(3), geom=GEOM)
    outcome = evaluate_repair_progress(a, b)
    assert outcome["decision"] == "block"
    assert outcome["progress"] == "stalled_equivalent"
    assert outcome["geometry"]["equivalent"] is True
    assert outcome["geometry"]["relation"] == "identical"


@pytest.mark.parametrize("relation", ["identical", "equivalent"])
def test_m3_equivalence_vocabulary_blocks_stall(monkeypatch, relation):
    """B may label a proven match either ``identical`` or ``equivalent``; both
    must block a proven stall. Uses B's real vocabulary, no mapping in harness."""
    monkeypatch.setattr("app.cad_generation_recovery._GEOMETRY_EVALUATOR",
                        _stub_evaluator(relation, equivalent=True))
    a = _invalid({"check": "outline", "failed_features": ["cusp"],
                  "measured_features": {"cusp": False}}, geom=GEOM)
    b = _invalid({"check": "outline", "failed_features": ["cusp"],
                  "measured_features": {"cusp": False}}, plan=_plan(3), geom=GEOM)
    outcome = evaluate_repair_progress(a, b)
    assert outcome["decision"] == "block"
    assert outcome["progress"] == "stalled_equivalent"
    assert outcome["geometry"]["equivalent"] is True
    assert outcome["geometry"]["relation"] == relation


def test_m3_unknown_relation_fails_safe_release(monkeypatch):
    """Out-of-contract vocabulary must not block; release as undetermined and
    record the unknown relation for audit."""
    monkeypatch.setattr("app.cad_generation_recovery._GEOMETRY_EVALUATOR",
                        _stub_evaluator("bogus_future_relation", equivalent=True))
    a = _invalid({"failed_features": ["cusp"], "measured_features": {"cusp": False}}, geom=GEOM)
    b = _invalid({"failed_features": ["cusp"], "measured_features": {"cusp": False}},
                 plan=_plan(3), geom=GEOM)
    outcome = evaluate_repair_progress(a, b)
    assert outcome["decision"] == "allow"
    assert outcome["geometry"]["undetermined"] is True
    assert outcome["geometry"]["equivalent"] is None
    assert any("unknown geometry relation" in reason for reason in outcome["geometry"]["fail_reasons"])


@pytest.mark.parametrize("factory,expected_progress", [
    (lambda: (_feat(["cusp", "side"], {"cusp": True, "side": False}),
              _feat(["side"], {"cusp": True, "side": False})), "feature_improved"),
    (lambda: (_feat(["cusp"]), _feat(["cusp", "side"])), "new_failure"),
    (lambda: (_feat(["cusp"]), _feat(["cusp"])), "undetermined"),
])
def test_m3_whitelist_releases(factory, expected_progress):
    a, b = factory()
    outcome = evaluate_repair_progress(a, b)
    assert outcome["decision"] == "allow"
    assert outcome["progress"] == expected_progress


@pytest.mark.parametrize("relation", [
    "same_trajectory_reversed", "compliant_other", "different",
])
def test_m3_changed_relations_release(monkeypatch, relation):
    """Determined non-equivalent geometry changes release via geometry_changed."""
    monkeypatch.setattr("app.cad_generation_recovery._GEOMETRY_EVALUATOR",
                        _stub_evaluator(relation, equivalent=False,
                                        reversed_flag=relation == "same_trajectory_reversed"))
    a = _invalid({"failed_features": ["cusp"], "measured_features": {"cusp": False}}, geom=GEOM)
    b = _invalid({"failed_features": ["cusp"], "measured_features": {"cusp": False}},
                 plan=_plan(3), geom=GEOM_OTHER)
    outcome = evaluate_repair_progress(a, b)
    assert outcome["decision"] == "allow"
    assert outcome["progress"] == "geometry_changed"
    assert outcome["geometry"]["equivalent"] is False
    assert outcome["geometry"]["relation"] == relation
    assert outcome["geometry"]["reversed"] == (relation == "same_trajectory_reversed")


@pytest.mark.parametrize("relation", ["similar_transform", "similar"])
def test_m3_similar_relation_maps_to_undetermined_release(monkeypatch, relation):
    """Similar transform is NOT equivalence: the target may really have moved.
    Explicitly mapped to undetermined and released; never blocked."""
    monkeypatch.setattr("app.cad_generation_recovery._GEOMETRY_EVALUATOR",
                        _stub_evaluator(relation, equivalent=True))
    a = _invalid({"failed_features": ["cusp"], "measured_features": {"cusp": False}}, geom=GEOM)
    b = _invalid({"failed_features": ["cusp"], "measured_features": {"cusp": False}},
                 plan=_plan(3), geom=GEOM)
    outcome = evaluate_repair_progress(a, b)
    assert outcome["decision"] == "allow"
    assert outcome["progress"] == "undetermined"
    assert outcome["geometry"]["undetermined"] is True
    assert outcome["geometry"]["equivalent"] is None
    assert any("similar transform is not equivalence" in r
               for r in outcome["geometry"]["fail_reasons"])


def test_m3_undetermined_evaluator_releases(monkeypatch):
    monkeypatch.setattr("app.cad_generation_recovery._GEOMETRY_EVALUATOR",
                        _stub_evaluator("different", equivalent=False, undetermined=True))
    a = _invalid({"failed_features": ["cusp"], "measured_features": {"cusp": False}}, geom=GEOM)
    b = _invalid({"failed_features": ["cusp"], "measured_features": {"cusp": False}},
                 plan=_plan(3), geom=GEOM)
    outcome = evaluate_repair_progress(a, b)
    assert outcome["decision"] == "allow"
    assert outcome["geometry"]["undetermined"] is True


def _poly(gid, pts):
    return {"id": gid, "type": "polyline", "closed": True, "vertices": pts}


def _recording_stub(records):
    def _fn(spec_a, spec_b, tolerance):
        records.append({
            "a": [g.get("id") for g in spec_a.get("geometries") or []],
            "b": [g.get("id") for g in spec_b.get("geometries") or []],
            "scope_refs": spec_b.get("scope_refs"),
        })
        return {"equivalent": True, "undetermined": False, "relation": "identical",
                "reversed": False,
                "checks": {"geometry": "pass", "orientation": "pass", "endpoints": "pass",
                           "closed": "pass", "topology": "pass", "transformation": "n/a"},
                "fail_reasons": []}
    return _fn


def test_m3_target_stall_unrelated_part_moved_blocks(monkeypatch):
    """Target part makes no progress while an unrelated part moves slightly.

    Comparison must be scoped to the failing target ref; the unrelated move
    must not surface as a whole-geometry ``geometry_changed`` release.
    """
    records = []
    monkeypatch.setattr("app.cad_generation_recovery._GEOMETRY_EVALUATOR",
                        _recording_stub(records))
    target_pts = [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}]
    keep_before = _poly("g2", [{"x": 0.0, "y": 0.0}, {"x": 0.0, "y": 1.0}])
    keep_after = _poly("g2", [{"x": 0.2, "y": 0.0}, {"x": 0.2, "y": 1.0}])
    details = {"check": "outline", "failed_features": ["cusp"],
               "measured_features": {"cusp": False}, "affected_output_refs": [REF]}
    table = {REF: ["g1"], "keep": ["g2"]}

    def _case(keep_geom):
        res = _invalid(details, plan=_plan())
        res["trial_result"] = {"geometries": [_poly("g1", target_pts), keep_geom],
                               "symbol_table": dict(table)}
        return res

    a, b = _case(keep_before), _case(keep_after)
    outcome = evaluate_repair_progress(a, b)
    # Evaluator sees only the target geometry on both sides.
    assert records and records[0]["a"] == ["g1"] and records[0]["b"] == ["g1"]
    assert records[0]["scope_refs"] == [REF]
    assert outcome["decision"] == "block"
    assert outcome["progress"] == "stalled_equivalent"


def test_m3_unresolved_target_scope_releases(monkeypatch):
    """Declared target refs cannot be bound to geometries: release, do not fall
    back to a whole-plan comparison."""
    monkeypatch.setattr("app.cad_generation_recovery._GEOMETRY_EVALUATOR",
                        _stub_evaluator("identical", equivalent=True))
    details = {"failed_features": ["cusp"], "measured_features": {"cusp": False},
               "affected_output_refs": [REF]}
    a = _invalid(details, geom=GEOM)
    b = _invalid(details, plan=_plan(3), geom=GEOM)
    outcome = evaluate_repair_progress(a, b)
    assert outcome["decision"] == "allow"
    assert outcome["geometry"]["undetermined"] is True
    assert outcome["geometry"]["relation"] == "scope_unresolved"


# ---------------------------------------------------------------------------
# M3 production-loop level: real request-count evidence under max_repairs=2
# ---------------------------------------------------------------------------

def test_m3_loop_blocks_proven_stall_after_second_request(tmp_path, monkeypatch):
    monkeypatch.setattr("app.cad_generation_recovery._GEOMETRY_EVALUATOR",
                        _stub_evaluator("identical", equivalent=True))
    """Positive intercept case: same failure vector, identical executed
    geometry. The loop must avoid a third repair request.

    Call accounting (max_repairs=2): request 1 first plan, request 2 first
    repair; the proven stall is detected between attempts 1 and 2, so the
    request that would have been a third model call is NOT issued.
    """
    details = {"check": "outline", "failed_features": ["cusp"],
               "measured_features": {"cusp": False}, "affected_output_refs": [REF]}
    a1 = _invalid(details, plan=_plan(0), geom=GEOM, message="失败轮次1")
    a1["trial_result"]["symbol_table"] = {REF: [REF]}
    a2 = _invalid(details, plan=_plan(3), geom=GEOM, message="失败轮次2")
    a2["trial_result"]["symbol_table"] = {REF: [REF]}
    result, calls, store, project = _run([a1, a2], tmp_path)

    assert len(calls) == 2, f"third request must be avoided, got {len(calls)}"
    interp = result["construction_interpretation"]
    assert interp["error"]["code"] == "no_progress"
    assert interp["progress"]["decision"] == "block"
    assert interp["progress"]["progress"] == "stalled_equivalent"
    assert not (store.get(project["id"]).get("variants") or [])
    recovery = interp["recovery"]
    assert recovery["repair_count"] == 1
    assert recovery["progress_log"][-1]["decision"] == "block"


def test_m3_loop_releases_when_geometry_snapshot_is_missing(tmp_path):
    """Negative intercept case: no executed-geometry snapshot. The gate must
    not block on plan strings alone; a further repair is allowed.
    """
    details = {"check": "outline", "failed_features": ["cusp"],
               "measured_features": {"cusp": False}, "affected_output_refs": [REF]}
    a1 = _invalid(details, plan=_plan(0), message="失败轮次1")
    a2 = _invalid(details, plan=_plan(3), message="失败轮次2")
    a3 = _invalid(details, plan=_plan(6), message="失败轮次3")
    result, calls, store, project = _run([a1, a2, a3], tmp_path)

    # No snapshot -> undetermined release; the third repair request is issued.
    assert len(calls) == 3
    interp = result["construction_interpretation"]
    assert interp["error"]["code"] != "no_progress"
    second_progress = interp["recovery"]["progress_log"][0]
    assert second_progress["decision"] == "allow"
    assert second_progress["progress"] == "undetermined"


def test_m3_loop_releases_on_geometry_change(tmp_path, monkeypatch):
    monkeypatch.setattr("app.cad_generation_recovery._GEOMETRY_EVALUATOR",
                        _stub_evaluator("different", equivalent=False))
    details = {"check": "outline", "failed_features": ["cusp"],
               "measured_features": {"cusp": False}, "affected_output_refs": [REF]}
    a1 = _invalid(details, plan=_plan(0), geom=GEOM, message="失败轮次1")
    a1["trial_result"]["symbol_table"] = {REF: [REF]}
    a2 = _invalid(details, plan=_plan(3), geom=GEOM_OTHER, message="失败轮次2")
    a2["trial_result"]["symbol_table"] = {REF: [REF]}
    a3 = _invalid(details, plan=_plan(6), message="失败轮次3")
    result, calls, store, project = _run([a1, a2, a3], tmp_path)

    assert len(calls) == 3
    second_progress = result["construction_interpretation"]["recovery"]["progress_log"][0]
    assert second_progress["decision"] == "allow"
    assert second_progress["progress"] == "geometry_changed"


def test_m3_rollback_switch_restores_legacy_behaviour(tmp_path, monkeypatch):
    """With the M3 gate switched off, the proven-stall case is not intercepted."""
    monkeypatch.setattr("app.agent_service.M3_PROGRESS_GATE_ENABLED", False)
    details = {"check": "outline", "failed_features": ["cusp"],
               "measured_features": {"cusp": False}, "affected_output_refs": [REF]}
    a1 = _invalid(details, plan=_plan(0), geom=GEOM, message="失败轮次1")
    a2 = _invalid(details, plan=_plan(3), geom=GEOM, message="失败轮次2")
    a3 = _invalid(details, plan=_plan(6), message="失败轮次3")
    result, calls, store, project = _run([a1, a2, a3], tmp_path)

    assert len(calls) == 3
    assert result["construction_interpretation"]["error"]["code"] != "no_progress"
