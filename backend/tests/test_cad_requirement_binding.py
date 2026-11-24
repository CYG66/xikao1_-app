from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from app.cad_candidate_state import candidate_is_accepted
from app.cad_construction_commit import commit_construction_interpretation
from app.cad_construction_interpreter import interpret_construction_request
from app.cad_requirement_binding import bind_construction_coverage
from app.creative_projects import CreativeProjectStore


def _interpret(source: str) -> dict:
    result = interpret_construction_request(source)
    assert result.get("status") == "ready", result.get("error")
    return result


def _coverage(result: dict) -> dict:
    return deepcopy(result["source_acceptance"]["coverage_evidence"])


def _trial(result: dict) -> dict:
    return result["trial_result"]


def _bind(source: str, coverage: dict, trial: dict, *, with_project: bool = True) -> dict:
    return bind_construction_coverage(
        coverage,
        logical_objects=deepcopy(_trial_objects(trial)),
        geometries=deepcopy(trial.get("geometries") or []),
        plan_steps=deepcopy((trial.get("plan") or {}).get("steps") or []),
        symbol_table=deepcopy(trial.get("symbol_table") or {}),
        project_evidence=(
            {"project_id": "project-1", "project_status": "ready_for_design",
             "project_exists": True, "authority": "creative_project_store"}
            if with_project else None
        ),
    )


def _trial_objects(trial: dict) -> list[dict]:
    return list(trial.get("logical_objects") or [])


def _store(tmp_path: Path) -> CreativeProjectStore:
    return CreativeProjectStore(tmp_path / "projects.json")


def test_a2_ordinary_rectangle_is_bound_to_unique_object_and_measurement(tmp_path: Path) -> None:
    source = "新建图纸，画一个宽5米高3米的矩形"
    result = _interpret(source)
    coverage = _bind(source, _coverage(result), _trial(result))
    assert coverage["state"] == "complete"
    clauses = {item["requirement"]: item for item in coverage["clauses"]}
    operation = clauses["新建图纸"]
    geometry = clauses["画一个宽5米高3米的矩形"]
    assert operation["status"] == "verified"
    assert operation["binding"]["operation"] == "create_drawing"
    assert geometry["status"] == "verified"
    assert geometry["binding"]["logical_object_id"] == "shape-1"
    assert geometry["binding"]["step_id"] == "step-1"
    measurements = [item["measurement"] for item in geometry["evidence"]]
    assert {item["field"] for item in measurements} == {"width", "height"}
    assert {item["actual_mm"] for item in measurements} == {5000.0, 3000.0}
    assert {item["authority"] for item in measurements} == {"backend_measured_geometry"}

    store = _store(tmp_path)
    committed = commit_construction_interpretation(source, result, store=store)
    variant = committed["recommended_variant"]
    assert variant["acceptance_summary"]["status"] == "passed"
    assert variant["acceptance_summary"]["requirement_coverage"] == "complete"
    assert candidate_is_accepted(variant) is True
    persisted = store.get(committed["project_id"])
    assert persisted is not None
    assert persisted["variants"][0]["id"] == variant["id"]


def test_same_rectangle_with_different_size_is_not_promoted() -> None:
    source = "新建图纸，画一个宽5米高3米的矩形"
    coverage = _coverage(_interpret(source))
    wrong = _interpret("画一个宽4米高3米的矩形")
    bound = _bind(source, coverage, _trial(wrong))
    assert bound["state"] == "partial"
    clause = next(item for item in bound["clauses"]
                  if item["requirement"] == "画一个宽5米高3米的矩形")
    assert clause["status"] == "partial"
    assert clause["binding_failures"][0]["field"] == "width"
    assert clause["binding_failures"][0]["actual_mm"] == 4000.0


def _minimal_coverage(requirement: str, fact: dict) -> dict:
    return {
        "schema": "cad.requirement-coverage-evidence.v1",
        "state": "partial", "authority": "backend_measured_geometry",
        "clauses": [{
            "requirement_id": "clause:0:0", "source_index": 0,
            "requirement": requirement,
            "span": {"start": 0, "end": len(requirement)},
            "status": "unbound", "reason": "无法唯一绑定验证对象",
            "unsupported_evidence": [fact], "evidence": [],
            "authority": "backend_measured_geometry",
        }],
        "verified_requirement_count": 0, "partial_requirement_count": 0,
        "unverified_requirement_count": 1,
        "blocking_requirements": [{
            "requirement_id": "clause:0:0", "requirement": requirement,
            "status": "unbound", "reason": "无法唯一绑定验证对象",
        }],
        "unresolved_fact_ids": ["clause:0:0"], "note": "test fixture",
    }


def test_circle_with_requested_dimensions_is_bound_independently() -> None:
    trial_source = "画一个圆，圆心(0,0)，半径1米，坐标单位米"
    trial = _trial(_interpret(trial_source))
    coverage = _minimal_coverage("画一个半径1米的圆", {
        "requirement_id": "user:0:scalar-1:radius:圆",
        "field": "radius", "expected_mm": 1000.0,
        "source_evidence": {"start": 0, "end": 7, "text": "半径1米"},
        "reason": "无法唯一绑定验证对象",
    })
    bound = _bind("画一个半径1米的圆", coverage, trial)
    assert bound["state"] == "complete"
    clause = bound["clauses"][0]
    assert clause["status"] == "verified"
    assert clause["binding"]["object_type"] == "circle"
    measurement = clause["evidence"][0]["measurement"]
    assert measurement["field"] == "radius"
    assert measurement["actual_mm"] == 1000.0


