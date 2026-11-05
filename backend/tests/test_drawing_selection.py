from __future__ import annotations

import json
from copy import deepcopy
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.agent_service import robot_agent
from app.incremental_cad import edit_candidate_geometries, parse_incremental_edit
from app.schemas import AgentChatRequest


def test_whole_assembly_selection_does_not_require_template_instance():
    source=_source()
    parent={"geometries":source["lines"],"logical_objects":[
        {"object_id":"a","geometry_refs":[1],"assembly_id":"first","assembly_label":"甲"},
        {"object_id":"b","geometry_refs":[2],"assembly_id":"second","assembly_label":"乙"}]}
    edit={"operation":"translate","dx_mm":1000,"dy_mm":0}
    error=robot_agent._bind_incremental_selection(edit,{'drawing_selection':{'scope':'group','geometry_ids':[1]}},parent)
    assert error is None
    assert edit['geometry_ids']==[1]
    assert edit['logical_object_id']=='a'
    assert 'instance' not in edit


def test_logical_object_identity_survives_http_schema_and_legacy_wire_format():
    from app.schemas import AgentDrawingSelection
    parent={'geometries':_source()['lines'],'logical_objects':[
        {'object_id':'part1','geometry_refs':[1],'assembly_id':'whole'},
        {'object_id':'part2','geometry_refs':[2],'assembly_id':'whole'}]}
    for scope in ['logical_object','group']:
        payload=AgentDrawingSelection(scope=scope,object_id='part1',geometry_ids=[1],project_id='p',variant_id='v').model_dump(exclude_none=True)
        edit={'operation':'retain'}
        assert robot_agent._bind_incremental_selection(edit,{'drawing_selection':payload},parent) is None
        assert edit['geometry_ids']==[1] and edit['logical_object_id']=='part1'
    anonymous={'scope':'group','geometry_ids':[1],'project_id':'p','variant_id':'v'}
    assert robot_agent._bind_incremental_selection({'operation':'retain'},{'drawing_selection':anonymous},parent) is not None
    wrong={**anonymous,'scope':'logical_object','object_id':'part2'}
    assert robot_agent._bind_incremental_selection({'operation':'retain'},{'drawing_selection':wrong},parent) is not None


def test_logical_object_scope_requires_identity_and_complete_candidate_context():
    from app.schemas import AgentDrawingSelection
    with pytest.raises(ValidationError):
        AgentDrawingSelection(scope='logical_object',geometry_ids=[1],project_id='p',variant_id='v')
    with pytest.raises(ValidationError):
        AgentDrawingSelection(scope='logical_object',object_id='part',object_ids=['part'],geometry_ids=[1],project_id='p',variant_id='v')


def test_legacy_whole_group_is_not_shrunk_to_one_member_id():
    parent={'geometries':_source()['lines'],'logical_objects':[
        {'object_id':'part1','geometry_refs':[1],'assembly_id':'whole'},
        {'object_id':'part2','geometry_refs':[2],'assembly_id':'whole'}]}
    edit={'operation':'translate','dx_mm':1000,'dy_mm':0}
    selection={'scope':'group','object_id':'part1','geometry_ids':[1,2],'project_id':'p','variant_id':'v'}
    assert robot_agent._bind_incremental_selection(edit,{'drawing_selection':selection},parent) is None
    assert edit['geometry_ids']==[1,2]


def _source() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "unit": "mm",
        "lines": [
            {
                "id": 1,
                "type": "line",
                "layer_id": 1,
                "start": {"x": 0, "y": 0, "z": 0},
                "end": {"x": 1000, "y": 0, "z": 0},
            },
            {
                "id": 2,
                "type": "line",
                "layer_id": 1,
                "start": {"x": 0, "y": 1000, "z": 0},
                "end": {"x": 1000, "y": 1000, "z": 0},
            },
        ],
    }


