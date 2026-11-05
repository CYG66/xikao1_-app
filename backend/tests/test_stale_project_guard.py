from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.agent_service import RobotAgentService
from app.conversation_memory import ConversationMemoryStore


class StaleProjectGuardTest(unittest.TestCase):
    """Guard must clean a reference only when the project is really gone,
    and must never block or forget a still-valid project."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.memory = ConversationMemoryStore(
            Path(self.temporary.name) / "memory.json"
        )
        self.agent = RobotAgentService()
        self._projects_patch = patch("app.agent_service.get_creative_project_store")
        self.projects = self._projects_patch.start()
        self._memory_patch = patch(
            "app.agent_service.conversation_memory", self.memory
        )
        self._memory_patch.start()

    def tearDown(self) -> None:
        self._memory_patch.stop()
        self._projects_patch.stop()
        self.temporary.cleanup()

    def _remember_project(self, conv: str, pid: str, label: str = "项目") -> None:
        self.memory.remember(
            conv, "", {"project": {"id": pid, "name": label}}
        )

    def _route(
        self, conv: str, target: dict | None = None, ambiguous: bool = False
    ) -> dict:
        return {
            "object_memory": self.memory.context(conv, None),
            "retrieved_memory": {},
            "reference_resolution": {
                "required": True,
                "resolved": target is not None and not ambiguous,
                "ambiguous": ambiguous,
                "target": target,
                "candidates": [],
            },
        }

    def test_guard_cleans_gone_project_and_returns_guide(self) -> None:
        self.projects.return_value.get.return_value = None
        self._remember_project("c1", "gone-id")
        route = self._route(
            "c1", {"type": "project", "id": "gone-id", "label": "x"}
        )
        guide = self.agent._stale_project_guard(route)
        self.assertIsNotNone(guide)
        self.assertIn("已不存在", guide)
        self.assertNotIn(
            "project", self.memory.context("c1", None)["objects"]
        )

    def test_explicitly_selected_project_has_priority_over_memory(self) -> None:
        route = self._route(
            "c1", {"type": "project", "id": "old-id", "label": "旧项目"}
        )
        route["selected_project_id"] = "selected-id"

        self.assertEqual(
            self.agent._project_id_from_route(route),
            "selected-id",
        )

    def test_fresh_design_does_not_inherit_selected_or_remembered_project(self) -> None:
        self._remember_project("c1", "old-id")
        route = self._route(
            "c1", {"type": "project", "id": "old-id", "label": "旧项目"}
        )
        route.update({
            "name": "drawing_design",
            "operation": "create",
            "stage": "requirements",
            "decision_source": "rules",
            "selected_project_id": "selected-id",
        })

        self.assertTrue(self.agent._is_fresh_design_request(route))
        self.assertIsNone(self.agent._project_id_from_route(route))

    def test_candidate_confirmation_keeps_selected_project(self) -> None:
        route = {
            "name": "drawing_design",
            "operation": "create",
            "stage": "candidate_generation",
            "decision_source": "design_confirmation_followup",
            "selected_project_id": "selected-id",
        }

        self.assertFalse(self.agent._is_fresh_design_request(route))
        self.assertEqual(self.agent._project_id_from_route(route), "selected-id")

    def test_guard_keeps_valid_project(self) -> None:
        self.projects.return_value.get.return_value = {"id": "valid-id", "status": "designing"}
        self._remember_project("c1", "valid-id")
        route = self._route(
            "c1", {"type": "project", "id": "valid-id", "label": "x"}
        )
        self.assertIsNone(self.agent._stale_project_guard(route))
        objs = self.memory.context("c1", None)["objects"]
        self.assertEqual(objs["project"][0]["id"], "valid-id")

    def test_guard_prefers_resolution_target_over_list_head(self) -> None:
        # memory: [gone-a (head), valid-b]; user refers to "上一个" -> valid-b
        self.projects.return_value.get.return_value = {"id": "valid-b", "status": "designing"}
        self.memory.remember("c1", "", {"project": {"id": "gone-a", "name": "A"}})
        self.memory.remember("c1", "", {"project": {"id": "valid-b", "name": "B"}})
        route = self._route(
            "c1", {"type": "project", "id": "valid-b", "label": "B"}
        )
        self.assertIsNone(self.agent._stale_project_guard(route))
        objs = self.memory.context("c1", None)["objects"]
        self.assertEqual(objs["project"][0]["id"], "valid-b")

    def test_guard_ambiguous_cleans_but_does_not_block(self) -> None:
        self.projects.return_value.get.return_value = None
        self._remember_project("c1", "gone-id")
        route = self._route("c1", None, ambiguous=True)
        self.assertIsNone(self.agent._stale_project_guard(route))
        self.assertNotIn(
            "project", self.memory.context("c1", None)["objects"]
        )

    def test_new_design_request_is_not_blocked_by_deleted_old_project(self) -> None:
        self.projects.return_value.get.return_value = None
        self._remember_project("c1", "gone-id")
        route = self._route(
            "c1", {"type": "project", "id": "gone-id", "label": "旧项目"}
        )
        route.update({
            "name": "drawing_design",
            "operation": "create",
            "reference_resolution": {"required": False},
        })

        self.assertIsNone(self.agent._stale_project_guard(route))

    def test_tool_guide_keeps_reference_when_project_still_valid(self) -> None:
        # update fails because of a state restriction, project still exists
        self.projects.return_value.get.return_value = {"id": "valid-id", "status": "planning"}
        self._remember_project("c1", "valid-id")
        output = self.agent._stale_project_tool_guide(
            "update_creative_project",
            {"project_id": "valid-id"},
            {"ok": False, "message": "创意项目不存在"},
            self._route(
                "c1", {"type": "project", "id": "valid-id", "label": "x"}
            ),
        )
        self.assertEqual(output["message"], "创意项目不存在")
        objs = self.memory.context("c1", None)["objects"]
        self.assertEqual(objs["project"][0]["id"], "valid-id")

    def test_tool_guide_keeps_reference_when_variant_missing(self) -> None:
        # select_variant fails because the variant is missing, project valid
        self.projects.return_value.get.return_value = {"id": "valid-id", "status": "designing"}
        self._remember_project("c1", "valid-id")
        output = self.agent._stale_project_tool_guide(
            "select_design_variant",
            {"project_id": "valid-id", "variant_id": "missing-variant"},
            {"ok": False, "message": "项目或候选方案不存在"},
            self._route(
                "c1", {"type": "project", "id": "valid-id", "label": "x"}
            ),
        )
        self.assertEqual(output["message"], "项目或候选方案不存在")
        objs = self.memory.context("c1", None)["objects"]
        self.assertEqual(objs["project"][0]["id"], "valid-id")

    def test_tool_guide_cleans_when_project_really_gone(self) -> None:
        self.projects.return_value.get.return_value = None
        self._remember_project("c1", "gone-id")
        output = self.agent._stale_project_tool_guide(
            "update_creative_project",
            {"project_id": "gone-id"},
            {"ok": False, "message": "创意项目不存在"},
            self._route(
                "c1", {"type": "project", "id": "gone-id", "label": "x"}
            ),
        )
        self.assertIn("新建项目", output["message"])
        self.assertNotIn(
            "project", self.memory.context("c1", None)["objects"]
        )

    def test_forget_object_keeps_other_references(self) -> None:
        self.projects.return_value.get.return_value = None
        self._remember_project("c1", "gone-id")
        self.memory.remember("c1", "", {"variant_id": "keep-variant"})
        route = self._route(
            "c1", {"type": "project", "id": "gone-id", "label": "x"}
        )
        self.agent._stale_project_guard(route)
        objs = self.memory.context("c1", None)["objects"]
        self.assertNotIn("project", objs)
        self.assertEqual(objs["variant"][0]["id"], "keep-variant")


if __name__ == "__main__":
    unittest.main()
