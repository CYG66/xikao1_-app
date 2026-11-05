import tempfile
import unittest
from pathlib import Path

from app.agent_run_store import AgentRunStore


class AgentRunStoreTests(unittest.TestCase):
    def test_lifecycle_persists_steps_artifacts_and_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.json"
            store = AgentRunStore(path)
            created = store.create(
                "把中心圆半径改为 2 米",
                conversation_id="chat-1",
                project_id="project-1",
                success_criteria=[{"kind": "radius", "target": "center_circle", "value": 2}],
            )
            run_id = created["id"]
            store.transition(run_id, "understanding", "开始理解需求")
            store.add_step(run_id, {"id": "resolve-target", "state": "done"})
            store.transition(run_id, "planning", "已生成修改计划")
            store.add_artifact(run_id, {"kind": "candidate", "id": "variant-2"})
            store.add_attempt(run_id, {"index": 0, "assertions": {"ok": False}})
            store.transition(run_id, "retrying", "目标断言未通过")
            store.transition(run_id, "planning", "重新生成计划")
            store.transition(run_id, "executing", "开始执行")
            store.transition(run_id, "verifying", "执行后复核")
            store.transition(run_id, "completed", "修改已通过复核")

            restored = AgentRunStore(path).get(run_id)
            self.assertIsNotNone(restored)
            self.assertEqual(restored["state"], "completed")
            self.assertEqual(restored["project_id"], "project-1")
            self.assertEqual(len(restored["steps"]), 1)
            self.assertEqual(len(restored["artifacts"]), 1)
            self.assertEqual(len(restored["attempts"]), 1)

    def test_invalid_transition_and_terminal_append_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AgentRunStore(Path(directory) / "runs.json")
            run = store.create("测试")
            run_id = run["id"]
            self.assertEqual(store.transition(run_id, "completed", "跳过计划")["state"], "created")
            store.transition(run_id, "understanding", "理解")
            store.transition(run_id, "failed", "失败")
            self.assertEqual(store.add_step(run_id, {"id": "late"})["steps"], [])
            self.assertEqual(store.get(run_id)["state"], "failed")

    def test_bind_context_records_discovered_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AgentRunStore(Path(directory) / "runs.json")
            run = store.create("修改当前图纸")
            store.bind_context(run["id"], project_id="project-2", source_variant_id="variant-1")
            restored = store.get(run["id"])
            self.assertEqual(restored["project_id"], "project-2")
            self.assertEqual(restored["source_variant_id"], "variant-1")

    def test_cancel_is_terminal_and_preserves_reason(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AgentRunStore(Path(directory) / "runs.json")
            run = store.create("测试", user_id="user-1")
            store.transition(run["id"], "understanding", "理解")
            cancelled = store.cancel(run["id"], "用户点击停止")
            self.assertEqual(cancelled["state"], "cancelled")
            self.assertEqual(cancelled["failure"]["category"], "user_cancelled")
            self.assertEqual(store.cancel(run["id"])["state"], "cancelled")

    def test_timeout_pauses_run_and_resume_keeps_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AgentRunStore(Path(directory) / "runs.json")
            run = store.create("长任务", timeout_seconds=30)
            store.transition(run["id"], "understanding", "理解")
            store.set_checkpoint(run["id"], {"step_id": "resolve-target", "project_id": "p1"})
            with store._lock:
                store._runs[run["id"]]["timeout_at"] = "2000-01-01T00:00:00+00:00"
                store._save()
            paused = store.get(run["id"])
            self.assertEqual(paused["state"], "paused")
            self.assertEqual(paused["checkpoint"]["step_id"], "resolve-target")
            resumed = store.resume(run["id"])
            self.assertEqual(resumed["state"], "planning")

    def test_step_artifact_and_attempt_idempotency_keys_are_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AgentRunStore(Path(directory) / "runs.json")
            run = store.create("测试步骤续跑", idempotency_key="request-1")
            store.transition(run["id"], "understanding", "理解")
            for _ in range(2):
                store.add_step(run["id"], {
                    "idempotency_key": "request-1:execute", "state": "done",
                })
                store.add_artifact(run["id"], {
                    "idempotency_key": "request-1:candidate:v1", "variant_id": "v1",
                })
                store.add_attempt(run["id"], {
                    "idempotency_key": "request-1:attempt:0", "index": 0,
                })
            restored = store.get(run["id"])
            self.assertEqual(restored["idempotency_key"], "request-1")
            self.assertEqual(len(restored["steps"]), 1)
            self.assertEqual(len(restored["artifacts"]), 1)
            self.assertEqual(len(restored["attempts"]), 1)


if __name__ == "__main__":
    unittest.main()
