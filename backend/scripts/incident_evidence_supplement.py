#!/usr/bin/env python3
"""Collect incident evidence from a read-only SQLite snapshot.

This script never opens the production database for writing.  It separates
observed rows from inferences and deliberately preserves the "business-row
deletion cannot be proven" boundary instead of asserting zero deletion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

PROJECT_ID = "9a7a99dc-1f68-4742-a9fa-25991ef432c0"
EXECUTION_ID = "4dc2acea-d4ff-45d4-b3b7-2c75613b2cad"
MEMORY_ID = "62d562c1-d4b2-482d-a703-218d0688249e"
WINDOW_START = "2026-11-22T02:32:00+00:00"


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _row(connection: sqlite3.Connection, sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    row = connection.execute(sql, params).fetchone()
    return dict(row) if row is not None else None


def collect(database: Path) -> dict[str, Any]:
    uri = f"file:{database.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        project = _row(
            connection,
            "SELECT * FROM projects WHERE project_id = ?",
            (PROJECT_ID,),
        )
        execution = _row(
            connection,
            "SELECT * FROM execution_tasks WHERE execution_id = ?",
            (EXECUTION_ID,),
        )
        memory = _row(
            connection,
            "SELECT * FROM ai_case_memory WHERE project_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (MEMORY_ID,),
        )
        segments = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM execution_segments WHERE execution_id = ? ORDER BY segment_id",
                (EXECUTION_ID,),
            )
        ]
        audit_window = connection.execute(
            "SELECT COUNT(*) AS count, MIN(recorded_at) AS first_at, "
            "MAX(recorded_at) AS last_at FROM audit_logs "
            "WHERE recorded_at >= ?",
            (WINDOW_START,),
        ).fetchone()
        counts = {}
        for table in (
            "projects",
            "execution_tasks",
            "execution_segments",
            "audit_logs",
            "ai_case_memory",
            "planning_tasks",
        ):
            counts[table] = connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
    finally:
        connection.close()

    project_payload = None
    if project and project.get("payload_json"):
        try:
            project_payload = json.loads(project["payload_json"])
        except (json.JSONDecodeError, TypeError):
            project_payload = None
    execution_payload = None
    if execution and execution.get("payload_json"):
        try:
            execution_payload = json.loads(execution["payload_json"])
        except (json.JSONDecodeError, TypeError):
            execution_payload = None
    memory_payload = None
    if memory:
        memory_payload = {
            key: memory[key]
            for key in ("case_id", "project_id", "category", "tool", "ok", "created_at")
            if key in memory
        }
        for source, target in (("input_json", "input"), ("outcome_json", "outcome")):
            if memory.get(source):
                try:
                    memory_payload[target] = json.loads(memory[source])
                except (json.JSONDecodeError, TypeError):
                    memory_payload[target] = None

    return {
        "database": str(database),
        "database_sha256": _hash_file(database),
        "database_bytes": database.stat().st_size,
        "read_only": True,
        "table_counts": counts,
        "observed": {
            "project": {
                "row": project,
                "payload": project_payload,
            },
            "execution_task": {
                "row": execution,
                "payload": execution_payload,
            },
            "execution_segments": segments,
            "ai_case_memory": {
                "row": memory,
                "payload": memory_payload,
            },
            "audit_window": dict(audit_window) if audit_window else None,
        },
        "assessments": {
            "62d562c1-d4b2-482d-a703-218d0688249e": {
                "status": "test_fixture_not_deletion_evidence",
                "basis": (
                    "Prior audit traced it to tests/test_design_requirement_followup.py: "
                    "TemporaryDirectory + CreativeProjectStore(Path(directory)/'projects.json') "
                    "with get_creative_project_store patched. The project row was written to "
                    "a temporary JSON store while audit/memory landed in the production DB."
                ),
                "certainty": "provenance established by prior code trace",
            },
            "9a7a99dc-1f68-4742-a9fa-25991ef432c0": {
                "status": "suspected_test_project_not_finalized",
                "basis": (
                    "Its original prompt matches the input used by "
                    "tests/test_cad_construction_commit.py. The exact runtime call stack was "
                    "not captured, so it is not conclusively classified as test-only."
                ),
                "certainty": "high similarity, call stack not traced",
            },
            "business_row_deletion": {
                "status": "unable_to_prove",
                "basis": (
                    "No trusted pre-incident byte-level database copy has been located. "
                    "The current rows show a contaminated window, but they cannot prove "
                    "that zero business rows were deleted."
                ),
                "certainty": "unproven",
            },
        },
        "limitations": [
            "No restore, cleanup, migration or VACUUM was performed.",
            "Only rows still present in the read-only snapshot are reported.",
            "Inferences are not promoted to facts.",
            "The snapshot is an audit copy, not an incident-preceding backup.",
        ],
    }


def markdown(report: dict[str, Any]) -> str:
    observed = report["observed"]
    project_payload = observed["project"]["payload"] or {}
    execution_row = observed["execution_task"]["row"] or {}
    execution_payload = observed["execution_task"]["payload"] or {}
    memory_row = observed["ai_case_memory"]["row"] or {}
    memory_payload = observed["ai_case_memory"]["payload"] or {}
    lines = [
        "# RELEASE-FIX-01 事故证据补全",
        "",
        f"- 只读快照 SHA256: `{report['database_sha256']}`",
        f"- 只读快照大小: {report['database_bytes']} bytes",
        "- 未执行恢复、清理、迁移或 VACUUM。",
        "",
        "## 已证实事实",
        "",
        f"- projects 表存在 `{PROJECT_ID}`，status=`{project_payload.get('status')}`，"
        f"name=`{project_payload.get('name')}`，updated_at=`{project_payload.get('updated_at')}`。",
        f"- execution_tasks 表存在 `{EXECUTION_ID}`，status=`{execution_row.get('status', execution_payload.get('status'))}`，"
        f"project_id=`{execution_row.get('project_id', execution_payload.get('project_id'))}`。",
        f"- execution_segments 表存在 {len(observed['execution_segments'])} 条关联记录。",
        f"- ai_case_memory 表存在 `{MEMORY_ID}`，tool=`{memory_row.get('tool', memory_payload.get('tool'))}`。",
        f"- 事故窗口 audit 行数: {(observed['audit_window'] or {}).get('count')}。",
        "",
        "## 推断与边界",
        "",
        "- `62d562c1…` 是测试夹具写入的审计/记忆，不是业务行删除证据。",
        "- `9a7a99dc…` 与测试输入同源，高度疑似测试项目；调用栈未追踪，不能最终定性。",
        "- 业务行历史删除情况：**无法证明**，不得写成零删除。",
        "",
        "## 表计数",
        "",
        "| 表 | 行数 |",
        "|---|---:|",
    ]
    for table, count in report["table_counts"].items():
        lines.append(f"| {table} | {count} |")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--label", default="RELEASE-FIX-01_incident_supplement")
    args = parser.parse_args(argv)
    if not args.db.exists():
        print(f"database is missing: {args.db}", file=sys.stderr)
        return 2
    report = collect(args.db)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / f"{args.label}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.out / f"{args.label}.md").write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report["table_counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
