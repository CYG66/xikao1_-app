from __future__ import annotations

import math

import pytest

from app.cad_construction import (
    ConstructionPlanError,
    ConstructionPoint,
    FreeOutlineLayout,
    _apply_free_outline_layout,
    _outline_shape_invariant_refs,
    execute_construction_plan,
)
from app.cad_construction_interpreter import (
    _source_allows_outline_deformation,
    _source_requires_shape_preservation,
)


def _flower_points(cx=2000.0, cy=2000.0, samples=300):
    points = []
    for index in range(samples):
        angle = 2 * math.pi * index / samples
        radius = (1.25 + 0.6 * math.cos(5 * angle)) * 1000.0
        points.append({"x": cx + radius * math.cos(angle),
                       "y": cy + radius * math.sin(angle)})
    return points


def _circle_points(cx=1000.0, cy=1000.0, radius=500.0, samples=180):
    return [{"x": cx + radius * math.cos(2 * math.pi * index / samples),
             "y": cy + radius * math.sin(2 * math.pi * index / samples)}
            for index in range(samples)]


def _bounds(points):
    xs = [point["x"] for point in points]
    ys = [point["y"] for point in points]
    return (max(xs) - min(xs), max(ys) - min(ys),
            (max(xs) + min(xs)) / 2.0, (max(ys) + min(ys)) / 2.0)


def _pairwise_ratios(points):
    ratios = []
    for index in range(0, len(points), 10):
        first = points[index]
        second = points[(index + 37) % len(points)]
        ratios.append(math.dist((first["x"], first["y"]),
                                (second["x"], second["y"])))
    return ratios


def test_inherent_curve_outline_conflicts_instead_of_stretching():
    outline = {"id": 1, "type": "polyline", "closed": True,
               "vertices": _circle_points(radius=1000.0)}
    original = [dict(point) for point in outline["vertices"]]
    layout = [FreeOutlineLayout(target_ref="curve", width=4.0, height=2.0)]
    with pytest.raises(ConstructionPlanError) as caught:
        _apply_free_outline_layout(
            layout, [outline], {"curve": [1]}, 1000.0,
            shape_invariant_refs={"curve"},
        )
    assert caught.value.code == "shape_constraint_conflict"
    assert outline["vertices"] == original


def test_explicit_deformation_permission_allows_independent_fit():
    outline = {"id": 1, "type": "polyline", "closed": True,
               "vertices": _circle_points(radius=1000.0)}
    layout = [FreeOutlineLayout(target_ref="curve", width=4.0, height=2.0,
                                preserve_shape=False)]
    _apply_free_outline_layout(
        layout, [outline], {"curve": [1]}, 1000.0,
        shape_invariant_refs={"curve"},
    )
    width, height, _, _ = _bounds(outline["vertices"])
    assert abs(width - 4000.0) < 1e-6
    assert abs(height - 2000.0) < 1e-6


def test_shape_invariant_refs_are_source_capability_based():
    from types import SimpleNamespace
    steps = [
        SimpleNamespace(op="add_bezier", output_ref="bezier"),
        SimpleNamespace(op="add_spline", output_ref="spline"),
        SimpleNamespace(op="add_parametric_curve", output_ref="parametric"),
        SimpleNamespace(op="add_composite_path", output_ref="polyline_only",
                        segments=[SimpleNamespace(kind="line")]),
        SimpleNamespace(op="add_composite_path", output_ref="curved",
                        segments=[SimpleNamespace(kind="bezier")]),
        SimpleNamespace(op="add_rotational_path", output_ref="radial",
                        segments=[SimpleNamespace(kind="line")]),
    ]
    refs = _outline_shape_invariant_refs(steps, {"asserted_radial"})
    assert refs == {"bezier", "spline", "curved", "radial", "asserted_radial"}
    assert "parametric" not in refs
    assert "polyline_only" not in refs


@pytest.mark.parametrize("text,expected", [
    ("把这朵花拉伸到宽4米高2米", True),
    ("允许非等比缩放到4x2", True),
    ("不要拉伸，保持形状，宽4米高2米", False),
    ("保持原有比例，不要改变形状", False),
    ("画一朵花，宽4米高2米", False),
])
def test_source_deformation_permission_is_explicit(text, expected):
    assert _source_allows_outline_deformation(text) is expected


