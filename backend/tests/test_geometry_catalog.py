from app.geometry_catalog import build_geometry_catalog
from unittest.mock import patch

from app.agent_service import robot_agent


def basketball_geometries():
    return [
        {
            "id": 1,
            "type": "polyline",
            "template_instance": 1,
            "template_type": "basketball",
            "vertices": [
                {"x": -14000, "y": -16500},
                {"x": 14000, "y": -16500},
                {"x": 14000, "y": -1500},
                {"x": -14000, "y": -1500},
                {"x": -14000, "y": -16500},
            ],
            "closed": True,
        },
        {
            "id": 2,
            "type": "line",
            "template_instance": 1,
            "template_type": "basketball",
            "start": {"x": 0, "y": -16500},
            "end": {"x": 0, "y": -1500},
        },
        {
            "id": 3,
            "type": "circle",
            "template_instance": 1,
            "template_type": "basketball",
            "center": {"x": 0, "y": -9000},
            "radius": 1800,
        },
        {
            "id": 4,
            "type": "polyline",
            "template_instance": 2,
            "template_type": "basketball",
            "vertices": [
                {"x": -14000, "y": 1500},
                {"x": 14000, "y": 1500},
                {"x": 14000, "y": 16500},
                {"x": -14000, "y": 16500},
                {"x": -14000, "y": 1500},
            ],
            "closed": True,
        },
        {
            "id": 5,
            "type": "line",
            "template_instance": 2,
            "template_type": "basketball",
            "start": {"x": 0, "y": 1500},
            "end": {"x": 0, "y": 16500},
        },
        {
            "id": 6,
            "type": "circle",
            "template_instance": 2,
            "template_type": "basketball",
            "center": {"x": 0, "y": 9000},
            "radius": 1800,
        },
    ]


def test_catalog_names_instances_and_center_circles():
    catalog = build_geometry_catalog(basketball_geometries())

    assert catalog["catalog_version"] == "geometry.catalog.v1"
    assert catalog["instance_count"] == 2
    assert [item["geometry_ids"] for item in catalog["instances"]] == [[1, 2, 3], [4, 5, 6]]
    assert [item["semantic"] for item in catalog["instances"]] == ["下方篮球场", "上方篮球场"]

    elements = {item["geometry_id"]: item for item in catalog["elements"]}
    assert elements[1]["semantic"] == "外框"
    assert elements[2]["semantic"] == "中线"
    assert elements[3]["semantic"] == "中心圆"
    assert elements[3]["radius_m"] == 1.8
    assert elements[6]["instance_id"] == 2


def test_catalog_preserves_explicit_semantic_and_does_not_guess_unknown_shape():
    catalog = build_geometry_catalog([
        {
            "id": 10,
            "type": "circle",
            "feature_name": "设备定位圆",
            "center": {"x": 0, "y": 0},
            "radius": 500,
        },
        {
            "id": 11,
            "type": "spline",
            "control_points": [{"x": 0, "y": 0}, {"x": 1, "y": 1}],
        },
    ])

    elements = {item["geometry_id"]: item for item in catalog["elements"]}
    assert elements[10]["semantic"] == "设备定位圆"
    assert elements[10]["semantic_source"] == "explicit"
    assert elements[11]["semantic"] == "样条曲线"
    assert elements[11]["semantic_source"] == "geometry_rule"


def test_advanced_project_context_includes_active_variant_catalog():
    project = {
        "id": "project-1",
        "name": "双篮球场",
        "status": "designing",
        "missing_parameters": [],
        "variants": [{
            "id": "variant-1",
            "name": "当前方案",
            "geometries": basketball_geometries(),
        }],
        "design_base_variant_id": "variant-1",
    }

    with patch("app.agent_service.get_creative_project_store.get", return_value=project):
        context = robot_agent._advanced_project_context("project-1")

    assert "geometry.catalog.v1" in context
    assert "下方篮球场" in context
    assert '"geometry_id":3' in context
    assert '"semantic":"中心圆"' in context
