from __future__ import annotations

from app.cad_sketch_graph import evaluate_sketch_graph_candidates
from app.cad_visual_scoring import score_candidate_visuals


def _semantic(label: str) -> dict:
    return {"label": label, "object_type": "visual_test"}


def test_visual_score_is_explicitly_non_authoritative() -> None:
    report = score_candidate_visuals([{
        "id": 1,
        "layer_id": 1,
        "type": "polyline",
        "vertices": [
            {"x": 0, "y": 0, "z": 0},
            {"x": 1000, "y": 0, "z": 0},
            {"x": 1000, "y": 1000, "z": 0},
            {"x": 0, "y": 1000, "z": 0},
            {"x": 0, "y": 0, "z": 0},
        ],
    }])
    assert report["score"] > 0
    assert report["authoritative"] is False
    assert report["used_for_gate"] is False
    assert report["role"] == "geometry_score_tie_break_only"


def test_visual_score_only_breaks_equal_geometry_score_ties() -> None:
    thin_rectangle_plan = {
        "steps": [{
            "op": "add_rectangle", "step_id": "thin", "output_ref": "thin",
            "semantic": _semantic("狭长矩形"), "origin": {"x": 0, "y": 0},
            "width": 10, "height": 1,
        }],
    }
    rectangle_plan = {
        "steps": [{
            "op": "add_rectangle", "step_id": "rectangle", "output_ref": "rectangle",
            "semantic": _semantic("矩形"), "origin": {"x": 0, "y": 0},
            "width": 5, "height": 3,
        }],
    }
    result = evaluate_sketch_graph_candidates({
        "requirement": "比较两个合法候选",
        "candidates": [
            {"candidate_id": "thin", "title": "狭长矩形", "rationale": "合法狭长矩形", "plan": thin_rectangle_plan},
            {"candidate_id": "rectangle", "title": "矩形", "rationale": "合法矩形", "plan": rectangle_plan},
        ],
    })
    by_id = {item["candidate_id"]: item for item in result["candidates"]}
    assert by_id["thin"]["score"] == by_id["rectangle"]["score"]
    assert by_id["rectangle"]["visual_score"]["score"] > by_id["thin"]["visual_score"]["score"]
    assert result["recommended_candidate_id"] == "rectangle"
    assert by_id["rectangle"]["score_evidence"]["geometry_is_authoritative"] is True
    assert by_id["rectangle"]["score_evidence"]["visual_score_is_authoritative"] is False
