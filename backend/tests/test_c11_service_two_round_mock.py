"""C1.1 service-level two-round Mock: A1.1 repair scope refs + previous plan.

Scope (C line only):
- Exercise the real service entry ``RobotAgentService._interpret_cad_construction_plan``
  twice, mirroring the production bounded-repair chain: round 1 surfaces a structured
  component-repair failure; round 2 re-enters the component repair channel with the
  failed attempt as context.
- The only mocked boundary is ``_structured_review_text`` (model text outlet). No direct
  call to ``merge_component_repair`` / ``interpret_construction_request`` is the hookup
  proof. No real model request; no persistence in these cases.

GAP attribution (see ``C1.1_GAP_复核报告.md``):
- GAP-1(b): service routing already consumes the full ``affected_output_refs`` list; no
  first-only short-circuit. Verified at agent_service.py:6481/6509/6225/6234.
- GAP-2: previous plan travels through ``rejected_plan`` into the next repair context;
  verified at agent_service.py:6493/6224/6482.
- The missing producer side was closed by A1.1 (commit below); these cases gate on it.
"""
from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from unittest.mock import patch

import pytest

from app.agent_service import RobotAgentService


# A1.1 commit that supplies affected refs and previous plan on the A branch.
A11_COMMIT = "ea8323a230f1cd53cf80f4fd4398328e836962b2"
A1_COMMIT = "0ed2288ca068534d86e1afddc93f592b7ef35e35"


def _a11_available() -> bool:
    if importlib.util.find_spec("app.cad_plan_component_repair") is None:
        return False
    try:
        from app.cad_plan_component_repair import ComponentRepairError  # noqa: F401
    except ImportError:
        return False
    return True


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


def _two_step_plan() -> dict:
    """Generic two-step open smooth composite path; no case id / fixed shape."""
    base_segments = [
        [_point(0.0, 0.0), _point(0.8, 0.6), _point(1.4, 1.2), _point(2.0, 1.0)],
        [_point(2.0, 1.0), _point(2.2, 0.9333333333333333), _point(3.6, -0.9), _point(4.0, -1.0)],
        [_point(4.0, -1.0), _point(4.4, -1.1), _point(5.2, -0.6), _point(6.0, 0.0)],
    ]

    def step(ref: str, x0: float) -> dict:
        segments = [
            {"kind": "bezier", "control_points": [
                {"x": round(p["x"] + x0, 9), "y": p["y"]} for p in segment
            ]}
            for segment in base_segments
        ]
        return {
            "op": "add_composite_path",
            "step_id": ref,
            "output_ref": ref,
            "layer_id": 1,
            "semantic": {"object_type": "drawing_part", "label": ref},
            "segments": segments,
            "closed": False,
            "samples_per_curve": 64,
            "connection_tolerance": 0.000001,
            "continuity": "C1",
            "tangent_tolerance_deg": 0.01,
            "allow_self_intersection": False,
            "allow_duplicate_segments": False,
            "junction_constraints": deepcopy(_junction_constraints()),
        }

    return {
        "schema_version": "cad.construction-plan.v1",
        "units": "m",
        "steps": [step("c11-a", 0.0), step("c11-b", 6.0)],
        "assertions": [],
    }


def _envelope(plan: dict, prompt: str) -> str:
    return json.dumps({
        "schema_version": "cad.construction-interpretation.v1",
        "is_construction_request": True,
        "plan": plan,
        "confidence": 0.95,
        "evidence_text": [prompt],
        "assumptions": [],
    }, ensure_ascii=False)


def _service() -> RobotAgentService:
    service = object.__new__(RobotAgentService)
    service.mode = "deepseek"
    service.api_keys = {"deepseek": "test-key"}
    service.model = "test-model"
    service.base_model = "test-model"
    service.advanced_model = "test-model"
    service._cad_planning_model = "deepseek-chat"
    return service


PROMPT = "生成两条开放、平滑的三次 Bezier 复合路径，两处内部连接点满足 C1 切向连续，坐标单位为米。"


