from app.cad_project_candidates import (
    assess_reusable_variant,
    candidate_generation_context,
    candidate_requirement_readiness,
    candidate_response_payload,
    candidate_variant_metadata,
    design_geometries_for_project,
    effective_parent_variant,
    project_logical_graph,
    scale_factor_from_message,
    scale_geometries,
    template_instance_assessment,
    validate_candidate_geometries,
)


def test_candidate_response_payload_restores_current_project_contract() -> None:
    variant = {"id": "variant-1"}
    project = {"id": "project-1", "variants": [variant]}
    payload = candidate_response_payload(
        project,
        variant,
        [[[0.0, 0.0], [1.0, 0.0]]],
        {"geometries": []},
        restored=True,
    )

    assert payload["project_id"] == "project-1"
    assert payload["variants"] == [variant]
    assert payload["tool_result"]["message"] == "已恢复现有候选方案"
    assert "layout_validation" not in payload["tool_result"]
    assert payload["next_action"] == "select_design_variant"


def test_semicircular_arch_builds_closed_outline_at_requested_size() -> None:
    geometries, missing = design_geometries_for_project(
        {
            "name": "半圆拱门 宽2米高3米",
            "original_prompt": "半圆拱门 宽2米高3米",
            "requirements": {
                "shape": "closed_semicircular_arch",
                "dimensions": {"width_m": 2.0, "height_m": 3.0},
            },
            "variants": [],
        },
        {},
    )

    assert missing == []
    assert geometries is not None
    assert [item["type"] for item in geometries] == ["line", "arc", "line", "line"]
    assert geometries[1]["center"] == {"x": 0.0, "y": 2000.0, "z": 0.0}
    assert geometries[1]["radius"] == 1000.0
    assert geometries[1]["start_angle"] == 0.0
    assert geometries[1]["end_angle"] == 180.0


def test_candidate_response_payload_keeps_generated_layout_contract() -> None:
    variant = {"id": "variant-2"}
    payload = candidate_response_payload(
        {"id": "project-1", "variants": [variant]},
        variant,
        [],
        {"geometries": []},
        restored=False,
    )

    assert payload["tool_result"]["message"] == "候选方案已生成"
    assert payload["tool_result"]["layout_validation"] is None
    assert "本次没有启动小车" in payload["response_text"]


ACCEPTED = {
    "status": "passed",
    "review_required": False,
    "authority": "backend_measured_geometry",
    "source": "test_geometry_acceptance",
}


def test_readiness_uses_only_persisted_contract() -> None:
    readiness = candidate_requirement_readiness(
        {"requirements": {"shape": "basketball", "printer": "center"},
         "missing_parameters": []},
        {"prompt": "生成一个标准篮球场"},
    )

    assert readiness["ready"] is True
    assert readiness["missing"] == []
    assert readiness["apply_default_printer"] is False
    assert readiness["default_requirements"] == {}
    assert readiness["source"] == "persisted_project_requirement_contract"


def test_custom_geometry_readiness_keeps_shape_and_dimensions_required() -> None:
    readiness = candidate_requirement_readiness(
        {"missing_parameters": ["shape", "dimensions", "printer"]},
        {"prompt": "生成一个自定义施工图"},
    )

    assert readiness["ready"] is False
    assert readiness["missing"] == ["shape", "dimensions", "printer"]
    assert readiness["apply_default_printer"] is False


def test_candidate_metadata_builds_quantity_repair_title_and_dimensions() -> None:
    metadata = candidate_variant_metadata(
        {
            "expected_template": {"template": "parking", "label": "停车位"},
            "expected_template_name": "parking",
            "expected_quantity": 3,
            "requirements": {"dimensions": {"width_m": 2.5, "height_m": 5.0}},
            "template_set": [{"template": "parking", "quantity": 3}],
        },
        quantity_mismatch=True,
    )

    assert metadata["title"] == "3 个车位修正方案"
    assert "未满足 3 个车位" in metadata["description"]
    assert metadata["graph_match"]["quantity"] == 3
    assert metadata["graph_match"]["width_m"] == 2.5


def test_candidate_metadata_names_composite_scene() -> None:
    metadata = candidate_variant_metadata(
        {
            "expected_template": {"template": "basketball", "label": "篮球场"},
            "expected_template_name": "basketball",
            "expected_quantity": 2,
            "requirements": {},
            "template_set": [
                {"template": "basketball", "quantity": 1},
                {"template": "badminton", "quantity": 1},
            ],
        },
        quantity_mismatch=True,
    )

    assert metadata["title"] == "篮球场 + 羽毛球场组合方案"
    assert metadata["composite"] is True
    assert "全部复合场地" in metadata["description"]


def test_reusable_variant_requires_matching_authoritative_instance_count() -> None:
    geometries = [
        {"id": 1, "type": "line", "template_instance": 1},
        {"id": 2, "type": "line", "template_instance": 2},
    ]
    reusable = assess_reusable_variant(
        {"id": "variant-1", "geometries": geometries,
         "acceptance_summary": ACCEPTED},
        expected_geometries=geometries,
        expected_template_name="basketball",
        expected_quantity=2,
    )
    mismatch = assess_reusable_variant(
        {"id": "variant-1", "geometries": geometries,
         "acceptance_summary": ACCEPTED},
        expected_geometries=geometries,
        expected_template_name="basketball",
        expected_quantity=1,
    )

    assert reusable["reusable"] is True
    assert reusable["reason"] == "instance_count_match"
    assert mismatch["reusable"] is False
    assert mismatch["reason"] == "instance_count_mismatch"