def _update(entity_id: int) -> dict[str, object]:
    y = 0 if entity_id == 1 else 1000
    return {
        "op": "update",
        "id": entity_id,
        "geometry": {
            "type": "line",
            "layer_id": 1,
            "start": {"x": 0, "y": y, "z": 0},
            "end": {"x": 2000, "y": y, "z": 0},
        },
    }


def test_chat_request_validates_editor_selection_contract() -> None:
    request = AgentChatRequest.model_validate({
        "message": "把这条线加长",
        "mode": "advanced",
        "drawing_selection": {
            "source_file_name": "court.json",
            "scope": "entity",
            "geometry_ids": [1],
        },
    })
    assert request.drawing_selection is not None
    assert request.drawing_selection.geometry_ids == [1]

    candidate_request = AgentChatRequest.model_validate({
        "message": "移动选中的图形",
        "mode": "advanced",
        "project_id": "project-1",
        "variant_id": "variant-2",
        "drawing_selection": {
            "project_id": "project-1",
            "variant_id": "variant-2",
            "scope": "group",
            "geometry_ids": [3, 4],
            "instance_id": 2,
        },
    })
    assert candidate_request.drawing_selection is not None
    assert candidate_request.drawing_selection.source_file_name is None
    assert candidate_request.drawing_selection.instance_id == 2

    with pytest.raises(ValidationError):
        AgentChatRequest.model_validate({
            "message": "修改选中线段",
            "drawing_selection": {
                "source_file_name": "court.json",
                "scope": "entity",
                "geometry_ids": [1, 2],
            },
        })


def test_route_selection_overrides_model_target() -> None:
    bound = robot_agent._bind_drawing_selection(
        "modify_drawing",
        {"source_file_name": "guessed.json", "operations": [_update(1)]},
        {"drawing_selection": {
            "source_file_name": "court.json",
            "scope": "group",
            "geometry_ids": [1, 2],
        }},
    )
    assert bound["source_file_name"] == "court.json"
    assert bound["target"] == {
        "scope": "geometry",
        "geometry_ids": [1, 2],
        "instance_ids": [],
    }


def test_editor_selection_uses_direct_drawing_modification_context() -> None:
    context = robot_agent._system_context(
        "把选中的线段加长",
        mode="advanced",
        route={
            "name": "drawing_design",
            "operation": "modify",
            "tool_family": "cad",
            "drawing_selection": {
                "source_file_name": "court.json",
                "scope": "entity",
                "geometry_ids": [1],
            },
        },
    )
    assert "调用 modify_drawing" in context
    assert "必须调用 add_design_variant" not in context


def test_selected_geometry_can_be_modified_but_outside_target_is_blocked() -> None:
    with tempfile.TemporaryDirectory() as directory, patch.dict(
        "os.environ", {"XLINE_CAD_DIR": directory}
    ):
        source_name = "selection_source.json"
        Path(directory, source_name).write_text(
            json.dumps(_source()), encoding="utf-8"
        )
        allowed = robot_agent._prepare_drawing_modification({
            "source_file_name": source_name,
            "operations": [_update(1)],
            "selection_scope": "entity",
            "selected_geometry_ids": [1],
        })
        blocked = robot_agent._prepare_drawing_modification({
            "source_file_name": source_name,
            "operations": [_update(2)],
            "selection_scope": "entity",
            "selected_geometry_ids": [1],
        })

    assert allowed["ok"] is True
    assert blocked["ok"] is False
    assert "不在当前选择" in str(blocked["message"])


