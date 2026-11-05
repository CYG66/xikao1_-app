from __future__ import annotations

import math

import pytest

from app.cad_construction import (
    CadConstructionPlan,
    ConstructionPlanError,
    execute_construction_plan,
)
from app.cad_constraint_solver import available_constraint_backends


def _semantic(label: str) -> dict:
    return {"label": label, "object_type": "test_object"}


def test_concentric_and_equal_radius_constraints_are_solved_and_verified() -> None:
    result = execute_construction_plan({
        "schema_version": "cad.construction-plan.v1",
        "units": "m",
        "steps": [
            {
                "op": "add_circle", "step_id": "reference",
                "output_ref": "reference", "semantic": _semantic("参考圆"),
                "center": {"x": 4, "y": 6}, "radius": 2,
            },
            {
                "op": "add_circle", "step_id": "concentric_target",
                "output_ref": "concentric_target", "semantic": _semantic("同心目标圆"),
                "center": {"x": -1, "y": 3}, "radius": 0.5,
            },
            {
                "op": "add_circle", "step_id": "radius_target",
                "output_ref": "radius_target", "semantic": _semantic("等半径目标圆"),
                "center": {"x": 10, "y": 0}, "radius": 0.5,
            },
        ],
        "constraints": [
            {
                "kind": "concentric", "constraint_id": "same-center",
                "target_ref": "concentric_target", "reference_ref": "reference",
            },
            {
                "kind": "equal_radius", "constraint_id": "same-radius",
                "target_ref": "radius_target", "reference_ref": "reference",
            },
        ],
    })

    concentric_target = result["geometries"][1]
    radius_target = result["geometries"][2]
    assert concentric_target["center"]["x"] == pytest.approx(4000)
    assert concentric_target["center"]["y"] == pytest.approx(6000)
    assert concentric_target["radius"] == pytest.approx(500)
    assert radius_target["center"]["x"] == pytest.approx(10000)
    assert radius_target["center"]["y"] == pytest.approx(0)
    assert radius_target["radius"] == pytest.approx(2000)
    assert result["constraint_solve"]["verified"] is True
    assert result["constraint_solve"]["constraint_count"] == 2
    assert all(item["residual"] == 0 for item in result["constraint_solve"]["constraints"])


def test_parallel_and_perpendicular_constraints_rotate_only_target() -> None:
    base = {
        "schema_version": "cad.construction-plan.v1",
        "units": "m",
        "steps": [
            {
                "op": "add_line", "step_id": "reference",
                "output_ref": "reference", "semantic": _semantic("参考线"),
                "start": {"x": 0, "y": 0}, "end": {"x": 5, "y": 0},
            },
            {
                "op": "add_line", "step_id": "target",
                "output_ref": "target", "semantic": _semantic("目标线"),
                "start": {"x": 10, "y": 0}, "end": {"x": 11, "y": 1},
            },
        ],
    }
    parallel = execute_construction_plan({
        **base,
        "constraints": [{
            "kind": "parallel", "constraint_id": "parallel-lines",
            "target_ref": "target", "reference_ref": "reference",
        }],
    })
    target = parallel["geometries"][1]
    assert target["end"]["y"] == pytest.approx(target["start"]["y"])
    assert parallel["geometries"][0]["end"] == {"x": 5000.0, "y": 0.0, "z": 0.0}

    perpendicular = execute_construction_plan({
        **base,
        "constraints": [{
            "kind": "perpendicular", "constraint_id": "perpendicular-lines",
            "target_ref": "target", "reference_ref": "reference",
        }],
    })
    target = perpendicular["geometries"][1]
    assert target["end"]["x"] == pytest.approx(target["start"]["x"])


def test_equal_size_and_center_distance_update_geometry_and_logical_bounds() -> None:
    result = execute_construction_plan({
        "schema_version": "cad.construction-plan.v1",
        "units": "m",
        "steps": [
            {
                "op": "add_rectangle", "step_id": "reference",
                "output_ref": "reference", "semantic": _semantic("参考矩形"),
                "origin": {"x": 0, "y": 0}, "width": 8, "height": 4,
            },
            {
                "op": "add_rectangle", "step_id": "target",
                "output_ref": "target", "semantic": _semantic("目标矩形"),
                "origin": {"x": 20, "y": 0}, "width": 2, "height": 1,
            },
        ],
        "constraints": [
            {
                "kind": "equal_size", "constraint_id": "same-size",
                "target_ref": "target", "reference_ref": "reference",
            },
            {
                "kind": "center_distance", "constraint_id": "ten-apart",
                "target_ref": "target", "reference_ref": "reference",
                "distance": 10,
            },
        ],
    })

    target_object = result["logical_objects"][1]
    bounds = target_object["bounds"]
    assert bounds["max_x"] - bounds["min_x"] == pytest.approx(8000)
    assert bounds["max_y"] - bounds["min_y"] == pytest.approx(4000)
    centers = []
    for geometry in result["geometries"]:
        xs = [point["x"] for point in geometry["vertices"]]
        ys = [point["y"] for point in geometry["vertices"]]
        centers.append(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2))
    assert math.hypot(
        centers[1][0] - centers[0][0],
        centers[1][1] - centers[0][1],
    ) == pytest.approx(10000)


