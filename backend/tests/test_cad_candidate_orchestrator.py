from app.cad_candidate_orchestrator import (
    persist_candidate_variant,
    candidate_preflight,
    design_confirmation_gate,
    persist_prepared_candidate,
    prepare_new_candidate,
    restore_existing_candidate,
)


ACCEPTED = {
    "status": "passed",
    "review_required": False,
    "authority": "backend_measured_geometry",
    "source": "test_geometry_acceptance",
}


def test_candidate_writer_returns_preview_records_with_geometry_identity():
    geometry={"id":7,"type":"line","start":{"x":0,"y":0},"end":{"x":1000,"y":0}}
    result=persist_candidate_variant(project_id="p",name="候选",geometries=[geometry],rationale="",assessment={},
        acceptance_summary=ACCEPTED,
        add_variant=lambda *a,**kw:{"id":"v"},get_project=lambda _: {"id":"p"})
    assert result["preview_paths"][0]["geometry_id"]==7
    assert result["preview_paths"][0]["points"]==[[0,0],[1,0]]


def test_short_confirmation_is_owned_for_ready_project() -> None:
    result = design_confirmation_gate(
        "确认",
        {
            "id": "project-1",
            "status": "ready_for_design",
            "missing_parameters": [],
            "variants": [],
        },
        explicit_confirmation=False,
    )

    assert result["should_handle"] is True
    assert result["contextual_confirmation"] is True


def test_short_confirmation_does_not_override_incomplete_project() -> None:
    result = design_confirmation_gate(
        "确认",
        {
            "id": "project-1",
            "status": "clarifying",
            "missing_parameters": ["dimensions"],
            "variants": [],
        },
        explicit_confirmation=False,
    )

    assert result["should_handle"] is False


def test_explicit_confirmation_without_project_returns_actionable_error() -> None:
    result = design_confirmation_gate(
        "确认生成候选方案",
        None,
        explicit_confirmation=True,
    )

    assert result["should_handle"] is True
    assert "选择" in result["error"]


def test_candidate_preflight_formats_layout_conflict() -> None:
    result = candidate_preflight(
        {"missing_parameters": []},
        {"layout_conflicts": ["同时要求上下排列和左右排列"]},
    )

    assert result["ok"] is False
    assert "排列要求存在冲突" in result["message"]


def test_candidate_preflight_never_infers_default_from_prompt() -> None:
    result = candidate_preflight(
        {"missing_parameters": ["printer"]},
        {"layout_conflicts": [], "prompt": "生成一个标准篮球场"},
    )

    assert result["ok"] is False
    assert result["readiness"]["missing"] == ["printer"]
    assert result["readiness"]["apply_default_printer"] is False


def test_layout_only_preflight_does_not_block_existing_candidate_restore() -> None:
    result = candidate_preflight(
        {"missing_parameters": ["dimensions"]},
        {"layout_conflicts": [], "prompt": "自定义图形"},
        check_requirements=False,
    )

    assert result == {"ok": True}


def test_restore_existing_candidate_prefers_latest_exact_match() -> None:
    old = {
        "id": "old",
        "acceptance_summary": ACCEPTED,
        "geometries": [{"id": 1, "type": "line", "template_instance": 1}],
    }
    latest = {
        "id": "latest",
        "acceptance_summary": ACCEPTED,
        "geometries": [{"id": 1, "type": "line", "template_instance": 1}],
    }
    migrations = []
    result = restore_existing_candidate(
        {"id": "project-1", "status": "designing"},
        [old, latest],
        {"expected_template_name": "basketball", "expected_quantity": 1},
        latest["geometries"],
        migrate_variant=lambda *args: migrations.append(args),
    )

    assert result["variant"] is latest
    assert result["quantity_mismatch"] is False
    assert migrations == []


def test_restore_existing_candidate_marks_eligible_mismatch() -> None:
    geometries = [{"id": 1, "type": "line", "template_instance": 1}]
    result = restore_existing_candidate(
        {"id": "project-1", "status": "ready_for_planning"},
        [{"id": "variant-1", "geometries": geometries,
          "acceptance_summary": ACCEPTED}],
        {"expected_template_name": "basketball", "expected_quantity": 2},
        geometries,
        migrate_variant=lambda *_: None,
    )

    assert result == {"variant": None, "quantity_mismatch": True}


