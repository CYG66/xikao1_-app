from __future__ import annotations


def test_project_owner_persists_without_guessing_legacy_owner(tmp_path):
    from app.creative_projects import CreativeProjectStore
    path = tmp_path / 'owners.json'
    store = CreativeProjectStore(path)
    owned = store.create('owned', 'draw', owner_conversation_id='conversation-a')
    unowned = store.create('legacy', 'draw')
    loaded = CreativeProjectStore(path)
    assert loaded.get(owned['id'])['owner_conversation_id'] == 'conversation-a'
    assert loaded.get(unowned['id'])['owner_conversation_id'] is None


def test_supplementing_active_design_keeps_parent_and_project(tmp_path):
    from app.creative_projects import CreativeProjectStore
    store = CreativeProjectStore(tmp_path / 'projects.json')
    project = store.create('court', 'draw a court')
    parent = store.add_variant(
        project['id'], 'base', [{'id': 1}], 'base', {}, [],
        acceptance_summary={'status': 'passed', 'review_required': False},
    )
    active = store.begin_design_iteration(project['id'], parent['id'])
    assert active['status'] == 'designing'
    updated = store.update(project['id'], requirements={'added_shapes': [
        {'shape': 'rectangle', 'width_m': 2, 'height_m': 1},
    ]}, missing_parameters=[])
    assert updated is not None
    assert updated['status'] == 'designing'
    assert updated['design_base_variant_id'] == parent['id']
    assert store.get(project['id'])['requirements']['added_shapes'][0]['width_m'] == 2
    waiting = store.update(project['id'], missing_parameters=['rectangle size'])
    assert waiting['status'] == 'clarifying'
    resumed = store.update(project['id'], missing_parameters=[])
    assert resumed['status'] == 'designing'
    assert resumed['design_base_variant_id'] == parent['id']

import json
import tempfile
import unittest
from pathlib import Path

from app.creative_projects import CreativeProjectStore
from app.geometry_identity import (
    normalize_geometry_identity,
    validate_identity_continuity,
)
from app.cad_revision import verify_variant_revision_for_planning


ACCEPTED = {
    "status": "passed", "review_required": False,
    "authority": "backend_measured_geometry", "source": "test_geometry_acceptance",
}


