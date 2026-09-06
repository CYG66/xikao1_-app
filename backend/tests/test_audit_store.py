from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.audit_store import AgentAuditStore


class AgentAuditStoreTest(unittest.TestCase):
    def test_audit_database_failure_does_not_block_append(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.jsonl"
            store = AgentAuditStore(path)
            with patch("app.audit_store.xline_database.record_audit", side_effect=RuntimeError("db down")):
                record = store.append("tool_executed", "example", {}, {"ok": True})
            self.assertTrue(record["ok"])

    def test_audit_is_append_only_and_redacts_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.jsonl"
            store = AgentAuditStore(path)
            store.append(
                "tool_executed",
                "example",
                {"distance": 1, "api_key": "secret", "nested": {"token": "secret"}},
                {"ok": True, "message": "done"},
            )
            store.append(
                "tool_blocked",
                "example",
                {},
                {"ok": False, "message": "blocked"},
            )

            records = store.list(10)

            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["message"], "blocked")
            self.assertEqual(records[1]["arguments"]["api_key"], "***")
            self.assertEqual(records[1]["arguments"]["nested"]["token"], "***")
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