def test_typed_patch_updates_only_the_declared_geometry_target() -> None:
    with tempfile.TemporaryDirectory() as directory, patch.dict(
        "os.environ", {"XLINE_CAD_DIR": directory}
    ):
        source_name = "typed_patch_source.json"
        source = _source()
        Path(directory, source_name).write_text(json.dumps(source), encoding="utf-8")
        result = robot_agent._prepare_drawing_modification({
            "source_file_name": source_name,
            "target": {
                "scope": "geometry",
                "geometry_ids": [1],
                "instance_ids": [],
            },
            "operations": [{
                "op": "update",
                "geometry_id": 1,
                "patch": {"end": {"x": 2500, "y": 0, "z": 0}},
            }],
        })

    assert result["ok"] is True
    assert result["scope_validation"]["ok"] is True
    assert result["scope_validation"]["actual"]["modified_ids"] == [1]
    integrity = result["scope_validation"]["non_target_integrity"]
    assert integrity["verified"] is True
    assert integrity["protected_geometry_ids"] == [2]
    assert result["geometry_diff"]["counts"] == {
        "added": 0, "removed": 0, "modified": 1, "unchanged": 1,
    }
    geometries = {item["id"]: item for item in result["geometries"]}
    assert geometries[1]["end"]["x"] == 2500
    assert geometries[2] == source["lines"][1]


def test_noop_typed_patch_is_rejected_without_persisting_a_version() -> None:
    with tempfile.TemporaryDirectory() as directory, patch.dict(
        "os.environ", {"XLINE_CAD_DIR": directory}
    ):
        source_name = "noop_patch_source.json"
        source_path = Path(directory, source_name)
        source = _source()
        original_text = json.dumps(source)
        source_path.write_text(original_text, encoding="utf-8")

        result = robot_agent._prepare_drawing_modification({
            "source_file_name": source_name,
            "target": {
                "scope": "geometry",
                "geometry_ids": [1],
                "instance_ids": [],
            },
            "operations": [{
                "op": "update",
                "geometry_id": 1,
                "patch": {"end": {"x": 1000, "y": 0, "z": 0}},
            }],
        })

        assert result["ok"] is False
        rollback = result["rollback_evidence"]
        assert rollback["verified"] is True
        assert rollback["candidate_discarded"] is True
        assert rollback["persisted"] is False
        assert rollback["source_before_sha256"] == rollback["source_after_sha256"]
        assert source_path.read_text(encoding="utf-8") == original_text
        assert list(Path(directory).glob("*_v*.json")) == []


def test_typed_patch_cannot_escape_declared_target() -> None:
    with tempfile.TemporaryDirectory() as directory, patch.dict(
        "os.environ", {"XLINE_CAD_DIR": directory}
    ):
        source_name = "typed_patch_scope.json"
        Path(directory, source_name).write_text(json.dumps(_source()), encoding="utf-8")
        result = robot_agent._prepare_drawing_modification({
            "source_file_name": source_name,
            "target": {
                "scope": "geometry",
                "geometry_ids": [1],
                "instance_ids": [],
            },
            "operations": [{
                "op": "update",
                "geometry_id": 2,
                "patch": {"end": {"x": 2500, "y": 1000, "z": 0}},
            }],
        })

    assert result["ok"] is False
    assert "不在当前选择" in result["message"]


def test_group_selection_allows_every_bound_geometry() -> None:
    with tempfile.TemporaryDirectory() as directory, patch.dict(
        "os.environ", {"XLINE_CAD_DIR": directory}
    ):
        source_name = "group_source.json"
        Path(directory, source_name).write_text(
            json.dumps(_source()), encoding="utf-8"
        )
        result = robot_agent._prepare_drawing_modification({
            "source_file_name": source_name,
            "operations": [_update(1), _update(2)],
            "selection_scope": "group",
            "selected_geometry_ids": [1, 2],
        })

    assert result["ok"] is True
    assert result["geometry_diff"]["counts"]["modified"] == 2


