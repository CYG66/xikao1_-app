from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from app.agent_service import PendingAction, robot_agent
from app.agent_skills import calculate_geometry_bounds, parameterize_design
from app.cad_project_candidates import (
    template_instance_assessment,
    template_instance_count,
)
from app.creative_projects import CreativeProjectStore
from app.drawing_store import preview_paths
from app.ros_adapter import ros_adapter
from app.state import robot_state


@contextmanager
def structured_plan_provider(steps):
    """Offline transport fixture; production executor and persistence remain real."""
    state={'provider_attempted':False,'request_attempts':0}
    def callback(text,schema):
        state.update(provider_attempted=True,request_attempts=state['request_attempts']+1)
        return {'schema_version':'cad.construction-interpretation.v1',
            'is_construction_request':True,'confidence':.99,
            'evidence_text':[text.split('\n',1)[0]],'plan':{'units':'m','steps':steps}}
    with patch.object(robot_agent,'_cad_construction_model_callback',return_value=(callback,state)):
        yield state


class AgentDrawingTest(unittest.TestCase):
    def test_imported_cad_first_candidate_preserves_source_geometry(self) -> None:
        source = [
            {
                "id": 41,
                "type": "line",
                "layer_id": 7,
                "start": {"x": 1234.0, "y": 5678.0, "z": 0.0},
                "end": {"x": 9234.0, "y": 5678.0, "z": 0.0},
                "role": "printing",
                "path_semantic": "DRAW",
            },
            {
                "id": 42,
                "type": "circle",
                "layer_id": 7,
                "center": {"x": 5234.0, "y": 5678.0, "z": 0.0},
                "radius": 750.0,
                "role": "printing",
                "path_semantic": "DRAW",
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "导入 CAD 修改",
                "基于已导入 CAD 图纸 imported_custom_v001.json 进行局部修改",
                {"shape": "imported_cad", "quantity": 1},
                {},
                [],
                source_drawing={
                    "file_name": "imported_custom_v001.json",
                    "source_format": "dwg",
                    "geometries": source,
                },
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                result = robot_agent.generate_project_candidate(project["id"])

        self.assertTrue(result["ok"], result)
        variant = result["variants"][0]
        self.assertEqual(variant["geometries"], source)
        self.assertTrue(variant["preview_paths"])
        self.assertEqual(len(variant["logical_objects"]), 1)
        self.assertEqual(
            variant["logical_objects"][0]["geometry_refs"], [41, 42]
        )

    def test_legacy_imported_cad_candidate_receives_complete_shape_group(self) -> None:
        source = [
            {
                "id": geometry_id,
                "type": "line",
                "layer_id": 1,
                "start": {"x": float(geometry_id * 1000), "y": 0.0, "z": 0.0},
                "end": {"x": float(geometry_id * 1000), "y": 5000.0, "z": 0.0},
            }
            for geometry_id in range(1, 23)
        ]
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "旧导入 CAD 修改",
                "基于 imported_v001.json 修改图纸",
                {},
                {},
                [],
                source_drawing={
                    "file_name": "imported_v001.json",
                    "source_format": "dwg",
                    "geometries": source,
                },
            )
            variant = store.add_variant(
                project["id"],
                "旧候选",
                source,
                "旧版本未保存逻辑对象",
                {"feasibility": {"ok": True, "errors": []}},
                [],
            )
            self.assertIsNotNone(variant)
            self.assertEqual(variant["logical_objects"], [])
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                repaired = robot_agent.reconcile_creative_projects(project["id"])
            restored = store.get(project["id"])

        self.assertEqual(repaired, 1)
        restored_variant = restored["variants"][0]
        self.assertEqual(len(restored_variant["logical_objects"]), 1)
        self.assertEqual(
            restored_variant["logical_objects"][0]["geometry_refs"],
            list(range(1, 23)),
        )

    def test_standard_basketball_and_badminton_request_generates_both_candidates(self) -> None:
        prompt = "规划一个标准的篮球场与一个标准的羽毛球场，用于地面划线"
        requirements = parameterize_design(prompt)
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "篮球场与羽毛球场组合划线",
                prompt,
                requirements,
                {},
                [],
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                result = robot_agent.generate_project_candidate(project["id"])

        self.assertTrue(result["ok"], result)
        variant = result["variants"][0]
        geometries = variant["geometries"]
        instances: dict[str, set[int]] = {}
        for item in geometries:
            instances.setdefault(item["template_type"], set()).add(
                item["template_instance"]
            )
        self.assertEqual(instances, {"basketball": {1}, "badminton": {2}})
        by_type = {
            template_type: [item for item in geometries if item["template_type"] == template_type]
            for template_type in ("basketball", "badminton")
        }
        basketball_bounds = calculate_geometry_bounds(by_type["basketball"])["bounds"]
        badminton_bounds = calculate_geometry_bounds(by_type["badminton"])["bounds"]
        self.assertAlmostEqual(basketball_bounds["max_x_mm"], badminton_bounds["min_x_mm"])
        self.assertEqual(
            [item["object_type"] for item in variant["logical_objects"]],
            ["basketball", "badminton"],
        )
        self.assertEqual(variant["name"], "篮球场 + 羽毛球场组合方案")
        self.assertTrue(result["preview_paths"])

    def test_mixed_court_request_generates_every_confirmed_template(self) -> None:
        prompt = (
            "规划两个标准的篮球场，中间夹着个羽毛球场，"
            "他们3个的间距为2m，长边平行一字排开"
        )
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "双篮球场夹羽毛球场划线",
                prompt,
                {
                    "shape": "basketball",
                    "quantity": 2,
                    "spacing_m": 2.0,
                    "printer": "center",
                },
                {},
                [],
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                result = robot_agent.generate_project_candidate(project["id"])

        self.assertTrue(result["ok"], result)
        variant = result["variants"][0]
        instances: dict[str, set[int]] = {}
        for item in variant["geometries"]:
            instances.setdefault(item["template_type"], set()).add(
                item["template_instance"]
            )
        self.assertEqual(
            {key: len(value) for key, value in instances.items()},
            {"basketball": 2, "badminton": 1},
        )
        self.assertEqual(
            [item["object_type"] for item in variant["logical_objects"]],
            ["basketball", "badminton", "basketball"],
        )

    def test_large_circle_generates_preview_and_requires_partitioning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                result = robot_agent._local_intent(
                    "设计一个半径200米的圆形划线图纸",
                    allow_design=True,
                    mode="advanced",
                )

            self.assertIsNotNone(result)
            self.assertTrue(result["ok"], result)
            self.assertNotIn("超出当前支持范围", result["message"])
            self.assertIn("已生成完整候选和预览", result["message"])
            projects = store.list()
            self.assertEqual(len(projects), 1)
            variant = projects[0]["variants"][0]
            self.assertTrue(variant["preview_paths"])
            scale = variant["assessment"]["project_scale"]
            self.assertEqual(scale["width_m"], 400.0)
            self.assertEqual(scale["height_m"], 400.0)
            self.assertTrue(scale["requires_partitioning"])
            self.assertEqual(scale["suggested_zone_count"], 64)

    def test_confirmed_inscribed_basketball_court_generates_circle_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
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
            route = {
                "object_memory": {
                    "objects": {"project": [{"id": project["id"]}]}
                },
                "retrieved_memory": {},
            }
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                result = robot_agent._deterministic_design_confirmation(
                    "确认生成候选方案", route
                )

        self.assertTrue(result["ok"])
        self.assertTrue(result["preview_paths"])
        geometries = result["variants"][-1]["geometries"]
        outer = next(item for item in geometries if item.get("label") == "篮球场外接圆")
        self.assertAlmostEqual(outer["radius"], 15882.380, places=2)
        self.assertTrue(any(
            item.get("name") == "persist_candidate_variant"
            and item.get("variant_id")
            and item.get("preview_paths")
            for item in result["tool_results"]
        ))

    def test_four_connected_parking_spaces_reject_unsafe_middle_pair_move(self) -> None:
        """The requested pair is resolved, then shared-boundary safety is enforced."""
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "四个相连标准车位",
                "生成4个标准的相连停车位",
                {
                    "shape": "parking",
                    "dimensions": {"width_m": 2.5, "height_m": 5.0},
                    "quantity": 4,
                    "arrangement": "long_side_adjacent",
                    "printer": "center",
                },
                {},
                [],
            )
            route = {
                "name": "drawing_design",
                "operation": "modify",
                "decision_source": "incremental_cad_edit",
                "object_memory": {"objects": {"project": [{"id": project["id"]}]}},
            }
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                generated = robot_agent.generate_project_candidate(project["id"])
                parent = generated["variants"][0]
                store.begin_design_iteration(project["id"], parent["id"])
                result = robot_agent._apply_incremental_candidate_edit(
                    "把中间的两个停车位整体向前移动5m", route,
                )

        self.assertTrue(generated["ok"])
        self.assertEqual(len(parent["logical_objects"]), 4)
        self.assertTrue(parent["topology"]["shared_geometries"])
        self.assertTrue(result["ok"], result)
        self.assertTrue(result.get("clarification_required"))
        self.assertIn("共享边界", result["message"])
        self.assertEqual(len(store.get(project["id"])["variants"]), 1)

    def test_template_project_has_complete_requirements(self) -> None:
        with patch("app.agent_skills._default_printer", return_value="center"):
            from app.agent_skills import parameterize_design

            result = parameterize_design("标准篮球场划线")

        self.assertEqual(result["shape"], "basketball")
        self.assertEqual(result["dimensions"], {"width_m": 28.0, "height_m": 15.0})
        self.assertEqual(result["missing"], [])

    def test_two_basketball_courts_keep_quantity_layout_and_spacing(self) -> None:
        from app.agent_skills import (
            drawing_template_geometries,
            parameterize_design,
            recognize_drawing_template,
        )

        requirements = parameterize_design(
            "两个标准篮球场并排，长边相邻，间距2m"
        )
        geometries = drawing_template_geometries({
            "template": "basketball",
            "width_m": 28.0,
            "height_m": 15.0,
            "quantity": requirements["quantity"],
            "arrangement": requirements["arrangement"],
            "spacing_m": requirements["spacing_m"],
        })

        self.assertEqual(requirements["quantity"], 2)
        self.assertEqual(requirements["arrangement"], "long_side_adjacent")
        self.assertEqual(requirements["spacing_m"], 2.0)
        self.assertEqual(len(geometries), 38)
        self.assertEqual(
            {item["template_instance"] for item in geometries}, {1, 2}
        )
        centers = sorted(
            item["center"]["y"]
            for item in geometries
            if item["type"] == "circle"
        )
        self.assertEqual(centers, [-8500.0, 8500.0])

    def test_parking_space_phrase_resolves_to_standard_gap(self) -> None:
        from app.agent_skills import drawing_template_geometries, recognize_drawing_template

        match = recognize_drawing_template(
            "规划一个长边并排间距预留一个停车位大小的两个标准篮球场"
        )
        self.assertIsNotNone(match)
        self.assertEqual(match["quantity"], 2)
        self.assertEqual(match["spacing_m"], 2.5)
        self.assertEqual(match["spacing_reference"], "standard_parking_space_width")
        geometries = drawing_template_geometries(match)
        self.assertEqual(len(geometries), 38)
        self.assertEqual({item["template_instance"] for item in geometries}, {1, 2})

    def test_two_basketball_project_replaces_stale_single_court_candidate(self) -> None:
        from app.agent_skills import (
            drawing_template_geometries,
            preview_paths,
            score_design_variant,
        )

        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "两个标准篮球场划线",
                "绘制两个标准篮球场并排，长边相邻，间距2m",
                {
                    "shape": "basketball",
                    "dimensions": {"width_m": 28.0, "height_m": 15.0},
                    "quantity": 2,
                    "arrangement": "long_side_adjacent",
                    "spacing_m": 2.0,
                    "printer": "center",
                },
                {},
                [],
            )
            single = drawing_template_geometries({
                "template": "basketball",
                "width_m": 28.0,
                "height_m": 15.0,
            })
            store.add_variant(
                project["id"],
                "旧单场方案",
                single,
                "旧版本错误方案",
                score_design_variant(single),
                preview_paths({"lines": single}),
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                result = robot_agent.generate_project_candidate(project["id"])

        self.assertTrue(result["ok"])
        latest = result["variants"][-1]["geometries"]
        self.assertEqual(
            template_instance_count(latest, "basketball"), 2
        )
        self.assertEqual(len(latest), 38)
        self.assertEqual(len(result["preview_paths"]), 38)

    def test_latest_project_quantity_replaces_original_single_candidate(self) -> None:
        from app.agent_skills import drawing_template_geometries, preview_paths, score_design_variant

        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "标准篮球场划线",
                "绘制标准篮球场",
                {
                    "shape": "basketball",
                    "dimensions": {"width_m": 28.0, "height_m": 15.0},
                    "quantity": 1,
                    "printer": "center",
                },
                {},
                [],
            )
            single = drawing_template_geometries({
                "template": "basketball", "width_m": 28.0, "height_m": 15.0,
            })
            store.add_variant(
                project["id"], "原单场方案", single, "原始需求",
                score_design_variant(single), preview_paths({"lines": single}),
            )
            store.begin_design_iteration(project["id"], store.get(project["id"])["variants"][0]["id"])
            updated_requirements = store.update(
                project["id"], requirements={"quantity": 2},
                event_message="用户把最新确认数量改为两个",
            )
            self.assertIsNotNone(updated_requirements)
            route = {
                "object_memory": {
                    "objects": {"project": [{"id": project["id"]}]}
                }
            }
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                result = robot_agent._deterministic_design_confirmation(
                    "确认生成候选方案", route
                )

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["variants"]), 2)
        self.assertEqual(
            template_instance_count(
                result["variants"][-1]["geometries"], "basketball"
            ),
            2,
        )
        self.assertIn("2 个篮球场", result["variants"][-1]["name"])

    def test_model_variant_with_excess_quantity_is_rejected(self) -> None:
        from app.agent_skills import drawing_template_geometries

        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "两个篮球场",
                "绘制两个篮球场",
                {
                    "shape": "basketball",
                    "dimensions": {"width_m": 28.0, "height_m": 15.0},
                    "quantity": 2,
                    "printer": "center",
                },
                {},
                [],
            )
            three_courts = drawing_template_geometries({
                "template": "basketball",
                "width_m": 28.0,
                "height_m": 15.0,
                "quantity": 3,
            })
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                output = robot_agent._execute_safe(
                    "add_design_variant",
                    {
                        "project_id": project["id"],
                        "name": "错误的三场方案",
                        "geometries": three_courts,
                        "rationale": "数量超过已确认需求",
                    },
                    mode="advanced",
                )

        self.assertFalse(output["ok"])
        self.assertEqual(store.get(project["id"])["variants"], [])
        self.assertIn("add_design_variant", output["message"])

    def test_legacy_template_candidate_is_migrated_to_instance_contract(self) -> None:
        from app.agent_skills import drawing_template_geometries, preview_paths, score_design_variant

        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "标准篮球场", "绘制标准篮球场",
                {"shape": "basketball", "quantity": 1, "printer": "center"}, {}, [],
            )
            geometries = drawing_template_geometries({
                "template": "basketball", "width_m": 28.0, "height_m": 15.0,
            })
            geometries = [{key: value for key, value in item.items()
                           if key not in {"template_instance", "template_type"}}
                          for item in geometries]
            parent = store.add_variant(
                project["id"], "旧方案", geometries, "旧模板",
                score_design_variant(geometries), preview_paths({"lines": geometries}),
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                assessment = template_instance_assessment(
                    geometries, "basketball", allow_legacy_migration=True,
                    expected_geometries=drawing_template_geometries({
                        "template": "basketball", "width_m": 28.0, "height_m": 15.0,
                    }),
                )
                migrated = store.migrate_variant_instances(
                    project["id"], parent["id"], assessment["migrated_geometries"], assessment,
                )

        self.assertEqual(assessment["status"], "migrated")
        self.assertTrue(assessment["authoritative"])
        self.assertEqual(assessment["count"], 1)
        self.assertEqual(
            {item["template_instance"] for item in migrated["geometries"]}, {1}
        )

    def test_unlabeled_model_candidate_is_estimate_and_cannot_pass_quantity(self) -> None:
        geometries = [{
            "id": index,
            "type": "line",
            "layer_id": 1,
            "start": {"x": 0, "y": 0, "z": 0},
            "end": {"x": 1000, "y": 0, "z": 0},
        } for index in range(1, 4)]
        assessment = template_instance_assessment(geometries, "basketball")
        self.assertEqual(assessment["status"], "estimated")
        self.assertFalse(assessment["authoritative"])

    def test_unconfirmed_cad_groups_require_confirmation(self) -> None:
        geometries = [{
            "id": 1,
            "type": "line",
            "layer_id": 1,
            "start": {"x": 0, "y": 0, "z": 0},
            "end": {"x": 1000, "y": 0, "z": 0},
        }]
        assessment = template_instance_assessment(
            geometries, "basketball",
            source_drawing={"source_format": "dxf", "cad_analysis": {
                "instance_groups_confirmed": False,
            }},
        )
        self.assertEqual(assessment["status"], "confirmation_required")
        self.assertFalse(assessment["authoritative"])

    def test_legacy_basketball_project_is_repaired_when_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "标准篮球场划线",
                "在场地内绘制标准篮球场",
                {"shape": None, "dimensions": {}},
                {},
                ["shape", "dimensions"],
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                repaired = robot_agent.reconcile_creative_projects(project["id"])

            restored = store.get(project["id"])

        self.assertEqual(repaired, 1)
        self.assertEqual(restored["status"], "ready_for_design")
        self.assertEqual(restored["missing_parameters"], [])
        self.assertEqual(restored["requirements"]["shape"], "basketball")
        self.assertEqual(
            restored["requirements"]["dimensions"],
            {"width_m": 28.0, "height_m": 15.0},
        )

    def test_legacy_composite_project_repairs_components_and_invented_spacing(self) -> None:
        prompt = "规划一个标准的篮球场与一个标准的羽毛球场，用于地面划线"
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "标准篮球场与羽毛球场组合划线",
                prompt,
                {
                    "shape": "basketball",
                    "dimensions": {"width_m": 28.0, "height_m": 15.0},
                    "quantity": 1,
                    "spacing_m": 1.0,
                    "printer": "center",
                },
                {},
                [],
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                repaired = robot_agent.reconcile_creative_projects(project["id"])

            restored = store.get(project["id"])

        self.assertEqual(repaired, 1)
        self.assertEqual(restored["requirements"]["quantity"], 2)
        self.assertEqual(restored["requirements"]["spacing_m"], 0.0)
        self.assertEqual(
            [item["template"] for item in restored["requirements"]["template_components"]],
            ["basketball", "badminton"],
        )

    def test_designing_composite_project_repairs_summary_without_resetting_stage(self) -> None:
        prompt = (
            "规划一个标准的篮球场与一个标准的羽毛球场，用于地面喷墨划线。"
            "篮球场按标准尺寸28m×15m，羽毛球场按标准尺寸13.4m×6.1m。"
        )
        from app.agent_skills import (
            drawing_template_geometries,
            preview_paths,
            recognize_drawing_template,
            score_design_variant,
        )

        basketball_only = drawing_template_geometries(
            recognize_drawing_template("标准篮球场")
        )
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "标准篮球场与羽毛球场组合划线",
                prompt,
                {
                    "shape": "basketball",
                    "dimensions": {"width_m": 28.0, "height_m": 15.0},
                    "quantity": 1,
                    "spacing_m": 1.0,
                    "printer": "center",
                },
                {},
                [],
            )
            store.add_variant(
                project["id"], "旧方案", basketball_only, "旧错误候选",
                score_design_variant(basketball_only),
                preview_paths({"lines": basketball_only}),
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                repaired = robot_agent.reconcile_creative_projects(project["id"])

            restored = store.get(project["id"])

        self.assertEqual(repaired, 1)
        self.assertEqual(restored["status"], "designing")
        self.assertEqual(restored["requirements"]["quantity"], 2)
        self.assertEqual(restored["requirements"]["spacing_m"], 0.0)
        self.assertEqual(
            [item["template"] for item in restored["requirements"]["template_components"]],
            ["basketball", "badminton"],
        )

    def test_repaired_basketball_project_generates_visible_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "标准篮球场划线",
                "绘制边线、中线、中圈、罚球区、罚球圈与三分线",
                {"shape": None, "dimensions": {}},
                {},
                ["shape", "dimensions"],
            )
            route = {
                "object_memory": {
                    "objects": {
                        "project": [{"type": "project", "id": project["id"]}]
                    }
                },
                "retrieved_memory": {},
            }
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                robot_agent.reconcile_creative_projects(project["id"])
                result = robot_agent._deterministic_design_confirmation(
                    "确认生成候选方案", route
                )

        self.assertTrue(result["ok"])
        self.assertEqual(result["project"]["status"], "designing")
        self.assertTrue(result["preview_paths"])
        self.assertGreaterEqual(len(result["drawing_json"]["lines"]), 3)

    def test_selected_project_candidate_does_not_use_stale_chat_memory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "标准篮球场划线",
                "绘制标准篮球场",
                {
                    "shape": "basketball",
                    "dimensions": {"width_m": 28.0, "height_m": 15.0},
                    "printer": "center",
                },
                {},
                [],
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                result = robot_agent.generate_project_candidate(project["id"])

        self.assertTrue(result["ok"])
        self.assertEqual(result["project_id"], project["id"])
        self.assertTrue(result["preview_paths"])

    def test_semicircular_arch_confirmation_generates_visible_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "半圆拱门 宽2米高3米",
                "半圆拱门 宽2米高3米",
                {
                    "shape": "closed_semicircular_arch",
                    "dimensions": {"width_m": 2.0, "height_m": 3.0},
                    "printer": "center",
                },
                {},
                [],
            )
            steps=[
                {'op':'add_line','step_id':'right','output_ref':'right','start':{'x':2,'y':0},'end':{'x':2,'y':2}},
                {'op':'add_arc','step_id':'arch','output_ref':'arch','center':{'x':1,'y':2},'radius':1,'start_angle':0,'end_angle':180},
                {'op':'add_line','step_id':'left','output_ref':'left','start':{'x':0,'y':2},'end':{'x':0,'y':0}},
                {'op':'add_line','step_id':'base','output_ref':'base','start':{'x':0,'y':0},'end':{'x':2,'y':0}}]
            for step in steps:
                step['semantic']={'label':step['step_id'],'assembly_id':'arch','assembly_label':'拱门'}
            with patch("app.agent_service.get_creative_project_store", return_value=store),structured_plan_provider(steps) as provider:
                result = robot_agent.generate_project_candidate(project["id"])
                self.assertEqual(provider['request_attempts'],1)

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["project_id"], project["id"])
        self.assertEqual(
            [item["type"] for item in result["variant"]["geometries"]],
            ["line", "arc", "line", "line"],
        )
        self.assertTrue(result["preview_paths"])
        self.assertEqual(result["next_action"], "select_design_variant")

    def test_three_parking_space_project_generates_all_requested_bays(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "三个并排标准车位",
                "绘制三个并排标准车位，不需要通道",
                {
                    "shape": "parking",
                    "dimensions": {"width_m": 2.5, "height_m": 5.0},
                    "quantity": 3,
                    "printer": "center",
                },
                {},
                [],
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                result = robot_agent.generate_project_candidate(project["id"])

        self.assertTrue(result["ok"])
        geometries = result["variants"][0]["geometries"]
        self.assertEqual(len(geometries), 10)
        self.assertEqual(result["project"]["requirements"]["quantity"], 3)
        variant = result["variants"][0]
        self.assertEqual(
            [item["object_id"] for item in variant["logical_objects"]],
            ["parking-space-1", "parking-space-2", "parking-space-3"],
        )
        self.assertEqual(
            variant["topology"]["shared_geometries"][0]["object_ids"],
            ["parking-space-1", "parking-space-2"],
        )

    def test_natural_language_connected_parking_quantity_is_three(self) -> None:
        from app.agent_skills import (
            drawing_template_geometries,
            parameterize_design,
            recognize_drawing_template,
        )

        prompt = "给我生成3个相连的停车位的图纸"
        requirements = parameterize_design(prompt)
        self.assertEqual(requirements["quantity"], 3)
        self.assertEqual(requirements["arrangement"], "long_side_adjacent")
        match = recognize_drawing_template(prompt)
        self.assertIsNotNone(match)
        self.assertEqual(len(drawing_template_geometries(match)), 10)

    def test_multi_warehouse_project_generates_independent_instances(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "两个仓库网格",
                "绘制两个仓库网格并排，间距1m",
                {
                    "shape": "warehouse",
                    "dimensions": {"width_m": 20.0, "height_m": 12.0},
                    "quantity": 2,
                    "arrangement": "long_side_adjacent",
                    "spacing_m": 1.0,
                    "printer": "center",
                },
                {},
                [],
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                result = robot_agent.generate_project_candidate(project["id"])

        self.assertTrue(result["ok"])
        geometries = result["variants"][0]["geometries"]
        self.assertEqual(
            template_instance_count(geometries, "warehouse"), 2
        )
        self.assertEqual(
            {item.get("template_instance") for item in geometries}, {1, 2}
        )
        self.assertEqual(len(result["preview_paths"]), 12)

    def test_existing_single_bay_candidate_is_replaced_by_quantity_fix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "三个并排标准车位",
                "绘制三个并排标准车位，不需要通道",
                {
                    "shape": "parking",
                    "dimensions": {"width_m": 2.5, "height_m": 5.0},
                    "printer": "center",
                },
                {},
                [],
            )
            wrong_geometry = [{
                "id": 1,
                "type": "polyline",
                "layer_id": 1,
                "vertices": [
                    {"x": -1250, "y": -2500, "z": 0},
                    {"x": 1250, "y": -2500, "z": 0},
                    {"x": 1250, "y": 2500, "z": 0},
                    {"x": -1250, "y": 2500, "z": 0},
                ],
                "closed": True,
            }]
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                from app.agent_skills import preview_paths, score_design_variant

                store.add_variant(
                    project["id"],
                    "旧单车位方案",
                    wrong_geometry,
                    "旧版本错误方案",
                    score_design_variant(wrong_geometry),
                    preview_paths({"lines": wrong_geometry}),
                )
                result = robot_agent.generate_project_candidate(project["id"])

        self.assertTrue(result["ok"])
        self.assertEqual(len(result["variants"]), 2)
        self.assertEqual(len(result["variants"][-1]["geometries"]), 10)
        self.assertIn("3 个车位修正方案", result["variants"][-1]["name"])

    def test_selected_missing_project_returns_refresh_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                result = robot_agent.generate_project_candidate("missing")

        self.assertFalse(result["ok"])
        self.assertIn("项目列表已刷新", result["message"])

    def test_project_creation_cannot_claim_design_completed_when_parameters_missing(self) -> None:
        result = robot_agent.enrich_result(
            robot_agent._result(
                "设计已经完成。",
                robot_agent._empty_usage(),
                tool_results=[{
                    "name": "create_creative_project",
                    "ok": True,
                    "project_id": "project-1",
                    "project_status": "clarifying",
                    "missing_parameters": ["shape", "dimensions"],
                }],
            ),
            {"tool_family": "cad", "name": "design", "required_context": []},
        )

        self.assertFalse(result["design_ready"])
        self.assertIn("还不能生成路径规划图纸", result["message"])
        self.assertNotIn("设计已经完成", result["message"])

    def test_design_variant_result_promotes_valid_preview_to_response(self) -> None:
        geometries = [{
            "id": 1,
            "type": "line",
            "layer_id": 1,
            "start": {"x": 0, "y": 0, "z": 0},
            "end": {"x": 3000, "y": 0, "z": 0},
        }]
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "直线方案",
                "生成一条三米直线",
                {"shape": "line", "dimensions": {"length_m": 3.0}, "printer": "center"},
                {},
                [],
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                output = robot_agent._execute_safe(
                    "add_design_variant",
                    {
                        "project_id": project["id"],
                        "name": "方案 A",
                        "geometries": geometries,
                        "rationale": "标准直线路径",
                    },
                    mode="advanced",
                )
                summary = robot_agent._tool_result_summary("add_design_variant", output)

        self.assertFalse(output["ok"])
        self.assertFalse(summary["ok"])
        self.assertIn("add_design_variant", output["message"])

    def test_llm_single_court_candidate_is_rebuilt_from_composite_project_request(self) -> None:
        prompt = "规划一个标准的篮球场与一个标准的羽毛球场，用于地面划线"
        from app.agent_skills import drawing_template_geometries, recognize_drawing_template

        basketball_only = drawing_template_geometries(
            recognize_drawing_template("标准篮球场")
        )
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "标准篮球场与羽毛球场组合划线",
                prompt,
                {
                    "shape": "basketball",
                    "dimensions": {"width_m": 28.0, "height_m": 15.0},
                    "quantity": 1,
                    "printer": "center",
                },
                {},
                [],
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                result = robot_agent._execute_safe(
                    "add_design_variant",
                    {
                        "project_id": project["id"],
                        "name": "模型生成的单篮球场方案",
                        "geometries": basketball_only,
                        "rationale": "模型遗漏了羽毛球场",
                    },
                    mode="advanced",
                )

        self.assertFalse(result["ok"])
        self.assertEqual(store.get(project["id"])["variants"], [])
        self.assertIn("add_design_variant", result["message"])

    def test_existing_wrong_composite_candidate_can_be_regenerated_without_parent(self) -> None:
        prompt = "规划一个标准的篮球场与一个标准的羽毛球场，用于地面划线"
        from app.agent_skills import (
            drawing_template_geometries,
            preview_paths,
            recognize_drawing_template,
            score_design_variant,
        )

        basketball_only = drawing_template_geometries(
            recognize_drawing_template("标准篮球场")
        )
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "标准篮球场与羽毛球场组合划线",
                prompt,
                {
                    "shape": "basketball",
                    "dimensions": {"width_m": 28.0, "height_m": 15.0},
                    "quantity": 1,
                    "printer": "center",
                },
                {},
                [],
            )
            store.add_variant(
                project["id"],
                "旧单篮球场方案",
                basketball_only,
                "旧错误候选",
                score_design_variant(basketball_only),
                preview_paths({"lines": basketball_only}),
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                result = robot_agent._execute_safe(
                    "add_design_variant",
                    {
                        "project_id": project["id"],
                        "name": "再次生成",
                        "geometries": basketball_only,
                        "rationale": "模型仍遗漏羽毛球场",
                    },
                    mode="advanced",
                )

        self.assertFalse(result["ok"])
        self.assertEqual(len(store.get(project["id"])["variants"]), 1)
        self.assertIn("add_design_variant", result["message"])

    def test_advanced_iteration_scales_entire_basketball_candidate(self) -> None:
        from app.drawing_store import preview_paths

        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "标准篮球场划线",
                "绘制标准篮球场",
                {
                    "shape": "basketball",
                    "dimensions": {"width_m": 28.0, "height_m": 15.0},
                    "printer": "center",
                },
                {},
                [],
            )
            route = {
                "name": "drawing_design",
                "operation": "modify",
                "object_memory": {
                    "objects": {"project": [{"id": project["id"]}]}
                },
            }
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                initial = robot_agent.generate_project_candidate(project["id"])
                parent = initial["variants"][0]
                store.begin_design_iteration(project["id"], parent["id"])
                result = robot_agent.chat(
                    "将篮球场扩大一倍", [], mode="advanced", route=route
                )

            updated = store.get(project["id"])

        self.assertTrue(result["ok"], result)
        self.assertEqual(len(updated["variants"]), 2, result)
        child = updated["variants"][-1]
        self.assertEqual(child["parent_variant_id"], parent["id"])
        self.assertEqual(parent["geometries"], initial["variants"][0]["geometries"])
        parent_points = [
            point for path in preview_paths({"lines": parent["geometries"]}) for point in path
        ]
        child_points = [
            point for path in preview_paths({"lines": child["geometries"]}) for point in path
        ]
        parent_width = max(p[0] for p in parent_points) - min(p[0] for p in parent_points)
        parent_height = max(p[1] for p in parent_points) - min(p[1] for p in parent_points)
        child_width = max(p[0] for p in child_points) - min(p[0] for p in child_points)
        child_height = max(p[1] for p in child_points) - min(p[1] for p in child_points)
        self.assertAlmostEqual(child_width, parent_width * 2.0, places=3)
        self.assertAlmostEqual(child_height, parent_height * 2.0, places=3)
        self.assertTrue(result["preview_paths"])
        self.assertGreater(child["diff"]["counts"]["modified"], 0)
        self.assertEqual(result["cad_edit_contract"]["schema"], "cad.edit.v2")
        self.assertEqual(result["cad_edit_contract"]["operation"], "scale")
        self.assertEqual(
            result["cad_edit_contract"]["parameters"]["factor"], 2.0
        )

    def test_layout_followup_creates_new_spaced_candidate_and_preview(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "两个标准篮球场划线",
                "绘制两个标准篮球场",
                {
                    "shape": "basketball",
                    "dimensions": {"width_m": 28.0, "height_m": 15.0},
                    "quantity": 2,
                    "printer": "center",
                },
                {},
                [],
            )
            route = {
                "name": "drawing_design",
                "operation": "modify",
                "decision_source": "drawing_layout_followup",
                "object_memory": {
                    "objects": {"project": [{"id": project["id"]}]}
                },
            }
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                initial = robot_agent.generate_project_candidate(project["id"])
                parent = initial["variants"][0]
                store.begin_design_iteration(project["id"], parent["id"])
                result = robot_agent.chat(
                    "基于“标准候选方案”继续优化。修改目标：长边并列排布，间距为2米",
                    [],
                    mode="advanced",
                    route=route,
                )
                updated = store.get(project["id"])

        self.assertTrue(result["ok"], result)
        self.assertEqual(len(updated["variants"]), 2, result)
        child = updated["variants"][-1]
        self.assertEqual(child["parent_variant_id"], parent["id"])
        self.assertNotEqual(child["geometries"], parent["geometries"])
        centers = sorted(
            item["center"]["y"]
            for item in child["geometries"]
            if item["type"] == "circle"
        )
        self.assertEqual(centers, [-8500.0, 8500.0])
        self.assertTrue(result["preview_paths"])
        self.assertEqual(result["variant"]["id"], child["id"])
        self.assertEqual(
            result["cad_edit_contract"]["operation"],
            "rearrange_layout",
        )
        self.assertEqual(
            result["cad_edit_contract"]["parameters"]["gap_mm"],
            2000.0,
        )

    def test_layout_followup_router_accepts_iteration_prompt(self) -> None:
        route = robot_agent._drawing_layout_followup_route(
            "基于“标准候选方案”继续优化。修改目标：长边并列排布，间距为2米",
            "advanced",
            [],
        )

        self.assertIsNotNone(route)
        self.assertEqual(route["decision_source"], "drawing_layout_followup")

        spacing_route = robot_agent._drawing_layout_followup_route(
            "基于“标准候选方案”继续优化。修改目标：间距改成3m",
            "advanced",
            [],
        )
        self.assertIsNotNone(spacing_route)
        self.assertEqual(
            spacing_route["decision_source"], "drawing_layout_followup"
        )

    def test_layout_followup_uses_previewed_variant_and_inherits_spacing(self) -> None:
        prompt = "规划一个标准篮球场与一个标准羽毛球场，用于地面划线"
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            requirements = parameterize_design(prompt)
            requirements["spacing_m"] = 3.0
            requirements["arrangement"] = "long_side_adjacent"
            requirements["peer_placement"] = "above"
            project = store.create(
                "篮球场与羽毛球场标准划线",
                prompt,
                requirements,
                {},
                [],
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                initial = robot_agent.generate_project_candidate(project["id"])
                self.assertTrue(initial["ok"], initial)
                parent = initial["variants"][0]
                # A second candidate makes the old implicit-parent path
                # ambiguous, matching the user's screenshot.
                store.add_variant(
                    project["id"], "另一个候选方案", parent["geometries"],
                    "用于测试候选切换", parent["assessment"],
                    preview_paths({"lines": parent["geometries"]}),
                )
                route = {
                    "name": "drawing_design",
                    "operation": "modify",
                    "decision_source": "drawing_layout_followup",
                    "selected_project_id": project["id"],
                    "selected_variant_id": parent["id"],
                }
                result = robot_agent.chat(
                    "改成短边并排，间距为不变，篮球场在左侧",
                    [], mode="advanced", route=route,
                )
                updated = store.get(project["id"])

        self.assertTrue(result["ok"], result)
        self.assertEqual(len(updated["variants"]), 3, result)
        child = updated["variants"][-1]
        self.assertEqual(child["parent_variant_id"], parent["id"])
        self.assertEqual(updated["requirements"]["spacing_m"], 3.0)
        self.assertEqual(updated["requirements"]["arrangement"], "short_side_adjacent")
        # Internal renderer direction is the secondary template's placement;
        # with basketball named as the primary object, "basketball on the
        # left" is normalized to the badminton instance on the right.
        self.assertEqual(updated["requirements"]["peer_placement"], "right")
        self.assertTrue(result["preview_paths"])

    def test_explicit_vertical_layout_rebuilds_badminton_court_above_basketball(self) -> None:
        prompt = "规划一个标准的篮球场与一个标准的羽毛球场，用于地面划线"
        requirements = parameterize_design(prompt)
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "篮球场+羽毛球场标准划线",
                prompt,
                requirements,
                {},
                [],
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                initial = robot_agent.generate_project_candidate(project["id"])
                self.assertTrue(initial["ok"], initial)
                parent = initial["variants"][0]
                store.begin_design_iteration(project["id"], parent["id"])
                message = "上下排列，间距为2m，并且羽毛球场在上方"
                route = robot_agent.resolve_intent(message, "advanced", [])
                route["object_memory"] = {
                    "objects": {"project": [{"id": project["id"]}]}
                }
                result = robot_agent.chat(message, [], mode="advanced", route=route)
                updated = store.get(project["id"])

        self.assertEqual(route["decision_source"], "drawing_layout_followup")
        self.assertTrue(result["ok"], result)
        child = updated["variants"][-1]
        basketball = [
            item for item in child["geometries"]
            if item.get("template_type") == "basketball"
        ]
        badminton = [
            item for item in child["geometries"]
            if item.get("template_type") == "badminton"
        ]
        basketball_bounds = calculate_geometry_bounds(basketball)["bounds"]
        badminton_bounds = calculate_geometry_bounds(badminton)["bounds"]
        self.assertAlmostEqual(
            badminton_bounds["min_y_mm"] - basketball_bounds["max_y_mm"],
            2000.0,
        )
        self.assertAlmostEqual(
            (badminton_bounds["min_x_mm"] + badminton_bounds["max_x_mm"]) / 2,
            (basketball_bounds["min_x_mm"] + basketball_bounds["max_x_mm"]) / 2,
        )

    def test_relative_template_addition_creates_two_badminton_courts(self) -> None:
        from app.agent_skills import calculate_geometry_bounds

        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "标准篮球场",
                "绘制一个标准篮球场",
                {
                    "shape": "basketball",
                    "quantity": 1,
                    "dimensions": {"width_m": 28.0, "height_m": 15.0},
                    "printer": "center",
                },
                {},
                [],
            )
            message = "在篮球场的上下方各添加一个羽毛球场"
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                initial = robot_agent.generate_project_candidate(project["id"])
                parent = initial["variants"][0]
                store.begin_design_iteration(project["id"], parent["id"])
                route = robot_agent.resolve_intent(message, "advanced", [])
                route["object_memory"] = {
                    "objects": {"project": [{"id": project["id"]}]}
                }
                result = robot_agent.chat(
                    message, [], mode="advanced", route=route
                )
                updated = store.get(project["id"])

        self.assertEqual(
            route["decision_source"], "drawing_relative_template_addition"
        )
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["cad_edit_contract"]["operation"], "add_template")
        self.assertEqual(
            result["cad_edit_contract"]["parameters"]["relative_positions"],
            ["above", "below"],
        )
        self.assertEqual(len(updated["variants"]), 2)
        child = updated["variants"][-1]
        self.assertEqual(child["parent_variant_id"], parent["id"])
        self.assertEqual(child["geometries"][:len(parent["geometries"])], parent["geometries"])
        badminton = [
            item for item in child["geometries"]
            if item.get("template_type") == "badminton"
        ]
        self.assertEqual(
            {item["template_instance"] for item in badminton}, {2, 3}
        )
        centers = []
        for instance in (2, 3):
            report = calculate_geometry_bounds([
                item for item in badminton
                if item["template_instance"] == instance
            ])
            bounds = report["bounds"]
            centers.append((bounds["min_y_mm"] + bounds["max_y_mm"]) / 2)
        self.assertEqual(sorted(centers), [-10550.0, 10550.0])
        self.assertTrue(result["preview_paths"])
        self.assertIn("各添加一个羽毛球场", result["message"])

    def test_relative_template_addition_allows_same_template_type(self) -> None:
        message = "在篮球场的上下方各添加一个篮球场"
        route = robot_agent.resolve_intent(message, "advanced", [])

        self.assertEqual(
            route["decision_source"], "drawing_relative_template_addition"
        )
        self.assertEqual(route["relative_addition"]["source_label"], "篮球场")
        self.assertEqual(route["relative_addition"]["target_label"], "篮球场")

    def test_new_parallel_basketball_request_is_not_layout_followup(self) -> None:
        prompt = "规划两个并排相连的篮球场"

        followup = robot_agent._drawing_layout_followup_route(
            prompt,
            "advanced",
            [],
        )
        route = robot_agent.resolve_intent(prompt, "advanced", [])

        self.assertIsNone(followup)
        self.assertEqual(route["name"], "drawing_design")
        self.assertEqual(route["operation"], "create")
        self.assertNotEqual(route["decision_source"], "drawing_layout_followup")

    def test_new_parallel_basketball_request_keeps_quantity_and_layout(self) -> None:
        from app.agent_skills import recognize_drawing_template

        match = recognize_drawing_template("规划两个并排相连的篮球场")

        self.assertIsNotNone(match)
        self.assertEqual(match["template"], "basketball")
        self.assertEqual(match["quantity"], 2)
        self.assertEqual(match["arrangement"], "long_side_adjacent")

    def test_spacing_change_phrase_creates_second_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "两个标准篮球场划线",
                "绘制两个标准篮球场，长边并列，间距2米",
                {
                    "shape": "basketball",
                    "dimensions": {"width_m": 28.0, "height_m": 15.0},
                    "quantity": 2,
                    "arrangement": "long_side_adjacent",
                    "spacing_m": 2.0,
                    "printer": "center",
                },
                {},
                [],
            )
            route = {
                "name": "drawing_design",
                "operation": "modify",
                "decision_source": "drawing_layout_followup",
                "object_memory": {
                    "objects": {"project": [{"id": project["id"]}]}
                },
            }
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                initial = robot_agent.generate_project_candidate(project["id"])
                parent = initial["variants"][0]
                store.begin_design_iteration(project["id"], parent["id"])
                result = robot_agent.chat(
                    "基于“标准候选方案”继续优化。修改目标：间距改成3m",
                    [],
                    mode="advanced",
                    route=route,
                )
                updated = store.get(project["id"])

        self.assertTrue(result["ok"], result)
        self.assertEqual(len(updated["variants"]), 2, result)
        child = updated["variants"][-1]
        centers = sorted(
            item["center"]["y"]
            for item in child["geometries"]
            if item["type"] == "circle"
        )
        self.assertEqual(centers, [-8500.0, 9500.0])
        self.assertEqual(child["geometries"][:19], parent["geometries"][:19])
        self.assertEqual(result["variant"]["id"], child["id"])
        self.assertTrue(result["preview_paths"])

    def test_parking_width_followup_rebuilds_stale_single_court_preview(self) -> None:
        from app.agent_skills import drawing_template_geometries, preview_paths, score_design_variant

        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "标准篮球场双场划线",
                "规划两个标准篮球场",
                {
                    "shape": "basketball",
                    "dimensions": {"width_m": 28.0, "height_m": 15.0},
                    "quantity": 2,
                    "printer": "center",
                },
                {},
                [],
            )
            single = drawing_template_geometries({
                "template": "basketball", "width_m": 28.0, "height_m": 15.0,
            })
            parent = store.add_variant(
                project["id"], "旧单场方案", single, "旧候选",
                score_design_variant(single), preview_paths({"lines": single}),
            )
            store.begin_design_iteration(project["id"], parent["id"])
            route = {
                "name": "drawing_design",
                "operation": "modify",
                "decision_source": "drawing_layout_followup",
                "object_memory": {"objects": {"project": [{"id": project["id"]}]}},
            }
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                result = robot_agent.chat(
                    "长边并排，间距预留一个停车位大小",
                    [], mode="advanced", route=route,
                )
                updated = store.get(project["id"])

        self.assertTrue(result["ok"], result)
        self.assertEqual(updated["requirements"]["quantity"], 2)
        self.assertEqual(updated["requirements"]["spacing_m"], 2.5)
        self.assertEqual(len(result["variant"]["geometries"]), 38)
        self.assertEqual(
            {item["template_instance"] for item in result["variant"]["geometries"]},
            {1, 2},
        )
        self.assertEqual(len(result["preview_paths"]), 38)

    def test_composite_layout_followup_rebuilds_candidate_and_preview(self) -> None:
        prompt = (
            "规划一个标准篮球场与一个标准羽毛球场，含场地边线、中线、"
            "中圈、罚球区及羽毛球场发球线，需给出两场地相对布局与间距。"
        )
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            requirements = parameterize_design(prompt)
            requirements["peer_placement"] = "right"
            requirements["spacing_reference"] = "standard_parking_space_width"
            project = store.create(
                "篮球场与羽毛球场场地划线",
                prompt,
                requirements,
                {},
                [],
            )
            route = {
                "name": "drawing_design",
                "operation": "modify",
                "decision_source": "drawing_layout_followup",
                "object_memory": {
                    "objects": {"project": [{"id": project["id"]}]}
                },
            }
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                initial = robot_agent.generate_project_candidate(project["id"])
                self.assertTrue(initial["ok"], initial)
                result = robot_agent.chat(
                    "长边并排，间距为2m",
                    [],
                    mode="advanced",
                    route=route,
                )
                updated = store.get(project["id"])

        self.assertTrue(result["ok"], result)
        self.assertEqual(updated["requirements"]["arrangement"], "long_side_adjacent")
        self.assertEqual(updated["requirements"]["spacing_m"], 2.0)
        self.assertIsNone(updated["requirements"].get("peer_placement"))
        self.assertIsNone(updated["requirements"].get("spacing_reference"))
        self.assertEqual(len(updated["variants"]), 2)
        self.assertEqual(result["variant"]["id"], updated["variants"][-1]["id"])
        self.assertTrue(result["preview_paths"])
        geometries = result["variant"]["geometries"]
        basketball = [
            item for item in geometries
            if item.get("template_type") == "basketball"
        ]
        badminton = [
            item for item in geometries
            if item.get("template_type") == "badminton"
        ]
        basketball_bounds = calculate_geometry_bounds(basketball)["bounds"]
        badminton_bounds = calculate_geometry_bounds(badminton)["bounds"]
        self.assertAlmostEqual(
            badminton_bounds["min_y_mm"] - basketball_bounds["max_y_mm"],
            2000.0,
        )

    def test_identical_iteration_candidate_is_not_saved(self) -> None:
        from app.agent_skills import preview_paths, score_design_variant

        geometries = [{
            "id": 1,
            "type": "line",
            "layer_id": 1,
            "start": {"x": 0.0, "y": 0.0, "z": 0.0},
            "end": {"x": 3000.0, "y": 0.0, "z": 0.0},
        }]
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "直线方案",
                "生成一条三米直线",
                {"shape": "line", "dimensions": {"length_m": 3.0}, "printer": "center"},
                {},
                [],
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                parent = store.add_variant(
                    project["id"],
                    "原始方案",
                    geometries,
                    "有效父方案",
                    score_design_variant(geometries),
                    preview_paths({"lines": geometries}),
                )
                store.begin_design_iteration(project["id"], parent["id"])
                output = robot_agent._execute_safe(
                    "add_design_variant",
                    {
                        "project_id": project["id"],
                        "parent_variant_id": parent["id"],
                        "name": "没有变化的方案",
                        "geometries": parent["geometries"],
                        "rationale": "模型没有实际修改几何",
                    },
                    mode="advanced",
                )

            updated = store.get(project["id"])

        self.assertFalse(output["ok"])
        self.assertEqual(len(updated["variants"]), 1)
        self.assertNotIn("已生成", output["message"])

    def test_streaming_iteration_returns_new_scaled_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "标准篮球场划线",
                "绘制标准篮球场",
                {
                    "shape": "basketball",
                    "dimensions": {"width_m": 28.0, "height_m": 15.0},
                    "printer": "center",
                },
                {},
                [],
            )
            route = {
                "name": "drawing_design",
                "operation": "modify",
                "object_memory": {
                    "objects": {"project": [{"id": project["id"]}]}
                },
            }
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                initial = robot_agent.generate_project_candidate(project["id"])
                store.begin_design_iteration(project["id"], initial["variants"][0]["id"])
                events = list(robot_agent.chat_stream(
                    "将篮球场扩大一倍", [], mode="advanced", route=route
                ))

            updated = store.get(project["id"])

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "result")
        self.assertTrue(events[0]["ok"])
        self.assertTrue(events[0]["preview_paths"])
        self.assertEqual(len(updated["variants"]), 2)
        self.assertEqual(events[0]["cad_edit_contract"]["operation"], "scale")

    def test_path_preview_is_promoted_to_agent_response(self) -> None:
        path_preview = {
            "contract_version": "path-preview-1.0",
            "status": "preview_ready",
            "printing_paths": [{
                "namespace": "drawing_preview",
                "frame_id": "map",
                "route_type": "printing",
                "points": [[0.0, 0.0], [1.0, 0.0]],
            }],
            "transition_paths": [],
            "transition_status": "pending_ros2_replan",
            "requires_ros2_replan": True,
            "execution_allowed": False,
        }
        summary = robot_agent._tool_result_summary(
            "modify_drawing", {"ok": True, "path_preview": path_preview}
        )
        response = robot_agent._result(
            "图纸已修改。", robot_agent._empty_usage(), tool_results=[summary]
        )

        self.assertEqual(response["path_preview"], path_preview)
        self.assertEqual(response["preview_paths"], path_preview["printing_paths"])

    def test_drawing_modification_previews_before_apply_and_saves_after_confirm(self) -> None:
        source_name = f"preview_source_{time.time_ns()}.json"
        source = {
            "schema_version": "1.0",
            "unit": "mm",
            "lines": [{
                "id": 1,
                "type": "line",
                "layer_id": 1,
                "start": {"x": 0, "y": 0, "z": 0},
                "end": {"x": 1000, "y": 0, "z": 0},
            }],
        }
        arguments = {
            "source_file_name": source_name,
            "operations": [{
                "op": "update",
                "id": 1,
                "geometry": {
                    "type": "line",
                    "layer_id": 1,
                    "start": {"x": 0, "y": 0, "z": 0},
                    "end": {"x": 2000, "y": 0, "z": 0},
                },
            }],
            "operation_id": f"preview-{time.time_ns()}",
        }
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"XLINE_CAD_DIR": directory}),
        ):
            Path(directory, source_name).write_text(
                json.dumps(source), encoding="utf-8"
            )

            pending = robot_agent._register_pending(
                "modify_drawing", arguments, mode="advanced"
            )
            saved_before_confirm = list(Path(directory).glob("*_v*.json"))

            self.assertEqual(pending["preview_status"], "ready")
            self.assertEqual(pending["review"]["result"]["status"], "preview_pending")
            self.assertTrue(pending["command_batch"]["verified"])
            self.assertIn(
                "modified", {item["diff_kind"] for item in pending["preview_paths"]}
            )
            self.assertIn(
                "modified_before",
                {item["diff_kind"] for item in pending["preview_paths"]},
            )
            self.assertEqual(saved_before_confirm, [])

            result = robot_agent.confirm(pending["id"], True)

            self.assertTrue(result["ok"])
            self.assertTrue(Path(directory, result["file_name"]).exists())
            self.assertEqual(result["command_batch"]["batch_id"], pending["command_batch"]["batch_id"])
            self.assertEqual(result["version"]["geometry_diff"], result["geometry_diff"])
            self.assertEqual(result["version"]["path_impact"], result["path_impact"])

    def test_cancelled_drawing_modification_does_not_save_version(self) -> None:
        source_name = f"cancel_source_{time.time_ns()}.json"
        source = {
            "schema_version": "1.0",
            "unit": "mm",
            "lines": [{
                "id": 1,
                "type": "line",
                "layer_id": 1,
                "start": {"x": 0, "y": 0, "z": 0},
                "end": {"x": 1000, "y": 0, "z": 0},
            }],
        }
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"XLINE_CAD_DIR": directory}),
        ):
            Path(directory, source_name).write_text(
                json.dumps(source), encoding="utf-8"
            )
            pending = robot_agent._register_pending(
                "modify_drawing",
                {
                    "source_file_name": source_name,
                    "operations": [{"op": "remove", "id": 1}],
                },
                mode="advanced",
            )

            result = robot_agent.confirm(pending["id"], False)

            self.assertTrue(result["ok"])
            self.assertEqual(list(Path(directory).glob("*_v*.json")), [])

    def test_empty_design_variant_cannot_report_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "空方案", "生成方案", {"printer": "center"}, {}, []
            )
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                output = robot_agent._execute_safe(
                    "add_design_variant",
                    {
                        "project_id": project["id"],
                        "name": "空方案",
                        "geometries": [],
                        "rationale": "无有效路径",
                    },
                    mode="advanced",
                )

        self.assertFalse(output["ok"])
        self.assertEqual(store.get(project["id"])["variants"], [])
        self.assertNotIn("已生成", output["message"])

    def test_rectangle_request_creates_selected_creative_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                result = robot_agent._local_intent("规划一个 5×3 米矩形")

            self.assertIsNotNone(result)
            self.assertIsNone(result["pending_action"])
            projects = store.list()
            self.assertEqual(len(projects), 1)
            self.assertEqual(projects[0]["status"], "ready_for_planning")
            self.assertEqual(projects[0]["requirements"]["dimensions"]["width_m"], 5.0)

    def test_confirm_design_generation_returns_project_and_preview_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "演示矩形",
                "设计一个 5x3 米矩形",
                {
                    "shape": "rectangle",
                    "dimensions": {"width_m": 5.0, "height_m": 3.0},
                    "printer": "center",
                },
                {},
                [],
            )
            route = {
                "object_memory": {
                    "objects": {
                        "project": [{"type": "project", "id": project["id"]}]
                    }
                },
                "retrieved_memory": {},
            }
            steps=[{'op':'add_rectangle','step_id':'rectangle','output_ref':'rectangle',
                'origin':{'x':0,'y':0},'width':5,'height':3,'semantic':{'label':'矩形'}}]
            with patch("app.agent_service.get_creative_project_store", return_value=store),structured_plan_provider(steps) as provider:
                result = robot_agent._deterministic_design_confirmation(
                    "确认生成", route
                )
                self.assertEqual(provider['request_attempts'],1)

            self.assertTrue(result["ok"])
            self.assertEqual(result["next_action"], "select_design_variant")
            self.assertEqual(result["project_id"], project["id"])
            self.assertTrue(result["preview_paths"])
            self.assertTrue(result["drawing_json"]["lines"])
            self.assertEqual(len(result["variants"]), 1)
            self.assertEqual(store.get(project["id"])["status"], "designing")

    def test_confirm_design_generation_does_not_generate_without_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "待补充图纸",
                "设计一个矩形",
                {"shape": "rectangle"},
                {},
                ["dimensions"],
            )
            route = {
                "object_memory": {
                    "objects": {
                        "project": [{"type": "project", "id": project["id"]}]
                    }
                },
                "retrieved_memory": {},
            }
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                result = robot_agent._deterministic_design_confirmation(
                    "确认生成候选方案", route
                )

            self.assertFalse(result["ok"])
            self.assertIn("dimensions", result["message"])
            self.assertEqual(store.get(project["id"])["variants"], [])
            self.assertEqual(store.get(project["id"])["status"], "clarifying")

    def test_stream_design_confirmation_bypasses_empty_deepseek_response(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "流式矩形",
                "设计一个 4x2 米矩形",
                {
                    "shape": "rectangle",
                    "dimensions": {"width_m": 4.0, "height_m": 2.0},
                    "printer": "center",
                },
                {},
                [],
            )
            route = {
                "object_memory": {
                    "objects": {
                        "project": [{"type": "project", "id": project["id"]}]
                    }
                },
                "retrieved_memory": {},
            }
            with (
                patch("app.agent_service.get_creative_project_store", return_value=store),
                structured_plan_provider([{'op':'add_rectangle','step_id':'rectangle','output_ref':'rectangle',
                    'origin':{'x':0,'y':0},'width':4,'height':2,'semantic':{'label':'矩形'}}]),
                patch.object(robot_agent, "mode", "deepseek"),
                patch.object(
                    robot_agent,
                    "_deepseek_response",
                    side_effect=AssertionError("不应调用模型"),
                ),
            ):
                events = list(robot_agent.chat_stream(
                    "确认生成",
                    [],
                    mode="advanced",
                    route=route,
                ))

            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["type"], "result")
            self.assertTrue(events[0]["preview_paths"])
            self.assertNotIn("空内容", events[0]["message"])

    def test_bare_confirmation_from_requirement_card_generates_without_model_tool_call(self) -> None:
        """The requirement card sends `确认` without repeating the design prompt."""
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "篮球场与羽毛球场长边并排布局",
                "规划一个标准篮球场和一个标准羽毛球场，长边并排，间距2米",
                {
                    "shape": "basketball",
                    "dimensions": {"width_m": 28.0, "height_m": 15.0},
                    "printer": "center",
                },
                {},
                [],
            )
            route = {
                "name": "conversation",
                "operation": "query",
                "selected_project_id": project["id"],
                "object_memory": {},
                "retrieved_memory": {},
            }
            with (
                patch("app.agent_service.get_creative_project_store", return_value=store),
                patch.object(
                    robot_agent,
                    "_deepseek_response",
                    side_effect=AssertionError("待生成项目的短确认不应调用模型"),
                ),
            ):
                events = list(robot_agent.chat_stream(
                    "确认",
                    [],
                    mode="advanced",
                    route=route,
                ))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "result")
        self.assertTrue(events[0]["ok"], events[0])
        self.assertTrue(events[0].get("preview_paths"), events[0])
        self.assertIn("候选方案", events[0]["message"])

    def test_advanced_empty_model_response_uses_project_stage_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "篮球场",
                "标准篮球场",
                {
                    "shape": "basketball",
                    "dimensions": {"width_m": 28.0, "height_m": 15.0},
                    "printer": "center",
                },
                {},
                [],
            )
            route = {
                "object_memory": {
                    "objects": {
                        "project": [{"type": "project", "id": project["id"]}]
                    }
                }
            }
            with patch("app.agent_service.get_creative_project_store", return_value=store):
                result = robot_agent._advanced_empty_response(
                    route, robot_agent._empty_usage()
                )

        self.assertTrue(result["ok"])
        self.assertEqual(result["message"], "设计要求已确认，可以生成候选方案。")
        self.assertNotIn("空内容", result["message"])

    def test_deepseek_design_selection_excludes_legacy_direct_save_tools(self) -> None:
        tools = robot_agent._selected_deepseek_tools("设计一个 5x3 米矩形")
        names = {item["function"]["name"] for item in tools}

        self.assertIn("create_creative_project", names)
        self.assertNotIn("add_design_variant", names)
        self.assertNotIn("create_drawing", names)
        self.assertNotIn("create_rectangle_drawing", names)

    def test_legacy_rectangle_direct_save_is_retired(self) -> None:
        """create_rectangle_drawing 直接保存链路已退役。

        工具规格与执行器均已移除，矩形生成统一走 add_design_variant /
        正式构造的候选流水线；确认执行旧动作应被授权层拒绝。
        """
        action = PendingAction(
            name="create_rectangle_drawing",
            arguments={"width_m": 5.0, "height_m": 3.0},
            expires_at=datetime.now() + timedelta(minutes=1),
        )
        with tempfile.TemporaryDirectory() as directory:
            result = robot_agent._execute_confirmed(action)

        self.assertFalse(result["ok"])
        self.assertTrue(
            "不允许" in str(result.get("message") or "")
            or "未知" in str(result.get("message") or "")
            or "不存在" in str(result.get("message") or "")
        )

    def test_virtual_preview_planning_never_starts_motion(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"XLINE_CAD_DIR": directory}),
            patch.object(robot_state, "bridge_mode", "virtual_ros2"),
            patch.object(robot_state, "mission_running", True),
            patch.object(robot_state, "planned_paths", [{"points": [[0, 0], [1, 0]]}]),
        ):
            Path(directory, "agent_preview.json").write_text(
                json.dumps({
                    "lines": [{
                        "id": 1,
                        "type": "line",
                        "start": {"x": 0, "y": 0},
                        "end": {"x": 1000, "y": 0},
                    }],
                }),
                encoding="utf-8",
            )
            accepted = ros_adapter.prepare_mission("agent_preview.json")
            self.assertTrue(accepted)
            self.assertFalse(robot_state.mission_running)
            self.assertEqual(robot_state.mission_stage, "ready")
            self.assertEqual(robot_state.mission_file, "agent_preview.json")
            route_types = [item["route_type"] for item in robot_state.planned_paths]
            self.assertIn("printing", route_types)

    def test_agent_can_start_a_user_saved_drawing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            file_name = "app_drawing_user.json"
            Path(directory, file_name).write_text(
                json.dumps({"lines": []}), encoding="utf-8"
            )
            action = PendingAction(
                name="set_mission",
                arguments={"running": True, "file_name": file_name},
                expires_at=datetime.now() + timedelta(minutes=1),
            )
            with (
                patch.dict(os.environ, {"XLINE_CAD_DIR": directory}),
                patch.object(robot_state, "mission_nodes_ready", True),
                patch.object(robot_state, "control_owner", "test-client"),
                patch.object(robot_state, "control_ready", True),
                patch.object(robot_state, "localization_valid", True),
                patch.object(robot_state, "emergency_stopped", False),
                patch.object(ros_adapter, "control_mission", return_value=True) as control,
            ):
                result = robot_agent._execute_confirmed(action)

            self.assertTrue(result["ok"])
            control.assert_called_once_with(True, file_name)

    def test_agent_drive_matches_installed_vehicle_orientation(self) -> None:
        action = PendingAction(
            name="drive_robot",
            arguments={"linear": 0.1, "angular": 0.2, "duration_seconds": 0.2},
            expires_at=datetime.now() + timedelta(minutes=1),
        )
        with (
            patch.object(robot_state, "control_owner", "test-client"),
            patch.object(robot_state, "control_ready", True),
            patch.object(robot_state, "emergency_stopped", False),
            patch.object(robot_state, "mission_running", False),
            patch.object(
                ros_adapter, "publish_timed_velocity", return_value=True
            ) as publish,
        ):
            result = robot_agent._execute_confirmed(action)

        self.assertTrue(result["ok"])
        # xline_ws3 follows the standard ROS2 convention: positive
        # linear.x is forward and positive angular.z is left.
        publish.assert_called_once_with(0.1, 0.2, 0.2)

    def test_forward_distance_creates_confirmable_drive_action(self) -> None:
        result = robot_agent._local_intent("前进3米")

        self.assertTrue(result["ok"])
        action = result["pending_action"]
        self.assertEqual(action["name"], "drive_robot")
        self.assertEqual(action["arguments"], {
            "linear": 0.1,
            "angular": 0.0,
            "duration_seconds": 30.0,
        })

    def test_long_drive_is_automatically_segmented(self) -> None:
        result = robot_agent._local_intent("向前走4米")

        self.assertTrue(result["ok"])
        action = result["pending_action"]
        self.assertEqual(action["name"], "drive_sequence")
        self.assertEqual(len(action["arguments"]["steps"]), 2)
        self.assertEqual(sum(step["duration_seconds"] for step in action["arguments"]["steps"]), 40.0)

    def test_forward_distance_creates_confirmable_drive_action(self) -> None:
        result = robot_agent._local_intent("\u524d\u8fdb3\u7c73")

        self.assertTrue(result["ok"])
        action = result["pending_action"]
        self.assertEqual(action["name"], "drive_robot")
        self.assertEqual(action["arguments"], {
            "linear": 0.1,
            "angular": 0.0,
            "duration_seconds": 30.0,
        })

    def test_long_drive_unicode_input_is_automatically_segmented(self) -> None:
        result = robot_agent._local_intent("\u5411\u524d\u8d704\u7c73")

        self.assertTrue(result["ok"])
        action = result["pending_action"]
        self.assertEqual(action["name"], "drive_sequence")
        self.assertEqual(len(action["arguments"]["steps"]), 2)

    def test_stop_tool_cancels_agent_motion(self) -> None:
        with patch.object(
            ros_adapter, "stop_agent_motion", return_value=True
        ) as stop_motion:
            result = robot_agent._execute_safe("stop_robot", {})

        self.assertTrue(result["ok"])
        stop_motion.assert_called_once_with("AI stop tool requested")

    def test_timed_agent_motion_automatically_stops(self) -> None:
        with (
            patch.object(robot_state, "control_owner", "test-client"),
            patch.object(robot_state, "control_lease_expires_at", time.time() + 3),
            patch.object(robot_state, "control_ready", True),
            patch.object(robot_state, "emergency_stopped", False),
            patch.object(robot_state, "mission_running", False),
        ):
            started = ros_adapter.publish_timed_velocity(-0.05, 0.0, 0.25)
            self.assertTrue(started)
            self.assertTrue(robot_state.agent_motion_active)
            time.sleep(0.45)
            self.assertFalse(robot_state.agent_motion_active)
            self.assertEqual(robot_state.last_command.get("linear"), 0.0)
            self.assertEqual(robot_state.agent_motion_outcome, "completed")

        ros_adapter.fail_safe_stop("test cleanup")

    def test_motion_verification_waits_for_normal_completion(self) -> None:
        result = {"ok": True, "estimated_duration_seconds": 5.0}
        before = {"last_velocity_command_at": "before"}
        with (
            patch.object(robot_state, "agent_motion_active", True),
            patch.object(robot_state, "agent_motion_outcome", "running"),
            patch.object(robot_state, "last_velocity_command_at", "after"),
        ):
            running = robot_agent._validate_tool_result(
                "drive_robot", {"duration_seconds": 5.0}, result, before
            )
        self.assertEqual(running["status"], "pending")
        self.assertFalse(running["verified"])

        with (
            patch.object(robot_state, "agent_motion_active", False),
            patch.object(robot_state, "agent_motion_outcome", "completed"),
            patch.object(robot_state, "last_velocity_command_at", "after"),
        ):
            completed = robot_agent._validate_tool_result(
                "drive_robot", {"duration_seconds": 5.0}, result, before
            )
        self.assertEqual(completed["status"], "success")
        self.assertTrue(completed["verified"])

    def test_operator_stop_is_cancelled_instead_of_failed(self) -> None:
        result = {"ok": True, "estimated_duration_seconds": 5.0}
        before = {"last_velocity_command_at": "before"}
        with (
            patch.object(robot_state, "agent_motion_active", False),
            patch.object(robot_state, "agent_motion_outcome", "stopped"),
            patch.object(
                robot_state,
                "agent_motion_completion_reason",
                "AI motion stopped by operator",
            ),
            patch.object(robot_state, "last_velocity_command_at", "after"),
        ):
            cancelled = robot_agent._validate_tool_result(
                "drive_robot", {"duration_seconds": 5.0}, result, before
            )

        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled["reason_code"], "operator_cancelled")
        self.assertIn("按你的要求停止", cancelled["message"])

    def test_safety_stop_remains_a_failure(self) -> None:
        with (
            patch.object(robot_state, "agent_motion_active", False),
            patch.object(robot_state, "agent_motion_outcome", "stopped"),
            patch.object(
                robot_state,
                "agent_motion_completion_reason",
                "AI motion safety condition lost",
            ),
        ):
            failed = robot_agent._validate_tool_result(
                "drive_robot", {"duration_seconds": 5.0}, {"ok": True}, {}
            )

        self.assertEqual(failed["status"], "failed")

    def test_mission_verification_waits_until_the_same_mission_completes(self) -> None:
        arguments = {"file_name": "court.json"}
        result = {"ok": True}
        with (
            patch.object(robot_state, "mission_file", "court.json"),
            patch.object(robot_state, "mission_running", True),
            patch.object(robot_state, "mission_stage", "executing"),
            patch.object(robot_state, "mission_completed", 2),
            patch.object(robot_state, "mission_total", 8),
        ):
            executing = robot_agent._validate_tool_result(
                "execute_prepared_mission", arguments, result, {}
            )
        self.assertEqual(executing["status"], "pending")
        self.assertFalse(executing["verified"])
        self.assertEqual(executing["observed"]["mission_completed"], 2)

        with (
            patch.object(robot_state, "mission_file", "court.json"),
            patch.object(robot_state, "mission_running", False),
            patch.object(robot_state, "mission_stage", "completed"),
            patch.object(robot_state, "mission_completed", 8),
            patch.object(robot_state, "mission_total", 8),
        ):
            completed = robot_agent._validate_tool_result(
                "execute_prepared_mission", arguments, result, {}
            )
        self.assertEqual(completed["status"], "success")
        self.assertTrue(completed["verified"])

    def test_user_cancelled_mission_is_not_reported_as_execution_failure(self) -> None:
        arguments = {"file_name": "court.json"}
        with (
            patch.object(robot_state, "mission_file", "court.json"),
            patch.object(robot_state, "mission_running", False),
            patch.object(robot_state, "mission_stage", "cancelled"),
        ):
            cancelled = robot_agent._validate_tool_result(
                "execute_prepared_mission", arguments, {"ok": True}, {}
            )

        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled["reason_code"], "user_cancelled")
        self.assertFalse(cancelled["verified"])
        self.assertIn("用户取消", cancelled["message"])

    def test_mission_verification_rejects_a_different_running_drawing(self) -> None:
        with (
            patch.object(robot_state, "mission_file", "other.json"),
            patch.object(robot_state, "mission_running", True),
            patch.object(robot_state, "mission_stage", "executing"),
        ):
            verification = robot_agent._validate_tool_result(
                "execute_prepared_mission",
                {"file_name": "court.json"},
                {"ok": True},
                {},
            )
        self.assertEqual(verification["status"], "failed")
        self.assertFalse(verification["verified"])

    def test_agent_rejects_unknown_drawing(self) -> None:
        action = PendingAction(
            name="set_mission",
            arguments={"running": True, "file_name": "missing.json"},
            expires_at=datetime.now() + timedelta(minutes=1),
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(os.environ, {"XLINE_CAD_DIR": directory}),
            patch.object(robot_state, "mission_nodes_ready", True),
            patch.object(robot_state, "control_owner", "test-client"),
            patch.object(robot_state, "control_ready", True),
            patch.object(robot_state, "localization_valid", True),
            patch.object(robot_state, "emergency_stopped", False),
        ):
            result = robot_agent._execute_confirmed(action)

        self.assertFalse(result["ok"])
        self.assertIn("图纸不存在", result["message"])


if __name__ == "__main__":
    unittest.main()