def test_reusable_variant_rejects_geometry_drift_before_restore() -> None:
    result = assess_reusable_variant(
        {"id": "variant-1", "geometries": [{"id": 1, "type": "line"}],
         "acceptance_summary": ACCEPTED},
        expected_geometries=[{"id": 2, "type": "line"}],
        expected_template_name="basketball",
        expected_quantity=1,
    )

    assert result == {"reusable": False, "reason": "geometry_mismatch"}


def test_first_imported_candidate_preserves_source_geometry() -> None:
    source_geometries = [
        {
            "id": 17,
            "type": "line",
            "start": {"x": 0.0, "y": 0.0, "z": 0.0},
            "end": {"x": 1000.0, "y": 0.0, "z": 0.0},
        }
    ]
    geometries, missing = design_geometries_for_project(
        {
            "name": "standard_basketball_court CAD 修改",
            "source_drawing": {"source_format": "dwg", "geometries": source_geometries},
            "variants": [],
        },
        {},
    )

    assert missing == []
    assert geometries == source_geometries
    assert geometries is not source_geometries


def test_imported_project_gets_stable_logical_root_when_semantics_are_missing() -> None:
    geometries = [
        {
            "id": 1,
            "type": "line",
            "layer_id": 1,
            "start": {"x": 0.0, "y": 0.0, "z": 0.0},
            "end": {"x": 1000.0, "y": 0.0, "z": 0.0},
        }
    ]
    graph = project_logical_graph(
        {"source_drawing": {"source_format": "dwg"}},
        {},
        geometries,
    )

    assert graph["logical_objects"]
    assert graph["logical_objects"][0]["geometry_refs"] == [1]


def test_candidate_context_resolves_composite_layout_expectations() -> None:
    context = candidate_generation_context(
        {
            "name": "篮球场与羽毛球场",
            "original_prompt": "一个标准篮球场和一个标准羽毛球场长边并排，间距2米",
            "requirements": {
                "arrangement": "long_side_adjacent",
                "spacing_m": 2.0,
            },
        },
        {},
    )

    assert len(context["template_set"]) == 2
    assert context["requirements"]["arrangement"] == "long_side_adjacent"
    assert context["requirements"]["spacing_m"] == 2.0
    assert context["layout_conflicts"] == []


def test_candidate_validation_rejects_missing_composite_instance() -> None:
    result = validate_candidate_geometries(
        [
            {
                "id": 1,
                "type": "line",
                "layer_id": 1,
                "start": {"x": 0.0, "y": 0.0, "z": 0.0},
                "end": {"x": 1000.0, "y": 0.0, "z": 0.0},
                "template_type": "basketball",
                "template_instance": 1,
            }
        ],
        {
            "requirements": {"printer": "center"},
            "template_set": [
                {"template": "basketball", "quantity": 1},
                {"template": "badminton", "quantity": 1},
            ],
        },
    )

    assert result["ok"] is False
    assert "实际生成" in result["message"]


def test_scale_factor_handles_chinese_multiplier_and_percent() -> None:
    assert scale_factor_from_message("整个图纸扩大一倍") == 2.0
    assert scale_factor_from_message("整体缩小到50%") == 0.5
    assert scale_factor_from_message("移动2米") is None


def test_effective_parent_prefers_explicit_preview() -> None:
    project = {
        "selected_variant_id": "selected",
        "variants": [
            {"id": "selected", "acceptance_summary": ACCEPTED},
            {"id": "preview", "acceptance_summary": ACCEPTED},
        ],
    }
    assert effective_parent_variant(
        project, preferred_variant_id="preview"
    ) == {"id": "preview", "acceptance_summary": ACCEPTED}


def test_scale_geometries_preserves_ids_and_scales_about_group_center() -> None:
    source = [
        {
            "id": 1,
            "type": "line",
            "start": {"x": 0.0, "y": 0.0},
            "end": {"x": 1000.0, "y": 0.0},
        }
    ]
    scaled = scale_geometries(source, 2.0)
    assert scaled[0]["id"] == 1
    assert scaled[0]["start"]["x"] == -500.0
    assert scaled[0]["end"]["x"] == 1500.0
    assert source[0]["start"]["x"] == 0.0


def test_imported_cad_requires_confirmed_grouping_for_authoritative_count() -> None:
    result = template_instance_assessment(
        [{"id": 1, "type": "line"}],
        "basketball",
        source_drawing={"source_format": "dwg", "cad_analysis": {}},
    )
    assert result["count"] is None
    assert result["status"] == "confirmation_required"
    assert result["authoritative"] is False


def test_stable_instance_ids_are_authoritative() -> None:
    result = template_instance_assessment(
        [
            {"id": 1, "template_instance": 1},
            {"id": 2, "template_instance": 2},
        ],
        "basketball",
    )
    assert result["count"] == 2
    assert result["source"] == "stable_instance_ids"
    assert result["authoritative"] is True