def _candidate_geometries() -> list[dict[str, object]]:
    return [
        {
            "id": 1, "type": "line", "template_instance": 1,
            "start": {"x": 0, "y": 0}, "end": {"x": 1000, "y": 0},
        },
        {
            "id": 2, "type": "line", "template_instance": 1,
            "start": {"x": 1000, "y": 0}, "end": {"x": 1000, "y": 1000},
        },
        {
            "id": 3, "type": "line", "template_instance": 2,
            "start": {"x": 3000, "y": 0}, "end": {"x": 4000, "y": 0},
        },
        {
            "id": 4, "type": "line", "template_instance": 2,
            "start": {"x": 4000, "y": 0}, "end": {"x": 4000, "y": 1000},
        },
    ]


@pytest.mark.parametrize(
    ("message", "operation"),
    [
        ("向右移动1米", "translate"),
        ("逆时针旋转90度", "rotate"),
        ("缩放到1.5倍", "scale"),
        ("宽度改为2米", "resize"),
        ("删除选中的图形", "delete"),
        ("只保留选中的图形", "retain"),
    ],
)
def test_entity_selection_drives_supported_incremental_edits(
    message: str, operation: str
) -> None:
    source = _candidate_geometries()
    edit = parse_incremental_edit(message + " 图形")
    assert edit is not None
    error = robot_agent._bind_incremental_selection(
        edit,
        {"drawing_selection": {
            "source_file_name": "candidate.json",
            "scope": "entity",
            "geometry_ids": [3],
        }},
        {"geometries": source},
    )
    assert error is None
    assert edit["geometry_ids"] == [3]
    assert edit["operation"] == operation

    changed, edit_error = edit_candidate_geometries(source, edit)

    assert edit_error is None
    assert changed is not None
    if operation not in {"delete", "retain"}:
        unchanged = next(item for item in changed if item["id"] == 4)
        assert unchanged == source[3]


def test_entity_selection_without_instance_group_supports_local_edit() -> None:
    source = _candidate_geometries()
    source[2].pop("template_instance")
    edit = parse_incremental_edit("向右移动1米 图形")
    assert edit is not None

    error = robot_agent._bind_incremental_selection(
        edit,
        {"drawing_selection": {
            "source_file_name": "candidate.json",
            "scope": "entity",
            "geometry_ids": [3],
        }},
        {"geometries": source},
    )

    assert error is None
    assert edit["geometry_ids"] == [3]
    changed, edit_error = edit_candidate_geometries(source, edit)
    assert edit_error is None
    assert changed is not None
    assert changed[2]["start"]["x"] == 4000


def test_entity_selection_without_instance_group_rejects_group_operation() -> None:
    source = _candidate_geometries()
    source[2].pop("template_instance")
    edit = parse_incremental_edit("把图形左右镜像")
    assert edit is not None

    error = robot_agent._bind_incremental_selection(
        edit,
        {"drawing_selection": {
            "source_file_name": "candidate.json",
            "scope": "entity",
            "geometry_ids": [3],
        }},
        {"geometries": source},
    )

    assert error is not None
    assert "完整图形" in error


def test_group_selection_overrides_conflicting_spoken_instance() -> None:
    source = _candidate_geometries()
    edit = parse_incremental_edit("第1个图形向右移动1米")
    assert edit is not None and edit["instance"] == 1

    error = robot_agent._bind_incremental_selection(
        edit,
        {"drawing_selection": {
            "source_file_name": "candidate.json",
            "scope": "group",
            "geometry_ids": [3, 4],
        }},
        {"geometries": source},
    )
    changed, edit_error = edit_candidate_geometries(source, edit)

    assert error is None
    assert edit["instance"] == 2
    assert edit_error is None
    assert changed is not None
    assert changed[0] == source[0]
    assert changed[1] == source[1]
    assert changed[2]["start"]["x"] == 4000