def test_c11_round1_surfaces_full_ref_scope_and_previous_plan():
    """Round 1: repair rejection keeps the complete ref set and previous plan.

    GAP-1: details carry the complete deduplicated, ordered affected ref list plus the
    compat single ref. GAP-2: top-level ``rejected_plan`` keeps the prior plan for the
    next repair round. The error stays a bounded local-repair category, not a structural
    regeneration.
    """
    if not _a11_available():
        pytest.fail(
            "failed_dep_pending: A1.1 ComponentRepairError/refs/previous_plan not merged "
            f"on C baseline; depends on A1.1 commit {A11_COMMIT} (A1 {A1_COMMIT})."
        )

    from app.cad_generation_recovery import recovery_category, should_repair

    plan = _two_step_plan()
    bad_plan = deepcopy(plan)
    bad_plan["steps"][0]["junction_constraints"] = []
    context = {
        "plan": plan,
        "construction_error": {"details": {"affected_output_refs": ["c11-b", "c11-a"]}},
    }

    service = _service()
    with patch.object(
        service, "_structured_review_text",
        side_effect=[_envelope(bad_plan, PROMPT), "round-two-payload"],
    ) as review:
        first = service._interpret_cad_construction_plan(
            PROMPT, component_repair_context=context,
        )

    review.assert_called_once()
    assert first["status"] == "invalid", json.dumps(first, ensure_ascii=False)[:3000]

    error = first["construction_error"]
    assert error["code"] == "junction_constraints_clear_rejected", error
    details = error["details"]
    # Full, deduplicated, stably ordered list (not just the first affected ref).
    assert details["affected_output_refs"] == ["c11-a", "c11-b"]
    # Compat single-ref field is retained alongside the list.
    assert details.get("output_ref") == "c11-a"
    # GAP-2: previous plan survives the exception for the next round.
    assert first["rejected_plan"] == plan

    # Local repair bucket, not a promoted structural regeneration.
    assert details.get("requires_structural_replan") is not True
    assert recovery_category(first) == "constraint_conflict"
    assert should_repair(first) is True


def test_c11_round2_reuses_scope_keeps_unaffected_part_and_constraints():
    """Round 2: re-enter component repair; only target geometry changes, rest preserved.

    Driven through the same service entry, with the failed attempt handed back as
    ``component_repair_context`` (the shape the production loop builds at
    agent_service.py:6508).
    """
    if not _a11_available():
        pytest.fail(
            "failed_dep_pending: A1.1 repair-merge contract not merged on C baseline; "
            f"depends on A1.1 commit {A11_COMMIT}."
        )

    plan = _two_step_plan()
    bad_plan = deepcopy(plan)
    bad_plan["steps"][0]["junction_constraints"] = []
    context = {
        "plan": plan,
        "construction_error": {"details": {"affected_output_refs": ["c11-b", "c11-a"]}},
    }

    service = _service()
    with patch.object(
        service, "_structured_review_text",
        side_effect=[_envelope(bad_plan, PROMPT), "stub"],
    ):
        first = service._interpret_cad_construction_plan(
            PROMPT, component_repair_context=context,
        )
    assert first["status"] == "invalid"
    first_error = first["construction_error"]

    # Round 2: edit only the target part's last control point; emit both steps but the
    # untouched part must come back identical to the original.
    repaired = deepcopy(plan)
    repaired["steps"][0]["segments"][2]["control_points"][3] = _point(6.0, 0.2)
    replacement_steps = []
    for original in repaired["steps"]:
        replacement_steps.append({
            "op": original["op"],
            "step_id": original["step_id"],
            "output_ref": original["output_ref"],
            "semantic": original["semantic"],
            "segments": deepcopy(original["segments"]),
        })
    second_payload = _envelope({"units": "m", "steps": replacement_steps}, PROMPT)

    failed_attempt = {
        "rejected_plan": first["rejected_plan"],
        "construction_error": first_error,
        "assumptions": [],
    }
    with patch.object(
        service, "_structured_review_text", return_value=second_payload,
    ) as review:
        second = service._interpret_cad_construction_plan(
            PROMPT, component_repair_context=failed_attempt,
        )

    review.assert_called_once()
    assert second["status"] == "ready", json.dumps(second, ensure_ascii=False)[:3000]
    assert second["provider_attempted"] is True
    assert second["persisted"] is False

    merged = second["plan"]
    # Target geometry edit landed.
    assert merged["steps"][0]["segments"][2]["control_points"][3] == _point(6.0, 0.2)
    # Untouched part: geometry, ref and protected fields identical to original.
    other = merged["steps"][1]
    original_other = plan["steps"][1]
    assert other["output_ref"] == original_other["output_ref"]
    assert other["segments"] == original_other["segments"]
    assert other["junction_constraints"] == original_other["junction_constraints"]
    for index, merged_step in enumerate(merged["steps"]):
        assert merged_step["junction_constraints"] == plan["steps"][index]["junction_constraints"]
        assert merged_step["continuity"] == "C1"
        assert merged_step["tangent_tolerance_deg"] == 0.01
