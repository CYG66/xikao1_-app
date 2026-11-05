from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.cad_sketch_graph import (
    SketchGraphCandidateSet,
    evaluate_sketch_graph_candidates,
    sketch_graph_candidate_set_json_schema,
)
from app.cad_constraint_solver import available_constraint_backends


def _rectangle_plan(*, x: float = 0.0, asserted: bool = False) -> dict:
    plan = {
        "schema_version": "cad.construction-plan.v1",
        "units": "m",
        "steps": [{
            "step_id": "room",
            "op": "add_rectangle",
            "output_ref": "room.outline",
            "origin": {"x": x, "y": 0},
            "width": 5,
            "height": 3,
            "semantic": {"label": "房间", "object_type": "room"},
        }],
        "assertions": [],
    }
    if asserted:
        plan["assertions"] = [{
            "kind": "bounds_size",
            "assertion_id": "room-size",
            "target_ref": "room.outline",
            "width": 5,
            "height": 3,
        }]
    return plan


def _candidate(candidate_id: str, plan: dict, title: str | None = None) -> dict:
    return {
        "candidate_id": candidate_id,
        "title": title or candidate_id,
        "rationale": "用于比较的确定性拓扑方案",
        "plan": plan,
    }


def test_candidate_set_requires_two_to_three_strict_candidates() -> None:
    with pytest.raises(ValidationError):
        SketchGraphCandidateSet.model_validate({
            "requirement": "画一个房间",
            "candidates": [_candidate("only", _rectangle_plan())],
        })
    with pytest.raises(ValidationError):
        SketchGraphCandidateSet.model_validate({
            "requirement": "画一个房间",
            "candidates": [
                _candidate(str(index), _rectangle_plan(x=index * 10))
                for index in range(4)
            ],
        })
    with pytest.raises(ValidationError):
        SketchGraphCandidateSet.model_validate({
            "requirement": "画一个房间",
            "candidates": [
                _candidate("one", _rectangle_plan()),
                {**_candidate("two", _rectangle_plan(x=10)), "unknown": True},
            ],
        })

    schema = sketch_graph_candidate_set_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["properties"]["candidates"]["minItems"] == 2
    assert schema["properties"]["candidates"]["maxItems"] == 3


def test_graph_exposes_composite_segments_continuity_and_constraints() -> None:
    composite = {
        "schema_version": "cad.construction-plan.v1",
        "steps": [{
            "step_id": "heart",
            "op": "add_composite_path",
            "output_ref": "heart.outline",
            "closed": True,
            "segments": [
                {
                    "kind": "bezier",
                    "control_points": [
                        {"x": 0, "y": 2}, {"x": -4, "y": 5},
                        {"x": -5, "y": -1}, {"x": 0, "y": -4},
                    ],
                },
                {
                    "kind": "bezier",
                    "control_points": [
                        {"x": 0, "y": -4}, {"x": 5, "y": -1},
                        {"x": 4, "y": 5}, {"x": 0, "y": 2},
                    ],
                },
            ],
            "semantic": {"label": "爱心", "object_type": "heart"},
        }],
        "assertions": [{
            "kind": "closed",
            "assertion_id": "heart-closed",
            "target_ref": "heart.outline",
        }],
    }
    result = evaluate_sketch_graph_candidates({
        "requirement": "生成一个闭合爱心",
        "candidates": [
            _candidate("heart", composite),
            _candidate("room", _rectangle_plan(x=10)),
        ],
    })

    graph = result["candidates"][0]["graph"]
    assert [node["kind"] for node in graph["nodes"]].count("segment") == 2
    relations = [edge["relation"] for edge in graph["edges"]]
    assert "connected_to" in relations
    assert "closes_to" in relations
    assert graph["constraints"][0]["constraint_id"] == "heart-closed"
    assert graph["constraints"][0]["target_ref"] == "heart.outline"


def test_graph_exposes_array_dependency() -> None:
    array_plan = {
        "schema_version": "cad.construction-plan.v1",
        "steps": [
            {
                "step_id": "seed", "op": "add_circle",
                "output_ref": "column.seed", "center": {"x": 0, "y": 0},
                "radius": 0.2,
                "semantic": {"label": "立柱", "object_type": "column"},
            },
            {
                "step_id": "array", "op": "rectangular_array",
                "output_ref": "column.array", "source_ref": "column.seed",
                "rows": 1, "columns": 3, "column_spacing": 2,
                "semantic": {"label": "立柱阵列", "object_type": "column_array"},
            },
        ],
    }
    result = evaluate_sketch_graph_candidates({
        "requirement": "三个立柱",
        "candidates": [
            _candidate("array", array_plan),
            _candidate("room", _rectangle_plan(x=10)),
        ],
    })
    edges = result["candidates"][0]["graph"]["edges"]
    dependency = next(item for item in edges if item["relation"] == "depends_on")
    assert dependency["source"] == "object:column.array"
    assert dependency["target"] == "object:column.seed"


