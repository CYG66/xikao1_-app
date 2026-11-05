from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from app.routers.system import database_cleanup
from app.schemas import DatabaseCleanupRequest


class _MaintenanceDatabase:
    def __init__(self) -> None:
        self.path = Path("/tmp/xline.db")
        self.calls: list[str] = []

    def backup(self, destination: Path) -> dict[str, object]:
        self.calls.append("backup")
        return {"ok": True, "path": str(destination), "size_bytes": 1024}

    def cleanup_history(self, retention_days: int, targets: list[str]) -> dict[str, object]:
        self.calls.append("cleanup")
        return {
            "ok": True,
            "retention_days": retention_days,
            "deleted": {target: 1 for target in targets},
            "deleted_total": len(targets),
        }

    def integrity_status(self) -> dict[str, object]:
        self.calls.append("integrity")
        return {"ok": True, "checks": ["ok"]}


class DatabaseMaintenanceApiTest(unittest.TestCase):
    def test_cleanup_creates_recovery_point_then_verifies_database(self) -> None:
        database = _MaintenanceDatabase()
        command = DatabaseCleanupRequest(
            retention_days=30,
            targets=["telemetry", "audit_logs", "ai_case_memory"],
        )

        with patch("app.routers.system.xline_database", database):
            result = database_cleanup(command)

        self.assertEqual(database.calls, ["backup", "cleanup", "integrity"])
        self.assertEqual(result["deleted_total"], 3)
        self.assertTrue(result["backup"]["ok"])
        self.assertTrue(result["integrity"]["ok"])
        self.assertIn("pre-cleanup", result["backup"]["path"])


if __name__ == "__main__":
    unittest.main()