def test_complete_ungrouped_imported_cad_selection_supports_geometry_scale() -> None:
    source = _candidate_geometries()
    for item in source:
        item.pop("template_instance", None)
    edit = parse_incremental_edit("把当前图形扩大一倍")
    assert edit is not None and edit["operation"] == "scale"

    error = robot_agent._bind_incremental_selection(
        edit,
        {
            "drawing_selection": {
                "source_file_name": "imported-court.json",
                "scope": "group",
                "geometry_ids": [item["id"] for item in source],
            }
        },
        {"geometries": source},
    )

    assert error is None
    assert edit["geometry_ids"] == [1, 2, 3, 4]
    changed, edit_error = edit_candidate_geometries(source, edit)
    assert edit_error is None
    assert changed is not None
    assert changed != source


def test_ungrouped_imported_cad_still_requires_groups_for_instance_operations() -> None:
    source = _candidate_geometries()
    for item in source:
        item.pop("template_instance", None)
    edit = parse_incremental_edit("把当前图形阵列成2行2列，行间距2米，列间距2米")
    assert edit is not None and edit["operation"] == "array"

    error = robot_agent._bind_incremental_selection(
        edit,
        {
            "drawing_selection": {
                "source_file_name": "imported-court.json",
                "scope": "group",
                "geometry_ids": [item["id"] for item in source],
            }
        },
        {"geometries": source},
    )

    assert error is not None
    assert "稳定实例编号" in error


@pytest.mark.parametrize(
    ("message", "operation"),
    [
        ("把图形左右镜像", "mirror"),
        ("把图形向外偏移500毫米", "offset"),
        ("把图形阵列成2行3列，行间距2米，列间距3米", "array"),
    ],
)
def test_group_selection_preserves_structured_operation(
    message: str, operation: str
) -> None:
    source = _candidate_geometries()
    edit = parse_incremental_edit(message)
    assert edit is not None and edit["operation"] == operation
    original_parameters = {
        key: value for key, value in edit.items()
        if key not in {"instance", "instances", "geometry_ids"}
    }

    error = robot_agent._bind_incremental_selection(
        edit,
        {"drawing_selection": {
            "source_file_name": "candidate.json",
            "scope": "group",
            "geometry_ids": [3, 4],
        }},
        {"geometries": source},
    )

    assert error is None
    assert edit["instance"] == 2
    assert edit["operation"] == operation
    assert {
        key: value for key, value in edit.items()
        if key not in {"instance", "instances", "geometry_ids"}
    } == original_parameters


@pytest.mark.parametrize("message", ["复制到右边2米", "与第1个图形左对齐"])
def test_entity_selection_rejects_operations_that_require_a_whole_group(
    message: str,
) -> None:
    edit = parse_incremental_edit(message + " 图形")
    assert edit is not None

    error = robot_agent._bind_incremental_selection(
        edit,
        {"drawing_selection": {
            "source_file_name": "candidate.json",
            "scope": "entity",
            "geometry_ids": [3],
        }},
        {"geometries": _candidate_geometries()},
    )

    assert error is not None
    assert "整个图形" in error


def test_incomplete_group_selection_is_rejected() -> None:
    edit = parse_incremental_edit("图形向右移动1米")
    assert edit is not None

    error = robot_agent._bind_incremental_selection(
        edit,
        {"drawing_selection": {
            "source_file_name": "candidate.json",
            "scope": "group",
            "geometry_ids": [3],
        }},
        {"geometries": _candidate_geometries()},
    )

    assert error is not None
    assert "选区不完整" in error


def test_canvas_selection_overrides_spoken_attribute_selector() -> None:
    source = _candidate_geometries()
    source[0]["role"] = "reference"
    source[0]["path_semantic"] = "TRAVEL"
    edit = parse_incremental_edit("删除所有参考线")
    assert edit is not None and edit["selector"]["kind"] == "attribute"
    error = robot_agent._bind_incremental_selection(
        edit,
        {"drawing_selection": {
            "source_file_name": "candidate.json", "scope": "entity",
            "geometry_ids": [3],
        }},
        {"geometries": source},
    )
    changed, edit_error = edit_candidate_geometries(source, edit)
    assert error is None and edit_error is None
    assert "selector" not in edit
    assert [item["id"] for item in changed] == [1, 2, 4]


