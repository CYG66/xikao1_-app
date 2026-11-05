# -*- coding: utf-8 -*-
"""Regression tests for MIRROR / OFFSET / ARRAY / parametric constraints."""

import math

import pytest

from app.cad_edit_contract import (
    CadEditCommand,
    build_cad_edit_contract,
    cad_edit_contract_to_edit,
)
from app.cad_edit_gate import build_cad_edit_preflight, validate_declared_edit_effect
from app.incremental_cad import edit_candidate_geometries, parse_incremental_edit
from app.logical_topology import evolve_logical_graph_for_edit


def _rectangle(instance, x, y, width=2000, height=1000):
    return [
        {"id": instance * 10 + 1, "type": "line", "start": {"x": x, "y": y},
         "end": {"x": x + width, "y": y}, "template_instance": instance,
         "template_type": "rectangle"},
        {"id": instance * 10 + 2, "type": "line", "start": {"x": x + width, "y": y},
         "end": {"x": x + width, "y": y + height}, "template_instance": instance,
         "template_type": "rectangle"},
        {"id": instance * 10 + 3, "type": "line", "start": {"x": x + width, "y": y + height},
         "end": {"x": x, "y": y + height}, "template_instance": instance,
         "template_type": "rectangle"},
        {"id": instance * 10 + 4, "type": "line", "start": {"x": x, "y": y + height},
         "end": {"x": x, "y": y}, "template_instance": instance,
         "template_type": "rectangle"},
    ]


def _asymmetric_rect(instance, x, y):
    """Non-symmetric L-shape so a mirror visibly changes the geometry."""
    return [
        {"id": instance * 10 + 1, "type": "line", "start": {"x": x, "y": y},
         "end": {"x": x + 2000, "y": y}, "template_instance": instance},
        {"id": instance * 10 + 2, "type": "line", "start": {"x": x + 2000, "y": y},
         "end": {"x": x + 2000, "y": y + 1000}, "template_instance": instance},
        {"id": instance * 10 + 3, "type": "line", "start": {"x": x + 2000, "y": y + 1000},
         "end": {"x": x + 1000, "y": y + 1000}, "template_instance": instance},
        {"id": instance * 10 + 4, "type": "line", "start": {"x": x + 1000, "y": y + 1000},
         "end": {"x": x + 1000, "y": y + 2000}, "template_instance": instance},
        {"id": instance * 10 + 5, "type": "line", "start": {"x": x + 1000, "y": y + 2000},
         "end": {"x": x, "y": y + 2000}, "template_instance": instance},
        {"id": instance * 10 + 6, "type": "line", "start": {"x": x, "y": y + 2000},
         "end": {"x": x, "y": y}, "template_instance": instance},
    ]


def _circle(instance, cx, cy, radius):
    return [{"id": instance * 10 + 1, "type": "circle",
             "center": {"x": cx, "y": cy}, "radius": radius,
             "template_instance": instance}]


def _instances(geometries):
    return sorted({item["template_instance"] for item in geometries})


def _x_range(geometries, instance):
    xs = []
    for item in geometries:
        if item["template_instance"] != instance:
            continue
        for point in (item.get("start"), item.get("end"), item.get("center")):
            if isinstance(point, dict):
                xs.append(float(point["x"]))
    return min(xs), max(xs)


def _contract_for(geometries, edit, source_text):
    contract = build_cad_edit_contract(edit, source_text=source_text)
    replayed, error = edit_candidate_geometries(geometries, cad_edit_contract_to_edit(contract))
    return contract, replayed, error


# ---------------------------------------------------------------- mirror


