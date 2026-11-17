"""C1 service-level Mock integration tests for A1/B1 production hookup.

Scope (C line only):
- Go through the real service entry ``RobotAgentService._interpret_cad_construction_plan``
  (construction interpretation -> repair merge -> interpreter validation/execution ->
  error mapping). The only mocked boundary is ``_structured_review_text`` (the model
  text outlet). No direct call to ``merge_component_repair`` or
  ``interpret_construction_request`` is used as the hookup proof.
- No real DeepSeek / any real model interface is called; no network model request is made.
- No production code under ``backend/app`` is modified.

Dependency states (recorded in ``backend/evaluations/v1/C1_test_status.json``):
- ``passed``: verified on the C baseline (a4f2af7).
- ``failed_dep_pending``: strict assertions kept; the case fails until the named A/B
  change lands on the C branch. Dependency reason is split: A1 gap vs B-not-committed.
- ``not_run`` / ``environment_blocked``: reserved for cases that could not execute.
"""
from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from unittest.mock import patch

import pytest

from app.agent_service import RobotAgentService


# ---------------------------------------------------------------------------
# Dependency detection (defensive: collection must not crash on the C baseline)
# ---------------------------------------------------------------------------

def _a1_component_repair_error_available() -> bool:
    spec = importlib.util.find_spec("app.cad_plan_component_repair")
    if spec is None:
        return False
    try:
        from app.cad_plan_component_repair import ComponentRepairError  # noqa: F401
    except ImportError:
        return False
    return True


def _b1_curve_intersection_available() -> bool:
    return importlib.util.find_spec("app.cad_curve_intersection") is not None


# A1 commits already present on the A branch; not yet merged into the C baseline.
A1_COMMIT = "0ed2288ca068534d86e1afddc93f592b7ef35e35"
A1_TEST_COMMIT = "d8cb85f68db08b90beb4872ccfc9fdf93d8735d9"
# B1 has no committed change on the B worktree (HEAD a4f2af7, clean).
B1_COMMIT = "not_committed"


# ---------------------------------------------------------------------------
# Fixtures (generic synthetic plans; no A9/S1/case_id special-casing)
# ---------------------------------------------------------------------------

def _point(x: float, y: float) -> dict:
    return {"x": x, "y": y}


def _junction_constraints() -> list[dict]:
    return [
        {
            "junction_index": 0,
            "left_segment_index": 0,
            "right_segment_index": 1,
            "intent": "smooth",
            "required_continuity": "C1",
            "tangent_tolerance_deg": 0.01,
            "source_requirement_refs": ["user:0"],
        },
        {
            "junction_index": 1,
            "left_segment_index": 1,
            "right_segment_index": 2,
            "intent": "smooth",
            "required_continuity": "C1",
            "tangent_tolerance_deg": 0.01,
            "source_requirement_refs": ["user:0"],
        },
    ]


def _original_composite_plan() -> dict:
    """A generic three-segment open composite path with valid junction fields."""
    return {
        "schema_version": "cad.construction-plan.v1",
        "units": "m",
        "steps": [{
            "op": "add_composite_path",
            "step_id": "c1-repair-step",
            "output_ref": "c1-repair-curve",
            "layer_id": 1,
            "semantic": {"object_type": "drawing_part", "label": "C1 generic repair fixture"},
            "segments": [
                {"kind": "line", "start": _point(0, 0), "end": _point(1, 0)},
                {"kind": "line", "start": _point(1, 0), "end": _point(2, 1)},
                {"kind": "line", "start": _point(2, 1), "end": _point(3, 0)},
            ],
            "closed": False,
            "samples_per_curve": 64,
            "connection_tolerance": 0.000001,
            "continuity": "C1",
            "tangent_tolerance_deg": 0.01,
            "allow_self_intersection": False,
            "allow_duplicate_segments": False,
            "junction_constraints": _junction_constraints(),
        }],
        "assertions": [{
            "kind": "bounds_size",
            "assertion_id": "c1-bounds",
            "target_ref": "c1-repair-curve",
            "width": 3.0,
            "height": 1.7,
            "tolerance": 0.001,
        }],
    }