def test_chat_api_applies_canvas_group_selection_to_active_candidate() -> None:
    from app.conversation_memory import ConversationMemoryStore
    from app.creative_projects import CreativeProjectStore
    from app.drawing_store import preview_paths
    from app.agent_skills import score_design_variant
    from app.agent_http_service import agent_chat

    with tempfile.TemporaryDirectory() as directory:
        project_store = CreativeProjectStore(Path(directory) / "projects.json")
        memory_store = ConversationMemoryStore(Path(directory) / "memory.json")
        source = _candidate_geometries()
        project = project_store.create(
            "画布选择测试", "创建两个自定义图形",
            {"shape": "custom", "quantity": 2}, {}, [],
            source_drawing={"file_name": "candidate.json", "geometries": source},
        )
        parent = project_store.add_variant(
            project["id"], "初始方案", source, "测试画布选区",
            score_design_variant(source), preview_paths({"lines": source}),
        
                acceptance_summary={'status': 'passed', 'review_required': False, 'authority': 'test_fixture'},
            )
        assert parent is not None
        project_store.begin_design_iteration(project["id"], parent["id"])
        memory_store.remember("canvas-selection", "", {
            "ok": True,
            "project_id": project["id"],
            "project": project_store.get(project["id"]),
        })

        with (
            patch("app.agent_service.get_creative_project_store", return_value=project_store),
            patch("app.agent_http_service.get_creative_project_store", return_value=project_store),
            patch("app.agent_http_service.conversation_memory", memory_store),
        ):
            result = agent_chat(AgentChatRequest(
                message="第1个图形向右移动1米",
                mode="advanced",
                conversation_id="canvas-selection",
                drawing_selection={
                    "source_file_name": "candidate.json",
                    "scope": "group",
                    "geometry_ids": [3, 4],
                },
            ))

    assert result["ok"] is True
    assert result["variant"]["parent_variant_id"] == parent["id"]
    assert result["cad_edit_command"]["target_instance_id"] == 2
    changed = result["variant"]["geometries"]
    assert changed[0] == source[0]
    assert changed[1] == source[1]
    assert changed[2]["start"]["x"] == 4000
    assert result["preview_paths"]


def test_chat_api_prefers_canvas_candidate_selection_over_text_ambiguity() -> None:
    from app.conversation_memory import ConversationMemoryStore
    from app.creative_projects import CreativeProjectStore
    from app.drawing_store import preview_paths
    from app.agent_skills import score_design_variant
    from app.agent_http_service import agent_chat

    with tempfile.TemporaryDirectory() as directory:
        project_store = CreativeProjectStore(Path(directory) / "projects.json")
        memory_store = ConversationMemoryStore(Path(directory) / "memory.json")
        source = _candidate_geometries()
        project = project_store.create(
            "两个羽毛球场", "创建两个羽毛球场", {"quantity": 2}, {}, []
        )
        parent = project_store.add_variant(
            project["id"], "初始方案", source, "两个实例",
            score_design_variant(source), preview_paths({"lines": source}),
        
                acceptance_summary={'status': 'passed', 'review_required': False, 'authority': 'test_fixture'},
            )
        assert parent is not None
        project_store.begin_design_iteration(project["id"], parent["id"])
        ambiguous_resolution = {
            "message": "向前平移2m",
            "ambiguous": True,
            "question": "需要指定移动哪一个场地。",
            "memory": {"enabled": True, "objects": {}},
            "retrieved": {},
        }

        with (
            patch("app.agent_service.get_creative_project_store", return_value=project_store),
            patch("app.agent_http_service.get_creative_project_store", return_value=project_store),
            patch("app.agent_http_service.conversation_memory", memory_store),
            patch.object(memory_store, "resolve", return_value=ambiguous_resolution),
        ):
            result = agent_chat(AgentChatRequest(
                message="向前平移2m",
                mode="advanced",
                conversation_id="candidate-selection-priority",
                project_id=project["id"],
                variant_id=parent["id"],
                drawing_selection={
                    "project_id": project["id"],
                    "variant_id": parent["id"],
                    "scope": "group",
                    "geometry_ids": [3, 4],
                    "instance_id": 2,
                },
            ))

    assert result["ok"] is True
    assert result.get("clarification_required") is not True
    assert result["cad_edit_command"]["target_instance_id"] == 2
    assert result["variant"]["parent_variant_id"] == parent["id"]


