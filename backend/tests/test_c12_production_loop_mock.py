"""C1.2 production-loop-level Mock: real ``_formal_cad_construction`` two-round repair.

Upgrade over C1.1: the entry under test is the production method
``RobotAgentService._formal_cad_construction``. The repair loop, failure
capture, context routing, recovery policy, execution, independent acceptance
and candidate persistence all run for real.

Mock boundary (only): ``_structured_review_text`` (the model text outlet).
- The repair loop itself is NOT replaced; ``_interpret_cad_construction_plan``
  is NOT patched.
- ``merge_component_repair`` is wrapped by a delegating observer that records
  the routed refs / prior plan and then calls the real merger; it does not
  substitute merge logic.
- Persistence goes to an isolated ``CreativeProjectStore`` backed by a
  ``tmp_path`` file; saved candidates are reloaded from that store and checked.

No real DeepSeek / model request is made. No production code under
``backend/app`` is modified.

Covered chain (fresh start, real loop):
  round 1 plan -> reproducible executor/assertion failure -> service captures
  the failure, keeps the prior plan and affected refs -> the loop itself routes
  round 2 to ``component_repair_context`` -> round 2 changes only the target
  geometry, the other component and its fields are preserved -> execution and
  independent acceptance pass -> one candidate persisted in the isolated store.
"""
from __future__ import annotations

import json
from copy import deepcopy
from unittest.mock import patch, PropertyMock

import pytest

from app.agent_service import RobotAgentService
from app.creative_projects import CreativeProjectStore


SOURCE = "新建CAD图纸，画两条竖直线，整体宽2米高1米，坐标单位米"


def _line(ref: str, x: float) -> dict:
    return {
        "op": "add_line",
        "step_id": ref,
        "output_ref": ref,
        "semantic": {
            "label": ref,
            "object_id": ref,
            "assembly_id": "whole",
            "assembly_label": "图案",
        },
        "start": {"x": x, "y": 0},
        "end": {"x": x, "y": 1},
    }


def _bounds_assertion(target_ref: str) -> dict:
    return {
        "kind": "bounds_size",
        "assertion_id": "size",
        "target_ref": target_ref,
        "width": 2,
        "height": 1,
    }


def _envelope(plan: dict) -> str:
    return json.dumps({
        "schema_version": "cad.construction-interpretation.v1",
        "is_construction_request": True,
        "confidence": 0.95,
        "evidence_text": [SOURCE],
        "assumptions": [],
        "plan": plan,
    }, ensure_ascii=False)


def _two_line_plan(fixed: bool) -> dict:
    return {
        "units": "m",
        "steps": [_line("r0", 0.0), _line("r1", 2.0 if fixed else 1.0)],
        "assertions": [_bounds_assertion("r1")],
    }


def test_c12_production_loop_two_round_component_repair_persists_one_candidate(tmp_path):
    """Real production loop: first failure auto-routes a second component repair.

    Round 1 returns a plan whose right line sits at x=1, failing the width=2
    bounds assertion; the executor records the affected ref ``r1`` and no local
    coordinate scope. The production loop then builds a ``component_repair_context``
    from that failed attempt and round 2 moves only ``r1`` to x=2; ``r0`` and
    its identity/assembly fields are preserved by the real merger. The accepted
    plan is persisted as exactly one candidate in the isolated store.
    """
    from app.cad_plan_component_repair import merge_component_repair

    service = RobotAgentService(restore_pending_actions=False)
    service.mode = "deepseek"

    store = CreativeProjectStore(tmp_path / "projects.json")
    project = store.create(
        "两线", SOURCE,
        requirements={"shape": "generic_2d_cad", "dimensions": {"width_m": 2, "height_m": 1}},
        missing_parameters=[],
    )

    bad_plan = _two_line_plan(fixed=False)
    good_plan = _two_line_plan(fixed=True)

    real_merge = merge_component_repair
    merger_calls: list[dict] = []

    def observing_merge(context, payload):
        details = (context.get("construction_error") or {}).get("details") or {}
        merger_calls.append({
            "refs": details.get("affected_output_refs"),
            "has_prior_plan": bool(context.get("plan") or context.get("rejected_plan")),
        })
        return real_merge(context, payload)

    route = {
        "name": "drawing_design",
        "operation": "create",
        "stage": "candidate_generation",
        "selected_project_id": project["id"],
    }

    with patch("app.agent_service.get_creative_project_store", return_value=store), \
         patch.object(RobotAgentService, "configured", new_callable=PropertyMock, return_value=True), \
         patch.object(service, "_structured_review_text",
                       side_effect=[_envelope(bad_plan), _envelope(good_plan)]) as review, \
         patch("app.cad_plan_component_repair.merge_component_repair",
               side_effect=observing_merge):
        result = service._formal_cad_construction(SOURCE, route, mode="advanced")

    # The loop really ran twice: one model outlet call per attempt.
    assert review.call_count == 2, f"expected two production rounds, got {review.call_count}"
    assert result["ok"] is True, json.dumps(result, ensure_ascii=False)[:3000]

    recovery = result["construction_commit"]["recovery"]
    attempts = recovery["attempts"]
    assert recovery["repair_count"] == 1
    assert len(attempts) == 2, f"expected two recorded attempts, got {len(attempts)}"

    # Round 1: reproducible structural/assertion failure with the affected ref
    # recorded and no coordinate-only local scope (so the component channel is
    # selected, not the local coordinate-patch channel).
    first = attempts[0]
    first_error = first.get("construction_error") or first.get("error") or {}
    first_details = first_error.get("details") or {}
    assert first["status"] == "invalid"
    assert first_error["code"] == "assertion_failed"
    assert first_details["affected_output_refs"] == ["r1"]
    assert "local_repair_scope" not in first_details
    assert "coordinate_patch" not in first
    # Prior plan is retained for the next repair round (baseline keeps it under
    # ``plan``; the top-level ``rejected_plan`` alias is the A1.1 producer shape).
    assert isinstance(first.get("plan"), dict)

    # Round 2: routed through the real component repair merger with the full ref
    # list and the prior plan carried in context.
    assert merger_calls == [{"refs": ["r1"], "has_prior_plan": True}]

    second = attempts[1]
    assert second["status"] == "ready"
    second_steps = {s["output_ref"]: s for s in second["plan"]["steps"]}
    # Target geometry corrected; unaffected part preserved verbatim.
    assert second_steps["r1"]["start"] == {"x": 2.0, "y": 0}
    assert second_steps["r0"]["start"] == {"x": 0.0, "y": 0}
    # Identity fields of the unaffected part are preserved; the backend may add
    # schema-normalized defaults (object_type/role), which are not constraint losses.
    preserved_semantic = second_steps["r0"]["semantic"]
    expected_semantic = _line("r0", 0.0)["semantic"]
    for key in ("label", "object_id", "assembly_id", "assembly_label"):
        assert preserved_semantic.get(key) == expected_semantic[key], key

    # Isolated store: reload from disk and inspect the real saved candidate.
    reloaded = CreativeProjectStore(tmp_path / "projects.json").get(project["id"])
    variants = reloaded.get("variants") or []
    assert len(variants) == 1
    variant = variants[0]
    assert len(variant.get("geometries") or []) == 2
    assert len(variant.get("logical_objects") or []) == 2
    assert result["construction_commit"]["persisted_candidate_count"] == 1