def _bow_tie_plan() -> dict:
    """Closed four-line bow tie that the baseline executor rejects as self-intersecting."""
    return {
        "schema_version": "cad.construction-plan.v1",
        "units": "m",
        "steps": [{
            "step_id": "c1-bow",
            "op": "add_composite_path",
            "output_ref": "c1-bow.path",
            "closed": True,
            "segments": [
                {"kind": "line", "start": _point(0, 0), "end": _point(2, 2)},
                {"kind": "line", "start": _point(2, 2), "end": _point(0, 2)},
                {"kind": "line", "start": _point(0, 2), "end": _point(2, 0)},
                {"kind": "line", "start": _point(2, 0), "end": _point(0, 0)},
            ],
            "semantic": {
                "label": "C1 crossing outline",
                "object_id": "c1-bow",
                "assembly_id": "whole",
                "assembly_label": "C1 outline",
            },
        }],
        "assertions": [],
    }


def _repair_context(plan: dict, ref: str = "c1-repair-curve") -> dict:
    return {
        "plan": plan,
        "construction_error": {"details": {"affected_output_refs": [ref]}},
    }


def _model_payload(plan: dict, source: str) -> str:
    return json.dumps({
        "schema_version": "cad.construction-interpretation.v1",
        "is_construction_request": True,
        "plan": plan,
        "confidence": 0.95,
        "evidence_text": [source],
        "assumptions": [],
    }, ensure_ascii=False)


def _service(provider: str = "deepseek") -> RobotAgentService:
    service = object.__new__(RobotAgentService)
    service.mode = provider
    service.api_keys = {provider: "test-key"}
    service.model = "test-model"
    service.base_model = "test-model"
    service.advanced_model = "test-model"
    service._cad_planning_model = "deepseek-chat"
    return service


SOURCE_COMPOSITE = (
    "新建一条开放的三段连续复合路径，整体宽3米高1.7米，坐标单位米，"
    "两处内部连接保持平滑，不允许尖点或自交，路径不闭合。"
)
SOURCE_BOW_TIE = "新建一个交叉闭合轮廓，宽2米高2米，坐标单位米。"


# ---------------------------------------------------------------------------
# Goal 3 (baseline-verifiable): topology failure is a structured error, not a
# silent success. This relies on the baseline executor's existing rejection.
# ---------------------------------------------------------------------------

def test_c1_service_topology_failure_is_structured_not_silent_success():
    """A self-intersecting plan must surface a structured construction_error."""
    service = _service()
    payload = _model_payload(_bow_tie_plan(), SOURCE_BOW_TIE)
    with patch.object(service, "_structured_review_text", return_value=payload) as review:
        result = service._interpret_cad_construction_plan(SOURCE_BOW_TIE, mode="advanced")

    review.assert_called_once()
    assert result["status"] == "invalid", json.dumps(result, ensure_ascii=False)[:3000]
    assert result["provider_attempted"] is True
    assert result["persisted"] is False

    error = result.get("construction_error") or {}
    assert error.get("code") == "self_intersecting_composite_path", json.dumps(result, ensure_ascii=False)[:3000]
    details = error.get("details") or {}
    # Structured diagnostic evidence must reach the service layer; no silent ready.
    assert details.get("conflicts") or details.get("affected_segment_indices")
    assert result.get("trial_result") is None or result.get("status") != "ready"


# ---------------------------------------------------------------------------
# Goal 1 (A1 pending): a rejected local repair maps to a structured local-repair
# error, classified as repairable rather than a full structural regeneration.
# ---------------------------------------------------------------------------