def test_restore_existing_candidate_ignores_non_design_state() -> None:
    result = restore_existing_candidate(
        {"id": "project-1", "status": "clarifying"},
        [{"id": "variant-1", "geometries": [{"id": 1}]}],
        {"expected_template_name": "basketball", "expected_quantity": 1},
        None,
        migrate_variant=lambda *_: None,
    )

    assert result == {"variant": None, "quantity_mismatch": False}


def test_prepare_new_candidate_builds_complete_persistence_payload() -> None:
    project = {
        "id": "project-1",
        "name": "标准篮球场",
        "original_prompt": "生成一个标准篮球场",
        "requirements": {"printer": "center"},
        "missing_parameters": [],
        "variants": [],
    }
    context = {
        "prompt": "生成一个标准篮球场",
        "expected_template": {
            "template": "basketball",
            "label": "篮球场",
            "quantity": 1,
        },
        "expected_template_name": "basketball",
        "expected_quantity": 1,
        "template_set": [{"template": "basketball", "quantity": 1}],
        "requirements": {"printer": "center"},
        "layout_conflicts": [],
    }
    updates = []

    def update_project(project_id, **changes):
        updates.append((project_id, changes))
        return {
            **project,
            "requirements": {"printer": "center"},
            "missing_parameters": [],
        }

    result = prepare_new_candidate(
        project,
        {},
        context,
        quantity_mismatch=False,
        update_project=update_project,
    )

    assert result["ok"] is True
    assert result["geometries"]
    assert result["logical_objects"]
    assert result["title"] == "标准候选方案"
    assert updates == []


def test_prepare_new_candidate_returns_missing_geometry_reason() -> None:
    project = {
        "id": "project-1",
        "name": "自定义图形",
        "original_prompt": "生成自定义图形",
        "requirements": {},
        "missing_parameters": [],
        "variants": [],
    }
    context = {
        "prompt": "生成自定义图形",
        "expected_template": None,
        "expected_template_name": "",
        "expected_quantity": 1,
        "template_set": [],
        "requirements": {},
        "layout_conflicts": [],
    }
    result = prepare_new_candidate(
        project,
        {},
        context,
        quantity_mismatch=False,
        update_project=lambda *_args, **_kwargs: None,
    )

    assert result["ok"] is False
    assert "图形类型和关键尺寸" in result["message"]


def test_persist_prepared_candidate_builds_generated_response() -> None:
    prepared = {
        "project": {"id": "project-1", "variants": []},
        "geometries": [{"id": 1, "type": "line"}],
        "title": "标准候选方案",
        "description": "测试候选",
        "assessment": {"score": 1},
        "instance_contract": None,
        "logical_objects": [{"id": "object-1", "geometry_ids": [1]}],
        "topology": {"relations": []},
        "layout_validation": {"ok": True},
        "acceptance_summary": ACCEPTED,
    }
    stored_variant = {
        "id": "variant-1",
        "logical_objects": prepared["logical_objects"],
        "topology": prepared["topology"],
        "acceptance_summary": ACCEPTED,
    }
    calls = []

    result = persist_prepared_candidate(
        prepared,
        add_variant=lambda *args, **kwargs: calls.append((args, kwargs))
        or stored_variant,
        get_project=lambda _project_id: {
            "id": "project-1",
            "variants": [stored_variant],
        },
        geometry_preview=lambda _payload: [[[0.0, 0.0], [1.0, 1.0]]],
        drawing_payload=lambda payload: {"drawing": payload},
    )

    assert result["ok"] is True
    assert result["response"]["project_id"] == "project-1"
    assert result["response"]["tool_result"]["variant_id"] == "variant-1"
    assert result["response"]["layout_validation"] == {"ok": True}
    assert calls[0][1]["logical_objects"] == prepared["logical_objects"]


def test_persist_prepared_candidate_reports_stale_project() -> None:
    result = persist_prepared_candidate(
        {
            "project": {"id": "project-1"},
            "geometries": [{"id": 1, "type": "line"}],
            "title": "标准候选方案",
            "description": "测试候选",
            "assessment": {},
            "instance_contract": None,
            "logical_objects": [],
            "topology": {},
            "acceptance_summary": ACCEPTED,
        },
        add_variant=lambda *_args, **_kwargs: None,
        get_project=lambda _project_id: None,
        geometry_preview=lambda _payload: [],
        drawing_payload=lambda payload: payload,
    )

    assert result["ok"] is False
    assert "项目状态可能已发生变化" in result["message"]