@pytest.mark.parametrize("text,expected", [
    ("画一个自由轮廓，保持形状，宽4米高2米", True),
    ("保持原有比例，不要改变形状", True),
    ("不要拉伸，保持形状，宽4米高2米", True),
    ("允许非等比缩放，保持形状", False),
    ("画一个自由轮廓，宽4米高2米", False),
])
def test_source_shape_preservation_requires_explicit_words(text, expected):
    assert _source_requires_shape_preservation(text) is expected


def test_preserve_layout_reports_center_metrics_without_overwriting_legacy():
    outline = {"id": 1, "type": "polyline", "closed": True,
               "vertices": _circle_points(radius=1000.0)}
    layout = [FreeOutlineLayout(
        target_ref="curve", width=4.0, height=4.0,
        center=ConstructionPoint(x=5.0, y=5.0),
    )]
    diagnostics = _apply_free_outline_layout(
        layout, [outline], {"curve": [1]}, 1000.0,
        rotational_refs={"curve"}, shape_invariant_refs={"curve"},
    )
    diagnostic = diagnostics[0]
    assert diagnostic["shape_center"] == diagnostic["area_centroid_mm"]
    assert diagnostic["bbox_center_mm"] == [1000.0, 1000.0]
    assert diagnostic["rotational_symmetry_center_mm"] == diagnostic["area_centroid_mm"]
    assert diagnostic["center_policy"] == "rotational_symmetry_center"
    assert diagnostic["construction_reference_center_mm"] == [5000.0, 5000.0]


def test_execution_reports_post_transform_centers_without_overwriting_pre_fit_fields():
    plan = {
        "units": "mm",
        "steps": [{"op": "add_polyline", "step_id": "outline",
                   "output_ref": "flower", "semantic": {"label": "花瓣轮廓"},
                   "closed": True, "vertices": _flower_points()}],
        "assertions": [{"kind": "radial_pattern", "assertion_id": "lobes",
                        "target_ref": "flower", "lobes": 5,
                        "profile": "smooth"}],
        "free_outline_layout": [{"target_ref": "flower", "width": 5000.0,
                                 "height": 5000.0, "preserve_shape": True}],
    }
    result = execute_construction_plan(plan)
    diagnostic = result["layout_quality"][0]
    assert diagnostic["measurement_stage"] == "post_transform"
    assert abs(diagnostic["final_bbox_size_mm"][0] - 5000.0) < 60.0
    assert abs(diagnostic["final_bbox_size_mm"][1] - 5000.0) < 60.0
    assert max(diagnostic["final_residual_mm"]) < 60.0
    assert diagnostic["bbox_center_mm"] != diagnostic["final_bbox_center_mm"]
    assert all(abs(a - b) < 1e-6 for a, b in zip(
        diagnostic["final_area_centroid_mm"], diagnostic["area_centroid_mm"]))


def test_circle_keeps_radius_consistency_after_uniform_fit():
    outline = {"id": 1, "type": "polyline", "closed": True,
               "vertices": _circle_points()}
    layout = [FreeOutlineLayout(target_ref="circle", width=3.0, height=3.0,
                                preserve_shape=True)]
    diagnostics = _apply_free_outline_layout(
        layout, [outline], {"circle": [1]}, 1000.0,
    )
    radii = [math.dist((point["x"], point["y"]), (1000.0, 1000.0))
             for point in outline["vertices"]]
    assert max(radii) - min(radii) < 1e-6
    assert abs(max(radii) - 1500.0) < 1e-6
    assert diagnostics[0]["policy"] == "preserve_shape"
    assert diagnostics[0]["rotation_deg"] == 0.0
    assert diagnostics[0]["residual_mm"] == [0.0, 0.0]