class TestMirror:
    def test_mirror_vertical_keep_source(self):
        source = _asymmetric_rect(1, 0, 0) + _asymmetric_rect(2, 5000, 0)
        out, err = edit_candidate_geometries(source, {
            "operation": "mirror", "instance": 1, "mirror_axis": "vertical",
            "keep_source": True,
        })
        assert err is None and out is not None
        assert _instances(out) == [1, 2, 3]
        assert out[0]["template_instance"] == 1  # source untouched
        mirror_items = [item for item in out if item["template_instance"] == 3]
        # duplicate edges that coincide with the source are dropped (L-shape
        # mirror keeps 4 of the 6 edges; the notch moves from x=0 to x=2000)
        assert len(mirror_items) == 4
        corner_keys = {
            tuple(sorted(((item["start"]["x"], item["start"]["y"]),
                          (item["end"]["x"], item["end"]["y"]))))
            for item in mirror_items
        }
        assert (0.0, 0.0) in {p for key in corner_keys for p in key}
        assert (2000.0, 0.0) in {p for key in corner_keys for p in key}

    def test_mirror_horizontal_replaces_source(self):
        source = _asymmetric_rect(1, 0, 0)
        out, err = edit_candidate_geometries(source, {
            "operation": "mirror", "instance": 1, "mirror_axis": "horizontal",
            "keep_source": False,
        })
        assert err is None and out is not None
        assert _instances(out) == [1]
        assert "new_instance" not in out and out[0]["template_instance"] == 1

    def test_mirror_contract_roundtrip(self):
        source = _asymmetric_rect(1, 0, 0) + _asymmetric_rect(2, 5000, 0)
        edit = {
            "operation": "mirror", "instance": 1, "mirror_axis": "vertical",
            "keep_source": True, "new_instance": 3,
        }
        contract, replayed, error = _contract_for(source, edit, "把第1个图形左右镜像")
        assert error is None and replayed is not None
        direct, _ = edit_candidate_geometries(source, dict(edit))
        assert [x["id"] for x in replayed] == [x["id"] for x in direct]
        effect = validate_declared_edit_effect(source, replayed, contract)
        assert effect["verified"] is True

    def test_mirror_without_axis_rejected(self):
        source = _asymmetric_rect(1, 0, 0)
        out, err = edit_candidate_geometries(source, {
            "operation": "mirror", "instance": 1, "keep_source": True,
        })
        assert out is None and "镜像方向" in str(err)

    def test_mirror_fully_symmetric_shape_rejected(self):
        # A symmetric rectangle mirrors onto itself -> no meaningful copy
        source = _rectangle(1, 0, 0)
        out, err = edit_candidate_geometries(source, {
            "operation": "mirror", "instance": 1, "mirror_axis": "vertical",
            "keep_source": True,
        })
        assert out is None and "完全对称" in str(err)

    def test_mirror_updates_arc_direction_and_ellipse_axis(self):
        source = [
            {"id": 1, "type": "arc", "center": {"x": 0, "y": 0},
             "radius": 500, "start_angle": 20, "end_angle": 110,
             "template_instance": 1},
            {"id": 2, "type": "ellipse", "center": {"x": 1000, "y": 0},
             "major_axis": {"x": 300, "y": 100}, "ratio": 0.5,
             "start_angle": 10, "end_angle": 80, "template_instance": 1},
        ]
        out, err = edit_candidate_geometries(source, {
            "operation": "mirror", "instance": 1, "mirror_axis": "vertical",
            "keep_source": False,
        })
        assert err is None and out is not None
        arc = next(item for item in out if item["type"] == "arc")
        ellipse = next(item for item in out if item["type"] == "ellipse")
        assert (arc["start_angle"], arc["end_angle"]) == (70.0, 160.0)
        assert ellipse["major_axis"] == {"x": -300, "y": 100}
        assert (ellipse["start_angle"], ellipse["end_angle"]) == (280.0, 350.0)


# ---------------------------------------------------------------- offset


