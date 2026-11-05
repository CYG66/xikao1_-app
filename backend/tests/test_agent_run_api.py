import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.agent_run_store import AgentRunStore
from app.main import app
from app.agent_http_service import _record_agent_run_result


class AgentRunApiTests(unittest.TestCase):
    def test_chat_exposes_run_id_and_persists_completion(self) -> None:
        store = AgentRunStore(Path(tempfile.mkdtemp()) / "runs.json")
        with patch("app.agent_http_service.agent_runs", store), patch(
            "app.agent_http_service._agent_chat", return_value={"ok": True, "message": "完成"}
        ):
            response = TestClient(app).post(
                "/api/agent/chat",
                json={"message": "检查当前图纸", "conversation_id": "chat-1", "client_id": "user-1"},
            )
        self.assertEqual(response.status_code, 200)
        run_id = response.json()["agent_run_id"]
        self.assertEqual(store.get(run_id)["state"], "completed")

    def test_run_detail_returns_persisted_record(self) -> None:
        store = AgentRunStore(Path(tempfile.mkdtemp()) / "runs.json")
        run = store.create("测试", conversation_id="chat-2")
        with patch("app.agent_http_service.agent_runs", store), patch(
            "app.agent_http_service._agent_chat", return_value={"ok": True, "message": "已恢复"}
        ):
            response = TestClient(app).get(f"/api/agent/runs/{run['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["run"]["id"], run["id"])

    def test_cad_result_records_plan_artifact_and_assertions(self) -> None:
        store = AgentRunStore(Path(tempfile.mkdtemp()) / "runs.json")
        run = store.create("把中心圆扩大一倍")
        store.transition(run["id"], "understanding", "理解")
        result = {
            "ok": True,
            "project_id": "project-1",
            "variant": {
                "id": "variant-2",
                "parent_variant_id": "variant-1",
                "name": "中心圆扩大",
                "edit_plan": {
                    "operation": "resize",
                    "target": {"scope": "geometry", "geometry_ids": [6]},
                    "expected_changes": {"modified_geometry_ids": [6]},
                    "assertions": [{"kind": "exact_modified_ids", "expected": [6]}],
                },
                "machine_assertions": {
                    "verified": True,
                    "failure_codes": [],
                    "report_sha256": "report-1",
                },
            },
        }
        with patch("app.agent_http_service.agent_runs", store):
            _record_agent_run_result(run["id"], result)
        restored = store.get(run["id"])
        self.assertEqual(restored["state"], "completed")
        self.assertEqual(restored["project_id"], "project-1")
        self.assertEqual(len(restored["steps"]), 3)
        self.assertEqual(restored["artifacts"][0]["variant_id"], "variant-2")
        self.assertTrue(restored["attempts"][0]["verified"])
        self.assertEqual(restored["success_criteria"][0]["kind"], "exact_modified_ids")

    def test_cad_repair_records_both_attempts_without_running_again(self) -> None:
        store = AgentRunStore(Path(tempfile.mkdtemp()) / "runs.json")
        run = store.create("移动选中图形")
        store.transition(run["id"], "understanding", "理解")
        result = {
            "ok": True,
            "project_id": "project-1",
            "variant": {
                "id": "variant-2",
                "parent_variant_id": "variant-1",
                "edit_plan": {
                    "operation": "translate",
                    "target": {"scope": "geometry", "geometry_ids": [6]},
                    "assertions": [],
                },
                "machine_assertions": {
                    "verified": True,
                    "failure_codes": [],
                    "report_sha256": "after",
                },
            },
            "edit_repair": {
                "attempted": True,
                "attempt_count": 1,
                "strategy": "restore_protected_geometries",
                "trigger_failure_codes": ["edit_plan", "non_target_integrity"],
                "actions": [{"kind": "restore", "geometry_id": 9}],
                "before_report_sha256": "before",
                "after_report_sha256": "after",
                "recovered": True,
            },
        }
        with patch("app.agent_http_service.agent_runs", store):
            _record_agent_run_result(run["id"], result)
        restored = store.get(run["id"])
        self.assertEqual(restored["state"], "completed")
        self.assertEqual(len(restored["attempts"]), 2)
        self.assertFalse(restored["attempts"][0]["verified"])
        self.assertTrue(restored["attempts"][1]["verified"])
        repair_steps = [step for step in restored["steps"] if step["kind"] == "cad_repair"]
        self.assertEqual(repair_steps[0]["attempt_count"], 1)

    def test_target_failure_becomes_structured_clarification(self) -> None:
        store = AgentRunStore(Path(tempfile.mkdtemp()) / "runs.json")
        run = store.create("扩大那个圆")
        store.transition(run["id"], "understanding", "理解")
        result = {
            "ok": False,
            "message": "目标无法唯一确定",
            "machine_assertions": {
                "verified": False,
                "failure_codes": ["target_resolved"],
            },
        }
        with patch("app.agent_http_service.agent_runs", store):
            _record_agent_run_result(run["id"], result)
        restored = store.get(run["id"])
        self.assertEqual(restored["state"], "awaiting_clarification")
        self.assertEqual(result["failure_resolution"]["next_action"], "ask_user")

    def test_cancel_run_api_respects_owner(self) -> None:
        store = AgentRunStore(Path(tempfile.mkdtemp()) / "runs.json")
        run = store.create("测试", user_id="user-1")
        with patch("app.agent_http_service.agent_runs", store):
            denied = TestClient(app).post(
                f"/api/agent/runs/{run['id']}/cancel?client_id=user-2"
            )
            cancelled = TestClient(app).post(
                f"/api/agent/runs/{run['id']}/cancel?client_id=user-1"
            )
        self.assertFalse(denied.json()["ok"])
        self.assertTrue(cancelled.json()["ok"])
        self.assertEqual(cancelled.json()["run"]["state"], "cancelled")

    def test_resume_run_api_respects_owner(self) -> None:
        store = AgentRunStore(Path(tempfile.mkdtemp()) / "runs.json")
        run = store.create("测试", user_id="user-1")
        store.transition(run["id"], "understanding", "理解")
        with store._lock:
            store._runs[run["id"]]["state"] = "paused"
            store._save()
        with patch("app.agent_http_service.agent_runs", store), patch(
            "app.agent_http_service._agent_chat", return_value={"ok": True, "message": "已恢复"}
        ):
            denied = TestClient(app).post(
                f"/api/agent/runs/{run['id']}/resume?client_id=user-2"
            )
            resumed = TestClient(app).post(
                f"/api/agent/runs/{run['id']}/resume?client_id=user-1"
            )
        self.assertFalse(denied.json()["ok"])
        self.assertTrue(resumed.json()["ok"])
        self.assertEqual(resumed.json()["run"]["state"], "completed")

    def test_resume_run_api_replays_original_request_into_same_run(self) -> None:
        store = AgentRunStore(Path(tempfile.mkdtemp()) / "runs.json")
        run = store.create(
            "检查当前图纸",
            user_id="user-1",
            conversation_id="chat-1",
            project_id="project-1",
            source_variant_id="variant-1",
            mode="advanced",
        )
        with store._lock:
            store._runs[run["id"]]["state"] = "paused"
            store._save()
        with patch("app.agent_http_service.agent_runs", store), patch(
            "app.agent_http_service._agent_chat", return_value={"ok": True, "message": "已恢复"}
        ) as chat:
            response = TestClient(app).post(
                f"/api/agent/runs/{run['id']}/resume?client_id=user-1"
            )
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["run"]["id"], run["id"])
        self.assertEqual(response.json()["run"]["state"], "completed")
        self.assertEqual(chat.call_args.args[0].message, "检查当前图纸")

    def test_resume_from_generated_result_skips_model_and_execution(self) -> None:
        store = AgentRunStore(Path(tempfile.mkdtemp()) / "runs.json")
        run = store.create("生成候选", user_id="user-1", conversation_id="chat-1")
        with store._lock:
            store._runs[run["id"]]["state"] = "paused"
            store._save()
        store.set_checkpoint(run["id"], {
            "schema": "agent.checkpoint.v3",
            "step_id": "result_generated",
            "next_step": "finalize",
            "completed_steps": ["understanding", "context_prepared", "execute"],
            "result": {"ok": True, "message": "候选已经生成"},
        })
        with patch("app.agent_http_service.agent_runs", store), patch(
            "app.agent_http_service._agent_chat"
        ) as chat, patch("app.agent_http_service._prepare_agent_chat_context") as prepare:
            response = TestClient(app).post(
                f"/api/agent/runs/{run['id']}/resume?client_id=user-1"
            )
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["result"]["resumed_step"], "finalize")
        chat.assert_not_called()
        prepare.assert_not_called()

    def test_resume_from_prepared_context_skips_context_rebuild(self) -> None:
        store = AgentRunStore(Path(tempfile.mkdtemp()) / "runs.json")
        run = store.create("生成候选", user_id="user-1", conversation_id="chat-1")
        with store._lock:
            store._runs[run["id"]]["state"] = "paused"
            store._save()
        prepared = {"route": {"intent": "cad"}, "model_messages": []}
        store.set_checkpoint(run["id"], {
            "schema": "agent.checkpoint.v3",
            "step_id": "context_prepared",
            "next_step": "execute",
            "completed_steps": ["understanding", "context_prepared"],
            "prepared_context": prepared,
        })
        with patch("app.agent_http_service.agent_runs", store), patch(
            "app.agent_http_service._agent_chat",
            return_value={"ok": True, "message": "执行完成"},
        ) as chat, patch("app.agent_http_service._prepare_agent_chat_context") as prepare:
            response = TestClient(app).post(
                f"/api/agent/runs/{run['id']}/resume?client_id=user-1"
            )
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["result"]["resumed_step"], "execute")
        prepare.assert_not_called()
        self.assertEqual(chat.call_args.kwargs["prepared"], prepared)


if __name__ == "__main__":
    unittest.main()
