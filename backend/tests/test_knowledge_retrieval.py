from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.agent_service import RobotAgentService
from app.knowledge_retrieval import ProjectKnowledgeRetriever


class ProjectKnowledgeRetrieverTest(unittest.TestCase):
    def test_search_returns_machine_readable_source_and_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "printer.md").write_text(
                "# 喷码机说明\n喷码机通过 printer_control 服务执行测试打印。\n"
                "当前是否在线必须读取实时遥测，文档不能证明在线。\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"XLINE_KNOWLEDGE_ROOTS": directory}):
                result = ProjectKnowledgeRetriever().search("喷码机测试打印", limit=2)

        self.assertTrue(result["matches"])
        match = result["matches"][0]
        self.assertEqual(match["id"], "K1")
        self.assertIn("printer.md", match["source"])
        self.assertEqual(match["line_start"], 1)
        self.assertIn("实时遥测", match["excerpt"])

    def test_generated_directories_and_sensitive_values_are_not_exposed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "guide.md").write_text(
                "# 联网说明\nAPI_KEY=do-not-expose\n网络连接状态由接口返回。\n",
                encoding="utf-8",
            )
            generated = root / "build"
            generated.mkdir()
            (generated / "wrong.md").write_text(
                "错误知识：网络永远在线。", encoding="utf-8"
            )
            with patch.dict(os.environ, {"XLINE_KNOWLEDGE_ROOTS": directory}):
                result = ProjectKnowledgeRetriever().search("网络连接状态", limit=4)

        excerpts = "\n".join(item["excerpt"] for item in result["matches"])
        sources = "\n".join(item["source"] for item in result["matches"])
        self.assertNotIn("do-not-expose", excerpts)
        self.assertIn("[敏感配置已隐藏]", excerpts)
        self.assertNotIn("wrong.md", sources)

    def test_system_context_includes_citable_knowledge_but_keeps_live_boundary(self) -> None:
        service = object.__new__(RobotAgentService)
        route = {"tool_family": "conversation", "name": "conversation"}
        knowledge = {
            "matches": [{
                "id": "K1",
                "source": "xline_ws3/guide.md",
                "title": "运行说明",
                "line_start": 10,
                "line_end": 12,
                "score": 1.2,
                "excerpt": "路径规划接口只生成规划结果。",
            }]
        }
        with (
            patch.object(service, "runtime_context", return_value={"fresh": False}),
            patch.object(service, "knowledge_context", return_value=knowledge),
        ):
            context = service._system_context("路径规划会启动小车吗", route=route)

        self.assertIn('"id": "K1"', context)
        self.assertIn("不能证明设备当前状态", context)
        self.assertIn("路径规划接口只生成规划结果", context)

    def test_enriched_result_exposes_metadata_without_document_excerpt(self) -> None:
        knowledge = {
            "matches": [{
                "id": "K1",
                "source": "xline_ws3/guide.md",
                "title": "运行说明",
                "line_start": 1,
                "line_end": 2,
                "score": 1.0,
                "excerpt": "internal context",
            }]
        }
        with patch.object(RobotAgentService, "runtime_context", return_value={}):
            result = RobotAgentService.enrich_result(
                {"ok": True, "message": "answer"}, {}, knowledge
            )

        self.assertEqual(result["knowledge_sources"][0]["id"], "K1")
        self.assertNotIn("excerpt", result["knowledge_sources"][0])


if __name__ == "__main__":
    unittest.main()