class TestOffset:
    def test_offset_circle_outside(self):
        source = _circle(1, 0, 0, 500)
        out, err = edit_candidate_geometries(source, {
            "operation": "offset", "instance": 1, "offset_side": "outside",
            "distance_mm": 300,
        })
        assert err is None and out is not None
        new = [x for x in out if x["template_instance"] == 2]
        assert new[0]["radius"] == 800.0

    def test_offset_circle_inside_too_far(self):
        source = _circle(1, 0, 0, 200)
        out, err = edit_candidate_geometries(source, {
            "operation": "offset", "instance": 1, "offset_side": "inside",
            "distance_mm": 500,
        })
        assert out is None and "半径" in str(err)

    def test_offset_rectangle_scales(self):
        source = _rectangle(1, 0, 0)
        out, err = edit_candidate_geometries(source, {
            "operation": "offset", "instance": 1, "offset_side": "inside",
            "distance_mm": 200,
        })
        assert err is None and out is not None
        lo, hi = _x_range(out, 2)
        # closed outline scales about its center: 2000 wide * (1000-400)/1000
        assert hi - lo == pytest.approx(1200.0)

    def test_offset_line_translates_along_normal(self):
        source = [{"id": 1, "type": "line", "start": {"x": 0, "y": 0},
                   "end": {"x": 1000, "y": 0}, "template_instance": 1}]
        out, err = edit_candidate_geometries(source, {
            "operation": "offset", "instance": 1, "offset_side": "outside",
            "distance_mm": 100,
        })
        assert err is None and out is not None
        new = [x for x in out if x["template_instance"] == 2][0]
        assert new["start"]["y"] == pytest.approx(100.0)

    def test_offset_contract_roundtrip(self):
        source = _circle(1, 0, 0, 500)
        edit = {
            "operation": "offset", "instance": 1, "offset_side": "outside",
            "distance_mm": 300, "new_instance": 2,
        }
        contract, replayed, error = _contract_for(source, edit, "把第1个图形向外偏移 300 毫米")
        assert error is None and replayed is not None
        effect = validate_declared_edit_effect(source, replayed, contract)
        assert effect["verified"] is True


# ---------------------------------------------------------------- array


class TestArray:
    def test_array_rectangular(self):
        source = _rectangle(1, 0, 0)
        out, err = edit_candidate_geometries(source, {
            "operation": "array", "instance": 1, "array_mode": "rectangular",
            "rows": 2, "columns": 3, "row_spacing_mm": 2000,
            "column_spacing_mm": 3000,
        })
        assert err is None and out is not None
        assert _instances(out) == [1, 2, 3, 4, 5, 6]
        lo, hi = _x_range(out, 6)
        # 3 columns spaced 3000 apart starting at x=0 -> last at 6000
        assert hi == pytest.approx(8000.0)
        ys = [item["start"]["y"] for item in out if item["template_instance"] == 5]
        assert ys[0] == pytest.approx(2000.0)  # second row

    def test_array_polar(self):
        source = _rectangle(1, 0, 0)
        out, err = edit_candidate_geometries(source, {
            "operation": "array", "instance": 1, "array_mode": "polar",
            "count": 4, "angle_degrees": 90,
        })
        assert err is None and out is not None
        assert _instances(out) == [1, 2, 3, 4]

    def test_array_too_many_rejected(self):
        source = _rectangle(1, 0, 0)
        out, err = edit_candidate_geometries(source, {
            "operation": "array", "instance": 1, "array_mode": "rectangular",
            "rows": 8, "columns": 8, "row_spacing_mm": 1000,
            "column_spacing_mm": 1000,
        })
        assert out is None and "50" in str(err)

    def test_array_contract_roundtrip(self):
        source = _rectangle(1, 0, 0)
        edit = {
            "operation": "array", "instance": 1, "array_mode": "rectangular",
            "rows": 2, "columns": 2, "row_spacing_mm": 2000,
            "column_spacing_mm": 3000, "new_instance": 2,
        }
        contract, replayed, error = _contract_for(source, edit, "把第1个图形阵列成 2 行 2 列")
        assert error is None and replayed is not None
        effect = validate_declared_edit_effect(source, replayed, contract)
        assert effect["verified"] is True


# ---------------------------------------------------------------- constraint


