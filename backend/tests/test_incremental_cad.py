from __future__ import annotations

import tempfile
import unittest
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from app.agent_service import robot_agent
from app.creative_projects import CreativeProjectStore
from app.incremental_cad import (
    add_symmetric_rectangles_on_circle,
    edit_candidate_geometries,
    parse_constrained_addition,
    parse_incremental_edit,
    resolve_incremental_correction,
    resolve_incremental_followup,
    space_two_instances,
)
from app.cad_edit_contract import build_cad_edit_contract
from app.cad_edit_chain import replay_cad_edit_chain
from app.agent_skills import drawing_template_geometries, score_design_variant
from app.drawing_store import preview_paths


class IncrementalCadTest(unittest.TestCase):
    def test_whole_domain_object_is_parsed_as_a_complete_target(self) -> None:
        edit = parse_incremental_edit("整个篮球场扩大一倍")

        self.assertIsNotNone(edit)
        self.assertEqual(edit["operation"], "scale")
        self.assertEqual(edit["factor"], 2.0)
        self.assertEqual(edit["instances"], "all")

    def test_diagonal_translation_parser_keeps_both_axes(self) -> None:
        edit = parse_incremental_edit("第2个图形向右移动2米并向上移动500毫米")

        self.assertIsNotNone(edit)
        self.assertEqual(edit["operation"], "translate")
        self.assertEqual(edit["instance"], 2)
        self.assertEqual(edit["dx_mm"], 2000.0)
        self.assertEqual(edit["dy_mm"], 500.0)

        source = drawing_template_geometries({
            "template": "room", "width_m": 5, "height_m": 3, "quantity": 2,
        })
        changed, error = edit_candidate_geometries(source, edit)
        self.assertIsNone(error)
        self.assertEqual(
            min(point["x"] for point in changed[1]["vertices"])
            - min(point["x"] for point in source[1]["vertices"]),
            2000,
        )
        self.assertEqual(
            min(point["y"] for point in changed[1]["vertices"])
            - min(point["y"] for point in source[1]["vertices"]),
            500,
        )

    def test_diagonal_translation_reply_preserves_both_axes(self) -> None:
        reply = robot_agent._cad_target_reply(
            {"operation": "translate", "dx_mm": 2000, "dy_mm": 500}, 2,
        )

        self.assertEqual(reply, "第2个图形向右移动2000毫米并向上移动500毫米")

    def test_chat_chain_preserves_pronoun_semantic_target_in_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "两个篮球场", "两个标准篮球场",
                {
                    "shape": "basketball", "quantity": 2,
                    "dimensions": {"width_m": 28, "height_m": 15},
                    "printer": "center",
                },
                {},
                [],
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                initial = robot_agent.generate_project_candidate(project["id"])
                parent = initial.get("variant") or initial["variants"][0]
                store.begin_design_iteration(project["id"], parent["id"])
                message = (
                    "先把第二个篮球场向右移动2米，"
                    "然后把它的中心圆扩大一倍"
                )
                route = robot_agent.resolve_intent(message, "advanced", [])
                route["object_memory"] = {
                    "objects": {"project": [{"id": project["id"]}]}
                }
                result = robot_agent.chat(
                    message, [], mode="advanced", route=route
                )

        self.assertEqual(route["decision_source"], "incremental_cad_edit_chain")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["edit_preview"]["schema"], "cad.edit-preview.v1")
        self.assertEqual(
            result["edit_preview"]["candidate"]["geometry_sha256"],
            result["variant"]["edit_preview"]["candidate"]["geometry_sha256"],
        )
        self.assertTrue(result["variant"]["edit_preview"]["execution"]["persisted"])
        self.assertFalse(
            result["variant"]["edit_preview"]["execution"]["execution_allowed"]
        )
        self.assertTrue(result["machine_assertions"]["verified"])
        self.assertTrue(result["variant"]["machine_assertions"]["verified"])
        self.assertEqual(
            result["variant"]["machine_assertions"]["failure_codes"], []
        )
        steps = result["cad_edit_contract"]["chain_steps"]
        self.assertEqual(
            steps[1]["parameters"]["selector"],
            {"kind": "semantic_within_target", "semantic": "中心圆"},
        )
        before = {item["id"]: item for item in parent["geometries"]}
        after = {item["id"]: item for item in result["variant"]["geometries"]}
        target_circle = next(
            item for item in parent["geometries"]
            if item.get("template_instance") == 2 and item.get("type") == "circle"
        )
        circle_after = after[target_circle["id"]]
        self.assertEqual(
            circle_after["center"]["x"] - target_circle["center"]["x"],
            2000.0,
        )
        self.assertEqual(circle_after["radius"], target_circle["radius"] * 2)
        translated_only, error = edit_candidate_geometries(
            parent["geometries"],
            {
                "operation": "translate", "instance": 2,
                "dx_mm": 2000.0, "dy_mm": 0.0,
            },
        )
        self.assertIsNone(error)
        translated_by_id = {item["id"]: item for item in translated_only or []}
        for geometry_id, geometry in before.items():
            if geometry.get("template_instance") == 1:
                self.assertEqual(after[geometry_id], geometry)
            elif geometry_id != target_circle["id"]:
                self.assertEqual(after[geometry_id], translated_by_id[geometry_id])
        replay = result["chain_replay"]
        self.assertTrue(all(
            item["verification"]["verified"] for item in replay
        ))
        self.assertEqual(
            replay[1]["modified_geometry_ids"], [target_circle["id"]]
        )

    def test_chat_applies_multi_target_chain_without_touching_other_instances(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "三个篮球场", "三个标准篮球场",
                {
                    "shape": "basketball", "quantity": 3,
                    "dimensions": {"width_m": 28, "height_m": 15},
                    "printer": "center",
                },
                {},
                [],
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                initial = robot_agent.generate_project_candidate(project["id"])
                parent = initial.get("variant") or initial["variants"][0]
                store.begin_design_iteration(project["id"], parent["id"])
                message = (
                    "先把第二个图形向右移动2米，"
                    "然后把第一个图形逆时针旋转90度"
                )
                route = robot_agent.resolve_intent(message, "advanced", [])
                route["object_memory"] = {
                    "objects": {"project": [{"id": project["id"]}]}
                }
                result = robot_agent.chat(
                    message, [], mode="advanced", route=route
                )
                updated = store.get(project["id"])

        self.assertEqual(route["decision_source"], "incremental_cad_edit_chain")
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(updated["variants"]), 2)
        self.assertEqual(
            result["cad_edit_contract"]["target"]["instance_ids"], [1, 2]
        )
        before = {item["id"]: item for item in parent["geometries"]}
        after = {item["id"]: item for item in result["variant"]["geometries"]}
        changed_instances = {
            int(before[geometry_id]["template_instance"])
            for geometry_id in before
            if before[geometry_id] != after[geometry_id]
        }
        self.assertEqual(changed_instances, {1, 2})
        for geometry_id, geometry in before.items():
            if geometry.get("template_instance") == 3:
                self.assertEqual(after[geometry_id], geometry)
        self.assertTrue(
            result["variant"]["edit_plan"]["verification"]["verified"]
        )

    def test_chat_applies_ordered_edit_chain_as_one_verified_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "两个篮球场", "两个标准篮球场",
                {
                    "shape": "basketball", "quantity": 2,
                    "dimensions": {"width_m": 28, "height_m": 15},
                    "printer": "center",
                },
                {},
                [],
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                initial = robot_agent.generate_project_candidate(project["id"])
                parent = initial.get("variant") or initial["variants"][0]
                store.begin_design_iteration(project["id"], parent["id"])
                message = "先把第二个图形向右移动2米，然后逆时针旋转90度"
                route = robot_agent.resolve_intent(message, "advanced", [])
                route["object_memory"] = {
                    "objects": {"project": [{"id": project["id"]}]}
                }
                result = robot_agent.chat(
                    message, [], mode="advanced", route=route
                )
                updated = store.get(project["id"])

        self.assertEqual(route["decision_source"], "incremental_cad_edit_chain")
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(updated["variants"]), 2)
        self.assertEqual(result["edit_chain"]["step_count"], 2)
        self.assertEqual(len(result["chain_replay"]), 2)
        expected, error, _ = replay_cad_edit_chain(
            parent["geometries"], result["cad_edit_contract"]
        )
        self.assertIsNone(error)
        self.assertEqual(result["variant"]["geometries"], expected)
        before = {item["id"]: item for item in parent["geometries"]}
        after = {item["id"]: item for item in result["variant"]["geometries"]}
        for geometry_id, geometry in before.items():
            if geometry.get("template_instance") == 1:
                self.assertEqual(after[geometry_id], geometry)
        plan = result["variant"]["edit_plan"]
        self.assertEqual(plan["operation"], "chain")
        self.assertEqual(len(plan["steps"]), 2)
        self.assertTrue(all(
            step["verification"]["verified"] for step in plan["steps"]
        ))
        self.assertTrue(plan["verification"]["verified"], plan)

    def test_chat_edit_chain_ambiguous_target_returns_candidate_card(self) -> None:
        # 复合修改链中任一步目标歧义时，必须返回结构化候选卡片
        # （target_clarification + 候选选项 + 预览路径 + 可点击回复），
        # 不能只返回文字提示。覆盖 _apply_incremental_candidate_chain 的澄清出口。
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "两个并排房间", "两个并排房间",
                {"shape": "room", "quantity": 2,
                 "arrangement": "short_side_adjacent",
                 "dimensions": {"width_m": 5, "height_m": 3}}, {}, [],
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                initial = robot_agent.generate_project_candidate(project["id"])
                parent = initial.get("variant") or initial["variants"][0]
                store.begin_design_iteration(project["id"], parent["id"])
                message = "把最上方的图形向右移动2米"
                route = robot_agent.resolve_intent(message, "advanced", [])
                route["decision_source"] = "incremental_cad_edit_chain"
                route["edit_chain"] = [parse_incremental_edit(message)]
                route["object_memory"] = {
                    "objects": {"project": [{"id": project["id"]}]}
                }
                result = robot_agent.chat(
                    message, [], mode="advanced", route=route,
                )
        self.assertEqual(route["decision_source"], "incremental_cad_edit_chain")
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["clarification_required"])
        self.assertEqual(
            result["target_clarification"]["schema"],
            "cad.target-clarification.v1",
        )
        self.assertGreaterEqual(
            len(result["target_clarification"]["options"]), 2
        )
        self.assertTrue(all(
            item.get("reply") for item in result["target_clarification"]["options"]
        ))
        self.assertTrue(result["preview_paths"])
        self.assertEqual(
            result["preview_paths"],
            result["target_clarification"]["preview_paths"],
        )

    def test_high_risk_edit_chain_waits_for_confirmation_and_saves_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "两个篮球场", "两个标准篮球场",
                {
                    "shape": "basketball", "quantity": 2,
                    "dimensions": {"width_m": 28, "height_m": 15},
                    "printer": "center",
                },
                {},
                [],
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                initial = robot_agent.generate_project_candidate(project["id"])
                parent = initial.get("variant") or initial["variants"][0]
                store.begin_design_iteration(project["id"], parent["id"])
                message = "先把第二个图形向右移动12米，然后逆时针旋转90度"
                route = robot_agent.resolve_intent(message, "advanced", [])
                route["object_memory"] = {
                    "objects": {"project": [{"id": project["id"]}]}
                }
                pending = robot_agent.chat(
                    message, [], mode="advanced", route=route
                )
                before_confirm = store.get(project["id"])
                action_id = pending["pending_action"]["id"]
                confirmed = robot_agent.confirm(action_id, True)
                after_confirm = store.get(project["id"])
                replay = robot_agent.confirm(action_id, True)

        self.assertEqual(route["decision_source"], "incremental_cad_edit_chain")
        self.assertTrue(pending["ok"], pending)
        self.assertEqual(pending["next_action"], "confirm_cad_edit")
        self.assertTrue(pending["cad_preflight"]["requires_confirmation"])
        self.assertEqual(pending["edit_preview"]["schema"], "cad.edit-preview.v1")
        self.assertFalse(pending["edit_preview"]["execution"]["persisted"])
        self.assertEqual(len(before_confirm["variants"]), 1)
        self.assertTrue(confirmed["ok"], confirmed)
        self.assertTrue(confirmed["confirmed_high_risk_edit"])
        self.assertTrue(confirmed["preview_validation"]["verified"])
        self.assertTrue(confirmed["variant"]["edit_preview"]["execution"]["persisted"])
        self.assertEqual(confirmed["edit_chain"]["step_count"], 2)
        self.assertEqual(len(confirmed["chain_replay"]), 2)
        self.assertEqual(len(after_confirm["variants"]), 2)
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(len(store.get(project["id"])["variants"]), 2)

    def test_constrained_rectangle_parser_and_solver_verify_circle_contacts(self) -> None:
        source = drawing_template_geometries({"template": "basketball"})
        source.append({
            "id": 4,
            "type": "circle",
            "layer_id": 1,
            "center": {"x": 0.0, "y": 0.0, "z": 0.0},
            "radius": 15882.380,
            "template_instance": 1,
            "template_type": "basketball",
        })
        request = "在篮球场上下方各放一个大小合适的矩形，每个矩形与篮球场相连，并且有两个顶点在圆上"

        parsed = parse_constrained_addition(request)
        solved = add_symmetric_rectangles_on_circle(source)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["operation"], "add_constrained")
        self.assertTrue(solved["ok"], solved)
        self.assertEqual(solved["validation"]["added_rectangle_count"], 2)
        self.assertTrue(solved["validation"]["outer_vertices_on_circle"])
        self.assertTrue(solved["validation"]["attached_to_target"])
        self.assertGreater(solved["width_mm"], 0)
        self.assertGreater(solved["height_mm"], 0)
        self.assertEqual(len(solved["geometries"]), len(source) + 2)

    def test_chat_adds_verified_symmetric_rectangles_as_new_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "大圆内接篮球场",
                "生成一个大圆内接标准篮球场",
                {
                    "shape": "basketball",
                    "quantity": 1,
                    "dimensions": {"width_m": 28.0, "height_m": 15.0},
                    "printer": "center",
                },
                {},
                [],
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                initial = robot_agent.generate_project_candidate(project["id"])
                parent = initial.get("variant") or initial["variants"][0]
                store.begin_design_iteration(project["id"], parent["id"])
                message = (
                    "在篮球场的上下方各放置一个大小合适的矩形，"
                    "每个矩形与篮球场相连，并且有两个顶点在圆上"
                )
                route = robot_agent.resolve_intent(message, "advanced", [])
                route["object_memory"] = {
                    "objects": {"project": [{"id": project["id"]}]}
                }
                result = robot_agent.chat(
                    message, [], mode="advanced", route=route
                )
                updated = store.get(project["id"])

        self.assertEqual(route["decision_source"], "constrained_cad_addition")
        self.assertEqual(route["edit_intent"]["schema"], "cad.edit-intent.v1")
        self.assertEqual(route["edit_intent"]["missing_parameters"], [])
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["constraint_validation"]["verified"])
        self.assertEqual(len(updated["variants"]), 2)
        latest = updated["variants"][-1]
        self.assertEqual(len(latest["geometries"]), len(parent["geometries"]) + 2)
        created = {
            item["object_id"] for item in latest["logical_objects"]
            if item["object_type"] == "rectangle"
        }
        self.assertEqual(
            created,
            {"constrained-rectangle-top", "constrained-rectangle-bottom"},
        )
        self.assertEqual(
            latest["revision_contract"]["status"], "verified"
        )
        self.assertEqual(latest["edit_plan"]["schema"], "cad.edit-plan.v1")
        self.assertTrue(latest["edit_plan"]["verification"]["verified"])
        self.assertEqual(
            latest["edit_plan"]["constraints"],
            result["edit_intent"]["constraints"],
        )
        self.assertEqual(
            latest["edit_plan"]["auto_decisions"],
            result["edit_intent"]["auto_decisions"],
        )
        self.assertTrue(result["preview_paths"])

    def test_dimension_delegation_followup_restores_previous_constraints(self) -> None:
        history = [
            {
                "role": "user",
                "content": "在篮球场上下方放置矩形，要求矩形的两个端点都在圆上",
            },
            {
                "role": "assistant",
                "content": "请确认矩形高度。",
            },
        ]
        message = "矩形高度由你判断，每个矩形与篮球场相连，并且有两个顶点在圆上"

        route = robot_agent.resolve_intent(message, "advanced", history)

        self.assertEqual(route["decision_source"], "constrained_cad_addition")
        self.assertEqual(route["constraint_edit"]["dimension_mode"], "maximize_area")
        self.assertEqual(route["edit_intent"]["source_text"], route["resolved_message"])
        self.assertIn("上下方放置矩形", route["resolved_message"])

    def test_natural_language_correction_rewrites_safe_previous_edit(self) -> None:
        translated = {
            "operation": "translate", "target_instance_id": 2,
            "parameters": {"dx_mm": 2000, "dy_mm": 0},
        }
        self.assertEqual(
            resolve_incremental_correction(
                "不是向右2米，是向左1米", translated, [1, 2]
            ),
            "第2个图形向左移动1000毫米",
        )
        rotated = {
            "operation": "rotate", "target_instance_ids": [1, 3],
            "parameters": {"angle_degrees": 30, "pivot": "group_center"},
        }
        self.assertEqual(
            resolve_incremental_correction(
                "不是逆时针30度，应该是顺时针45度", rotated, [1, 2, 3]
            ),
            "第1个图形、第3个图形作为整体绕组合中心顺时针旋转45度",
        )
        scaled = {
            "operation": "scale", "target_instance_ids": [1, 2],
            "parameters": {"factor": 2, "pivot": "each_instance_center"},
        }
        self.assertEqual(
            resolve_incremental_correction(
                "不是2倍，改成缩放到1.5倍", scaled, [1, 2]
            ),
            "第1个图形、第2个图形分别以各自中心等比例缩放到1.5倍",
        )
        deleted = {
            "operation": "delete", "target_instance_ids": [1, 3],
            "parameters": {},
        }
        self.assertIsNone(resolve_incremental_correction(
            "不是删除第1和第3个，改成第2个", deleted, [1, 2, 3]
        ))

    def test_pronoun_and_distance_followups_use_structured_command(self) -> None:
        previous = {
            "schema": "cad.instance_edit.v1",
            "operation": "translate",
            "target_instance_id": 2,
            "parameters": {"dx_mm": 2000, "dy_mm": 0},
        }
        self.assertEqual(
            resolve_incremental_followup("把它向左移动1米", previous),
            "第2个图形向左移动1米",
        )
        self.assertEqual(
            resolve_incremental_followup("再向右移动同样距离", previous),
            "第2个图形向右移动2000毫米",
        )
        self.assertIsNone(resolve_incremental_followup("让小车向右移动", previous))
        self.assertEqual(
            resolve_incremental_followup("刚才那个逆时针旋转30度", previous),
            "第2个图形逆时针旋转30度",
        )
        rotated = {
            **previous,
            "operation": "rotate",
            "parameters": {"angle_degrees": -45},
        }
        self.assertEqual(
            resolve_incremental_followup("再旋转同样角度", rotated),
            "第2个图形顺时针旋转45度",
        )

    def test_repeat_previous_only_replays_safe_deterministic_edit(self) -> None:
        translated = {
            "operation": "translate",
            "target_instance_id": 2,
            "parameters": {"dx_mm": -1500, "dy_mm": 0},
        }
        self.assertEqual(
            resolve_incremental_followup("再来一次", translated),
            "第2个图形向左移动1500毫米",
        )
        resized = {
            "operation": "resize",
            "target_instance_id": 1,
            "parameters": {"dimension": "高度", "value_mm": 3200},
        }
        self.assertEqual(
            resolve_incremental_followup("重复刚才的操作", resized),
            "第1个图形高度改为3200毫米",
        )
        deleted = {
            "operation": "delete",
            "target_instance_id": 1,
            "parameters": {},
        }
        self.assertIsNone(resolve_incremental_followup("再来一次", deleted))
        self.assertIsNone(resolve_incremental_followup("让小车再来一次", translated))

    def test_copied_instance_reference_uses_created_stable_id(self) -> None:
        copied = {
            "operation": "duplicate",
            "target_instance_id": 2,
            "created_instance_id": 5,
            "parameters": {"direction": "右", "distance_mm": 2000},
        }
        self.assertEqual(
            resolve_incremental_followup("把刚才复制的那个向上移动1米", copied),
            "第5个图形向上移动1米",
        )
        self.assertIsNone(resolve_incremental_followup(
            "把刚才复制的那个向上移动1米",
            {**copied, "operation": "translate"},
        ))

    def test_other_instance_reference_requires_one_real_candidate(self) -> None:
        previous = {
            "operation": "translate",
            "target_instance_id": 2,
            "parameters": {"dx_mm": 2000, "dy_mm": 0},
        }
        self.assertEqual(
            resolve_incremental_followup(
                "把另一个图形向左移动1米", previous, [1, 2]
            ),
            "第1个图形向左移动1米",
        )
        self.assertEqual(
            resolve_incremental_followup(
                "把剩余图形向上移动50厘米", previous, [2, 5]
            ),
            "第5个图形向上移动50厘米",
        )
        self.assertIsNone(resolve_incremental_followup(
            "把另一个图形向左移动1米", previous, [1, 2, 3]
        ))
        self.assertIsNone(resolve_incremental_followup(
            "把另一个图形向左移动1米", previous, [2]
        ))

    def test_remaining_instances_can_be_translated_as_verified_batch(self) -> None:
        previous = {
            "operation": "translate",
            "target_instance_id": 1,
            "parameters": {"dx_mm": 1000, "dy_mm": 0},
        }
        resolved = resolve_incremental_followup(
            "把剩余三个图形整体向右移动1米", previous, [1, 2, 3, 4]
        )
        self.assertEqual(
            resolved,
            "第2个图形、第3个图形、第4个图形向右移动1米",
        )
        edit = parse_incremental_edit(resolved)
        self.assertEqual(edit["instances"], [2, 3, 4])
        source = drawing_template_geometries({
            "template": "room", "width_m": 5, "height_m": 3,
            "quantity": 4, "spacing_m": 2,
        })
        result, error = edit_candidate_geometries(source, edit)
        self.assertIsNone(error)
        self.assertEqual(result[0], source[0])
        for index in (1, 2, 3):
            self.assertEqual(
                result[index]["vertices"][0]["x"]
                - source[index]["vertices"][0]["x"],
                1000,
            )

        repeated = {
            "operation": "translate",
            "target_instance_ids": [2, 3, 4],
            "parameters": {"dx_mm": 1000, "dy_mm": 0},
        }
        self.assertEqual(
            resolve_incremental_followup("再来一次", repeated, [1, 2, 3, 4]),
            "第2个图形、第3个图形、第4个图形向右移动1000毫米",
        )

    def test_remaining_batch_rejects_count_mismatch_and_ambiguous_rotation(self) -> None:
        previous = {
            "operation": "translate",
            "target_instance_id": 1,
            "parameters": {"dx_mm": 1000, "dy_mm": 0},
        }
        self.assertIsNone(resolve_incremental_followup(
            "把剩余两个图形整体向右移动1米", previous, [1, 2, 3, 4]
        ))
        resolved = resolve_incremental_followup(
            "把剩余三个图形整体旋转30度", previous, [1, 2, 3, 4]
        )
        self.assertIsNone(resolved)
        source = drawing_template_geometries({
            "template": "room", "width_m": 5, "height_m": 3,
            "quantity": 3, "spacing_m": 2,
        })
        rotated, error = edit_candidate_geometries(
            source,
            parse_incremental_edit("把第1个图形和第3个图形一起逆时针旋转30度"),
        )
        self.assertIsNone(rotated)
        self.assertIn("必须明确选择各自中心或组合中心", error)

    def test_batch_rotation_supports_each_and_group_centers(self) -> None:
        source = drawing_template_geometries({
            "template": "room", "width_m": 5, "height_m": 3,
            "quantity": 3, "spacing_m": 2,
        })

        def center(item: dict[str, object]) -> tuple[float, float]:
            vertices = item["vertices"]
            xs = [float(point["x"]) for point in vertices]
            ys = [float(point["y"]) for point in vertices]
            return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2

        each_edit = parse_incremental_edit(
            "让第1个图形和第3个图形分别绕各自中心逆时针旋转90度"
        )
        self.assertEqual(each_edit["pivot"], "each_instance_center")
        each, error = edit_candidate_geometries(source, each_edit)
        self.assertIsNone(error)
        self.assertEqual(each[1], source[1])
        self.assertEqual(center(each[0]), center(source[0]))
        self.assertEqual(center(each[2]), center(source[2]))

        group_edit = parse_incremental_edit(
            "让第1个图形和第3个图形作为整体绕组合中心逆时针旋转90度"
        )
        self.assertEqual(group_edit["pivot"], "group_center")
        grouped, error = edit_candidate_geometries(source, group_edit)
        self.assertIsNone(error)
        self.assertEqual(grouped[1], source[1])
        self.assertNotEqual(center(grouped[0]), center(source[0]))
        self.assertNotEqual(center(grouped[2]), center(source[2]))

        repeated = {
            "operation": "rotate",
            "target_instance_ids": [1, 3],
            "parameters": {"angle_degrees": 90, "pivot": "group_center"},
        }
        self.assertEqual(
            resolve_incremental_followup("再来一次", repeated, [1, 2, 3]),
            "第1个图形、第3个图形作为整体绕组合中心逆时针旋转90度",
        )

    def test_remaining_instances_preserve_explicit_batch_rotation_pivot(self) -> None:
        previous = {
            "operation": "translate",
            "target_instance_id": 1,
            "parameters": {"dx_mm": 1000, "dy_mm": 0},
        }
        each = resolve_incremental_followup(
            "把剩余三个图形分别绕各自中心逆时针旋转30度",
            previous,
            [1, 2, 3, 4],
        )
        self.assertEqual(
            each,
            "第2个图形、第3个图形、第4个图形分别绕各自中心逆时针旋转30度",
        )
        self.assertEqual(
            parse_incremental_edit(each)["pivot"], "each_instance_center"
        )
        grouped = resolve_incremental_followup(
            "把其余三个图形作为整体绕组合中心顺时针旋转45度",
            previous,
            [1, 2, 3, 4],
        )
        self.assertEqual(
            grouped,
            "第2个图形、第3个图形、第4个图形作为整体绕组合中心顺时针旋转45度",
        )
        self.assertEqual(parse_incremental_edit(grouped)["pivot"], "group_center")

    def test_batch_scale_supports_each_and_group_centers(self) -> None:
        source = drawing_template_geometries({
            "template": "room", "width_m": 5, "height_m": 3,
            "quantity": 3, "spacing_m": 2,
        })

        def bounds(item: dict[str, object]) -> tuple[float, float, float, float]:
            vertices = item["vertices"]
            xs = [float(point["x"]) for point in vertices]
            ys = [float(point["y"]) for point in vertices]
            return min(xs), min(ys), max(xs), max(ys)

        each_edit = parse_incremental_edit(
            "把第1个图形和第3个图形分别以各自中心等比例放大到2倍"
        )
        self.assertEqual(each_edit["operation"], "scale")
        self.assertEqual(each_edit["pivot"], "each_instance_center")
        each, error = edit_candidate_geometries(source, each_edit)
        self.assertIsNone(error)
        self.assertEqual(each[1], source[1])
        for index in (0, 2):
            before = bounds(source[index])
            after = bounds(each[index])
            self.assertEqual(after[2] - after[0], (before[2] - before[0]) * 2)
            self.assertEqual(after[3] - after[1], (before[3] - before[1]) * 2)
            self.assertEqual(after[0] + after[2], before[0] + before[2])
            self.assertEqual(after[1] + after[3], before[1] + before[3])

        group_edit = parse_incremental_edit(
            "把第1个图形和第3个图形以组合中心整体缩放到2倍"
        )
        self.assertEqual(group_edit["pivot"], "group_center")
        grouped, error = edit_candidate_geometries(source, group_edit)
        self.assertIsNone(error)
        self.assertEqual(grouped[1], source[1])
        for index in (0, 2):
            grouped_bounds = bounds(grouped[index])
            each_bounds = bounds(each[index])
            grouped_center = (
                grouped_bounds[0] + grouped_bounds[2],
                grouped_bounds[1] + grouped_bounds[3],
            )
            each_center = (
                each_bounds[0] + each_bounds[2],
                each_bounds[1] + each_bounds[3],
            )
            self.assertNotEqual(grouped_center, each_center)

    def test_batch_scale_scales_curves_repeats_and_rejects_ambiguity(self) -> None:
        source = drawing_template_geometries({
            "template": "basketball", "width_m": 28, "height_m": 15,
            "quantity": 2, "spacing_m": 2,
        })
        ambiguous = parse_incremental_edit(
            "把第1个图形和第2个图形等比例放大到2倍"
        )
        result, error = edit_candidate_geometries(source, ambiguous)
        self.assertIsNone(result)
        self.assertIn("必须明确选择各自中心或组合中心", error)

        edit = parse_incremental_edit(
            "把第1个图形和第2个图形分别以各自中心等比例缩小一半"
        )
        result, error = edit_candidate_geometries(source, edit)
        self.assertIsNone(error)
        before_curve = next(
            item for item in source if item.get("type") in {"circle", "arc"}
        )
        after_curve = next(
            item for item in result if item.get("id") == before_curve.get("id")
        )
        self.assertEqual(after_curve["radius"], before_curve["radius"] * 0.5)

        repeated = {
            "operation": "scale",
            "target_instance_ids": [1, 2],
            "parameters": {"factor": 0.5, "pivot": "each_instance_center"},
        }
        self.assertEqual(
            resolve_incremental_followup("再来一次", repeated, [1, 2]),
            "第1个图形、第2个图形分别以各自中心等比例缩放到0.5倍",
        )
        invalid = {
            "operation": "scale", "instances": [1, 2],
            "factor": 100, "pivot": "group_center",
        }
        result, error = edit_candidate_geometries(source, invalid)
        self.assertIsNone(result)
        self.assertIn("0.05 到 20", error)

    def test_remaining_instances_can_be_scaled_with_explicit_center(self) -> None:
        previous = {
            "operation": "translate",
            "target_instance_id": 1,
            "parameters": {"dx_mm": 1000, "dy_mm": 0},
        }
        resolved = resolve_incremental_followup(
            "把剩余三个图形以组合中心整体缩放到150%",
            previous,
            [1, 2, 3, 4],
        )
        self.assertEqual(
            resolved,
            "第2个图形、第3个图形、第4个图形以组合中心整体缩放到1.5倍",
        )
        parsed = parse_incremental_edit(resolved)
        self.assertEqual(parsed["factor"], 1.5)
        self.assertEqual(parsed["pivot"], "group_center")

    def test_scale_updates_ellipse_axis_and_text_height(self) -> None:
        source = [
            {
                "id": 1, "type": "ellipse", "template_instance": 1,
                "center": {"x": 0, "y": 0},
                "major_axis": {"x": 1000, "y": 0}, "ratio": 0.5,
            },
            {
                "id": 2, "type": "text", "template_instance": 1,
                "position": {"x": 500, "y": 0}, "height": 200,
            },
            {
                "id": 3, "type": "ellipse", "template_instance": 2,
                "center": {"x": 5000, "y": 0},
                "major_axis": {"x": 1000, "y": 0}, "ratio": 0.5,
            },
        ]
        edit = parse_incremental_edit(
            "把第1个图形和第2个图形分别以各自中心等比例缩放到2倍"
        )
        result, error = edit_candidate_geometries(source, edit)
        self.assertIsNone(error)
        self.assertEqual(result[0]["major_axis"]["x"], 2000)
        self.assertEqual(result[1]["height"], 400)
        self.assertEqual(result[2]["major_axis"]["x"], 2000)

    def test_batch_delete_and_retain_are_atomic(self) -> None:
        source = drawing_template_geometries({
            "template": "room", "width_m": 5, "height_m": 3,
            "quantity": 4, "spacing_m": 2,
        })
        deleted_edit = parse_incremental_edit("删除第1、3个图形")
        self.assertEqual(deleted_edit["instances"], [1, 3])
        deleted, error = edit_candidate_geometries(source, deleted_edit)
        self.assertIsNone(error)
        self.assertEqual(
            {item["template_instance"] for item in deleted}, {2, 4}
        )
        self.assertEqual(
            deleted,
            [item for item in source if item["template_instance"] in {2, 4}],
        )

        retained_edit = parse_incremental_edit("只保留第2和第4个图形")
        self.assertEqual(retained_edit["instances"], [2, 4])
        retained, error = edit_candidate_geometries(source, retained_edit)
        self.assertIsNone(error)
        self.assertEqual(retained, deleted)

        generic_delete = parse_incremental_edit(
            "删除其他图形，只保留第2和第4个图形"
        )
        self.assertEqual(generic_delete["operation"], "retain")
        self.assertEqual(generic_delete["instances"], [2, 4])
        retained_from_combined, error = edit_candidate_geometries(
            source, generic_delete
        )
        self.assertIsNone(error)
        self.assertEqual(retained_from_combined, deleted)

        separate_clauses = parse_incremental_edit(
            "删除第1和第3个图形，只保留第2个图形"
        )
        self.assertEqual(separate_clauses["operation"], "delete")
        self.assertEqual(separate_clauses["instances"], [1, 3])
        separated, error = edit_candidate_geometries(source, separate_clauses)
        self.assertIsNone(error)
        self.assertEqual(
            {item["template_instance"] for item in separated}, {2, 4}
        )

        remove_all, error = edit_candidate_geometries(source, {
            "operation": "delete", "instances": [1, 2, 3, 4],
        })
        self.assertIsNone(remove_all)
        self.assertIn("至少需要保留一个实例", error)

        missing, error = edit_candidate_geometries(source, {
            "operation": "delete", "instances": [1, 9],
        })
        self.assertIsNone(missing)
        self.assertIn("必须真实存在", error)

    def test_translate_one_instance_does_not_touch_another(self) -> None:
        source = drawing_template_geometries({
            "template": "basketball", "width_m": 28, "height_m": 15, "quantity": 2,
            "spacing_m": 2,
        })
        edit = parse_incremental_edit("把第二个篮球场向右移动2米")
        self.assertEqual(edit["instance"], 2)
        result, error = edit_candidate_geometries(source, edit)
        self.assertIsNone(error)
        self.assertEqual(result[:19], source[:19])
        self.assertEqual(result[19]["vertices"][0]["x"] - source[19]["vertices"][0]["x"], 2000)
        self.assertEqual(result[21]["center"]["x"] - source[21]["center"]["x"], 2000)

    def test_resize_only_selected_simple_instance(self) -> None:
        source = drawing_template_geometries({
            "template": "room", "width_m": 5, "height_m": 3, "quantity": 2,
        })
        edit = parse_incremental_edit("把第二个图形宽度改为6米")
        result, error = edit_candidate_geometries(source, edit)
        self.assertIsNone(error)
        self.assertEqual(result[0], source[0])
        xs = [p["x"] for p in result[1]["vertices"]]
        self.assertEqual(max(xs) - min(xs), 6000)
        self.assertEqual(source[1]["vertices"][0]["x"], -2500)

    def test_ambiguous_target_and_distorting_arcs_fail_closed(self) -> None:
        source = drawing_template_geometries({
            "template": "basketball", "width_m": 28, "height_m": 15, "quantity": 2,
        })
        result, error = edit_candidate_geometries(source, parse_incremental_edit("图形向右移动2米"))
        self.assertIsNone(result)
        self.assertIn("第几个", error)
        result, error = edit_candidate_geometries(source, parse_incremental_edit("第二个篮球场宽度改为30米"))
        self.assertIsNone(result)
        self.assertIn("圆弧", error)

    def test_single_circle_radius_changes_without_moving_center(self) -> None:
        source = drawing_template_geometries({
            "template": "foundation", "radius_m": 3, "quantity": 1,
        })
        result, error = edit_candidate_geometries(
            source, parse_incremental_edit("第一个图形半径改为4米")
        )
        self.assertIsNone(error)
        self.assertEqual(result[0]["radius"], 4000)
        self.assertEqual(result[0]["center"], source[0]["center"])

    def test_spacing_moves_second_instance_only(self) -> None:
        source = drawing_template_geometries({
            "template": "basketball", "width_m": 28, "height_m": 15,
            "quantity": 2, "spacing_m": 2,
        })
        result, error = space_two_instances(source, 3000, "long_side_adjacent")
        self.assertIsNone(error)
        self.assertEqual(result[:19], source[:19])
        self.assertEqual(result[21]["center"]["y"] - source[21]["center"]["y"], 1000)

    def test_rotate_target_instance_around_its_center(self) -> None:
        source = drawing_template_geometries({
            "template": "room", "width_m": 6, "height_m": 2, "quantity": 2,
        })
        edit = parse_incremental_edit("把第二个图形逆时针旋转90度")
        self.assertEqual(edit, {"operation": "rotate", "instance": 2,
                                "angle_degrees": 90.0, "pivot": "instance_center"})
        result, error = edit_candidate_geometries(source, edit)
        self.assertIsNone(error)
        self.assertEqual(result[0], source[0])
        xs = [point["x"] for point in result[1]["vertices"]]
        ys = [point["y"] for point in result[1]["vertices"]]
        self.assertAlmostEqual(max(xs) - min(xs), 2000)
        self.assertAlmostEqual(max(ys) - min(ys), 6000)
        unspecified, message = edit_candidate_geometries(
            source, parse_incremental_edit("第二个图形旋转45度")
        )
        self.assertIsNone(unspecified)
        self.assertIn("顺时针或逆时针", message)

    def test_rotate_arc_updates_angles_but_not_radius(self) -> None:
        source = [{
            "id": 1, "type": "arc", "template_instance": 1,
            "center": {"x": 1000, "y": 2000}, "radius": 500,
            "start_angle": 0, "end_angle": 180,
        }]
        arc = source[0]
        old_radius = arc["radius"]
        result, error = edit_candidate_geometries(
            source, parse_incremental_edit("第一个篮球场顺时针旋转90度")
        )
        self.assertIsNone(error)
        rotated = next(item for item in result if item.get("id") == arc["id"])
        self.assertEqual(rotated["radius"], old_radius)
        self.assertEqual(rotated["start_angle"], (arc["start_angle"] - 90) % 360)

    def test_duplicate_has_stable_instance_and_unique_geometry_ids(self) -> None:
        source = drawing_template_geometries({
            "template": "room", "width_m": 5, "height_m": 3, "quantity": 1,
        })
        edit = parse_incremental_edit("复制第一个图形到右侧，间距2米")
        result, error = edit_candidate_geometries(source, edit)
        self.assertIsNone(error)
        self.assertEqual(result[0], source[0])
        self.assertEqual({item["template_instance"] for item in result}, {1, 2})
        self.assertEqual(len({item["id"] for item in result}), len(result))
        first_x = max(point["x"] for point in result[0]["vertices"])
        second_x = min(point["x"] for point in result[1]["vertices"])
        self.assertAlmostEqual(second_x - first_x, 2000)

    def test_duplicate_requires_non_overlapping_placement(self) -> None:
        source = drawing_template_geometries({
            "template": "room", "width_m": 5, "height_m": 3, "quantity": 1,
        })
        result, error = edit_candidate_geometries(source, parse_incremental_edit("复制第一个图形"))
        self.assertIsNone(result)
        self.assertIn("方向", error)

    def test_align_moves_only_requested_instance(self) -> None:
        source = drawing_template_geometries({
            "template": "room", "width_m": 5, "height_m": 3, "quantity": 2,
        })
        shifted, error = edit_candidate_geometries(source, {
            "operation": "translate", "instance": 2, "dx_mm": 1000, "dy_mm": 2000,
        })
        self.assertIsNone(error)
        edit = parse_incremental_edit("让第二个图形与第一个左对齐")
        result, error = edit_candidate_geometries(shifted, edit)
        self.assertIsNone(error)
        self.assertEqual(result[0], shifted[0])
        first_left = min(point["x"] for point in result[0]["vertices"])
        second_left = min(point["x"] for point in result[1]["vertices"])
        self.assertAlmostEqual(first_left, second_left)
        aligned, message = edit_candidate_geometries(
            shifted, parse_incremental_edit("将第一个和第二个图形顶部对齐")
        )
        self.assertIsNone(message)
        self.assertEqual(aligned[0], shifted[0])
        self.assertEqual(
            max(point["y"] for point in aligned[0]["vertices"]),
            max(point["y"] for point in aligned[1]["vertices"]),
        )

    def test_delete_lower_instance_preserves_upper_geometry(self) -> None:
        source = drawing_template_geometries({
            "template": "basketball", "width_m": 28, "height_m": 15,
            "quantity": 2, "spacing_m": 3,
        })
        edit = parse_incremental_edit("删除下方的篮球场，只保留上方的")
        result, error = edit_candidate_geometries(source, edit)
        self.assertIsNone(error)
        self.assertEqual(edit["operation"], "delete")
        self.assertEqual(edit["instance"], 1)
        self.assertEqual({item["template_instance"] for item in result}, {2})
        self.assertEqual(
            result,
            [item for item in source if item["template_instance"] == 2],
        )

    def test_upper_named_court_can_move_forward_without_instance_number(self) -> None:
        source = drawing_template_geometries({
            "template": "basketball", "width_m": 28, "height_m": 15,
            "quantity": 2, "spacing_m": 3,
        })
        edit = parse_incremental_edit("上边的篮球场向前平移2m")
        self.assertEqual(
            edit,
            {
                "operation": "translate",
                "instance": None,
                "position": "top",
                "coordinate_frame": "vehicle",
                "dx_mm": 2000,
                "dy_mm": 0,
            },
        )
        result, error = edit_candidate_geometries(source, edit)
        self.assertIsNone(error)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(
            result[0]["template_instance"], source[0]["template_instance"]
        )
        upper_before = [
            item for item in source if item["template_instance"] == 2
        ]
        upper_after = [
            item for item in result if item["template_instance"] == 2
        ]
        self.assertEqual(
            upper_after[0]["vertices"][0]["x"]
            - upper_before[0]["vertices"][0]["x"],
            2000,
        )
        lower_before = [
            item for item in source if item["template_instance"] == 1
        ]
        lower_after = [
            item for item in result if item["template_instance"] == 1
        ]
        self.assertEqual(lower_after, lower_before)

    def test_candidate_title_ordinal_does_not_override_lower_court(self) -> None:
        source = drawing_template_geometries({
            "template": "basketball", "width_m": 28, "height_m": 15,
            "quantity": 2, "spacing_m": 3,
        })
        edit = parse_incremental_edit(
            "基于‘标准候选方案 · 第 2 个图形平移’继续优化。"
            "修改目标：下方的篮球场向下移动3m"
        )

        result, error = edit_candidate_geometries(source, edit)

        self.assertIsNone(error)
        self.assertEqual(edit["instance"], 1)
        lower_before = [item for item in source if item["template_instance"] == 1]
        lower_after = [item for item in result if item["template_instance"] == 1]
        upper_before = [item for item in source if item["template_instance"] == 2]
        upper_after = [item for item in result if item["template_instance"] == 2]
        self.assertEqual(
            lower_after[0]["vertices"][0]["y"]
            - lower_before[0]["vertices"][0]["y"],
            -3000,
        )
        self.assertEqual(upper_after, upper_before)

    def test_lower_court_center_circle_scales_without_scaling_court(self) -> None:
        source = drawing_template_geometries({
            "template": "basketball", "width_m": 28, "height_m": 15,
            "quantity": 2, "spacing_m": 3,
        })
        edit = parse_incremental_edit(
            "基于‘标准候选方案 · 第 2 个图形平移 · 第 2 个图形平移’继续优化。"
            "修改目标：下方的篮球场中心的圆半径扩大一倍"
        )

        result, error = edit_candidate_geometries(source, edit)

        self.assertIsNone(error)
        self.assertEqual(edit["geometry_ids"], [3])
        by_id_before = {item["id"]: item for item in source}
        by_id_after = {item["id"]: item for item in result}
        self.assertEqual(by_id_after[3]["radius"], by_id_before[3]["radius"] * 2)
        self.assertEqual(by_id_after[3]["center"], by_id_before[3]["center"])
        self.assertEqual(by_id_after[1], by_id_before[1])
        self.assertEqual(by_id_after[2], by_id_before[2])
        self.assertEqual(by_id_after[4], by_id_before[4])
        self.assertEqual(by_id_after[5], by_id_before[5])
        self.assertEqual(by_id_after[6], by_id_before[6])

    def test_upper_court_outer_frame_moves_without_moving_inner_geometry(self) -> None:
        source = drawing_template_geometries({
            "template": "basketball", "width_m": 28, "height_m": 15,
            "quantity": 2, "spacing_m": 3,
        })
        edit = parse_incremental_edit("把上方篮球场的外框向右移动1米")

        result, error = edit_candidate_geometries(source, edit)

        self.assertIsNone(error)
        self.assertEqual(edit["geometry_ids"], [20])
        before = {item["id"]: item for item in source}
        after = {item["id"]: item for item in result}
        self.assertEqual(
            after[20]["vertices"][0]["x"] - before[20]["vertices"][0]["x"],
            1000,
        )
        self.assertEqual([after[value] for value in before if value != 20],
                         [before[value] for value in before if value != 20])

    def test_semantic_middle_line_targets_stable_geometry_id(self) -> None:
        source = drawing_template_geometries({
            "template": "basketball", "width_m": 28, "height_m": 15,
            "quantity": 1,
        })
        edit = parse_incremental_edit("把篮球场中线向左移动50厘米")

        result, error = edit_candidate_geometries(source, edit)

        self.assertIsNone(error)
        self.assertEqual(edit["geometry_ids"], [2])
        before = {item["id"]: item for item in source}
        after = {item["id"]: item for item in result}
        self.assertEqual(after[2]["start"]["x"], before[2]["start"]["x"] - 500)
        self.assertEqual(after[1], before[1])
        self.assertEqual(after[3], before[3])

    def test_semantic_feature_requires_an_instance_when_multiple_exist(self) -> None:
        source = drawing_template_geometries({
            "template": "basketball", "width_m": 28, "height_m": 15,
            "quantity": 2, "spacing_m": 3,
        })
        edit = parse_incremental_edit("把外框向右移动1米")

        result, error = edit_candidate_geometries(source, edit)

        self.assertIsNone(result)
        self.assertIn("修改第几个图形", error)

    def test_duplicate_semantic_names_fail_closed(self) -> None:
        source = drawing_template_geometries({
            "template": "basketball", "width_m": 28, "height_m": 15,
            "quantity": 1,
        })
        duplicate = deepcopy(source[1])
        duplicate["id"] = 99
        source.append(duplicate)
        edit = parse_incremental_edit("把篮球场中线向右移动1米")

        result, error = edit_candidate_geometries(source, edit)

        self.assertIsNone(result)
        self.assertIn("多个同名中线", error)

        clarification = robot_agent._cad_target_clarification(
            "把篮球场中线向右移动1米", edit, source,
        )
        self.assertEqual(clarification["schema"], "cad.target-clarification.v1")
        self.assertEqual(len(clarification["options"]), 2)
        self.assertNotIn("ID", clarification["options"][0]["label"])

        replay = parse_incremental_edit(clarification["options"][0]["reply"])
        replay_result, replay_error = edit_candidate_geometries(source, replay)
        self.assertIsNone(replay_error)
        selected_id = clarification["options"][0]["geometry_ids"][0]
        self.assertEqual(replay["geometry_ids"], [selected_id])
        before = {item["id"]: item for item in source}
        after = {item["id"]: item for item in replay_result}
        self.assertEqual(
            after[selected_id]["start"]["x"] - before[selected_id]["start"]["x"],
            1000,
        )
        other_id = ({2, 99} - {selected_id}).pop()
        self.assertEqual(after[other_id], before[other_id])

    def test_chat_candidate_chain_keeps_position_and_center_circle_targets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "两个篮球场", "两个标准篮球场",
                {
                    "shape": "basketball", "quantity": 2,
                    "dimensions": {"width_m": 28, "height_m": 15},
                    "spacing_m": 3, "printer": "center",
                },
                {},
                [],
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                initial = robot_agent.generate_project_candidate(project["id"])
                original = initial.get("variant") or initial["variants"][0]
                store.begin_design_iteration(project["id"], original["id"])

                move_message = (
                    "基于‘标准候选方案 · 第 2 个图形平移’继续优化。"
                    "修改目标：下方的篮球场向下移动3m"
                )
                move_route = robot_agent.resolve_intent(
                    move_message, "advanced", []
                )
                move_route["object_memory"] = {
                    "objects": {"project": [{"id": project["id"]}]}
                }
                moved = robot_agent.chat(
                    move_message, [], mode="advanced", route=move_route
                )
                moved_variant = moved["variant"]
                store.begin_design_iteration(project["id"], moved_variant["id"])

                scale_message = (
                    "基于‘标准候选方案 · 第 2 个图形平移 · 第 2 个图形平移’继续优化。"
                    "修改目标：下方的篮球场中心的圆半径扩大一倍"
                )
                scale_route = robot_agent.resolve_intent(
                    scale_message, "advanced", []
                )
                scale_route["object_memory"] = {
                    "objects": {"project": [{"id": project["id"]}]}
                }
                scaled = robot_agent.chat(
                    scale_message, [], mode="advanced", route=scale_route
                )

        self.assertTrue(moved["ok"], moved)
        self.assertTrue(moved["cad_preflight"]["effect_validation"]["verified"])
        self.assertEqual(
            moved["cad_edit_contract"]["target"]["instance_ids"], [1]
        )
        self.assertEqual(moved_variant["parent_variant_id"], original["id"])
        self.assertTrue(scaled["ok"], scaled)
        self.assertTrue(scaled["cad_preflight"]["effect_validation"]["verified"])
        self.assertEqual(
            scaled["cad_edit_contract"]["target"],
            {"scope": "geometry", "instance_ids": [], "geometry_ids": [3]},
        )
        self.assertEqual(scaled["variant"]["parent_variant_id"], moved_variant["id"])
        moved_by_id = {item["id"]: item for item in moved_variant["geometries"]}
        scaled_by_id = {
            item["id"]: item for item in scaled["variant"]["geometries"]
        }
        self.assertEqual(
            scaled_by_id[3]["radius"], moved_by_id[3]["radius"] * 2
        )
        self.assertEqual(
            [scaled_by_id[value] for value in (1, 2, 4, 5, 6)],
            [moved_by_id[value] for value in (1, 2, 4, 5, 6)],
        )

    def test_v2_contract_normalizes_resolved_target_and_coordinate_frame(self) -> None:
        contract = build_cad_edit_contract({
            "operation": "translate",
            "instance": 2,
            "coordinate_frame": "vehicle",
            "dx_mm": 2000,
            "dy_mm": 0,
        }, source_text="上边的篮球场向前平移2m")
        self.assertEqual(contract["schema"], "cad.edit.v2")
        self.assertEqual(contract["target"], {
            "scope": "instance", "instance_ids": [2], "geometry_ids": [],
        })
        self.assertEqual(contract["coordinate_frame"], "vehicle")
        self.assertEqual(contract["parameters"]["dx_mm"], 2000)

    def test_v2_contract_rejects_noop_translation(self) -> None:
        with self.assertRaisesRegex(ValueError, "must change"):
            build_cad_edit_contract({
                "operation": "translate", "instance": 1,
                "dx_mm": 0, "dy_mm": 0,
            })

    def test_add_template_contract_replays_declared_geometry_ids(self) -> None:
        source = drawing_template_geometries({
            "template": "basketball", "width_m": 28.0,
            "height_m": 15.0, "quantity": 1,
        })
        prototype = drawing_template_geometries({
            "template": "badminton", "width_m": 13.4,
            "height_m": 6.1, "quantity": 1,
        })
        next_id = max(int(item["id"]) for item in source)
        created_ids = list(range(next_id + 1, next_id + len(prototype) * 2 + 1))
        contract = build_cad_edit_contract({
            "operation": "add_template",
            "geometry_ids": [int(item["id"]) for item in source],
            "source_template": "basketball",
            "target_template": "badminton",
            "relative_positions": ["above", "below"],
            "gap_mm": 0.0,
            "created_geometry_ids": created_ids,
            "project_id": "project-1",
            "parent_variant_id": "variant-1",
        }, source_text="在篮球场上下方各添加一个羽毛球场")

        from app.cad_edit_contract import cad_edit_contract_to_edit

        geometries, error = edit_candidate_geometries(
            source, cad_edit_contract_to_edit(contract)
        )

        self.assertIsNone(error)
        self.assertIsNotNone(geometries)
        self.assertEqual(
            [int(item["id"]) for item in geometries if int(item["id"]) > next_id],
            created_ids,
        )

    def test_v2_vehicle_followup_preserves_forward_coordinate_frame(self) -> None:
        previous = {
            "schema": "cad.edit.v2", "operation": "translate",
            "target": {
                "scope": "instance", "instance_ids": [2], "geometry_ids": [],
            },
            "coordinate_frame": "vehicle",
            "parameters": {"dx_mm": 2000, "dy_mm": 0},
        }
        self.assertEqual(
            resolve_incremental_followup("再来一次", previous, [1, 2]),
            "第2个图形向前移动2000毫米",
        )

    def test_retain_right_instance_removes_all_other_groups(self) -> None:
        source = drawing_template_geometries({
            "template": "room", "width_m": 5, "height_m": 3,
            "quantity": 3, "spacing_m": 1, "arrangement": "short_side_adjacent",
        })
        edit = parse_incremental_edit("图纸只保留右侧图形")
        result, error = edit_candidate_geometries(source, edit)
        self.assertIsNone(error)
        self.assertEqual(edit["operation"], "retain")
        self.assertEqual(len({item["template_instance"] for item in result}), 1)
        self.assertEqual(edit["instance"], 3)

    def test_retain_clause_does_not_delete_the_retained_position(self) -> None:
        source = drawing_template_geometries({
            "template": "basketball", "width_m": 28, "height_m": 15,
            "quantity": 2, "spacing_m": 3,
        })
        edit = parse_incremental_edit("删除其他图形，只保留上方篮球场")
        result, error = edit_candidate_geometries(source, edit)
        self.assertIsNone(error)
        self.assertEqual(edit["operation"], "retain")
        self.assertEqual(edit["instance"], 2)
        self.assertEqual({item["template_instance"] for item in result}, {2})

    def test_duplicate_chat_updates_quantity_with_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "一间房", "画一个 5x3 米房间",
                {"shape": "room", "quantity": 1,
                 "dimensions": {"width_m": 5, "height_m": 3}, "printer": "center"}, {}, [],
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                initial = robot_agent.generate_project_candidate(project["id"])
                parent = initial.get("variant") or initial["variants"][0]
                store.begin_design_iteration(project["id"], parent["id"])
                route = robot_agent.resolve_intent("复制第一个图形到右侧，间距2米", "advanced", [])
                route["object_memory"] = {"objects": {"project": [{"id": project["id"]}]}}
                result = robot_agent.chat(
                    "复制第一个图形到右侧，间距2米", [], mode="advanced", route=route,
                )
                updated = store.get(project["id"])
        self.assertTrue(result["ok"], result)
        self.assertEqual(updated["requirements"]["quantity"], 2)
        self.assertEqual(len(updated["variants"]), 2)
        self.assertEqual(result["variant"]["instance_contract"]["count"], 2)
        self.assertEqual(result["cad_edit_command"]["schema"], "cad.instance_edit.v1")
        self.assertEqual(result["cad_edit_command"]["target_instance_id"], 1)
        self.assertEqual(result["cad_edit_command"]["created_instance_id"], 2)

    def test_duplicate_initializes_missing_legacy_quantity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create("导入图纸", "导入图纸", {"shape": "cad"}, {}, [])
            source = drawing_template_geometries({
                "template": "room", "width_m": 5, "height_m": 3, "quantity": 1,
            })
            parent = store.add_variant(
                project["id"], "导入方案", source, "导入",
                score_design_variant(source), preview_paths({"lines": source}),
            
                acceptance_summary={'status': 'passed', 'review_required': False, 'authority': 'test_fixture'},
            )
            store.begin_design_iteration(project["id"], parent["id"])
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                route = robot_agent.resolve_intent(
                    "复制第一个图形到右侧，间距2米", "advanced", []
                )
                route["object_memory"] = {"objects": {"project": [{"id": project["id"]}]}}
                result = robot_agent.chat(
                    "复制第一个图形到右侧，间距2米", [], mode="advanced", route=route,
                )
                updated = store.get(project["id"])
        self.assertTrue(result["ok"], result)
        self.assertEqual(updated["requirements"]["quantity"], 2)

    def test_middle_parking_move_stops_on_shared_topology_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "三个车位", "绘制三个并排标准车位",
                {"shape": "parking", "quantity": 3,
                 "dimensions": {"width_m": 2.5, "height_m": 5.0},
                 "printer": "center"}, {}, [],
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                initial = robot_agent.generate_project_candidate(project["id"])
                parent = initial.get("variant") or initial["variants"][0]
                store.begin_design_iteration(project["id"], parent["id"])
                message = "将中间的停车位向上移动2m"
                route = robot_agent.resolve_intent(message, "advanced", [])
                route["object_memory"] = {
                    "objects": {"project": [{"id": project["id"]}]}
                }
                result = robot_agent.chat(
                    message, [], mode="advanced", route=route,
                )
                updated = store.get(project["id"])

        self.assertEqual(route["decision_source"], "incremental_cad_edit")
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["clarification_required"])
        self.assertEqual(
            result["logical_target_resolution"]["object_id"],
            "parking-space-2",
        )
        self.assertEqual(
            result["topology_conflict"]["reason"],
            "shared_topology_conflict",
        )
        self.assertEqual(len(updated["variants"]), 1)

    def test_explicit_shared_boundary_split_requires_confirmation_and_persists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "四个标准相连停车位", "生成4个标准的相连停车位",
                {"shape": "parking", "quantity": 4,
                 "dimensions": {"width_m": 2.5, "height_m": 5.0},
                 "printer": "center"}, {}, [],
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                initial = robot_agent.generate_project_candidate(project["id"])
                parent = initial.get("variant") or initial["variants"][0]
                store.begin_design_iteration(project["id"], parent["id"])
                message = "拆分共享边界后，把中间两个停车位向前移动5米"
                route = robot_agent.resolve_intent(message, "advanced", [])
                route["object_memory"] = {
                    "objects": {"project": [{"id": project["id"]}]}
                }
                preview = robot_agent.chat(
                    message, [], mode="advanced", route=route,
                )
                confirmed = robot_agent.confirm(preview["pending_action"]["id"], True)
                updated = store.get(project["id"])

        self.assertTrue(preview["ok"], preview)
        self.assertEqual(preview["next_action"], "confirm_cad_edit")
        parameters = preview["cad_edit_contract"]["parameters"]
        self.assertEqual(parameters["boundary_policy"], "split_shared")
        self.assertEqual(len(parameters["shared_geometry_ids"]), 2)
        self.assertEqual(len(parameters["created_geometry_ids"]), 2)
        self.assertTrue(confirmed["ok"], confirmed)
        self.assertEqual(len(updated["variants"]), 2)
        latest = updated["variants"][-1]
        self.assertTrue(latest["revision_contract"]["logical_object_validation"]["verified"])
        refs = {
            item["object_id"]: item["geometry_refs"]
            for item in latest["logical_objects"]
        }
        self.assertEqual(len(refs["parking-space-2"]), 4)
        self.assertEqual(len(refs["parking-space-3"]), 4)
        self.assertNotIn(2, refs["parking-space-2"])
        self.assertNotIn(4, refs["parking-space-3"])
        self.assertIn(2, refs["parking-space-1"])
        self.assertIn(4, refs["parking-space-4"])
        objects = {item["object_id"]: item for item in latest["logical_objects"]}
        self.assertEqual(objects["parking-space-2"]["bounds"]["min_y"], 2500.0)
        self.assertEqual(objects["parking-space-3"]["bounds"]["min_y"], 2500.0)
        self.assertEqual(objects["parking-space-1"]["bounds"]["min_y"], -2500.0)
        geometries_by_id = {
            item["id"]: item for item in latest["geometries"]
        }
        for object_id in ("parking-space-2", "parking-space-3"):
            target_lines = [geometries_by_id[value] for value in refs[object_id]]
            points = [
                point
                for line in target_lines
                for point in (line["start"], line["end"])
            ]
            self.assertEqual(len(target_lines), 4)
            self.assertEqual(min(point["y"] for point in points), 2500.0)
            self.assertEqual(max(point["y"] for point in points), 7500.0)

    def test_candidate_save_repairs_one_non_target_drift_and_persists_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "两个篮球场", "生成两个标准篮球场",
                {"shape": "basketball", "quantity": 2,
                 "dimensions": {"width_m": 28, "height_m": 15},
                 "printer": "center"}, {}, [],
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                initial = robot_agent.generate_project_candidate(project["id"])
                parent = initial.get("variant") or initial["variants"][0]
                store.begin_design_iteration(project["id"], parent["id"])
                edit = {
                    "operation": "translate", "instance": 1,
                    "dx_mm": 500.0, "dy_mm": 0.0,
                    "project_id": project["id"],
                    "parent_variant_id": parent["id"],
                }
                geometries, error = edit_candidate_geometries(
                    parent["geometries"], edit
                )
                self.assertIsNone(error)
                self.assertIsNotNone(geometries)
                protected = next(
                    item for item in geometries or []
                    if item.get("template_instance") == 2
                    and isinstance(item.get("start"), dict)
                )
                protected["start"]["x"] += 123.0
                protected_id = protected["id"]
                contract = build_cad_edit_contract(
                    edit, source_text="第一个篮球场向右移动0.5米"
                )
                result = robot_agent._persist_candidate_edit(
                    project,
                    parent,
                    geometries,
                    "验证计划断言驱动的单次自动修复",
                    cad_edit_contract=contract,
                    logical_objects_override=deepcopy(
                        parent.get("logical_objects") or []
                    ),
                    topology_override=deepcopy(parent.get("topology") or {}),
                )

        self.assertTrue(result["ok"], result)
        self.assertTrue(result["edit_repair"]["attempted"])
        self.assertEqual(result["edit_repair"]["attempt_count"], 1)
        self.assertTrue(result["edit_repair"]["repaired"])
        self.assertEqual(result["variant"]["edit_plan"]["repair"]["attempt_count"], 1)
        source_by_id = {item["id"]: item for item in parent["geometries"]}
        saved_by_id = {item["id"]: item for item in result["variant"]["geometries"]}
        self.assertEqual(saved_by_id[protected_id], source_by_id[protected_id])

    def test_structured_language_fallback_executes_and_saves_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "两个篮球场", "生成两个标准篮球场",
                {"shape": "basketball", "quantity": 2,
                 "dimensions": {"width_m": 28, "height_m": 15},
                 "printer": "center"}, {}, [],
            )
            model_payload = {
                "schema_version": "cad.language-interpretation.v1",
                "is_cad_edit": True,
                "operation": "translate",
                "target": {"scope": "instance", "instance_ids": [2]},
                "parameters": {
                    "dx_mm": 2000.0, "dy_mm": 0.0,
                    "coordinate_frame": "drawing",
                },
                "assumptions": [],
                "constraints": [{"kind": "preserve_non_target"}],
                "evidence_text": ["第二个场地", "正向偏移2米"],
                "confidence": 0.95,
            }
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                initial = robot_agent.generate_project_candidate(project["id"])
                parent = initial.get("variant") or initial["variants"][0]
                store.begin_design_iteration(project["id"], parent["id"])
                message = "请将第二个场地沿水平方向正向偏移2米"
                route = robot_agent.route_intent(message, "advanced")
                route["decision_source"] = "rules"
                route["object_memory"] = {
                    "objects": {"project": [{"id": project["id"]}]}
                }
                with (
                    patch.object(robot_agent, "mode", "deepseek"),
                    patch.object(robot_agent, "api_keys", {"deepseek": "test-key"}),
                    patch.object(robot_agent, "_deepseek_request", return_value={
                        "choices": [{"message": {
                            "content": json.dumps(model_payload, ensure_ascii=False)
                        }}]
                    }),
                ):
                    result = robot_agent.chat(
                        message, [], mode="advanced", route=route
                    )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["edit_intent"]["parser"], "model_structured_fallback")
        self.assertEqual(result["cad_edit_contract"]["target"]["instance_ids"], [2])
        self.assertEqual(
            result["variant"]["edit_plan"]["intent_parser"],
            "model_structured_fallback",
        )
        self.assertEqual(
            result["variant"]["edit_plan"]["intent_evidence_text"],
            ["第二个场地", "正向偏移2米"],
        )
        self.assertTrue(
            result["variant"]["edit_plan"]["intent_grounding"]["verified"]
        )
        self.assertTrue(result["variant"]["edit_plan"]["verification"]["verified"])
        before = {item["id"]: item for item in parent["geometries"]}
        after = {item["id"]: item for item in result["variant"]["geometries"]}
        for geometry_id, item in before.items():
            if item.get("template_instance") == 1:
                self.assertEqual(after[geometry_id], item)
        moved_before = next(
            item for item in before.values()
            if item.get("template_instance") == 2
            and isinstance(item.get("start"), dict)
        )
        moved_after = after[moved_before["id"]]
        self.assertEqual(
            moved_after["start"]["x"] - moved_before["start"]["x"], 2000.0
        )

    def test_chat_moves_upper_court_forward_and_persists_new_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "两个篮球场", "两个标准篮球场",
                {"shape": "basketball", "quantity": 2,
                 "dimensions": {"width_m": 28, "height_m": 15},
                 "printer": "center"}, {}, [],
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                initial = robot_agent.generate_project_candidate(project["id"])
                parent = initial.get("variant") or initial["variants"][0]
                store.begin_design_iteration(project["id"], parent["id"])
                route = robot_agent.resolve_intent(
                    "上边的篮球场向前平移2m", "advanced", []
                )
                route["object_memory"] = {
                    "objects": {"project": [{"id": project["id"]}]}
                }
                result = robot_agent.chat(
                    "上边的篮球场向前平移2m", [],
                    mode="advanced", route=route,
                )
                updated = store.get(project["id"])
        self.assertEqual(route["decision_source"], "incremental_cad_edit")
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(updated["variants"]), 2)
        self.assertEqual(result["variant"]["parent_variant_id"], parent["id"])
        self.assertGreater(result["variant"]["diff"]["counts"]["modified"], 0)
        self.assertEqual(result["cad_edit_command"]["target_instance_id"], 2)
        self.assertEqual(result["cad_edit_contract"]["schema"], "cad.edit.v2")
        self.assertEqual(
            result["cad_edit_contract"]["target"]["instance_ids"], [2]
        )
        self.assertEqual(
            result["cad_edit_contract"]["coordinate_frame"], "vehicle"
        )

    def test_chat_requires_clarification_for_tied_extreme_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "两个并排房间", "两个并排房间",
                {"shape": "room", "quantity": 2,
                 "arrangement": "short_side_adjacent",
                 "dimensions": {"width_m": 5, "height_m": 3}}, {}, [],
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                initial = robot_agent.generate_project_candidate(project["id"])
                parent = initial.get("variant") or initial["variants"][0]
                store.begin_design_iteration(project["id"], parent["id"])
                route = robot_agent.resolve_intent(
                    "最上方的图形向右移动1米", "advanced", []
                )
                route["object_memory"] = {
                    "objects": {"project": [{"id": project["id"]}]}
                }
                result = robot_agent.chat(
                    "最上方的图形向右移动1米", [],
                    mode="advanced", route=route,
                )
                updated = store.get(project["id"])
        self.assertTrue(result["ok"])
        self.assertTrue(result["clarification_required"])
        self.assertIn("位置相同", result["clarification_question"])
        clarification = result["target_clarification"]
        self.assertEqual(clarification["schema"], "cad.target-clarification.v1")
        self.assertEqual(len(clarification["options"]), 2)
        self.assertTrue(all(item["reply"] for item in clarification["options"]))
        self.assertEqual(result["variant"]["id"], parent["id"])
        self.assertEqual(result["preview_paths"], clarification["preview_paths"])
        self.assertTrue(result["preview_paths"])
        self.assertEqual(len(updated["variants"]), 1)

    def test_high_risk_retain_waits_for_confirmation_then_saves_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "四个房间", "四个房间",
                {"shape": "room", "quantity": 4,
                 "dimensions": {"width_m": 5, "height_m": 3}}, {}, [],
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                initial = robot_agent.generate_project_candidate(project["id"])
                parent = initial.get("variant") or initial["variants"][0]
                store.begin_design_iteration(project["id"], parent["id"])
                route = robot_agent.resolve_intent(
                    "只保留第1个图形", "advanced", []
                )
                route["object_memory"] = {
                    "objects": {"project": [{"id": project["id"]}]}
                }
                pending_result = robot_agent.chat(
                    "只保留第1个图形", [], mode="advanced", route=route,
                )
                before_confirm = store.get(project["id"])
                action_id = pending_result["pending_action"]["id"]
                confirmed = robot_agent.confirm(action_id, True)
                after_confirm = store.get(project["id"])
                replay = robot_agent.confirm(action_id, True)
        self.assertTrue(pending_result["ok"])
        self.assertEqual(pending_result["next_action"], "confirm_cad_edit")
        self.assertTrue(pending_result["cad_preflight"]["requires_confirmation"])
        self.assertTrue(
            pending_result["cad_preflight"]["effect_validation"]["verified"]
        )
        self.assertEqual(len(before_confirm["variants"]), 1)
        self.assertTrue(confirmed["ok"], confirmed)
        self.assertEqual(confirmed["task_state"], "completed")
        self.assertTrue(confirmed["confirmed_high_risk_edit"])
        self.assertEqual(len(after_confirm["variants"]), 2)
        self.assertEqual(after_confirm["requirements"]["quantity"], 1)
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(len(store.get(project["id"])["variants"]), 2)

    def test_high_risk_confirmation_rejects_changed_design_base(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "四个房间", "四个房间",
                {"shape": "room", "quantity": 4,
                 "dimensions": {"width_m": 5, "height_m": 3}}, {}, [],
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                initial = robot_agent.generate_project_candidate(project["id"])
                parent = initial.get("variant") or initial["variants"][0]
                store.begin_design_iteration(project["id"], parent["id"])
                route = robot_agent.resolve_intent(
                    "只保留第1个图形", "advanced", []
                )
                route["object_memory"] = {
                    "objects": {"project": [{"id": project["id"]}]}
                }
                pending = robot_agent.chat(
                    "只保留第1个图形", [], mode="advanced", route=route,
                )
                sibling = store.add_variant(
                    project["id"], "并行候选", parent["geometries"], "并行修改",
                    score_design_variant(parent["geometries"]),
                    preview_paths({"lines": parent["geometries"]}),
                    parent_variant_id=parent["id"],
                
                acceptance_summary={'status': 'passed', 'review_required': False, 'authority': 'test_fixture'},
            )
                self.assertIsNotNone(sibling)
                store.begin_design_iteration(project["id"], sibling["id"])
                result = robot_agent.confirm(pending["pending_action"]["id"], True)
                updated = store.get(project["id"])
        self.assertFalse(result["ok"])
        self.assertIn("优化基准已变化", result["message"])
        self.assertEqual(len(updated["variants"]), 2)

    def test_second_edit_can_delete_instance_from_latest_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "两个篮球场", "两个标准篮球场",
                {"shape": "basketball", "quantity": 2,
                 "dimensions": {"width_m": 28, "height_m": 15}, "printer": "center"},
                {}, [],
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                initial = robot_agent.generate_project_candidate(project["id"])
                first = initial.get("variant") or initial["variants"][0]
                store.begin_design_iteration(project["id"], first["id"])
                route = robot_agent.resolve_intent(
                    "两个篮球场间距改为3米", "advanced", []
                )
                route["object_memory"] = {"objects": {"project": [{"id": project["id"]}]}}
                spacing_result = robot_agent.chat(
                    "两个篮球场间距改为3米", [], mode="advanced", route=route,
                )
                self.assertTrue(spacing_result["ok"], spacing_result)
                second = spacing_result["variant"]
                store.begin_design_iteration(project["id"], second["id"])
                delete_route = robot_agent.resolve_intent(
                    "删除下方的篮球场，只保留上方的", "advanced", []
                )
                delete_route["object_memory"] = {
                    "objects": {"project": [{"id": project["id"]}]}
                }
                result = robot_agent.chat(
                    "删除下方的篮球场，只保留上方的", [],
                    mode="advanced", route=delete_route,
                )
                updated = store.get(project["id"])
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(updated["variants"]), 3)
        self.assertEqual(updated["requirements"]["quantity"], 1)
        self.assertEqual(result["variant"]["parent_variant_id"], second["id"])
        self.assertEqual(
            {item["template_instance"] for item in result["variant"]["geometries"]},
            {2},
        )

    def test_chat_creates_persisted_incremental_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "两个标准篮球场", "两个标准篮球场", {
                    "shape": "basketball", "quantity": 2,
                    "dimensions": {"width_m": 28, "height_m": 15}, "printer": "center",
                }, {}, [],
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                initial = robot_agent.generate_project_candidate(project["id"])
                parent = initial["variant"] if initial.get("variant") else initial["variants"][0]
                store.begin_design_iteration(project["id"], parent["id"])
                route = robot_agent.resolve_intent("第二个篮球场向右移动2米", "advanced", [])
                route["object_memory"] = {"objects": {"project": [{"id": project["id"]}]}}
                response = robot_agent.chat_stream(
                    "第二个篮球场向右移动2米", [], mode="advanced", route=route,
                )
                result = list(response)[-1]
                updated = store.get(project["id"])
        self.assertEqual(route["decision_source"], "incremental_cad_edit")
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(updated["variants"]), 2)
        self.assertEqual(result["variant"]["parent_variant_id"], parent["id"])
        self.assertEqual(result["variant"]["geometries"][:3], parent["geometries"][:3])
        self.assertTrue(result["preview_paths"])
        self.assertGreater(result["variant"]["diff"]["counts"]["modified"], 0)

    def test_noop_edit_does_not_add_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "一间房", "画一个 5x3 米房间",
                {"shape": "room", "quantity": 1, "printer": "center"}, {}, [],
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                initial = robot_agent.generate_project_candidate(project["id"])
                parent = initial["variants"][0]
                store.begin_design_iteration(project["id"], parent["id"])
                route = robot_agent.resolve_intent("第一个图形宽度改为5米", "advanced", [])
                route["object_memory"] = {"objects": {"project": [{"id": project["id"]}]}}
                result = robot_agent.chat("第一个图形宽度改为5米", [], mode="advanced", route=route)
                updated = store.get(project["id"])
        self.assertFalse(result["ok"])
        self.assertEqual(len(updated["variants"]), 1)