def test_chat_api_uses_current_preview_instead_of_existing_design_base() -> None:
    from app.conversation_memory import ConversationMemoryStore
    from app.creative_projects import CreativeProjectStore
    from app.drawing_store import preview_paths
    from app.agent_skills import score_design_variant
    from app.agent_http_service import agent_chat

    with tempfile.TemporaryDirectory() as directory:
        project_store = CreativeProjectStore(Path(directory) / "projects.json")
        memory_store = ConversationMemoryStore(Path(directory) / "memory.json")
        source = _candidate_geometries()
        project = project_store.create(
            "两个候选方案", "创建两个图形", {"quantity": 2}, {}, []
        )
        first = project_store.add_variant(
            project["id"], "候选一", source, "第一个候选",
            score_design_variant(source), preview_paths({"lines": source}),
        
                acceptance_summary={'status': 'passed', 'review_required': False, 'authority': 'test_fixture'},
            )
        shifted = deepcopy(source)
        for geometry in shifted:
            for key in ("start", "end", "center"):
                point = geometry.get(key)
                if isinstance(point, dict):
                    point["x"] = float(point.get("x", 0)) + 5000.0
        second = project_store.add_variant(
            project["id"], "候选二", shifted, "右侧当前显示的候选",
            score_design_variant(shifted), preview_paths({"lines": shifted}),
        
                acceptance_summary={'status': 'passed', 'review_required': False, 'authority': 'test_fixture'},
            )
        assert first is not None and second is not None
        project_store.begin_design_iteration(project["id"], first["id"])

        with (
            patch("app.agent_service.get_creative_project_store", return_value=project_store),
            patch("app.agent_http_service.get_creative_project_store", return_value=project_store),
            patch("app.agent_http_service.conversation_memory", memory_store),
        ):
            result = agent_chat(AgentChatRequest(
                message="将第2个图形向下移动1米",
                mode="advanced",
                conversation_id="current-preview-edit-base",
                project_id=project["id"],
                variant_id=second["id"],
            ))

    assert result["ok"] is True
    assert result["variant"]["parent_variant_id"] == second["id"]
    assert result["cad_edit_command"]["target_instance_id"] == 2


