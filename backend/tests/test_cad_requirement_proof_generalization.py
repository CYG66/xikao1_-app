"""D-line generalization matrix: no case names, sizes or fixed positions."""
from __future__ import annotations

import pytest

from tests.test_cad_requirement_proof import (
    A9_TEXT, C7_TEXT, bind_heart, bind_scene, circle, circle_object,
    heart, rectangle, rectangle_object,
)

C7_VARIANTS = [
    (3000, 1000, 400, 100, 200, "矩形A", "角圆A"),
    (6000, 3000, 800, -300, 400, "矩形B", "角圆B"),
    (2500, 1500, 300, 0, 0, "外框C", "顶点圆C"),
    (4500, 2500, 600, 800, -500, "外框D", "角点圆D"),
    (8000, 4000, 1000, -1000, 600, "矩形E", "角圆E"),
    (3500, 2000, 450, 250, 750, "矩形F", "角圆F"),
]

HEART_VARIANTS = [
    (3000, 0, 0, "心形A"),
    (5000, 1000, -1000, "爱心B"),
    (4000, 2500, 3500, "轮廓C"),
    (3600, -500, 2000, "心形D"),
    (4200, 1500, 500, "爱心E"),
    (4800, 3000, -2000, "轮廓F"),
]


@pytest.mark.parametrize("width,height,radius,cx,cy,rect_label,circle_label", C7_VARIANTS)
def test_generalized_corner_circle_scene(width, height, radius, cx, cy,
                                          rect_label, circle_label):
    text = f"画一个矩形宽{width / 1000:g}米高{height / 1000:g}米，在四个角各放一个半径{radius / 1000:g}米的圆"
    geoms = [
        rectangle(1, cx, cy, width, height),
        circle(2, cx - width / 2, cy + height / 2, radius),
        circle(3, cx + width / 2, cy + height / 2, radius),
        circle(4, cx - width / 2, cy - height / 2, radius),
        circle(5, cx + width / 2, cy - height / 2, radius),
    ]
    objects = [
        rectangle_object(f"rect_{width}", 1, rect_label),
        circle_object(f"corner_1_{width}", 2, circle_label),
        circle_object(f"corner_2_{width}", 3, circle_label),
        circle_object(f"corner_3_{width}", 4, circle_label),
        circle_object(f"corner_4_{width}", 5, circle_label),
    ]
    steps = [{"step_id": f"s{i}", "output_ref": item["object_id"]}
             for i, item in enumerate(objects, 1)]
    bound = bind_scene(text, geoms, objects, steps)
    assert bound["state"] == "complete", (text, bound["blocking_requirements"])
    assert bound["verified_requirement_count"] == 2
    assert bound["unresolved_fact_ids"] == []


@pytest.mark.parametrize("size,cx,cy,label", HEART_VARIANTS)
def test_generalized_heart_scene(size, cx, cy, label):
    text = f"生成一个左右对称、平滑闭合的爱心，中心在({cx / 1000:g},{cy / 1000:g})，宽{size / 1000:g}米高{size / 1000:g}米"
    geometry = heart(1, cx, cy, size, size)
    objects = [{"object_id": f"heart_{size}", "object_type": "drawing_part",
                "label": label, "geometry_refs": [1]}]
    bound = bind_heart(text, geometry, objects)
    assert bound["state"] == "complete", (text, bound["blocking_requirements"])
    assert bound["verified_requirement_count"] == 3
    assert bound["unresolved_fact_ids"] == []


def test_multiple_heart_outlines_are_ambiguous():
    text = A9_TEXT
    geometry = heart()
    objects = [
        {"object_id": "heart_one", "object_type": "drawing_part",
         "label": "爱心一", "geometry_refs": [1]},
        {"object_id": "heart_two", "object_type": "drawing_part",
         "label": "爱心二", "geometry_refs": [1]},
    ]
    coverage = bind_heart(text, geometry, objects)
    assert coverage["state"] == "partial"
    assert not any(item["status"] == "verified" for item in coverage["clauses"]
                   if item["requirement"].startswith("生成一个"))