def test_constraint_references_are_strict_and_native_backend_is_not_faked() -> None:
    with pytest.raises(ValueError, match="unavailable reference_ref"):
        CadConstructionPlan.model_validate({
            "steps": [{
                "op": "add_circle", "step_id": "circle",
                "output_ref": "circle", "semantic": _semantic("圆"),
                "center": {"x": 0, "y": 0}, "radius": 1,
            }],
            "constraints": [{
                "kind": "concentric", "constraint_id": "bad-reference",
                "target_ref": "circle", "reference_ref": "missing",
            }],
        })

    capabilities = available_constraint_backends()
    unavailable = next(
        (name for name in ("solvespace", "planegcs") if not capabilities[name]["available"]),
        None,
    )
    if unavailable is None:
        pytest.skip("native solver is available on this machine")
    with pytest.raises(ConstructionPlanError) as error:
        execute_construction_plan({
            "constraint_backend": unavailable,
            "steps": [
                {
                    "op": "add_circle", "step_id": "one", "output_ref": "one",
                    "semantic": _semantic("圆1"), "center": {"x": 0, "y": 0},
                    "radius": 1,
                },
                {
                    "op": "add_circle", "step_id": "two", "output_ref": "two",
                    "semantic": _semantic("圆2"), "center": {"x": 2, "y": 0},
                    "radius": 1,
                },
            ],
            "constraints": [{
                "kind": "concentric", "constraint_id": "native-required",
                "target_ref": "two", "reference_ref": "one",
            }],
        })
    assert error.value.code == "constraint_backend_unavailable"


@pytest.mark.parametrize("backend", ["planegcs", "solvespace"])
def test_available_native_backend_solves_in_isolated_worker_and_is_reverified(
    backend: str,
) -> None:
    if not available_constraint_backends()[backend]["available"]:
        pytest.skip(f"{backend} is not installed")
    result = execute_construction_plan({
        "constraint_backend": backend,
        "steps": [
            {
                "op": "add_line", "step_id": "reference", "output_ref": "reference",
                "semantic": _semantic("参考线"),
                "start": {"x": 0, "y": 0}, "end": {"x": 5, "y": 0},
            },
            {
                "op": "add_line", "step_id": "target", "output_ref": "target",
                "semantic": _semantic("目标线"),
                "start": {"x": 10, "y": 0}, "end": {"x": 11, "y": 1},
            },
        ],
        "constraints": [{
            "kind": "perpendicular", "constraint_id": "native-perpendicular",
            "target_ref": "target", "reference_ref": "reference",
        }],
    })
    report = result["constraint_solve"]
    assert report["backend"] == backend
    assert report["verified"] is True
    assert report["native_result"]["schema"] == "cad.native-constraint-result.v1"
    assert report["native_result"]["constraints"][0]["constraint_id"] == "native-perpendicular"
    target = result["geometries"][1]
    assert target["end"]["x"] == pytest.approx(target["start"]["x"], abs=1e-5)


def test_auto_backend_remains_builtin_without_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XLINE_CONSTRAINT_BACKEND_AUTO", raising=False)
    result = execute_construction_plan({
        "steps": [
            {
                "op": "add_circle", "step_id": "one", "output_ref": "one",
                "semantic": _semantic("圆1"), "center": {"x": 0, "y": 0}, "radius": 1,
            },
            {
                "op": "add_circle", "step_id": "two", "output_ref": "two",
                "semantic": _semantic("圆2"), "center": {"x": 2, "y": 0}, "radius": 1,
            },
        ],
        "constraints": [{
            "kind": "center_distance", "constraint_id": "three-apart",
            "target_ref": "two", "reference_ref": "one", "distance": 3,
        }],
    })
    assert result["constraint_solve"]["backend"] == "builtin"
    assert result["constraint_solve"]["native_result"] is None


@pytest.mark.parametrize("backend", ["planegcs", "solvespace"])
def test_native_backend_reports_ordered_builtin_fallback_for_equal_size(backend: str) -> None:
    if not available_constraint_backends()[backend]["available"]:
        pytest.skip(f"{backend} is not installed")
    result = execute_construction_plan({
        "constraint_backend": backend,
        "steps": [
            {
                "op": "add_rectangle", "step_id": "reference", "output_ref": "reference",
                "semantic": _semantic("参考矩形"), "origin": {"x": 0, "y": 0},
                "width": 8, "height": 4,
            },
            {
                "op": "add_rectangle", "step_id": "target", "output_ref": "target",
                "semantic": _semantic("目标矩形"), "origin": {"x": 20, "y": 0},
                "width": 2, "height": 1,
            },
        ],
        "constraints": [{
            "kind": "equal_size", "constraint_id": "same-bounds",
            "target_ref": "target", "reference_ref": "reference",
        }],
    })
    report = result["constraint_solve"]
    assert report["verified"] is True
    assert report["builtin_fallback_constraint_ids"] == ["same-bounds"]
    assert report["native_result"]["constraints"][0]["status"] == "builtin_fallback"