def test_chat_api_edits_selected_imported_cad_entity_without_template_instance() -> None:
    from app.conversation_memory import ConversationMemoryStore
    from app.creative_projects import CreativeProjectStore
    from app.drawing_store import preview_paths
    from app.agent_skills import score_design_variant
    from app.agent_http_service import agent_chat

    with tempfile.TemporaryDirectory() as directory:
        project_store = CreativeProjectStore(Path(directory) / "projects.json")
        memory_store = ConversationMemoryStore(Path(directory) / "memory.json")
        source = [
            {
                "id": 1,
                "type": "line",
                "layer_id": 1,
                "start": {"x": 0.0, "y": 0.0, "z": 0.0},
                "end": {"x": 10000.0, "y": 0.0, "z": 0.0},
            },
            {
                "id": 6,
                "type": "circle",
                "layer_id": 1,
                "center": {"x": 5000.0, "y": 3000.0, "z": 0.0},
                "radius": 1800.0,
            },
        ]
        project = project_store.create(
            "导入 CAD 修改",
            "基于已导入 CAD 图纸进行局部修改",
            {"shape": "imported_cad"},
            {},
            [],
            source_drawing={
                "file_name": "imported_court.json",
                "geometries": source,
                "source_format": "dwg",
            },
        )
        parent = project_store.add_variant(
            project["id"],
            "导入候选",
            source,
            "保留导入图元",
            score_design_variant(source),
            preview_paths({"lines": source}),
        
                acceptance_summary={'status': 'passed', 'review_required': False, 'authority': 'test_fixture'},
            )
        assert parent is not None
        project_store.begin_design_iteration(project["id"], parent["id"])

        with (
            patch("app.agent_service.get_creative_project_store", return_value=project_store),
            patch("app.agent_http_service.get_creative_project_store", return_value=project_store),
            patch("app.agent_http_service.conversation_memory", memory_store),
        ):
            result = agent_chat(AgentChatRequest(
                message="将选中的圆半径扩大一倍",
                mode="advanced",
                conversation_id="imported-cad-selection",
                project_id=project["id"],
                variant_id=parent["id"],
                drawing_selection={
                    "source_file_name": "imported_court.json",
                    "scope": "entity",
                    "geometry_ids": [6],
                },
            ))

    assert result["ok"] is True
    assert result["cad_edit_command"]["schema"] == "cad.geometry_edit.v1"
    assert result["cad_edit_command"]["target_geometry_ids"] == [6]
    changed = result["variant"]["geometries"]
    assert changed[0] == source[0]
    assert changed[1]["radius"] == 3600.0


def test_local_circle_scale_is_not_parsed_as_whole_candidate_scale() -> None:
    message = (
        "基于‘标准候选方案 · 选中图元 6 等比例缩放到 2.0 倍’继续优化。\n"
        "修改目标：中心的圆半径缩小一倍"
    )
    edit = parse_incremental_edit(message)

    assert edit is not None
    assert edit["operation"] == "scale"
    assert edit["selector"] == {
        "kind": "geometry_within_target",
        "geometry_type": "circle",
        "spatial_role": "center",
    }
    assert edit.get("instances") != "all"


def test_standalone_editor_selection_keeps_versioned_modify_path() -> None:
    route = {
        "decision_source": "incremental_cad_edit",
        "drawing_selection": {
            "source_file_name": "standalone.json",
            "scope": "entity",
            "geometry_ids": [1],
        },
        "object_memory": {"enabled": True, "objects": {}},
    }

    result = robot_agent._apply_incremental_candidate_edit(
        "向右移动1米", route
    )

    assert result is None
    assert route["edit_domain"] == "standalone_drawing"


def test_selection_of_other_saved_file_never_edits_active_candidate() -> None:
    from app.creative_projects import CreativeProjectStore
    from app.drawing_store import preview_paths
    from app.agent_skills import score_design_variant

    with tempfile.TemporaryDirectory() as directory:
        project_store = CreativeProjectStore(Path(directory) / "projects.json")
        source = _candidate_geometries()
        project = project_store.create(
            "项目 A", "创建两个图形", {"shape": "custom", "quantity": 2}, {}, [],
            source_drawing={"file_name": "project-a.json", "geometries": source},
        )
        parent = project_store.add_variant(
            project["id"], "初始方案", source, "初始",
            score_design_variant(source), preview_paths({"lines": source}),
        
                acceptance_summary={'status': 'passed', 'review_required': False, 'authority': 'test_fixture'},
            )
        project_store.begin_design_iteration(project["id"], parent["id"])
        with patch("app.agent_service.get_creative_project_store", return_value=project_store):
            route = robot_agent.resolve_intent("向右移动1米", "advanced", [])
            route.update({
                "object_memory": {"objects": {"project": [{"id": project["id"]}]}},
                "drawing_selection": {"source_file_name": "other.json", "scope": "entity", "geometry_ids": [3]},
            })
            assert robot_agent._apply_incremental_candidate_edit("向右移动1米", route) is None
        assert len(project_store.get(project["id"])["variants"]) == 1
