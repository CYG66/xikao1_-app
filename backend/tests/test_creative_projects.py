from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.creative_projects import CreativeProjectStore


class CreativeProjectStoreTest(unittest.TestCase):
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
                project["id"], "方案 A", [{"id": 1}], "测试", {"score": 90}, []
            )
            store.select_variant(project["id"], variant["id"])

            result = store.update(project["id"], requirements={"printer": "left"})

            self.assertIsNone(result)
            restored = store.get(project["id"])
            self.assertNotIn("printer", restored["requirements"])
            self.assertEqual(restored["status"], "ready_for_planning")


if __name__ == "__main__":
    unittest.main()