def test_candidates_execute_independently_and_only_valid_candidate_is_ranked() -> None:
    invalid = {
        "schema_version": "cad.construction-plan.v1",
        "steps": [{
            "step_id": "broken", "op": "add_composite_path",
            "output_ref": "broken.path",
            "segments": [
                {"kind": "line", "start": {"x": 0, "y": 0}, "end": {"x": 1, "y": 0}},
                {"kind": "line", "start": {"x": 2, "y": 0}, "end": {"x": 3, "y": 0}},
            ],
            "semantic": {"label": "断线", "object_type": "path"},
        }],
    }
    result = evaluate_sketch_graph_candidates({
        "requirement": "比较两种方案",
        "candidates": [
            _candidate("broken", invalid),
            _candidate("verified", _rectangle_plan(asserted=True)),
        ],
    })

    assert result["invalid_candidate_count"] == 1
    assert result["valid_candidate_count"] == 1
    assert result["recommended_candidate_id"] == "verified"
    assert result["candidates"][0]["error"]["code"] == "disconnected_composite_path"
    assert result["candidates"][1]["rank"] == 1


def test_duplicate_geometry_is_not_presented_as_an_independent_candidate() -> None:
    plan = _rectangle_plan(asserted=True)
    result = evaluate_sketch_graph_candidates({
        "requirement": "比较两个矩形方案",
        "candidates": [
            _candidate("first", plan),
            _candidate("same", deepcopy(plan)),
            _candidate("shifted", _rectangle_plan(x=10)),
        ],
    })

    by_id = {item["candidate_id"]: item for item in result["candidates"]}
    assert result["duplicate_candidate_count"] == 1
    assert by_id["same"]["status"] == "duplicate"
    assert by_id["same"]["duplicate_of"] == "first"
    assert by_id["same"]["rank"] is None
    assert result["recommended_candidate_id"] == "first"


def test_graph_preserves_solved_geometric_constraints() -> None:
    constrained = {
        "schema_version": "cad.construction-plan.v1",
        "units": "m",
        "steps": [
            {
                "step_id": "reference", "op": "add_circle",
                "output_ref": "reference", "center": {"x": 0, "y": 0},
                "radius": 2,
                "semantic": {"label": "参考圆", "object_type": "circle"},
            },
            {
                "step_id": "target", "op": "add_circle",
                "output_ref": "target", "center": {"x": 5, "y": 3},
                "radius": 1,
                "semantic": {"label": "目标圆", "object_type": "circle"},
            },
        ],
        "constraints": [{
            "kind": "concentric", "constraint_id": "same-center",
            "target_ref": "target", "reference_ref": "reference",
        }],
    }
    result = evaluate_sketch_graph_candidates({
        "requirement": "比较带同心约束的方案",
        "candidates": [
            _candidate("constrained", constrained),
            _candidate("room", _rectangle_plan(x=10)),
        ],
    })

    first = result["candidates"][0]
    assert first["trial_result"]["constraint_solve"]["verified"] is True
    graph_constraint = first["graph"]["constraints"][0]
    assert graph_constraint["kind"] == "concentric"
    assert graph_constraint["target_ref"] == "target"
    assert graph_constraint["parameters"]["reference_ref"] == "reference"


def test_unavailable_constraint_backend_only_invalidates_its_candidate() -> None:
    capabilities = available_constraint_backends()
    unavailable = next(
        (name for name in ("solvespace", "planegcs") if not capabilities[name]["available"]),
        None,
    )
    if unavailable is None:
        pytest.skip("native constraint backends are available on this machine")

    native_required = {
        "schema_version": "cad.construction-plan.v1",
        "units": "m",
        "constraint_backend": unavailable,
        "steps": [
            {
                "step_id": "reference", "op": "add_circle",
                "output_ref": "reference", "center": {"x": 0, "y": 0},
                "radius": 1,
                "semantic": {"label": "参考圆", "object_type": "circle"},
            },
            {
                "step_id": "target", "op": "add_circle",
                "output_ref": "target", "center": {"x": 3, "y": 0},
                "radius": 0.5,
                "semantic": {"label": "目标圆", "object_type": "circle"},
            },
        ],
        "constraints": [{
            "kind": "concentric", "constraint_id": "same-center",
            "target_ref": "target", "reference_ref": "reference",
        }],
    }
    result = evaluate_sketch_graph_candidates({
        "requirement": "比较原生求解器和内置确定性方案",
        "candidates": [
            _candidate("native-required", native_required),
            _candidate("builtin-valid", _rectangle_plan(asserted=True)),
        ],
    })

    by_id = {item["candidate_id"]: item for item in result["candidates"]}
    assert result["invalid_candidate_count"] == 1
    assert result["valid_candidate_count"] == 1
    assert result["recommended_candidate_id"] == "builtin-valid"
    assert by_id["native-required"]["error"]["code"] == "constraint_backend_unavailable"
