from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from app.conversation_memory import ConversationMemoryStore
from app.schemas import AgentChatRequest


class ConversationMemoryStoreTest(unittest.TestCase):
    def test_same_sentence_plural_does_not_require_historical_objects(self) -> None:
        for text in (
            "生成一个爱心和一个五角星，爱心在左，五角星在右，它们的长宽均为5米，间距为8米",
            "绘制甲形和乙形，它们的宽度均为2米",
        ):
            with self.subTest(text=text):
                result=self.store.resolve("local-scope",text)
                self.assertFalse(result["required"])
                self.assertFalse(result.get("ambiguous",False))
                self.assertEqual(result["message"],text)

    def test_historical_or_mixed_references_still_require_resolution(self) -> None:
        for text in ("把它们的间距改为8米", "生成一个与它相同的爱心",
                     "生成一个爱心和一个五角星，把它们放到刚才的图纸右边"):
            with self.subTest(text=text):
                result=self.store.resolve("no-history",text)
                self.assertTrue(result["required"])
                self.assertTrue(result["ambiguous"])

    def test_http_preparation_keeps_creation_with_selection_and_local_plural(self) -> None:
        from app.agent_http_service import _prepare_agent_chat_context
        from app.agent_service import RobotAgentService
        service=RobotAgentService(restore_pending_actions=False)
        service.mode="local"
        command=AgentChatRequest(
            message="生成一个爱心和一个五角星，爱心在左，五角星在右，它们的长宽均为5米，间距为8米",
            mode="advanced",conversation_id="create-local-plural",project_id="old-project",
            drawing_selection={"scope":"entity","geometry_ids":[1],"project_id":"old-project","variant_id":"old-variant"},
        )
        with (patch("app.agent_http_service.conversation_memory",self.store),patch("app.agent_http_service.robot_agent",service),
              patch.object(service,"knowledge_context",return_value={}),
              patch.object(service,"_stale_project_guard",return_value=None)):
            prepared=_prepare_agent_chat_context(command)
        self.assertFalse(prepared["resolution"].get("ambiguous",False))
        self.assertEqual(prepared["route"]["operation"],"create")
        self.assertEqual(prepared["resolved_message"],command.message)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "memory.json"
        self.store = ConversationMemoryStore(self.path)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_extracts_multi_court_quantity_arrangement_and_spacing(self) -> None:
        requirements = self.store._extract_requirements(
            "两个标准篮球场并排，长边相邻，间距2m"
        )

        self.assertEqual(requirements["drawing_type"], "basketball_court")
        self.assertEqual(requirements["quantity"], 2)
        self.assertEqual(requirements["arrangement"], "long_side_adjacent")
        self.assertEqual(requirements["spacing_m"], 2.0)

    def test_parking_space_reference_does_not_change_court_quantity(self) -> None:
        requirements = self.store._extract_requirements(
            "规划一个长边并排间距预留一个停车位大小的两个标准篮球场"
        )

        self.assertEqual(requirements["quantity"], 2)
        self.assertEqual(requirements["spacing_m"], 2.5)
        self.assertEqual(
            requirements["spacing_reference"], "standard_parking_space_width"
        )

    def test_extracts_quantity_for_non_sports_template(self) -> None:
        requirements = self.store._extract_requirements(
            "三个仓库网格并排，间距1.5m"
        )

        self.assertEqual(requirements["drawing_type"], "warehouse")
        self.assertEqual(requirements["quantity"], 3)
        self.assertEqual(requirements["arrangement"], "long_side_adjacent")
        self.assertEqual(requirements["spacing_m"], 1.5)

    def test_remembers_drawing_and_resolves_reference(self) -> None:
        self.store.remember(
            "conversation-1",
            "创建篮球场图纸",
            {"ok": True, "file_name": "court_v003.json"},
        )

        resolution = self.store.resolve(
            "conversation-1", "继续修改这个图纸"
        )

        self.assertTrue(resolution["resolved"])
        self.assertEqual(resolution["target"]["type"], "drawing")
        self.assertEqual(resolution["target"]["id"], "court_v003.json")
        self.assertIn("drawing=court_v003.json", resolution["message"])

    def test_remembers_only_successful_persisted_cad_edit_command(self) -> None:
        command = {
            "schema": "cad.instance_edit.v1",
            "operation": "translate",
            "target_instance_id": 2,
            "parameters": {"dx_mm": 2000, "dy_mm": 0},
        }
        self.store.remember("conversation-1", "移动第二个图形", {
            "ok": True,
            "project_id": "project-1",
            "variant": {"id": "variant-2"},
            "cad_edit_command": command,
        })
        remembered = self.store.context("conversation-1")["last_cad_edit"]
        self.assertEqual(remembered["target_instance_id"], 2)
        self.assertEqual(remembered["variant_id"], "variant-2")

        self.store.remember("conversation-1", "失败修改", {
            "ok": False,
            "project_id": "project-1",
            "variant": {"id": "variant-bad"},
            "cad_edit_command": {**command, "target_instance_id": 1},
        })
        self.assertEqual(
            self.store.context("conversation-1")["last_cad_edit"]["variant_id"],
            "variant-2",
        )

    def test_prefers_v2_cad_edit_contract_for_followup_memory(self) -> None:
        self.store.remember("conversation-1", "移动第二个图形", {
            "ok": True,
            "project_id": "project-1",
            "variant": {"id": "variant-2", "parent_variant_id": "variant-1"},
            "cad_edit_contract": {
                "schema": "cad.edit.v2", "operation": "translate",
                "target": {
                    "scope": "instance", "instance_ids": [2], "geometry_ids": [],
                },
                "coordinate_frame": "drawing",
                "parameters": {"dx_mm": 1000, "dy_mm": 0},
            },
            "cad_edit_command": {
                "schema": "cad.instance_edit.v1", "operation": "translate",
                "target_instance_id": 1,
                "parameters": {"dx_mm": 1000, "dy_mm": 0},
            },
        })
        remembered = self.store.context("conversation-1")["last_cad_edit"]
        self.assertEqual(remembered["schema"], "cad.edit.v2")
        self.assertEqual(remembered["target"]["instance_ids"], [2])

    def test_candidate_navigation_is_persisted(self) -> None:
        navigation = {
            "project_id": "project-1",
            "redo_stack": ["variant-3", "variant-2"],
            "current_variant_id": "variant-1",
        }
        self.store.set_candidate_navigation("conversation-1", navigation)

        restored = ConversationMemoryStore(self.path)

        self.assertEqual(
            restored.context("conversation-1")["candidate_navigation"],
            navigation,
        )

    def test_active_cad_context_binds_variant_and_selected_object(self) -> None:
        self.store.remember(
            "conversation-1",
            "把下方篮球场向前移动5米",
            {
                "ok": True,
                "project_id": "project-1",
                "variant": {
                    "id": "variant-2",
                    "parent_variant_id": "variant-1",
                    "geometries": [{"id": 3}],
                    "logical_objects": [{"object_id": "court-2"}],
                    "identity_contract": {"instance_ids": [2]},
                },
                "cad_edit_contract": {
                    "schema": "cad.edit.v2",
                    "operation": "translate",
                    "target": {"scope": "logical_object", "object_id": "court-2", "geometry_ids": [3]},
                },
            },
        )
        context = self.store.context("conversation-1")["active_cad_context"]
        self.assertEqual(context["project_id"], "project-1")
        self.assertEqual(context["variant_id"], "variant-2")
        self.assertEqual(context["selected_object_ids"], ["court-2"])
        self.assertEqual(context["selected_geometry_ids"], [3])

    def test_cad_navigation_intent_does_not_capture_hardware_undo(self) -> None:
        from app.agent_http_service import _cad_navigation_action

        self.assertEqual(_cad_navigation_action("撤销刚才的修改"), "undo")
        self.assertEqual(_cad_navigation_action("回退上一步"), "undo")
        self.assertEqual(_cad_navigation_action("恢复刚才撤销的修改"), "redo")
        self.assertEqual(_cad_navigation_action("重做"), "redo")
        self.assertIsNone(_cad_navigation_action("撤销刚才的小车任务"))
        self.assertIsNone(_cad_navigation_action("恢复底盘上一步修改"))

    def test_chat_api_undo_redo_preserves_candidates_and_quantity(self) -> None:
        from copy import deepcopy

        from app.agent_service import robot_agent
        from app.agent_skills import drawing_template_geometries, score_design_variant
        from app.creative_projects import CreativeProjectStore
        from app.drawing_store import preview_paths
        from app.agent_http_service import agent_chat

        project_store = CreativeProjectStore(Path(self.temporary.name) / "undo-projects.json")
        memory_store = ConversationMemoryStore(Path(self.temporary.name) / "undo-memory.json")
        geometries = drawing_template_geometries({
            "template": "room", "width_m": 5, "height_m": 3,
            "quantity": 4, "spacing_m": 2,
        })
        project = project_store.create(
            "撤销重做测试", "创建四个房间",
            {"shape": "room", "quantity": 4, "printer": "center"}, {}, [],
        )
        parent = project_store.add_variant(
            project["id"], "四个房间", geometries, "初始候选",
            score_design_variant(geometries), preview_paths({"lines": geometries}),
            expected_quantity=4,
        )
        child_geometries = [
            deepcopy(item) for item in geometries
            if item.get("template_instance") in {1, 2}
        ]
        child = project_store.add_variant(
            project["id"], "保留两个房间", child_geometries, "删除两个实例",
            score_design_variant(child_geometries),
            preview_paths({"lines": child_geometries}),
            parent_variant_id=parent["id"], expected_quantity=2,
        )
        grand_geometries = deepcopy(child_geometries)
        for item in grand_geometries:
            if item.get("template_instance") == 2:
                for vertex in item.get("vertices", []):
                    vertex["x"] += 1000
        grandchild = project_store.add_variant(
            project["id"], "移动第二个房间", grand_geometries, "增量平移",
            score_design_variant(grand_geometries),
            preview_paths({"lines": grand_geometries}),
            parent_variant_id=child["id"], expected_quantity=2,
        )
        project_store.begin_design_iteration(project["id"], grandchild["id"])
        memory_store.remember("cad-history", "移动第二个图形", {
            "ok": True,
            "project_id": project["id"],
            "variant": grandchild,
            "cad_edit_command": {
                "schema": "cad.instance_edit.v1",
                "operation": "translate",
                "target_instance_id": 2,
                "parameters": {"dx_mm": 1000, "dy_mm": 0},
            },
        })

        with (
            patch("app.agent_http_service.get_creative_project_store", return_value=project_store),
            patch("app.agent_http_service.conversation_memory", memory_store),
            patch.object(robot_agent, "resolve_intent") as resolve_intent,
            patch.object(robot_agent, "chat") as chat,
        ):
            undo_one = agent_chat(AgentChatRequest(
                message="撤销刚才的修改", mode="advanced", conversation_id="cad-history",
            ))
            undo_two = agent_chat(AgentChatRequest(
                message="撤销上一步", mode="advanced", conversation_id="cad-history",
            ))
            redo_one = agent_chat(AgentChatRequest(
                message="重做", mode="advanced", conversation_id="cad-history",
            ))
            redo_two = agent_chat(AgentChatRequest(
                message="恢复刚才撤销的修改", mode="advanced", conversation_id="cad-history",
            ))

        resolve_intent.assert_not_called()
        chat.assert_not_called()
        self.assertEqual(undo_one["project"]["design_base_variant_id"], child["id"])
        self.assertEqual(undo_one["project"]["requirements"]["quantity"], 2)
        self.assertEqual(undo_two["project"]["design_base_variant_id"], parent["id"])
        self.assertEqual(undo_two["project"]["requirements"]["quantity"], 4)
        self.assertEqual(redo_one["project"]["design_base_variant_id"], child["id"])
        self.assertEqual(redo_one["project"]["requirements"]["quantity"], 2)
        self.assertEqual(redo_two["project"]["design_base_variant_id"], grandchild["id"])
        self.assertEqual(len(project_store.get(project["id"])["variants"]), 3)
        for result in (undo_one, undo_two, redo_one, redo_two):
            self.assertTrue(result["rollback_verification"]["verified"])
            self.assertEqual(result["rollback_verification"]["status"], "success")

    def test_new_candidate_after_undo_clears_redo_branch(self) -> None:
        from copy import deepcopy

        from app.agent_skills import drawing_template_geometries, score_design_variant
        from app.creative_projects import CreativeProjectStore
        from app.drawing_store import preview_paths
        from app.agent_http_service import agent_chat

        project_store = CreativeProjectStore(Path(self.temporary.name) / "branch-projects.json")
        memory_store = ConversationMemoryStore(Path(self.temporary.name) / "branch-memory.json")
        geometries = drawing_template_geometries({
            "template": "room", "width_m": 5, "height_m": 3, "quantity": 1,
        })
        project = project_store.create(
            "分支测试", "创建一个房间", {"shape": "room", "quantity": 1}, {}, [],
        )
        parent = project_store.add_variant(
            project["id"], "原始方案", geometries, "初始候选",
            score_design_variant(geometries), preview_paths({"lines": geometries}),
        )
        old_child = project_store.add_variant(
            project["id"], "旧分支", deepcopy(geometries), "旧修改",
            score_design_variant(geometries), preview_paths({"lines": geometries}),
            parent_variant_id=parent["id"],
        )
        project_store.begin_design_iteration(project["id"], old_child["id"])
        command = {
            "schema": "cad.instance_edit.v1", "operation": "translate",
            "target_instance_id": 1, "parameters": {"dx_mm": 1000, "dy_mm": 0},
        }
        memory_store.remember("cad-branch", "移动图形", {
            "ok": True, "project_id": project["id"], "variant": old_child,
            "cad_edit_command": command,
        })

        with (
            patch("app.agent_http_service.get_creative_project_store", return_value=project_store),
            patch("app.agent_http_service.conversation_memory", memory_store),
        ):
            undone = agent_chat(AgentChatRequest(
                message="撤销刚才的修改", mode="advanced", conversation_id="cad-branch",
            ))
            self.assertTrue(undone["ok"], undone)
            new_child = project_store.add_variant(
                project["id"], "新分支", deepcopy(geometries), "新修改",
                score_design_variant(geometries), preview_paths({"lines": geometries}),
                parent_variant_id=parent["id"],
            )
            project_store.begin_design_iteration(project["id"], new_child["id"])
            memory_store.remember("cad-branch", "新修改", {
                "ok": True, "project_id": project["id"], "variant": new_child,
                "cad_edit_command": command,
            })
            redo = agent_chat(AgentChatRequest(
                message="重做", mode="advanced", conversation_id="cad-branch",
            ))

        self.assertFalse(redo["ok"])
        self.assertEqual(redo["message"], "当前没有可重做的候选修改。")

    def test_external_candidate_switch_invalidates_undo_stack(self) -> None:
        from app.creative_projects import CreativeProjectStore
        from app.agent_http_service import agent_chat

        projects = CreativeProjectStore(Path(self.temporary.name) / "switch-projects.json")
        project = projects.create("切换分支", "原始图", {}, {}, [])
        source = [{"id": 1, "type": "line", "template_instance": 1,
                   "start": {"x": 0, "y": 0}, "end": {"x": 1000, "y": 0}}]
        first = projects.add_variant(project["id"], "初始", source, "", {}, [])
        second = projects.add_variant(
            project["id"], "修改", source, "", {}, [], parent_variant_id=first["id"],
        )
        third = projects.add_variant(
            project["id"], "其他分支", source, "", {}, [], parent_variant_id=first["id"],
        )
        projects.begin_design_iteration(project["id"], second["id"])
        self.store.remember("switch-branch", "修改", {
            "ok": True, "project_id": project["id"], "variant": second,
            "cad_edit_command": {"schema": "cad.instance_edit.v1", "operation": "translate",
                                 "target_instance_id": 1, "parameters": {"dx_mm": 1000, "dy_mm": 0}},
        })
        with (
            patch("app.agent_http_service.get_creative_project_store", return_value=projects),
            patch("app.agent_http_service.conversation_memory", self.store),
        ):
            undone = agent_chat(AgentChatRequest(
                message="撤销刚才的修改", mode="advanced", conversation_id="switch-branch",
            ))
            self.assertTrue(undone["ok"])
            projects.begin_design_iteration(project["id"], third["id"])
            blocked = agent_chat(AgentChatRequest(
                message="撤销上一步", mode="advanced", conversation_id="switch-branch",
            ))

        self.assertFalse(blocked["ok"])
        self.assertIn("分支已变化", blocked["message"])
        self.assertEqual(projects.get(project["id"])["design_base_variant_id"], third["id"])
        self.assertIsNone(self.store.context("switch-branch")["candidate_navigation"])

    def test_cad_followup_requires_same_active_candidate_branch(self) -> None:
        from app.agent_http_service import _resolve_cad_followup

        memory = {"last_cad_edit": {
            "schema": "cad.instance_edit.v1",
            "operation": "translate",
            "target_instance_id": 2,
            "parameters": {"dx_mm": 2000, "dy_mm": 0},
            "project_id": "project-1",
            "variant_id": "variant-2",
        }}
        with patch("app.agent_http_service.get_creative_project_store.get", return_value={
            "status": "designing", "design_base_variant_id": "variant-2",
        }):
            self.assertEqual(
                _resolve_cad_followup("再向右移动同样距离", memory),
                "第2个图形向右移动2000毫米",
            )
        with patch("app.agent_http_service.get_creative_project_store.get", return_value={
            "status": "designing", "design_base_variant_id": "another-variant",
        }):
            self.assertEqual(
                _resolve_cad_followup("再向右移动同样距离", memory),
                "再向右移动同样距离",
            )

    def test_chat_api_persists_followup_as_child_candidate(self) -> None:
        from app.agent_service import robot_agent
        from app.agent_skills import drawing_template_geometries, score_design_variant
        from app.creative_projects import CreativeProjectStore
        from app.drawing_store import preview_paths
        from app.agent_http_service import agent_chat

        project_store = CreativeProjectStore(Path(self.temporary.name) / "projects.json")
        memory_store = ConversationMemoryStore(Path(self.temporary.name) / "chat-memory.json")
        geometries = drawing_template_geometries({
            "template": "room", "width_m": 5, "height_m": 3,
            "quantity": 2, "spacing_m": 2,
        })
        project = project_store.create(
            "连续修改测试", "创建两个房间",
            {"shape": "room", "quantity": 2, "printer": "center"}, {}, [],
        )
        parent = project_store.add_variant(
            project["id"], "初始方案", geometries, "用于连续修改",
            score_design_variant(geometries), preview_paths({"lines": geometries}),
        )
        self.assertIsNotNone(parent)
        project_store.begin_design_iteration(project["id"], parent["id"])
        memory_store.remember("cad-followup-api", "", {
            "ok": True,
            "project_id": project["id"],
            "project": project_store.get(project["id"]),
        })

        with (
            patch("app.agent_service.get_creative_project_store", return_value=project_store),
            patch("app.agent_http_service.get_creative_project_store", return_value=project_store),
            patch("app.agent_http_service.conversation_memory", memory_store),
        ):
            first = agent_chat(AgentChatRequest(
                message="第2个图形向右移动2米",
                mode="advanced",
                conversation_id="cad-followup-api",
            ))
            self.assertTrue(first["ok"], first)
            first_variant = first["variant"]
            project_store.begin_design_iteration(project["id"], first_variant["id"])

            second = agent_chat(AgentChatRequest(
                message="再向右移动同样距离",
                mode="advanced",
                conversation_id="cad-followup-api",
            ))

            self.assertTrue(second["ok"], second)
            project_store.begin_design_iteration(
                project["id"], second["variant"]["id"]
            )
            third = agent_chat(AgentChatRequest(
                message="把另一个图形向左移动1米",
                mode="advanced",
                conversation_id="cad-followup-api",
            ))

        self.assertTrue(second["ok"], second)
        self.assertEqual(second["variant"]["parent_variant_id"], first_variant["id"])
        self.assertEqual(second["cad_edit_command"]["parameters"]["dx_mm"], 2000)
        first_x = first_variant["geometries"][1]["vertices"][0]["x"]
        second_x = second["variant"]["geometries"][1]["vertices"][0]["x"]
        self.assertEqual(second_x - first_x, 2000)
        self.assertTrue(third["ok"], third)
        self.assertEqual(
            third["variant"]["parent_variant_id"], second["variant"]["id"]
        )
        self.assertEqual(third["cad_edit_command"]["target_instance_id"], 1)
        self.assertEqual(third["cad_edit_command"]["parameters"]["dx_mm"], -1000)
        self.assertEqual(len(project_store.get(project["id"])["variants"]), 4)

    def test_chat_api_correction_branches_from_original_parent(self) -> None:
        from app.agent_skills import drawing_template_geometries, score_design_variant
        from app.creative_projects import CreativeProjectStore
        from app.drawing_store import preview_paths
        from app.agent_http_service import agent_chat

        project_store = CreativeProjectStore(Path(self.temporary.name) / "correction-projects.json")
        memory_store = ConversationMemoryStore(Path(self.temporary.name) / "correction-memory.json")
        geometries = drawing_template_geometries({
            "template": "room", "width_m": 5, "height_m": 3,
            "quantity": 2, "spacing_m": 2,
        })
        project = project_store.create(
            "纠正测试", "创建两个房间",
            {"shape": "room", "quantity": 2, "printer": "center"}, {}, [],
        )
        parent = project_store.add_variant(
            project["id"], "原始方案", geometries, "纠正基准",
            score_design_variant(geometries), preview_paths({"lines": geometries}),
        )
        self.assertIsNotNone(parent)
        project_store.begin_design_iteration(project["id"], parent["id"])
        memory_store.remember("cad-correction-api", "", {
            "ok": True, "project_id": project["id"],
            "project": project_store.get(project["id"]),
        })

        with (
            patch("app.agent_service.get_creative_project_store", return_value=project_store),
            patch("app.agent_http_service.get_creative_project_store", return_value=project_store),
            patch("app.agent_http_service.conversation_memory", memory_store),
        ):
            wrong = agent_chat(AgentChatRequest(
                message="第2个图形向右移动2米", mode="advanced",
                conversation_id="cad-correction-api",
            ))
            self.assertTrue(wrong["ok"], wrong)
            project_store.begin_design_iteration(
                project["id"], wrong["variant"]["id"]
            )
            corrected = agent_chat(AgentChatRequest(
                message="不是向右2米，是向左1米", mode="advanced",
                conversation_id="cad-correction-api",
            ))

        self.assertTrue(corrected["ok"], corrected)
        self.assertEqual(wrong["variant"]["parent_variant_id"], parent["id"])
        self.assertEqual(corrected["variant"]["parent_variant_id"], parent["id"])
        self.assertEqual(corrected["cad_edit_command"]["target_instance_id"], 2)
        self.assertEqual(corrected["cad_edit_command"]["parameters"]["dx_mm"], -1000)
        parent_x = parent["geometries"][1]["vertices"][0]["x"]
        wrong_x = wrong["variant"]["geometries"][1]["vertices"][0]["x"]
        corrected_x = corrected["variant"]["geometries"][1]["vertices"][0]["x"]
        self.assertEqual(wrong_x - parent_x, 2000)
        self.assertEqual(corrected_x - parent_x, -1000)
        remembered = memory_store.context("cad-correction-api")["last_cad_edit"]
        self.assertEqual(remembered["variant_id"], corrected["variant"]["id"])
        self.assertEqual(remembered["parent_variant_id"], parent["id"])

    def test_chat_api_applies_remaining_instances_as_batch_translation(self) -> None:
        from app.agent_service import robot_agent
        from app.agent_skills import drawing_template_geometries, score_design_variant
        from app.creative_projects import CreativeProjectStore
        from app.drawing_store import preview_paths
        from app.agent_http_service import agent_chat

        project_store = CreativeProjectStore(Path(self.temporary.name) / "batch-projects.json")
        memory_store = ConversationMemoryStore(Path(self.temporary.name) / "batch-memory.json")
        geometries = drawing_template_geometries({
            "template": "room", "width_m": 5, "height_m": 3,
            "quantity": 4, "spacing_m": 2,
        })
        project = project_store.create(
            "批量平移测试", "创建四个房间",
            {"shape": "room", "quantity": 4, "printer": "center"}, {}, [],
        )
        parent = project_store.add_variant(
            project["id"], "初始方案", geometries, "用于批量修改",
            score_design_variant(geometries), preview_paths({"lines": geometries}),
        )
        self.assertIsNotNone(parent)
        project_store.begin_design_iteration(project["id"], parent["id"])
        memory_store.remember("cad-batch-api", "", {
            "ok": True, "project_id": project["id"],
            "project": project_store.get(project["id"]),
        })

        with (
            patch("app.agent_service.get_creative_project_store", return_value=project_store),
            patch("app.agent_http_service.get_creative_project_store", return_value=project_store),
            patch("app.agent_http_service.conversation_memory", memory_store),
        ):
            first = agent_chat(AgentChatRequest(
                message="第1个图形向左移动1米", mode="advanced",
                conversation_id="cad-batch-api",
            ))
            self.assertTrue(first["ok"], first)
            project_store.begin_design_iteration(project["id"], first["variant"]["id"])
            batch = agent_chat(AgentChatRequest(
                message="把剩余三个图形整体向右移动1米", mode="advanced",
                conversation_id="cad-batch-api",
            ))
            self.assertTrue(batch["ok"], batch)
            project_store.begin_design_iteration(
                project["id"], batch["variant"]["id"]
            )
            rotated = agent_chat(AgentChatRequest(
                message=(
                    "让第2个图形和第4个图形分别绕各自中心"
                    "逆时针旋转90度"
                ),
                mode="advanced",
                conversation_id="cad-batch-api",
            ))
            self.assertTrue(rotated["ok"], rotated)
            project_store.begin_design_iteration(
                project["id"], rotated["variant"]["id"]
            )
            scaled = agent_chat(AgentChatRequest(
                message=(
                    "把第2个图形和第4个图形以组合中心"
                    "整体缩放到1.5倍"
                ),
                mode="advanced",
                conversation_id="cad-batch-api",
            ))
            self.assertTrue(scaled["ok"], scaled)
            project_store.begin_design_iteration(
                project["id"], scaled["variant"]["id"]
            )
            deleted = agent_chat(AgentChatRequest(
                message="删除第1、3个图形",
                mode="advanced",
                conversation_id="cad-batch-api",
            ))

        self.assertTrue(batch["ok"], batch)
        self.assertEqual(batch["cad_edit_command"]["target_instance_ids"], [2, 3, 4])
        self.assertEqual(
            batch["variant"]["parent_variant_id"], first["variant"]["id"]
        )
        before = first["variant"]["geometries"]
        after = batch["variant"]["geometries"]
        self.assertEqual(after[0], before[0])
        for index in (1, 2, 3):
            self.assertEqual(
                after[index]["vertices"][0]["x"]
                - before[index]["vertices"][0]["x"],
                1000,
            )
        self.assertTrue(rotated["ok"], rotated)
        self.assertEqual(rotated["cad_edit_command"]["target_instance_ids"], [2, 4])
        self.assertEqual(
            rotated["cad_edit_command"]["parameters"]["pivot"],
            "each_instance_center",
        )
        self.assertEqual(
            rotated["variant"]["parent_variant_id"], batch["variant"]["id"]
        )
        self.assertTrue(scaled["ok"], scaled)
        self.assertEqual(scaled["cad_edit_command"]["operation"], "scale")
        self.assertEqual(scaled["cad_edit_command"]["target_instance_ids"], [2, 4])
        self.assertEqual(scaled["cad_edit_command"]["parameters"]["factor"], 1.5)
        self.assertEqual(
            scaled["cad_edit_command"]["parameters"]["pivot"], "group_center"
        )
        self.assertEqual(
            scaled["variant"]["parent_variant_id"], rotated["variant"]["id"]
        )
        self.assertTrue(deleted["ok"], deleted)
        self.assertEqual(deleted["cad_edit_command"]["operation"], "delete")
        self.assertEqual(deleted["cad_edit_command"]["target_instance_ids"], [1, 3])
        self.assertEqual(
            deleted["variant"]["parent_variant_id"], scaled["variant"]["id"]
        )
        self.assertEqual(
            {item["template_instance"] for item in deleted["variant"]["geometries"]},
            {2, 4},
        )
        self.assertEqual(
            deleted["variant"]["geometries"],
            [
                item for item in scaled["variant"]["geometries"]
                if item["template_instance"] in {2, 4}
            ],
        )

    def test_conversations_are_isolated(self) -> None:
        self.store.remember("conversation-a", "", {"file_name": "a_v001.json"})
        self.store.remember("conversation-b", "", {"file_name": "b_v001.json"})

        first = self.store.resolve("conversation-a", "修改这个图纸")
        second = self.store.resolve("conversation-b", "修改这个图纸")

        self.assertEqual(first["target"]["id"], "a_v001.json")
        self.assertEqual(second["target"]["id"], "b_v001.json")

    def test_previous_variant_selects_second_most_recent(self) -> None:
        self.store.remember("conversation-1", "", {"variant_id": "variant-a"})
        self.store.remember("conversation-1", "", {"variant_id": "variant-b"})

        resolution = self.store.resolve("conversation-1", "使用上一个方案")

        self.assertTrue(resolution["resolved"])
        self.assertEqual(resolution["target"]["id"], "variant-a")

    def test_unresolved_reference_requires_clarification(self) -> None:
        resolution = self.store.resolve("empty-conversation", "继续修改它")

        self.assertTrue(resolution["required"])
        self.assertTrue(resolution["ambiguous"])
        self.assertIn("请明确", resolution["question"])

    def test_memory_survives_store_restart(self) -> None:
        self.store.remember("conversation-1", "", {"project_id": "project-1"})

        restored = ConversationMemoryStore(self.path)
        resolution = restored.resolve("conversation-1", "继续这个项目")

        self.assertTrue(resolution["resolved"])
        self.assertEqual(resolution["target"]["id"], "project-1")

    def test_structured_summary_and_requirement_profile_survive_restart(self) -> None:
        self.store.observe(
            "conversation-1",
            "设计一个 5×3 米篮球场，黄色喷墨，线宽 50mm，不使用全站仪，尽量慢",
        )
        pending = self.store.context("conversation-1")["requirement_profile"]["pending"]

        self.assertEqual(pending["drawing_type"], "basketball_court")
        self.assertEqual(pending["width_m"], 5.0)
        self.assertEqual(pending["height_m"], 3.0)
        self.assertEqual(pending["line_width_mm"], 50.0)
        self.assertEqual(pending["ink_color"], "黄色")
        self.assertEqual(pending["localization"], "relative")
        self.assertEqual(pending["speed_preference"], "low")

        decision = self.store.decide_requirements("conversation-1", True)
        self.assertTrue(decision["ok"])
        restored = ConversationMemoryStore(self.path)
        profile = restored.context("conversation-1")["requirement_profile"]
        self.assertEqual(profile["version"], 1)
        self.assertEqual(profile["confirmed"]["line_width_mm"], 50.0)
        self.assertEqual(profile["pending"], {})
        self.assertIn("已确认", restored.context("conversation-1")["summary"]["text"])

    def test_structured_workflow_state_survives_restart(self) -> None:
        self.store.observe("conversation-1", "继续修改当前方案")
        self.store.remember(
            "conversation-1",
            "继续修改当前方案",
            {
                "ok": True,
                "message": "候选方案已生成。",
                "project_id": "project-1",
                "variant": {
                    "id": "variant-2",
                    "parent_variant_id": "variant-1",
                },
                "next_action": "select_design_variant",
            },
        )

        state = self.store.context("conversation-1")["workflow_state"]
        restored = ConversationMemoryStore(self.path)
        restored_state = restored.context("conversation-1")["workflow_state"]

        self.assertEqual(state["schema"], "agent.conversation-state.v1")
        self.assertEqual(state["phase"], "candidate_review")
        self.assertEqual(state["active"]["project_id"], "project-1")
        self.assertEqual(state["active"]["variant_id"], "variant-2")
        self.assertEqual(state["active"]["parent_variant_id"], "variant-1")
        self.assertEqual(state["pending"]["kind"], "candidate_selection")
        self.assertEqual(restored_state, state)
        self.assertEqual(len(state["state_sha256"]), 64)

    def test_clarification_route_records_expected_answer(self) -> None:
        memory = self.store.remember(
            "conversation-1",
            "移动它",
            {"ok": True, "message": "请明确要移动哪个图形。"},
            route={
                "clarification_required": True,
                "clarification_question": "请明确要移动哪个图形。",
            },
        )

        state = memory["workflow_state"]
        self.assertEqual(state["phase"], "awaiting_clarification")
        self.assertEqual(state["pending"]["kind"], "clarification")
        self.assertEqual(state["pending"]["expected_response"], "answer")
        self.assertIn("哪个图形", state["pending"]["question"])

    def test_pending_action_records_confirmation_state(self) -> None:
        memory = self.store.remember(
            "conversation-1",
            "开始执行",
            {
                "ok": True,
                "message": "请确认执行。",
                "pending_action": {
                    "id": "action-1",
                    "name": "execute_prepared_mission",
                },
            },
        )

        state = memory["workflow_state"]
        self.assertEqual(state["phase"], "awaiting_confirmation")
        self.assertEqual(state["active"]["action_id"], "action-1")
        self.assertEqual(state["pending"]["kind"], "action_confirmation")
        self.assertEqual(state["pending"]["expected_response"], "confirm_or_cancel")

    def test_answering_clarification_clears_the_old_question(self) -> None:
        self.store.remember(
            "conversation-1",
            "移动它",
            {"ok": True, "message": "请明确要移动哪个图形。"},
            route={
                "clarification_required": True,
                "clarification_question": "请明确要移动哪个图形。",
            },
        )

        memory = self.store.remember(
            "conversation-1",
            "第二个图形",
            {"ok": True, "message": "已识别第二个图形。"},
            route={"stage": "design"},
        )

        self.assertEqual(memory["workflow_state"]["phase"], "designing")
        self.assertIsNone(memory["workflow_state"]["pending"])

    def test_terminal_action_clears_active_action(self) -> None:
        self.store.remember(
            "conversation-1",
            "开始执行",
            {
                "ok": True,
                "message": "请确认执行。",
                "pending_action": {"id": "action-1", "name": "drive_robot"},
            },
        )

        memory = self.store.remember(
            "conversation-1",
            "取消",
            {"ok": True, "message": "已取消。", "task_state": "cancelled"},
        )

        state = memory["workflow_state"]
        self.assertEqual(state["phase"], "cancelled")
        self.assertIsNone(state["active"]["action_id"])
        self.assertIsNone(state["pending"])

    def test_requirement_decision_transitions_structured_state(self) -> None:
        self.store.observe("conversation-1", "篮球场线宽 50mm")

        accepted = self.store.decide_requirements("conversation-1", True)

        state = accepted["memory"]["workflow_state"]
        self.assertEqual(state["phase"], "designing")
        self.assertIsNone(state["pending"])
        self.assertEqual(
            state["last_outcome"]["next_action"], "continue_design",
        )

    def test_parking_quantity_is_kept_in_requirement_profile(self) -> None:
        self.store.observe("conversation-1", "设计三个并排标准车位")

        pending = self.store.context("conversation-1")["requirement_profile"]["pending"]

        self.assertEqual(pending["drawing_type"], "parking_space")
        self.assertEqual(pending["quantity"], 3)

    def test_retrieval_returns_only_relevant_memory(self) -> None:
        self.store.observe("conversation-1", "篮球场线宽 50mm，黄色喷墨")
        self.store.decide_requirements("conversation-1", True)

        unrelated = self.store.retrieve("conversation-1", "你好")
        relevant = self.store.retrieve("conversation-1", "把线宽改成 60mm，其他不变")

        self.assertFalse(unrelated["relevant"])
        self.assertTrue(relevant["relevant"])
        self.assertEqual(relevant["confirmed_requirements"]["line_width_mm"], 50.0)
        self.assertEqual(relevant["confirmed_requirements"]["ink_color"], "黄色")

    def test_new_requirements_wait_for_confirmation_and_rejection_preserves_profile(self) -> None:
        self.store.observe("conversation-1", "篮球场线宽 50mm")
        self.store.decide_requirements("conversation-1", True)
        self.store.observe("conversation-1", "把线宽改成 60mm，其他不变")

        before = self.store.context("conversation-1")["requirement_profile"]
        self.assertEqual(before["confirmed"]["line_width_mm"], 50.0)
        self.assertEqual(before["pending"]["line_width_mm"], 60.0)
        self.store.decide_requirements("conversation-1", False)
        after = self.store.context("conversation-1")["requirement_profile"]
        self.assertEqual(after["confirmed"]["line_width_mm"], 50.0)
        self.assertEqual(after["pending"], {})

    def test_rejected_first_requirement_is_not_restored_from_history(self) -> None:
        history = [
            {"role": "user", "content": "设计黄色篮球场，线宽 50mm"},
            {"role": "assistant", "content": "请确认要求。"},
        ]
        self.store.context("conversation-1", history)
        self.store.decide_requirements("conversation-1", False)

        context = self.store.context("conversation-1", history)

        self.assertEqual(context["requirement_profile"]["status"], "needs_revision")
        self.assertEqual(context["requirement_profile"]["pending"], {})

    def test_summary_redacts_secrets(self) -> None:
        self.store.observe(
            "conversation-1",
            "设计篮球场，api_key=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        )
        summary = self.store.context("conversation-1")["summary"]
        self.assertNotIn("sk-", str(summary))
        self.assertIn("[已隐藏]", summary["last_user_request"])

    def test_history_bootstraps_summary_without_overwriting_confirmed_profile(self) -> None:
        context = self.store.context(
            "conversation-1",
            [
                {"role": "user", "content": "设计黄色篮球场，线宽 50mm"},
                {"role": "assistant", "content": "请确认要求。"},
            ],
        )

        self.assertIn("设计黄色篮球场", context["summary"]["last_user_request"])
        self.assertEqual(
            context["requirement_profile"]["pending"]["line_width_mm"],
            50.0,
        )
        self.assertEqual(context["requirement_profile"]["confirmed"], {})

    def test_old_memory_bootstraps_missing_profile_and_last_answer(self) -> None:
        self.path.write_text(json.dumps({
            "schema_version": "1.0",
            "conversations": {
                "conversation-1": {
                    "conversation_id": "conversation-1",
                    "objects": {"drawing": []},
                    "focus": None,
                    "summary": {
                        "last_user_request": "旧请求",
                        "recent_requests": ["旧请求"],
                        "last_answer": "",
                        "turn_count": 1,
                    },
                },
            },
        }, ensure_ascii=False), encoding="utf-8")
        restored = ConversationMemoryStore(self.path)

        context = restored.context("conversation-1", [
            {"role": "user", "content": "篮球场线宽 50mm，改成白色"},
            {"role": "assistant", "content": "已整理，token=secret-value"},
        ])

        self.assertEqual(
            context["requirement_profile"]["pending"]["line_width_mm"], 50.0
        )
        self.assertEqual(
            context["requirement_profile"]["pending"]["ink_color"], "白色"
        )
        self.assertIn("已整理", context["summary"]["last_answer"])
        self.assertNotIn("secret-value", context["summary"]["last_answer"])

    def test_history_profile_is_loaded_before_current_change(self) -> None:
        self.store.context("conversation-1", [
            {"role": "user", "content": "设计篮球场，黄色喷墨，线宽 50mm"},
            {"role": "assistant", "content": "请确认要求。"},
        ])
        self.store.observe("conversation-1", "把线宽改成 60mm，其他不变")

        pending = self.store.context("conversation-1")["requirement_profile"]["pending"]
        self.assertEqual(pending["ink_color"], "黄色")
        self.assertEqual(pending["line_width_mm"], 60.0)

    def test_requirement_extraction_uses_last_non_negated_choice(self) -> None:
        self.store.observe(
            "conversation-1",
            "篮球场不要黄色，改成白色；不要篮球场，改成足球场",
        )

        pending = self.store.context("conversation-1")["requirement_profile"]["pending"]
        self.assertEqual(pending["ink_color"], "白色")
        self.assertEqual(pending["drawing_type"], "football_field")

    def test_bare_color_mention_is_not_treated_as_design_change(self) -> None:
        self.store.observe("conversation-1", "我今天穿了白色衣服")

        pending = self.store.context("conversation-1")["requirement_profile"]["pending"]
        self.assertEqual(pending, {})

    def test_invalid_conversation_id_disables_server_memory(self) -> None:
        context = self.store.remember("../shared", "", {"file_name": "x.json"})

        self.assertFalse(context["enabled"])
        self.assertFalse(self.path.exists())

    def test_delete_removes_persisted_conversation(self) -> None:
        self.store.remember("rover:8000:conversation-1", "", {"file_name": "x.json"})

        self.assertTrue(self.store.delete("rover:8000:conversation-1"))
        restored = ConversationMemoryStore(self.path)
        resolution = restored.resolve("rover:8000:conversation-1", "修改这个图纸")
        self.assertTrue(resolution["ambiguous"])

    def test_chat_contract_accepts_scoped_conversation_id(self) -> None:
        request = AgentChatRequest(
            message="继续修改这个图纸",
            mode="advanced",
            conversation_id="192.168.0.100:8000:conversation-1",
        )

        self.assertEqual(
            request.conversation_id, "192.168.0.100:8000:conversation-1"
        )

    def test_chat_contract_rejects_path_like_conversation_id(self) -> None:
        with self.assertRaises(ValidationError):
            AgentChatRequest(message="继续", conversation_id="../shared")

    def test_requirement_decision_endpoint_persists_confirmation(self) -> None:
        from app.routers.agent import decide_agent_requirements
        from app.schemas import AgentRequirementDecisionRequest

        self.store.observe("conversation-1", "黄色篮球场线宽 50mm")
        with patch("app.routers.agent.conversation_memory", self.store):
            result = decide_agent_requirements(
                "conversation-1",
                AgentRequirementDecisionRequest(accepted=True),
            )

        self.assertTrue(result["ok"])
        profile = result["memory"]["requirement_profile"]
        self.assertEqual(profile["confirmed"]["line_width_mm"], 50.0)
        self.assertEqual(profile["version"], 1)

    def test_pending_requirements_block_physical_action_deterministically(self) -> None:
        from app.agent_service import robot_agent
        from app.agent_http_service import _enforce_requirement_confirmation

        pending_action = robot_agent.request_confirmation(
            "printer_spray",
            {"printer_name": "center", "spraying": True},
            mode="advanced",
        )
        action_id = pending_action["pending_action"]["id"]
        result = _enforce_requirement_confirmation(pending_action, {
            "retrieved_memory": {
                "relevant": True,
                "pending_requirements": {"printer": "center"},
            },
        })

        self.assertIsNone(result["pending_action"])
        self.assertTrue(result["requirements_confirmation_required"])
        self.assertIn("先检查并确认需求档案", result["message"])
        replay = robot_agent.confirm(action_id, True)
        self.assertEqual(replay["task_state"], "cancelled")
        self.assertTrue(replay["idempotent_replay"])
        self.assertFalse(replay["ok"])

    def test_explicit_matching_base_speed_keeps_confirmation_action(self) -> None:
        from app.agent_service import robot_agent
        from app.agent_http_service import _enforce_requirement_confirmation

        pending_action = robot_agent.request_confirmation(
            "drive_robot",
            {"linear": 0.15, "angular": 0.3, "duration_seconds": 20.944},
            mode="base",
        )
        result = _enforce_requirement_confirmation(pending_action, {
            "name": "motion_control",
            "mode": "base",
            "retrieved_memory": {
                "pending_requirements": {"linear_speed_mps": 0.15},
            },
        })

        self.assertIsNotNone(result["pending_action"])
        robot_agent.confirm(result["pending_action"]["id"], False)

    def test_base_circle_chat_returns_button_action_without_obstacle_claim(self) -> None:
        from app.agent_service import robot_agent
        from app.agent_http_service import agent_chat

        with (
            patch("app.agent_http_service.conversation_memory", self.store),
            patch.object(robot_agent, "_deepseek_request") as model,
        ):
            result = agent_chat(AgentChatRequest(
                message="以线速度 0.15 m/s、角速度 0.3 rad/s 走一圈",
                mode="base",
                conversation_id="circle-motion-confirmation",
            ))

        model.assert_not_called()
        self.assertEqual(result["pending_action"]["name"], "drive_robot")
        self.assertNotIn("0.82", result["message"])
        self.assertIn("人工确认", result["message"])
        robot_agent.confirm(result["pending_action"]["id"], False)

    def test_base_circle_parameter_followup_keeps_latest_speed_and_returns_action(self) -> None:
        from app.agent_service import robot_agent
        from app.agent_http_service import agent_chat

        conversation_id = "circle-parameter-followup"
        history = [
            {"role": "user", "content": "让小车画半径1米的圆"},
            {
                "role": "assistant",
                "content": "已记录圆周半径 1 米。请提供线速度，例如 0.15 m/s。",
            },
            {"role": "user", "content": "线速度0.3m/s"},
            {
                "role": "assistant",
                "content": "已识别圆周运动参数：半径 1 米，线速度 0m/s。请只确认运动方向。",
            },
        ]
        self.store.observe(conversation_id, "线速度0.3m/s")
        with (
            patch("app.agent_http_service.conversation_memory", self.store),
            patch.object(robot_agent, "_deepseek_request") as model,
        ):
            result = agent_chat(AgentChatRequest(
                message="顺时针",
                mode="base",
                conversation_id=conversation_id,
                history=history,
            ))

        model.assert_not_called()
        self.assertIsNotNone(result["pending_action"])
        self.assertEqual(result["pending_action"]["name"], "drive_robot")
        self.assertEqual(result["pending_action"]["arguments"]["linear"], 0.3)
        self.assertEqual(result["pending_action"]["arguments"]["angular"], -0.3)
        self.assertIn("确认执行", result["message"])
        self.assertNotIn("设计要求尚未确认", result["message"])
        robot_agent.confirm(result["pending_action"]["id"], False)

    def test_mismatched_base_speed_still_blocks_confirmation_action(self) -> None:
        from app.agent_service import robot_agent
        from app.agent_http_service import _enforce_requirement_confirmation

        pending_action = robot_agent.request_confirmation(
            "drive_robot",
            {"linear": 0.1, "angular": 0.3, "duration_seconds": 20.944},
            mode="base",
        )
        result = _enforce_requirement_confirmation(pending_action, {
            "name": "motion_control",
            "mode": "base",
            "retrieved_memory": {
                "pending_requirements": {"linear_speed_mps": 0.15},
            },
        })

        self.assertIsNone(result["pending_action"])

    def test_full_profile_blocks_action_when_short_command_skips_retrieval(self) -> None:
        from app.agent_service import robot_agent
        from app.agent_http_service import _enforce_requirement_confirmation

        pending_action = robot_agent.request_confirmation(
            "printer_spray",
            {"printer_name": "center", "spraying": True},
            mode="advanced",
        )
        result = _enforce_requirement_confirmation(pending_action, {
            "retrieved_memory": {"enabled": True, "relevant": False},
            "object_memory": {
                "requirement_profile": {"pending": {"ink_color": "白色"}},
            },
        })

        self.assertIsNone(result["pending_action"])
        self.assertTrue(result["requirements_confirmation_required"])

    def test_chat_endpoint_blocks_model_action_until_requirements_confirmed(self) -> None:
        from app.agent_service import robot_agent
        from app.agent_http_service import agent_chat

        self.store.observe("conversation-1", "喷墨改成白色")
        route = {
            "name": "printer_control",
            "tool_family": "printer",
            "context_requirements": [],
        }
        with (
            patch("app.agent_http_service.conversation_memory", self.store),
            patch.object(robot_agent, "resolve_intent", return_value=route),
            patch.object(robot_agent, "knowledge_context", return_value={"matches": []}),
            patch.object(
                robot_agent,
                "chat",
                side_effect=lambda *_args, **_kwargs: robot_agent.request_confirmation(
                    "printer_spray",
                    {"printer_name": "center", "spraying": True},
                    mode="advanced",
                ),
            ),
            patch.object(robot_agent, "enrich_result", side_effect=lambda value, *_: value),
        ):
            result = agent_chat(AgentChatRequest(
                message="开始",
                mode="advanced",
                conversation_id="conversation-1",
            ))

        self.assertIsNone(result["pending_action"])
        self.assertTrue(result["requirements_confirmation_required"])

    def test_confirmed_profile_does_not_block_new_physical_confirmation(self) -> None:
        from app.agent_service import robot_agent
        from app.agent_http_service import _enforce_requirement_confirmation

        self.store.observe("conversation-1", "喷墨改成白色")
        self.store.decide_requirements("conversation-1", True)
        memory = self.store.context("conversation-1")
        pending_action = robot_agent.request_confirmation(
            "printer_spray",
            {"printer_name": "center", "spraying": True},
            mode="advanced",
        )
        result = _enforce_requirement_confirmation(pending_action, {
            "retrieved_memory": {"enabled": True, "relevant": False},
            "object_memory": memory,
        })

        self.assertIsNotNone(result["pending_action"])
        robot_agent.confirm(result["pending_action"]["id"], False)

    def test_chat_endpoint_passes_resolved_object_to_agent(self) -> None:
        from app.agent_service import robot_agent
        from app.agent_http_service import agent_chat

        self.store.remember("conversation-1", "", {"file_name": "court_v003.json"})
        route = {
            "name": "drawing_design",
            "tool_family": "cad",
            "context_requirements": [],
        }
        with (
            patch("app.agent_http_service.conversation_memory", self.store),
            patch.object(robot_agent, "resolve_intent", return_value=route),
            patch.object(robot_agent, "knowledge_context", return_value={"matches": []}),
            patch.object(
                robot_agent,
                "chat",
                return_value={
                    "ok": True,
                    "message": "已找到图纸。",
                    "pending_action": None,
                    "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                },
            ) as chat,
            patch.object(robot_agent, "enrich_result", side_effect=lambda value, *_: value),
        ):
            result = agent_chat(AgentChatRequest(
                message="继续修改这个图纸",
                mode="advanced",
                conversation_id="conversation-1",
            ))

        self.assertTrue(result["ok"])
        self.assertTrue(result["api_attempted"])
        self.assertEqual(result["api_provider"], robot_agent.mode)
        self.assertIn("drawing=court_v003.json", chat.call_args.args[0])
        self.assertEqual(
            route["reference_resolution"]["target"]["id"], "court_v003.json"
        )

    def test_chat_endpoint_injects_retrieved_confirmed_requirements(self) -> None:
        from app.agent_service import robot_agent
        from app.agent_http_service import agent_chat

        self.store.observe("conversation-1", "篮球场线宽 50mm，黄色喷墨")
        self.store.decide_requirements("conversation-1", True)
        route = {
            "name": "drawing_design",
            "tool_family": "cad",
            "context_requirements": [],
        }
        with (
            patch("app.agent_http_service.conversation_memory", self.store),
            patch.object(robot_agent, "resolve_intent", return_value=route),
            patch.object(robot_agent, "knowledge_context", return_value={"matches": []}),
            patch.object(
                robot_agent,
                "chat",
                return_value={
                    "ok": True,
                    "message": "已读取要求。",
                    "pending_action": None,
                    "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                },
            ),
            patch.object(robot_agent, "enrich_result", side_effect=lambda value, *_: value),
        ):
            agent_chat(AgentChatRequest(
                message="按照已确认要求继续优化，其他不变",
                mode="advanced",
                conversation_id="conversation-1",
            ))

        self.assertEqual(
            route["retrieved_memory"]["confirmed_requirements"]["line_width_mm"],
            50.0,
        )

    def test_chat_endpoint_short_confirmation_generates_current_project_candidate(self) -> None:
        from app.agent_service import robot_agent
        from app.creative_projects import CreativeProjectStore
        from app.agent_http_service import agent_chat

        projects = CreativeProjectStore(Path(self.temporary.name) / "confirm-projects.json")
        memory = ConversationMemoryStore(Path(self.temporary.name) / "confirm-memory.json")
        project = projects.create(
            "大圆内接篮球场",
            "规划一个大圆，里面放置一个标准篮球场，四个顶角都在圆上",
            {
                "shape": "basketball",
                "dimensions": {"width_m": 28.0, "height_m": 15.0},
                "quantity": 1,
                "printer": "center",
            },
            {},
            [],
        )
        memory.remember("design-confirmation", "", {
            "ok": True,
            "project_id": project["id"],
            "project": project,
            "message": "确认按标准 28×15 米生成候选方案吗？确认后我再出图。",
        })
        history = [{
            "role": "assistant",
            "content": "确认按标准 28×15 米生成候选方案吗？确认后我再出图。",
        }]

        with (
            patch("app.agent_service.get_creative_project_store", return_value=projects),
            patch("app.agent_http_service.get_creative_project_store", return_value=projects),
            patch("app.agent_http_service.conversation_memory", memory),
            patch.object(robot_agent, "_deepseek_request") as model,
        ):
            result = agent_chat(AgentChatRequest(
                message="确认",
                mode="advanced",
                conversation_id="design-confirmation",
                history=history,
            ))

        model.assert_not_called()
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["preview_paths"])
        self.assertEqual(len(result["variants"]), 1)
        self.assertIn("候选方案已生成", result["message"])
        self.assertNotIn("geometry_count", result["message"])

    def test_ambiguous_reference_skips_model_route_review(self) -> None:
        from app.agent_service import robot_agent
        from app.agent_http_service import agent_chat

        with (
            patch("app.agent_http_service.conversation_memory", self.store),
            patch.object(robot_agent, "resolve_intent") as resolve,
            patch.object(robot_agent, "knowledge_context", return_value={"matches": []}),
            patch.object(robot_agent, "enrich_result", side_effect=lambda value, *_: value),
        ):
            result = agent_chat(AgentChatRequest(
                message="继续修改它",
                mode="advanced",
                conversation_id="empty-conversation",
            ))

        resolve.assert_not_called()
        self.assertIn("请明确", result["message"])
        self.assertIsNone(result["pending_action"])

    def test_stream_chat_returns_terminal_result_when_upstream_fails(self) -> None:
        from app.agent_service import robot_agent
        from app.agent_http_service import agent_chat_stream

        route = {
            "name": "conversation",
            "tool_family": "conversation",
            "context_requirements": [],
        }
        async def collect_events(response) -> list[dict[str, object]]:
            return [
                json.loads(line)
                async for line in response.body_iterator
            ]

        with (
            patch("app.agent_http_service.conversation_memory", self.store),
            patch.object(robot_agent, "mode", "deepseek"),
            patch.object(robot_agent, "api_keys", {"deepseek": "test-key"}),
            patch.object(robot_agent, "resolve_intent", return_value=route),
            patch.object(robot_agent, "knowledge_context", return_value={"matches": []}),
            patch.object(
                robot_agent,
                "chat_stream",
                side_effect=ValueError("upstream payload is invalid"),
            ),
            patch.object(robot_agent, "enrich_result", side_effect=lambda value, *_: value),
        ):
            response = agent_chat_stream(AgentChatRequest(
                message="你好",
                mode="advanced",
                conversation_id="conversation-1",
            ))
            events = asyncio.run(collect_events(response))

        result = next(event for event in events if event.get("type") == "result")
        self.assertFalse(result["ok"])
        self.assertEqual(result["message"], "AI 服务响应中断，请稍后重试。")
        self.assertNotIn("upstream payload", result["message"])

    def test_stream_template_creation_falls_back_to_formal_cad_after_model_error(self) -> None:
        from app.agent_service import robot_agent
        from app.agent_http_service import agent_chat_stream

        route = {
            "name": "drawing_design",
            "operation": "create",
            "tool_family": "cad",
            "context_requirements": [],
        }

        async def collect_events(response) -> list[dict[str, object]]:
            return [json.loads(line) async for line in response.body_iterator]

        with (
            patch("app.agent_http_service.conversation_memory", self.store),
            patch.object(robot_agent, "mode", "deepseek"),
            patch.object(robot_agent, "api_keys", {"deepseek": "test-key"}),
            patch.object(robot_agent, "resolve_intent", return_value=route),
            patch.object(robot_agent, "knowledge_context", return_value={"matches": []}),
            patch.object(
                robot_agent,
                "chat_stream",
                side_effect=ValueError("upstream payload is invalid"),
            ) as model_stream,
            patch.object(robot_agent, "enrich_result", side_effect=lambda value, *_: value),
        ):
            response = agent_chat_stream(AgentChatRequest(
                message="规划两个标准篮球场",
                mode="advanced",
                conversation_id="new-conversation",
            ))
            events = asyncio.run(collect_events(response))

        result = next(event for event in events if event.get("type") == "result")
        self.assertTrue(result["ok"])
        self.assertTrue(result["degraded"])
        self.assertIn("候选", result["message"])
        self.assertNotIn("AI 服务响应中断", result["message"])
        model_stream.assert_called_once()

    def test_stream_chat_navigation_bypasses_model(self) -> None:
        from app.agent_service import robot_agent
        from app.agent_http_service import agent_chat_stream

        async def collect_events(response) -> list[dict[str, object]]:
            return [json.loads(line) async for line in response.body_iterator]

        navigation_result = {
            "ok": True,
            "message": "已撤销候选修改，当前回到：原始方案。",
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            "pending_action": None,
            "api_attempted": False,
            "api_provider": None,
            "project_id": "project-1",
            "cad_history_navigation": {
                "action": "undo",
                "from_variant_id": "variant-2",
                "to_variant_id": "variant-1",
                "redo_available": True,
            },
        }
        with (
            patch("app.agent_http_service.conversation_memory", self.store),
            patch("app.agent_http_service._navigate_cad_candidate", return_value=navigation_result),
            patch.object(robot_agent, "resolve_intent") as resolve_intent,
            patch.object(robot_agent, "chat_stream") as chat_stream,
        ):
            response = agent_chat_stream(AgentChatRequest(
                message="撤销刚才的修改",
                mode="advanced",
                conversation_id="stream-navigation",
            ))
            events = asyncio.run(collect_events(response))

        resolve_intent.assert_not_called()
        chat_stream.assert_not_called()
        self.assertEqual([event["type"] for event in events], ["context", "result"])
        self.assertTrue(events[-1]["ok"])
        self.assertEqual(
            events[-1]["cad_history_navigation"]["to_variant_id"],
            "variant-1",
        )

    def test_base_motion_followup_uses_durable_memory_when_history_is_empty(self) -> None:
        from app.agent_http_service import agent_chat

        conversation_id = "durable-circle-demo"
        with patch("app.agent_http_service.conversation_memory", self.store):
            first = agent_chat(AgentChatRequest(
                message="生成一个半径1米的圆",
                mode="base",
                conversation_id=conversation_id,
            ))
            second = agent_chat(AgentChatRequest(
                message="只进行运动演示",
                mode="base",
                conversation_id=conversation_id,
                history=[],
            ))

        self.assertIn("半径 1 米", first["message"])
        self.assertIn("半径 1 米", second["message"])
        self.assertIn("线速度", second["message"])
        self.assertNotIn("设备和具体动作", second["message"])


if __name__ == "__main__":
    unittest.main()