def test_rotational_outline_uses_uniform_scale_and_legal_rotation():
    outline = {"id": 1, "type": "polyline", "closed": True,
               "vertices": _flower_points()}
    before = _pairwise_ratios(outline["vertices"])
    layout = [FreeOutlineLayout(target_ref="flower", width=8.0, height=8.0)]
    diagnostics = _apply_free_outline_layout(
        layout, [outline], {"flower": [1]}, 1000.0,
        rotational_refs={"flower"},
    )
    width, height, center_x, center_y = _bounds(outline["vertices"])
    assert abs(width - 8000.0) < 1e-6
    assert abs(height - 8000.0) < 1e-6
    assert len(diagnostics) == 1
    assert diagnostics[0]["policy"] == "preserve_shape"
    assert diagnostics[0]["residual_mm"] == [0.0, 0.0]
    assert 0.0 < diagnostics[0]["rotation_deg"] < 90.0
    assert diagnostics[0]["uniform_scale"] > 0
    after = _pairwise_ratios(outline["vertices"])
    scale = diagnostics[0]["uniform_scale"]
    for original, scaled in zip(before, after):
        assert abs(scaled - original * scale) <= 1e-6 * max(1.0, original)


def test_free_polygon_keeps_independent_width_and_height():
    outline = {"id": 1, "type": "polyline", "closed": True,
               "vertices": [{"x": 0, "y": 0}, {"x": 4000, "y": 0},
                            {"x": 4000, "y": 2000}, {"x": 0, "y": 2000}]}
    layout = [FreeOutlineLayout(target_ref="rectangle", width=4.0, height=4.0)]
    diagnostics = _apply_free_outline_layout(
        layout, [outline], {"rectangle": [1]}, 1000.0,
    )
    width, height, _, _ = _bounds(outline["vertices"])
    assert abs(width - 4000.0) < 1e-6
    assert abs(height - 4000.0) < 1e-6
    assert diagnostics == []


def test_explicit_preserve_never_rotates_an_oriented_outline():
    outline = {"id": 1, "type": "polyline", "closed": True,
               "vertices": [{"x": 0, "y": 0}, {"x": 4000, "y": 0},
                            {"x": 4000, "y": 2000}, {"x": 0, "y": 2000}]}
    layout = [FreeOutlineLayout(target_ref="rectangle", width=4.0, height=4.0,
                                preserve_shape=True)]
    with pytest.raises(ConstructionPlanError) as caught:
        _apply_free_outline_layout(
            layout, [outline], {"rectangle": [1]}, 1000.0,
        )
    assert caught.value.code == "shape_constraint_conflict"
    assert caught.value.details["requested_mm"] == [4000.0, 4000.0]
    assert caught.value.details["achievable_mm"] == [4000.0, 2000.0]
    assert caught.value.details["rotation_deg"] == 0.0
    width, height, _, _ = _bounds(outline["vertices"])
    assert width == 4000.0 and height == 2000.0


def test_rotational_conflict_is_reported_not_stretched_away():
    outline = {"id": 1, "type": "polyline", "closed": True,
               "vertices": _flower_points()}
    original = [dict(point) for point in outline["vertices"]]
    layout = [FreeOutlineLayout(target_ref="flower", width=3.0, height=7.0)]
    with pytest.raises(ConstructionPlanError) as caught:
        _apply_free_outline_layout(
            layout, [outline], {"flower": [1]}, 1000.0,
            rotational_refs={"flower"},
        )
    assert caught.value.code == "shape_constraint_conflict"
    assert max(caught.value.details["residual_mm"]) > 1.0
    assert caught.value.details["requested_mm"] == [3000.0, 7000.0]
    # The conflict is surfaced without mutating or stretching the source shape.
    assert outline["vertices"] == original


def test_centre_request_places_rotated_bbox_centre():
    outline = {"id": 1, "type": "polyline", "closed": True,
               "vertices": _flower_points(cx=3000.0, cy=3000.0)}
    layout = [FreeOutlineLayout(target_ref="flower", width=6.0, height=6.0,
                                center=ConstructionPoint(x=5, y=5))]
    _apply_free_outline_layout(
        layout, [outline], {"flower": [1]}, 1000.0,
        rotational_refs={"flower"},
    )
    width, height, center_x, center_y = _bounds(outline["vertices"])
    assert abs(width - 6000.0) < 1e-6
    assert abs(height - 6000.0) < 1e-6
    assert abs(center_x - 5000.0) < 1e-6
    assert abs(center_y - 5000.0) < 1e-6