class TestConstraint:
    def test_concentric(self):
        source = _circle(1, 0, 0, 500) + _circle(2, 3000, 0, 700)
        out, err = edit_candidate_geometries(source, {
            "operation": "constraint", "instance": 1,
            "reference_instance": 2, "constraint_type": "concentric",
        })
        assert err is None and out is not None
        moved = [x for x in out if x["template_instance"] == 1][0]
        assert moved["center"] == {"x": 3000.0, "y": 0.0}

    def test_parallel_rotates_to_match(self):
        source = [
            {"id": 1, "type": "line", "start": {"x": 0, "y": 0},
             "end": {"x": 1000, "y": 0}, "template_instance": 1},
            {"id": 2, "type": "line", "start": {"x": 0, "y": 500},
             "end": {"x": 0, "y": 1500}, "template_instance": 2},
        ]
        out, err = edit_candidate_geometries(source, {
            "operation": "constraint", "instance": 1,
            "reference_instance": 2, "constraint_type": "parallel",
        })
        assert err is None and out is not None
        line = [x for x in out if x["template_instance"] == 1][0]
        assert line["start"]["x"] == pytest.approx(line["end"]["x"])

    def test_perpendicular(self):
        source = [
            {"id": 1, "type": "line", "start": {"x": 0, "y": 0},
             "end": {"x": 1000, "y": 0}, "template_instance": 1},
            {"id": 2, "type": "line", "start": {"x": 0, "y": 500},
             "end": {"x": 0, "y": 1500}, "template_instance": 2},
        ]
        out, err = edit_candidate_geometries(source, {
            "operation": "constraint", "instance": 1,
            "reference_instance": 2, "constraint_type": "perpendicular",
        })
        assert err is None and out is not None
        line = [x for x in out if x["template_instance"] == 1][0]
        assert line["start"]["y"] == pytest.approx(line["end"]["y"])

    def test_equal_radius(self):
        source = _circle(1, 0, 0, 500) + _circle(2, 3000, 0, 700)
        out, err = edit_candidate_geometries(source, {
            "operation": "constraint", "instance": 1,
            "reference_instance": 2, "constraint_type": "equal",
            "dimension": "半径",
        })
        assert err is None and out is not None
        moved = [x for x in out if x["template_instance"] == 1][0]
        assert moved["radius"] == 700.0

    def test_tangent_circle_circle(self):
        source = _circle(1, 0, 0, 300) + _circle(2, 3000, 0, 700)
        out, err = edit_candidate_geometries(source, {
            "operation": "constraint", "instance": 1,
            "reference_instance": 2, "constraint_type": "tangent",
        })
        assert err is None and out is not None
        moved = [x for x in out if x["template_instance"] == 1][0]
        # external tangent: center distance == 300 + 700 == 1000
        distance = math.hypot(moved["center"]["x"] - 3000, moved["center"]["y"])
        assert distance == pytest.approx(1000.0)

    def test_constraint_contract_roundtrip(self):
        source = _circle(1, 0, 0, 500) + _circle(2, 3000, 0, 700)
        edit = {
            "operation": "constraint", "instance": 1,
            "reference_instance": 2, "constraint_type": "concentric",
        }
        contract, replayed, error = _contract_for(source, edit, "让第1个图形与第2个图形同心")
        assert error is None and replayed is not None
        effect = validate_declared_edit_effect(source, replayed, contract)
        assert effect["verified"] is True

    def test_constraint_same_instance_rejected(self):
        source = _circle(1, 0, 0, 500)
        out, err = edit_candidate_geometries(source, {
            "operation": "constraint", "instance": 1,
            "reference_instance": 1, "constraint_type": "concentric",
        })
        assert out is None and "两个不同的图形实例" in str(err)


# ---------------------------------------------------------------- machine gates