class CadSelectorTest(unittest.TestCase):
    @staticmethod
    def source() -> list[dict[str, object]]:
        return [
            {"id": 1, "type": "line", "template_instance": 1,
             "layer_id": 1, "role": "printing", "path_semantic": "DRAW",
             "start": {"x": 0, "y": 0}, "end": {"x": 1000, "y": 0}},
            {"id": 2, "type": "line", "template_instance": 1,
             "layer_id": 2, "role": "reference", "path_semantic": "TRAVEL",
             "start": {"x": 0, "y": 1000}, "end": {"x": 1000, "y": 1000}},
            {"id": 3, "type": "line", "template_instance": 2,
             "layer_id": 2, "role": "reference", "path_semantic": "TRAVEL",
             "start": {"x": 3000, "y": 0}, "end": {"x": 4000, "y": 0}},
            {"id": 4, "type": "line", "template_instance": 3,
             "layer_id": 3, "role": "annotation", "path_semantic": "ANNOTATION",
             "start": {"x": 6000, "y": 0}, "end": {"x": 7000, "y": 0}},
            {"id": 5, "type": "line", "template_instance": 4,
             "layer_id": 4, "role": "ignored", "path_semantic": "AUXILIARY",
             "start": {"x": -4000, "y": 0}, "end": {"x": -3000, "y": 0}},
        ]

    def test_attribute_selectors_match_real_geometry_fields(self) -> None:
        samples = (
            ("删除辅助线", [5]),
            ("删除所有参考线", [2, 3]),
            ("删除第2号图层的图形", [2, 3]),
            ("删除与第2个图形同图层的线段", [2, 3]),
            ("删除所有标注线", [4]),
            ("删除所有喷墨线", [1]),
        )
        for message, ids in samples:
            with self.subTest(message=message):
                edit = parse_incremental_edit(message)
                self.assertIsNotNone(edit)
                result, error = edit_candidate_geometries(self.source(), edit)
                self.assertIsNone(error)
                self.assertEqual(sorted(set(range(1, 6)) - {item["id"] for item in result}), ids)
                self.assertEqual(edit["geometry_ids"], ids)

        arc = self.source()
        arc[3]["type"] = "arc"
        edit = parse_incremental_edit("删除所有圆弧图形")
        result, error = edit_candidate_geometries(arc, edit)
        self.assertIsNone(error)
        self.assertEqual([item["id"] for item in result], [1, 2, 3, 5])

    def test_spatial_selector_selects_only_complete_instances(self) -> None:
        edit = parse_incremental_edit("把第1个图形右侧的所有图形向上移动1米")
        self.assertIsNotNone(edit)
        result, error = edit_candidate_geometries(self.source(), edit)
        self.assertIsNone(error)
        self.assertEqual(edit["instances"], [2, 3])
        self.assertEqual([item["start"]["y"] for item in result],
                         [0, 1000, 1000, 1000, 0])

        edit = parse_incremental_edit("把第4个图形右侧的两个图形向上移动1米")
        result, error = edit_candidate_geometries(self.source(), edit)
        self.assertIsNone(error)
        self.assertEqual(edit["instances"], [1, 2])
        self.assertEqual([item["start"]["y"] for item in result],
                         [1000, 2000, 1000, 0, 0])

        edit = parse_incremental_edit("把第1个图形右侧的三个图形向上移动1米")
        result, error = edit_candidate_geometries(self.source(), edit)
        self.assertIsNone(result)
        self.assertIn("数量不足", error)

    def test_nearest_selector_rejects_ties_and_invalid_references(self) -> None:
        edit = parse_incremental_edit("把离第1个图形最近的图形向上移动1米")
        self.assertIsNotNone(edit)
        result, error = edit_candidate_geometries(self.source(), edit)
        self.assertIsNone(error)
        self.assertEqual(edit["instance"], 2)
        self.assertEqual(result[2]["start"]["y"], 1000)

        edit = parse_incremental_edit("把离第5个图形最近的图形向上移动1米")
        result, error = edit_candidate_geometries(self.source(), edit)
        self.assertIsNone(result)
        self.assertIn("没有第 5 个图形", error)

        tied = self.source()
        tied[3]["start"]["x"] = -3000
        tied[3]["end"]["x"] = -2000
        tied[4]["start"]["x"] = -6000
        tied[4]["end"]["x"] = -5000
        edit = parse_incremental_edit("把离第1个图形最近的图形向上移动1米")
        result, error = edit_candidate_geometries(tied, edit)
        self.assertIsNone(result)
        self.assertIn("距离相同", error)

        # A long figure's center can be far away while its edge is closest.
        edge_case = self.source()
        edge_case[2]["start"]["x"] = 1100
        edge_case[2]["end"]["x"] = 20100
        edit = parse_incremental_edit("把离第1个图形最近的图形向上移动1米")
        result, error = edit_candidate_geometries(edge_case, edit)
        self.assertIsNone(error)
        self.assertEqual(edit["instance"], 2)

    def test_selector_no_match_and_ambiguous_batch_pivot_are_blocked(self) -> None:
        missing = parse_incremental_edit("删除第99号图层的图形")
        result, error = edit_candidate_geometries(self.source(), missing)
        self.assertIsNone(result)
        self.assertIn("没有符合", error)

        rotation = parse_incremental_edit("第1个图形右侧的所有图形逆时针旋转30度")
        result, error = edit_candidate_geometries(self.source(), rotation)
        self.assertIsNone(result)
        self.assertIn("各自中心或组合中心", error)

    def test_attribute_delete_of_complete_instance_updates_quantity(self) -> None:
        from copy import deepcopy

        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "selector-projects.json")
            geometries = drawing_template_geometries({
                "template": "room", "width_m": 5, "height_m": 3,
                "quantity": 2, "spacing_m": 2,
            })
            self.assertTrue(geometries)
            for item in geometries:
                item["layer_id"] = 2 if item["template_instance"] == 2 else 1
            project = store.create(
                "属性删除", "两个房间", {"shape": "room", "quantity": 2}, {}, [],
            )
            parent = store.add_variant(
                project["id"], "两间房", deepcopy(geometries), "初始",
                score_design_variant(geometries), preview_paths({"lines": geometries}),
            
                acceptance_summary={'status': 'passed', 'review_required': False, 'authority': 'test_fixture'},
            )
            self.assertIsNotNone(parent)
            store.begin_design_iteration(project["id"], parent["id"])
            route = robot_agent.resolve_intent("删除第2号图层的图形", "advanced", [])
            route["object_memory"] = {"objects": {"project": [{"id": project["id"]}]}}
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                result = robot_agent.chat(
                    "删除第2号图层的图形", [], mode="advanced", route=route,
                )
            self.assertTrue(result["ok"], result)
            self.assertEqual(store.get(project["id"])["requirements"]["quantity"], 1)
            self.assertEqual(result["cad_edit_command"]["target_geometry_ids"],
                             sorted(item["id"] for item in geometries if item["layer_id"] == 2))


if __name__ == "__main__":
    unittest.main()
