#!/usr/bin/env python3
"""Read-only, ID-level reconciliation of the audit ledgers.

Reads a JSONL mirror and a SQLite database in immutable/read-only mode, then
writes the one-sided events and a machine-readable report into an isolated
output directory.  It never deletes, edits, merges or back-fills either ledger.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, str], int, int]:
    records: dict[str, dict[str, Any]] = {}
    raw_lines: dict[str, str] = {}
    duplicates = 0
    malformed = 0
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                item = json.loads(stripped)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if not isinstance(item, dict) or not item.get("id"):
                malformed += 1
                continue
            event_id = str(item["id"])
            if event_id in records:
                duplicates += 1
                continue
            records[event_id] = item
            raw_lines[event_id] = stripped
    return records, raw_lines, duplicates, malformed


def read_sqlite(path: Path) -> dict[str, dict[str, Any]]:
    uri = f"file:{path.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        rows = connection.execute(
            "SELECT event_id, recorded_at, event, tool, ok, payload_json FROM audit_logs"
        ).fetchall()
    finally:
        connection.close()
    records: dict[str, dict[str, Any]] = {}
    for row in rows:
        event_id = str(row["event_id"])
        try:
            payload = json.loads(row["payload_json"])
        except (json.JSONDecodeError, TypeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload.setdefault("id", event_id)
        payload.setdefault("at", row["recorded_at"])
        payload.setdefault("event", row["event"])
        payload.setdefault("tool", row["tool"])
        payload.setdefault("ok", bool(row["ok"]))
        records[event_id] = payload
    return records


def event_counts(records: dict[str, dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(item.get("event", "")) for item in records.values()).items()))


def write_jsonl(path: Path, records: dict[str, dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for event_id in sorted(records):
            stream.write(json.dumps(records[event_id], ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonl", required=True, type=Path)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--label", default="audit-reconcile")
    args = parser.parse_args(argv)

    for path, name in ((args.jsonl, "JSONL"), (args.db, "SQLite")):
        if not path.exists() or not path.is_file():
            print(f"{name} input is missing: {path}", file=sys.stderr)
            return 2

    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    jsonl_records, jsonl_lines, duplicates, malformed = read_jsonl(args.jsonl)
    sqlite_records = read_sqlite(args.db)

    shared = set(jsonl_records).intersection(sqlite_records)
    jsonl_only = {key: jsonl_records[key] for key in sorted(set(jsonl_records) - shared)}
    sqlite_only = {key: sqlite_records[key] for key in sorted(set(sqlite_records) - shared)}

    with (out / "jsonl_only.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
        for event_id in sorted(jsonl_only):
            stream.write(jsonl_lines[event_id] + "\n")
    write_jsonl(out / "sqlite_only.jsonl", sqlite_only)
    with (out / "shared_ids.txt").open("w", encoding="utf-8", newline="\n") as stream:
        for event_id in sorted(shared):
            stream.write(event_id + "\n")

    report: dict[str, Any] = {
        "label": args.label,
        "read_only": True,
        "inputs": {
            "jsonl": str(args.jsonl),
            "jsonl_sha256": sha256(args.jsonl),
            "jsonl_bytes": args.jsonl.stat().st_size,
            "sqlite": str(args.db),
            "sqlite_sha256": sha256(args.db),
            "sqlite_bytes": args.db.stat().st_size,
        },
        "counts": {
            "jsonl": len(jsonl_records),
            "sqlite": len(sqlite_records),
            "shared": len(shared),
            "jsonl_only": len(jsonl_only),
            "sqlite_only": len(sqlite_only),
            "jsonl_duplicate_ids": duplicates,
            "jsonl_malformed_lines": malformed,
        },
        "event_distribution": {
            "jsonl": event_counts(jsonl_records),
            "sqlite": event_counts(sqlite_records),
            "jsonl_only": event_counts(jsonl_only),
            "sqlite_only": event_counts(sqlite_only),
        },
        "policy": {
            "authoritative_future_ledger": "sqlite audit_logs",
            "jsonl_role": "mirror/export",
            "no_delete": True,
            "no_backfill": True,
        },
        "artifacts": {
            "jsonl_only": "jsonl_only.jsonl",
            "sqlite_only": "sqlite_only.jsonl",
            "shared_ids": "shared_ids.txt",
        },
    }
    (out / f"{args.label}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    markdown = [
        f"# {args.label}",
        "",
        "只读对账；未删除、未修改、未补造任一账本。",
        "",
        "| 指标 | 数量 |",
        "|---|---:|",
        f"| JSONL 记录 | {len(jsonl_records)} |",
        f"| SQLite 记录 | {len(sqlite_records)} |",
        f"| 共同 ID | {len(shared)} |",
        f"| 仅 JSONL | {len(jsonl_only)} |",
        f"| 仅 SQLite | {len(sqlite_only)} |",
        f"| JSONL 重复 ID | {duplicates} |",
        f"| JSONL 无法解析行 | {malformed} |",
        "",
        "仅单侧事件已原样导出到 `jsonl_only.jsonl` 与 `sqlite_only.jsonl`。",
    ]
    (out / f"{args.label}.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    print(json.dumps(report["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