def test_correct_type_wrong_dimension_is_blocked() -> None:
    trial_source = "画一个圆，圆心(0,0)，半径2米，坐标单位米"
    trial = _trial(_interpret(trial_source))
    coverage = _minimal_coverage("画一个半径1米的圆", {
        "requirement_id": "user:0:scalar-1:radius:圆",
        "field": "radius", "expected_mm": 1000.0,
        "source_evidence": {"start": 0, "end": 7, "text": "半径1米"},
        "reason": "无法唯一绑定验证对象",
    })
    bound = _bind("画一个半径1米的圆", coverage, trial)
    assert bound["state"] == "partial"
    clause = bound["clauses"][0]
    assert clause["status"] == "partial"
    assert clause["binding_failures"][0]["actual_mm"] == 2000.0


def test_correct_size_wrong_type_is_not_bound() -> None:
    source = "新建图纸，画一个宽5米高3米的矩形"
    coverage = _coverage(_interpret(source))
    trial = _trial(_interpret(source))
    # Same bounding extents, but a triangle is not the requested rectangle.
    trial["geometries"] = [{
        "id": 1, "layer_id": 1, "type": "polyline", "closed": True,
        "vertices": [{"x": 0, "y": 0}, {"x": 5, "y": 0}, {"x": 0, "y": 3}],
    }]
    bound = _bind(source, coverage, trial)
    assert bound["state"] == "partial"
    clause = next(item for item in bound["clauses"]
                  if item["requirement"] == "画一个宽5米高3米的矩形")
    assert clause["status"] == "unbound"


def test_multiple_objects_make_binding_ambiguous() -> None:
    source = "新建图纸，画一个宽5米高3米的矩形"
    coverage = _coverage(_interpret(source))
    trial = _trial(_interpret(source))
    second = deepcopy(trial["logical_objects"][0])
    second["object_id"] = "shape-2"
    second["geometry_refs"] = [2]
    trial["logical_objects"].append(second)
    trial["geometries"].append({
        "id": 2, "layer_id": 1, "type": "polyline", "closed": True,
        "vertices": [{"x": 10, "y": 0}, {"x": 15, "y": 0},
                     {"x": 15, "y": 3}, {"x": 10, "y": 3}],
    })
    trial["symbol_table"]["shape-2"] = [2]
    trial["plan"]["steps"].append({
        "op": "add_rectangle", "step_id": "step-2", "output_ref": "shape-2",
        "layer_id": 1, "semantic": {"object_type": "rectangle"},
        "origin": {"x": 10, "y": 0}, "width": 5, "height": 3, "rotation_deg": 0,
    })
    bound = _bind(source, coverage, trial)
    assert bound["state"] == "partial"
    clause = next(item for item in bound["clauses"]
                  if item["requirement"] == "画一个宽5米高3米的矩形")
    assert clause["status"] == "unbound"


def test_conflicting_source_facts_are_not_collapsed_to_first_value() -> None:
    source = "新建图纸，画一个宽5米高3米的矩形"
    coverage = _coverage(_interpret(source))
    clause = next(item for item in coverage["clauses"]
                  if item["requirement"] == "画一个宽5米高3米的矩形")
    clause["unsupported_evidence"].append({
        "requirement_id": "user:0:scalar-3:width:?",
        "field": "width", "expected_mm": 6000.0,
        "source_evidence": {"start": 8, "end": 11, "text": "宽5米"},
        "reason": "来源冲突",
    })
    bound = _bind(source, coverage, _trial(_interpret(source)))
    assert bound["state"] == "partial"
    clause = next(item for item in bound["clauses"]
                  if item["requirement"] == "画一个宽5米高3米的矩形")
    assert clause["status"] == "partial"
    assert clause["binding_failures"][0]["expected_mm"] == 6000.0


def test_missing_project_evidence_leaves_create_clause_unverified() -> None:
    source = "新建图纸，画一个宽5米高3米的矩形"
    coverage = _coverage(_interpret(source))
    bound = _bind(source, coverage, _trial(_interpret(source)), with_project=False)
    assert bound["state"] == "partial"
    clauses = {item["requirement"]: item for item in bound["clauses"]}
    assert clauses["新建图纸"]["status"] == "unverified"
    assert clauses["画一个宽5米高3米的矩形"]["status"] == "verified"


def test_missing_geometry_keeps_dimension_requirement_unbound() -> None:
    source = "新建图纸，画一个宽5米高3米的矩形"
    coverage = _coverage(_interpret(source))
    trial = _trial(_interpret(source))
    trial["geometries"] = []
    bound = _bind(source, coverage, trial)
    assert bound["state"] == "partial"
    clause = next(item for item in bound["clauses"]
                  if item["requirement"] == "画一个宽5米高3米的矩形")
    assert clause["status"] == "unbound"