def test_c1_service_component_repair_failure_maps_to_structured_local_error():
    if not _a1_component_repair_error_available():
        pytest.fail(
            "failed_dep_pending: A1 ComponentRepairError not merged on C baseline; "
            f"depends on A commit {A1_COMMIT} (test {A1_TEST_COMMIT}). "
            "Baseline maps the merge failure to generic invalid_model_output."
        )

    from app.cad_generation_recovery import recovery_category, should_repair

    plan = _original_composite_plan()
    replacement_plan = deepcopy(plan)
    # Explicitly clearing the inherited junction constraints must be rejected.
    replacement_plan["steps"][0]["junction_constraints"] = []

    service = _service()
    with patch.object(
        service,
        "_structured_review_text",
        return_value=_model_payload(replacement_plan, SOURCE_COMPOSITE),
    ):
        result = service._interpret_cad_construction_plan(
            SOURCE_COMPOSITE,
            mode="advanced",
            component_repair_context=_repair_context(plan),
        )

    assert result["status"] == "invalid", json.dumps(result, ensure_ascii=False)[:3000]
    error = result.get("construction_error") or {}
    # A1 repair-error namespace; precise code must survive to the service layer.
    assert error.get("code", "").startswith(("junction_", "component_repair", "tangent", "continuity")), error
    details = error.get("details") or {}
    # The affected component must still be identifiable for a local repair route.
    assert details.get("output_ref") or details.get("affected_output_refs")
    # Not promoted to a structural regeneration: no structural-replan flag.
    assert details.get("requires_structural_replan") is not True

    # Recovery policy keeps it in the bounded local-repair bucket, not terminal.
    assert recovery_category(result) == "constraint_conflict"
    assert should_repair(result) is True


# ---------------------------------------------------------------------------
# Goal 2 (A1 pending): after a legal in-place repair, inherited junction fields
# remain complete in the service-level merged plan.
# ---------------------------------------------------------------------------

def test_c1_service_merged_repair_keeps_inherited_junction_fields():
    if not _a1_component_repair_error_available():
        pytest.fail(
            "failed_dep_pending: A1 constraint inheritance not merged on C baseline; "
            f"depends on A commit {A1_COMMIT} (test {A1_TEST_COMMIT}). "
            "Baseline replaces the whole step and drops inherited junction fields."
        )

    plan = _original_composite_plan()
    replacement_plan = deepcopy(plan)
    replacement_step = replacement_plan["steps"][0]
    for key in ("junction_constraints", "continuity", "tangent_tolerance_deg"):
        replacement_step.pop(key, None)

    service = _service()
    with patch.object(
        service,
        "_structured_review_text",
        return_value=_model_payload(replacement_plan, SOURCE_COMPOSITE),
    ) as review:
        result = service._interpret_cad_construction_plan(
            SOURCE_COMPOSITE,
            mode="advanced",
            component_repair_context=_repair_context(plan),
        )

    review.assert_called_once()
    assert result["provider_attempted"] is True
    assert result["persisted"] is False

    merged_steps = (result.get("plan") or {}).get("steps") or []
    assert len(merged_steps) == 1
    merged_step = merged_steps[0]
    # Protected connection fields are inherited verbatim from the original step.
    assert merged_step.get("junction_constraints") == plan["steps"][0]["junction_constraints"]
    assert merged_step.get("continuity") == plan["steps"][0]["continuity"]
    assert merged_step.get("tangent_tolerance_deg") == plan["steps"][0]["tangent_tolerance_deg"]
    # Unrelated assertion inventory is untouched by the component merge.
    assert (result.get("plan") or {}).get("assertions") == plan["assertions"]


# ---------------------------------------------------------------------------
# Goal 3 (B1 pending): exact Bezier intersection diagnostics must reach the
# service-level structured error. B1 module/fields are not committed yet.
# ---------------------------------------------------------------------------

def test_c1_service_exact_bezier_intersection_details_present():
    if not _b1_curve_intersection_available():
        pytest.fail(
            "failed_dep_pending: B1 cad_curve_intersection not committed; "
            f"depends on B commit {B1_COMMIT} (B worktree HEAD a4f2af7, clean). "
            "Baseline only has sampled polyline intersection diagnostics."
        )

    service = _service()
    with patch.object(
        service,
        "_structured_review_text",
        return_value=_model_payload(_bow_tie_plan(), SOURCE_BOW_TIE),
    ):
        result = service._interpret_cad_construction_plan(SOURCE_BOW_TIE, mode="advanced")

    error = result.get("construction_error") or {}
    details = error.get("details") or {}
    exact = details.get("exact_intersection_pairs") or []
    assert exact, "B1 must surface exact intersection pairs in the structured error"
    pair = exact[0]
    for field in ("left_segment_index", "right_segment_index", "left_t", "right_t", "kind", "error_bound"):
        assert field in pair, f"missing exact intersection field: {field}"