class TestMachineGates:
    def test_preflight_flags_array_as_risk(self):
        source = _rectangle(1, 0, 0)
        edit = {
            "operation": "array", "instance": 1, "array_mode": "rectangular",
            "rows": 3, "columns": 3, "row_spacing_mm": 2000,
            "column_spacing_mm": 2000, "new_instance": 2,
        }
        out, err = edit_candidate_geometries(source, dict(edit))
        assert err is None and out is not None
        contract = build_cad_edit_contract(edit, source_text="阵列")
        preflight = build_cad_edit_preflight(source, out, contract)
        assert preflight["ready"] is True
        assert any("阵列" in reason for reason in preflight["risk_reasons"])

    def test_preflight_rejects_declared_effect_mismatch(self):
        source = _circle(1, 0, 0, 500)
        edit = {
            "operation": "offset", "instance": 1, "offset_side": "outside",
            "distance_mm": 300, "new_instance": 2,
        }
        contract = build_cad_edit_contract(edit, source_text="向外偏移 300 毫米")
        tampered = [dict(item) for item in _circle(1, 0, 0, 500) + _circle(2, 0, 0, 900)]
        preflight = build_cad_edit_preflight(source, tampered, contract)
        assert preflight["ready"] is False

    def test_logical_graph_adopts_array_instances(self):
        source = _rectangle(1, 0, 0)
        edit = {
            "operation": "array", "instance": 1, "array_mode": "rectangular",
            "rows": 2, "columns": 2, "row_spacing_mm": 2000,
            "column_spacing_mm": 2000, "new_instance": 2,
        }
        out, err = edit_candidate_geometries(source, dict(edit))
        assert err is None and out is not None
        contract = build_cad_edit_contract(edit, source_text="阵列")
        objects = [{
            "object_id": "rect-1", "object_type": "rectangle",
            "geometry_refs": [11, 12, 13, 14],
            "bounds": {"min_x": 0, "min_y": 0, "max_x": 2000, "max_y": 1000},
        }]
        objs, _ = evolve_logical_graph_for_edit(source, out, objects, {}, contract)
        object_ids = [item.get("object_id") for item in objs]
        assert any(value == "rect-1" for value in object_ids)
        assert any(value in object_ids for value in ("rectangle-2", "rectangle-3", "rectangle-4"))


# ---------------------------------------------------------------- parse


class TestParseRules:
    @pytest.mark.parametrize("message,expected", [
        ("把第1个图形左右镜像", ("mirror", "vertical", True)),
        ("把第1个图形上下镜像，不保留原图", ("mirror", "horizontal", False)),
        ("把第1个图形向外偏移 500 毫米", ("offset", "outside", 500)),
        ("把第1个图形向内偏移 2 米", ("offset", "inside", 2000)),
        ("把第1个图形阵列成 2 行 3 列，行间距 2 米，列间距 3 米", ("array", "rectangular", None)),
        ("把第1个图形环形阵列 6 个，每 60 度", ("array", "polar", None)),
        ("让第2个图形与第1个图形同心", ("constraint", "concentric", 1)),
        ("让第2个图形与第1个图形平行", ("constraint", "parallel", 1)),
        ("让第2个图形与第1个图形相切", ("constraint", "tangent", 1)),
        ("让第2个图形与第1个图形一样大", ("constraint", "equal", 1)),
        ("让第2个图形与第1个图形垂直", ("constraint", "perpendicular", 1)),
    ])
    def test_parse_chinese(self, message, expected):
        operation, argument, reference = expected
        parsed = parse_incremental_edit(message)
        assert parsed is not None and parsed["operation"] == operation
        key = {
            "mirror": "mirror_axis", "offset": "offset_side",
            "array": "array_mode", "constraint": "constraint_type",
        }[operation]
        assert parsed.get(key) == argument
        if operation == "constraint":
            assert parsed.get("reference_instance") == reference

    def test_parse_keeps_existing_operations(self):
        parsed = parse_incremental_edit("把第1个图形向右移动 5 米")
        assert parsed is not None and parsed["operation"] == "translate"
        assert parse_incremental_edit("今天天气不错") is None

    def test_parse_mirror_without_direction_stays_ambiguous(self):
        parsed = parse_incremental_edit("把第1个图形镜像")
        assert parsed is not None and parsed["operation"] == "mirror"
        assert "mirror_axis" not in parsed


# ---------------------------------------------------------------- contract validation


class TestContractValidation:
    def test_array_requires_full_parameters(self):
        with pytest.raises(ValueError):
            CadEditCommand(
                operation="array",
                target={"scope": "instance", "instance_ids": [1]},
                parameters={"array_mode": "rectangular", "rows": 2},
                created_instance_id=2,
            )

    def test_constraint_requires_reference(self):
        with pytest.raises(ValueError):
            CadEditCommand(
                operation="constraint",
                target={"scope": "instance", "instance_ids": [1]},
                parameters={"constraint_type": "concentric"},
            )

    def test_mirror_keep_source_false_without_created_id(self):
        command = CadEditCommand(
            operation="mirror",
            target={"scope": "instance", "instance_ids": [1]},
            parameters={"mirror_axis": "vertical", "keep_source": False},
        )
        assert command.operation == "mirror"