class CreativeProjectStoreTest(unittest.TestCase):
    def test_terminal_execution_can_start_a_new_design_iteration(self) -> None:
        for terminal_stage, terminal_status in (
            ("completed", "completed"),
            ("cancelled", "cancelled"),
            ("interrupted", "execution_failed"),
        ):
            with self.subTest(stage=terminal_stage), tempfile.TemporaryDirectory() as directory:
                store = CreativeProjectStore(Path(directory) / "projects.json")
                project = store.create("篮球场", "创建篮球场")
                parent = store.add_variant(
                    project["id"], "方案 A", [{"id": 1}], "初始方案",
                    {"score": 90}, [], acceptance_summary=ACCEPTED,
                )
                store.select_variant(project["id"], parent["id"])
                store.set_planning(project["id"], {
                    "stage": "planning_preview",
                    "validation": {},
                    "file_name": "court.json",
                })
                store.set_planning(project["id"], {
                    "stage": "ready",
                    "validation": {"ok": True},
                    "file_name": "court.json",
                })
                store.set_execution(project["id"], {
                    "stage": "pending_confirmation", "action_id": "action-1",
                })
                store.set_execution(project["id"], {
                    "stage": "executing", "action_id": "action-1",
                })
                ended = store.set_execution(project["id"], {
                    "stage": terminal_stage, "action_id": "action-1",
                })
                store.set_report(project["id"], {"verdict": terminal_stage})

                self.assertEqual(ended["status"], terminal_status)
                reopened = store.begin_design_iteration(project["id"], parent["id"])

                self.assertIsNotNone(reopened)
                self.assertEqual(reopened["status"], "designing")
                self.assertEqual(reopened["design_base_variant_id"], parent["id"])
                self.assertNotIn("selected_variant_id", reopened)
                self.assertNotIn("planning", reopened)
                self.assertNotIn("execution", reopened)
                self.assertNotIn("acceptance_report", reopened)
                archived = reopened["iteration_history"][-1]
                self.assertEqual(archived["status"], terminal_status)
                self.assertEqual(archived["execution"]["stage"], terminal_stage)
                self.assertEqual(archived["acceptance_report"]["verdict"], terminal_stage)

    def test_active_or_paused_execution_cannot_start_design_iteration(self) -> None:
        for execution_stage in ("executing", "paused"):
            with self.subTest(stage=execution_stage), tempfile.TemporaryDirectory() as directory:
                store = CreativeProjectStore(Path(directory) / "projects.json")
                project = store.create("篮球场", "创建篮球场")
                parent = store.add_variant(
                    project["id"], "方案 A", [{"id": 1}], "初始方案",
                    {"score": 90}, [], acceptance_summary=ACCEPTED,
                )
                store.select_variant(project["id"], parent["id"])
                store.set_planning(project["id"], {
                    "stage": "planning_preview", "validation": {},
                })
                store.set_planning(project["id"], {
                    "stage": "ready", "validation": {"ok": True},
                })
                store.set_execution(project["id"], {
                    "stage": "pending_confirmation", "action_id": "action-1",
                })
                store.set_execution(project["id"], {
                    "stage": "executing", "action_id": "action-1",
                })
                if execution_stage == "paused":
                    store.set_execution(project["id"], {
                        "stage": "paused", "action_id": "action-1",
                    })

                reopened = store.begin_design_iteration(project["id"], parent["id"])

                self.assertIsNone(reopened)

    def test_iteration_does_not_replace_confirmed_quantity_with_stale_variant(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "双场", "两个篮球场", {"quantity": 2}, {}, [],
            )
            parent = store.add_variant(
                project["id"], "旧单场", [
                    {"id": 1, "type": "line", "template_instance": 1},
                ], "旧候选", {}, [], acceptance_summary=ACCEPTED,
            )

            updated = store.begin_design_iteration(project["id"], parent["id"])

        self.assertEqual(updated["requirements"]["quantity"], 2)

    def test_iteration_restores_quantity_declared_by_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create("版本数量", "四个房间", {"quantity": 2}, {}, [])
            parent = store.add_variant(
                project["id"], "四个房间", [
                    {"id": index, "type": "line", "template_instance": index}
                    for index in range(1, 5)
                ], "正式版本", {}, [], expected_quantity=4,
                acceptance_summary=ACCEPTED,
            )

            updated = store.begin_design_iteration(project["id"], parent["id"])

        self.assertEqual(parent["expected_quantity"], 4)
        self.assertEqual(updated["requirements"]["quantity"], 4)

    def test_variant_persists_logical_objects_and_shared_topology(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "projects.json"
            store = CreativeProjectStore(path)
            project = store.create("车位", "绘制两个相连车位")
            geometries = [
                {"id": 1, "type": "line", "template_instance": 1},
                {"id": 2, "type": "line", "template_instance": 1},
                {"id": 3, "type": "line", "template_instance": 1},
            ]
            logical_objects = [
                {"object_id": "parking-space-1", "object_type": "parking_space",
                 "label": "左侧车位", "geometry_refs": [1, 2]},
                {"object_id": "parking-space-2", "object_type": "parking_space",
                 "label": "右侧车位", "geometry_refs": [2, 3]},
            ]
            topology = {
                "schema_version": "cad.topology.v1",
                "shared_geometries": [{
                    "geometry_id": 2,
                    "object_ids": ["parking-space-1", "parking-space-2"],
                    "relation": "shared_boundary",
                }],
                "relations": [],
            }

            variant = store.add_variant(
                project["id"], "共享边界方案", geometries, "", {}, [],
                logical_objects=logical_objects, topology=topology,
            )

            self.assertEqual(variant["logical_objects"], logical_objects)
            self.assertEqual(variant["topology"], topology)
            restored = CreativeProjectStore(path)
            saved = restored.get(project["id"])["variants"][0]
            self.assertEqual(saved["logical_objects"], logical_objects)
            self.assertEqual(saved["topology"], topology)

    def test_modified_candidate_must_match_verified_revision_before_selection(self) -> None:
        geometry = {
            "id": 1, "type": "line", "layer_id": 1,
            "start": {"x": 0, "y": 0, "z": 0},
            "end": {"x": 1000, "y": 0, "z": 0},
        }
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create("线段", "创建线段")
            parent = store.add_variant(
                project["id"], "原始", [geometry], "初始",
                {"score": 90, "feasibility": {"ok": True, "errors": []}},
                [[[0, 0], [1, 0]]], acceptance_summary=ACCEPTED,
            )
            unchanged = store.add_variant(
                project["id"], "无效修改", [geometry], "没有实际变化",
                {"score": 90, "feasibility": {"ok": True, "errors": []}},
                [[[0, 0], [1, 0]]], parent_variant_id=parent["id"],
            )

            self.assertEqual(unchanged["revision_contract"]["status"], "invalid")
            self.assertIsNone(store.select_variant(project["id"], unchanged["id"]))
            self.assertIsNone(store.get(project["id"]).get("selected_variant_id"))

    def test_planning_rejects_tampered_logical_object_graph(self) -> None:
        source = [{
            "id": 1, "type": "line", "layer_id": 1,
            "start": {"x": 0, "y": 0, "z": 0},
            "end": {"x": 1000, "y": 0, "z": 0},
        }]
        target = [{**source[0], "end": {"x": 1500, "y": 0, "z": 0}}]
        objects = [{
            "object_id": "line-1", "object_type": "line",
            "label": "线段 1", "geometry_refs": [1],
        }]
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create("线段", "创建线段")
            parent = store.add_variant(
                project["id"], "原始", source, "", {"score": 90}, [],
                logical_objects=objects, acceptance_summary=ACCEPTED,
            )
            child = store.add_variant(
                project["id"], "加长", target, "", {"score": 90}, [],
                parent_variant_id=parent["id"], logical_objects=objects,
            )
        self.assertEqual(child["revision_contract"]["status"], "verified")
        child["logical_objects"][0]["label"] = "被篡改的名称"
        verified = verify_variant_revision_for_planning(child)
        self.assertFalse(verified["ok"])
        self.assertFalse(verified["checks"]["logical_objects"])

    def test_invalid_logical_graph_is_not_saved(self) -> None:
        geometry = {
            "id": 1, "type": "line", "layer_id": 1,
            "start": {"x": 0, "y": 0, "z": 0},
            "end": {"x": 1000, "y": 0, "z": 0},
        }
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create("线段", "创建线段")
            variant = store.add_variant(
                project["id"], "无效对象图", [geometry], "", {"score": 90}, [],
                logical_objects=[{
                    "object_id": "line-1", "object_type": "line",
                    "label": "线段 1", "geometry_refs": [99],
                }],
            )
            saved = store.get(project["id"])
        self.assertIsNone(variant)
        self.assertEqual(saved["variants"], [])

    def test_non_target_logical_drift_is_not_saved(self) -> None:
        source = [
            {"id": 1, "type": "line", "layer_id": 1, "template_instance": 1,
             "start": {"x": 0, "y": 0, "z": 0},
             "end": {"x": 1000, "y": 0, "z": 0}},
            {"id": 2, "type": "line", "layer_id": 1, "template_instance": 2,
             "start": {"x": 2000, "y": 0, "z": 0},
             "end": {"x": 3000, "y": 0, "z": 0}},
        ]
        target = [
            {**source[0], "start": {"x": 500, "y": 0, "z": 0},
             "end": {"x": 1500, "y": 0, "z": 0}},
            source[1],
        ]
        objects = [
            {"object_id": "line-1", "object_type": "line",
             "label": "线段 1", "geometry_refs": [1]},
            {"object_id": "line-2", "object_type": "line",
             "label": "线段 2", "geometry_refs": [2]},
        ]
        drifted = [objects[0], {**objects[1], "label": "被静默修改"}]
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create("两条线", "创建两条线")
            parent = store.add_variant(
                project["id"], "原始", source, "", {"score": 90}, [],
                logical_objects=objects,
            )
            child = store.add_variant(
                project["id"], "错误修改", target, "", {"score": 90}, [],
                parent_variant_id=parent["id"], logical_objects=drifted,
                edit_contract={
                    "schema": "cad.edit.v2", "operation": "translate",
                    "target": {"scope": "instance", "instance_ids": [1],
                               "geometry_ids": []},
                    "coordinate_frame": "drawing",
                    "parameters": {"dx_mm": 500, "dy_mm": 0},
                },
            )
            saved = store.get(project["id"])
        self.assertIsNone(child)
        self.assertEqual(len(saved["variants"]), 1)

    def test_planning_revision_gate_detects_geometry_drift(self) -> None:
        source = [{
            "id": 1, "type": "line", "layer_id": 1,
            "start": {"x": 0, "y": 0, "z": 0},
            "end": {"x": 1000, "y": 0, "z": 0},
        }]
        target = [{
            **source[0],
            "end": {"x": 2000, "y": 0, "z": 0},
        }]
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create("线段", "创建线段")
            parent = store.add_variant(
                project["id"], "原始", source, "初始", {"score": 90}, [],
                acceptance_summary=ACCEPTED,
            )
            child = store.add_variant(
                project["id"], "加长", target, "加长一倍", {"score": 90}, [],
                parent_variant_id=parent["id"],
            )

        verified = verify_variant_revision_for_planning(child)
        self.assertTrue(verified["ok"])
        self.assertEqual(verified["schema"], "cad.planning-source.v1")
        tampered = json.loads(json.dumps(child))
        tampered["geometries"][0]["end"]["x"] = 3000
        rejected = verify_variant_revision_for_planning(tampered)
        self.assertFalse(rejected["ok"])
        self.assertEqual(rejected["reason"], "revision_mismatch")
        self.assertFalse(rejected["checks"]["snapshot"])

    def test_child_variant_persists_unified_revision_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create("线段", "创建线段")
            source = [{
                "id": 1, "type": "line", "template_instance": 1,
                "start": {"x": 0, "y": 0}, "end": {"x": 1000, "y": 0},
            }]
            target = [{
                **source[0],
                "start": {"x": 500, "y": 0}, "end": {"x": 1500, "y": 0},
            }]
            parent = store.add_variant(
                project["id"], "原始", source, "初始", {"score": 90},
                [[[0, 0], [1, 0]]], acceptance_summary=ACCEPTED,
            )
            edit_contract = {
                "schema": "cad.edit.v2", "operation": "translate",
                "target": {"scope": "instance", "instance_ids": [1], "geometry_ids": []},
                "coordinate_frame": "drawing",
                "parameters": {"dx_mm": 500, "dy_mm": 0},
            }
            child = store.add_variant(
                project["id"], "平移", target, "平移线段", {"score": 90},
                [[[0.5, 0], [1.5, 0]]], parent_variant_id=parent["id"],
                edit_contract=edit_contract,
            )
        revision = child["revision_contract"]
        self.assertEqual(revision["schema"], "cad.revision.v1")
        self.assertEqual(revision["status"], "verified")
        self.assertNotEqual(
            revision["before_snapshot"]["sha256"],
            revision["after_snapshot"]["sha256"],
        )
        self.assertEqual(revision["diff"]["geometry_diff"]["counts"]["modified"], 1)
        self.assertEqual(revision["rollback"]["target_variant_id"], parent["id"])
        self.assertEqual(revision["edit_contract"]["schema"], "cad.edit.v2")
        self.assertEqual(revision["edit_contract"]["target"]["instance_ids"], [1])
        self.assertEqual(revision["edit_contract"]["parameters"]["dx_mm"], 500.0)

    def test_variant_rejects_invalid_edit_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create("线段", "创建线段")
            source = [{
                "id": 1, "type": "line", "template_instance": 1,
                "start": {"x": 0, "y": 0}, "end": {"x": 1000, "y": 0},
            }]
            parent = store.add_variant(
                project["id"], "原始", source, "初始", {"score": 90},
                [[[0, 0], [1, 0]]], acceptance_summary=ACCEPTED,
            )
            invalid = store.add_variant(
                project["id"], "错误修改", source, "缺少目标",
                {"score": 90}, [[[0, 0], [1, 0]]],
                parent_variant_id=parent["id"],
                edit_contract={"schema": "cad.edit.v2", "operation": "translate"},
            )
        self.assertIsNone(invalid)

    def test_geometry_identity_fills_legacy_ids_and_records_groups(self) -> None:
        normalized, contract, error = normalize_geometry_identity([
            {"id": 4, "type": "line", "template_instance": 1},
            {"type": "circle", "template_instance": 1},
            {"id": 8, "type": "line", "template_instance": 2},
        ])

        self.assertIsNone(error)
        self.assertEqual([item["id"] for item in normalized], [4, 9, 8])
        self.assertEqual(contract["geometry_ids"], [4, 8, 9])
        self.assertEqual(contract["instance_ids"], [1, 2])
        self.assertEqual(contract["groups"], [
            {"instance_id": 1, "geometry_ids": [4, 9]},
            {"instance_id": 2, "geometry_ids": [8]},
        ])
        self.assertTrue(contract["instances_authoritative"])

    def test_geometry_identity_rejects_duplicates_and_group_drift(self) -> None:
        normalized, contract, error = normalize_geometry_identity([
            {"id": 1, "template_instance": 1},
            {"id": 1, "template_instance": 1},
        ])
        self.assertIsNone(normalized)
        self.assertIsNone(contract)
        self.assertIn("重复", error)
        self.assertIsNotNone(validate_identity_continuity(
            [{"id": 1, "template_instance": 1}],
            [{"id": 1, "template_instance": 2}],
        ))

    def test_variant_persists_identity_contract_and_rejects_group_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create("两个图形", "创建两个图形")
            parent = store.add_variant(
                project["id"], "方案 A",
                [{"id": 1, "template_instance": 1},
                 {"id": 2, "template_instance": 2}],
                "初始", {"score": 90}, [], acceptance_summary=ACCEPTED,
            )
            self.assertEqual(parent["identity_contract"]["instance_count"], 2)
            drifted = store.add_variant(
                project["id"], "错误方案",
                [{"id": 1, "template_instance": 2},
                 {"id": 2, "template_instance": 2}],
                "错误换组", {"score": 90}, [],
                parent_variant_id=parent["id"],
            )
        self.assertIsNone(drifted)

    def test_project_lifecycle_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "projects.json"
            store = CreativeProjectStore(path)
            created = store.create(
                "停车场标线",
                "画一个 5x3 米矩形",
                {"shape": "rectangle", "dimensions": {"width_m": 5.0, "height_m": 3.0}},
                {"max_area_m2": 20},
                ["printer"],
            )
            self.assertEqual(created["status"], "clarifying")

            updated = store.update(
                created["id"],
                requirements={"printer": "center"},
                missing_parameters=[],
            )
            self.assertIsNotNone(updated)
            self.assertEqual(updated["status"], "ready_for_design")
            self.assertEqual(updated["requirements"]["printer"], "center")

            restored = CreativeProjectStore(path).get(created["id"])
            self.assertIsNotNone(restored)
            self.assertEqual(restored["status"], "ready_for_design")
            self.assertEqual(len(restored["events"]), 2)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["schema_version"], "1.0")

    def test_list_filter_and_delete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            clarifying = store.create("待补充", "画一个图", missing_parameters=["shape"])
            store.create("可设计", "画 2x2 米矩形，中喷头")

            self.assertEqual(len(store.list(status="clarifying")), 1)
            self.assertTrue(store.delete(clarifying["id"]))
            self.assertIsNone(store.get(clarifying["id"]))
            self.assertFalse(store.delete("missing"))

    def test_variant_selection_advances_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create("矩形", "画矩形")
            variant = store.add_variant(
                project["id"], "方案 A", [{"id": 1}], "最短路径",
                {"score": 95}, [[[0.0, 0.0], [1.0, 0.0]]],
                acceptance_summary=ACCEPTED,
            )
            self.assertIsNotNone(variant)
            selected = store.select_variant(project["id"], variant["id"])

            self.assertIsNotNone(selected)
            self.assertEqual(selected["status"], "ready_for_planning")
            self.assertEqual(selected["selected_variant_id"], variant["id"])
            self.assertTrue(selected["variants"][0]["selected"])

            store.set_planning(project["id"], {
                "stage": "planning_preview", "validation": {}, "file_name": "drawing.json"
            })
            planning = store.set_planning(project["id"], {
                "stage": "ready", "validation": {"ok": True}, "file_name": "drawing.json"
            })
            self.assertEqual(planning["status"], "planning_ready")

            reported = store.set_report(project["id"], {"verdict": "accepted"})
            self.assertEqual(reported["acceptance_report"]["verdict"], "accepted")

    def test_invalid_late_requirement_update_does_not_mutate_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create("矩形", "画矩形")
            variant = store.add_variant(
                project["id"], "方案 A", [{"id": 1}], "测试", {"score": 90}, [],
                acceptance_summary=ACCEPTED,
            )
            store.select_variant(project["id"], variant["id"])

            result = store.update(project["id"], requirements={"printer": "left"})

            self.assertIsNone(result)
            restored = store.get(project["id"])
            self.assertNotIn("printer", restored["requirements"])
            self.assertEqual(restored["status"], "ready_for_planning")

    def test_confirm_cad_instance_groups_writes_stable_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "导入篮球场",
                "检查两个篮球场",
                {"shape": "basketball", "quantity": 2},
                source_drawing={
                    "source_format": "dxf",
                    "cad_analysis": {"instance_groups_confirmed": False},
                    "geometries": [{"id": value} for value in range(1, 7)],
                },
            )

            confirmed = store.confirm_source_instance_groups(project["id"], [
                {"instance_id": 1, "geometry_ids": [1, 2, 3], "label": "左场"},
                {"instance_id": 2, "geometry_ids": [4, 5, 6], "label": "右场"},
            ])

        self.assertIsNotNone(confirmed)
        analysis = confirmed["source_drawing"]["cad_analysis"]
        self.assertTrue(analysis["instance_groups_confirmed"])
        self.assertEqual(analysis["instance_group_count"], 2)
        self.assertEqual(
            confirmed["source_drawing"]["identity_contract"]["instance_ids"],
            [1, 2],
        )
        self.assertEqual(
            [item["template_instance"] for item in confirmed["source_drawing"]["geometries"]],
            [1, 1, 1, 2, 2, 2],
        )
        self.assertEqual(
            [item["geometry_refs"] for item in confirmed["source_drawing"]["logical_objects"]],
            [[1, 2, 3], [4, 5, 6]],
        )

    def test_confirm_image_groups_creates_authoritative_logical_objects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "图片图纸",
                "确认图片识别结果",
                source_drawing={
                    "source_format": "image",
                    "cad_analysis": {"instance_groups_confirmed": False},
                    "geometries": [
                        {
                            "id": value,
                            "type": "line",
                            "start": {"x": value * 10, "y": 0},
                            "end": {"x": value * 10, "y": 100},
                        }
                        for value in range(1, 5)
                    ],
                },
            )

            confirmed = store.confirm_source_instance_groups(project["id"], [
                {"instance_id": 1, "geometry_ids": [1, 2], "label": "左侧图形"},
                {"instance_id": 2, "geometry_ids": [3, 4], "label": "右侧图形"},
            ])

        self.assertIsNotNone(confirmed)
        source = confirmed["source_drawing"]
        self.assertTrue(source["cad_analysis"]["instance_groups_confirmed"])
        self.assertEqual(
            [item["object_id"] for item in source["logical_objects"]],
            ["image_drawing-1", "image_drawing-2"],
        )
        self.assertEqual(source["logical_objects"][0]["label"], "左侧图形")

    def test_cad_instance_groups_must_cover_each_geometry_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = CreativeProjectStore(Path(directory) / "projects.json")
            project = store.create(
                "导入图纸", "分组",
                source_drawing={
                    "source_format": "dxf",
                    "geometries": [{"id": 1}, {"id": 2}, {"id": 3}],
                },
            )

            missing = store.confirm_source_instance_groups(
                project["id"], [{"geometry_ids": [1, 2]}]
            )
            duplicate = store.confirm_source_instance_groups(
                project["id"], [{"geometry_ids": [1, 2]}, {"geometry_ids": [2, 3]}]
            )
            unknown = store.confirm_source_instance_groups(
                project["id"], [{"geometry_ids": [1, 2, 99]}]
            )

        self.assertIsNone(missing)
        self.assertIsNone(duplicate)
        self.assertIsNone(unknown)


if __name__ == "__main__":
    unittest.main()
