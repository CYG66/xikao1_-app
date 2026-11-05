"""Versioned, deterministic command protocol for AI drawing edits.

The model may propose operations, but it never writes a drawing directly.
Every accepted edit is represented by a command with before/after snapshots
and hashes.  The executor checks those preconditions on a working copy and
commits the whole batch only when every command succeeds.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any


COMMAND_CONTRACT_VERSION = "cad-command-1.0"
COMMAND_BATCH_CONTRACT_VERSION = "cad-command-batch-1.0"
_COMMAND_TYPES = {"CREATE", "UPDATE", "DELETE"}


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _entity_id(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def drawing_snapshot_id(geometries: list[dict[str, Any]]) -> str:
    """Return a stable identifier for one exact geometry revision."""
    return f"cad_{_digest(geometries)[:16]}"


def build_command_rollback_evidence(
    source: list[dict[str, Any]],
    *,
    applied_command_count: int,
    triggered: bool,
) -> dict[str, Any]:
    """Prove that a rejected in-memory command batch restored its source."""
    source_snapshot_id = drawing_snapshot_id(source)
    restored_snapshot_id = drawing_snapshot_id(source)
    return {
        "schema": "cad.command.rollback.v1",
        "triggered": triggered,
        "candidate_discarded": True,
        "persisted": False,
        "applied_command_count": applied_command_count,
        "source_snapshot_id": source_snapshot_id,
        "restored_snapshot_id": restored_snapshot_id,
        "verified": source_snapshot_id == restored_snapshot_id,
    }


def build_drawing_commands(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize operation snapshots into the public command contract."""
    commands: list[dict[str, Any]] = []
    type_map = {"add": "CREATE", "update": "UPDATE", "remove": "DELETE"}
    for sequence, record in enumerate(records, 1):
        command_type = type_map.get(str(record.get("op") or "").lower(), "")
        entity_id = _entity_id(record.get("id"))
        before = deepcopy(record.get("before"))
        after = deepcopy(record.get("after"))
        identity = {
            "contract_version": COMMAND_CONTRACT_VERSION,
            "sequence": sequence,
            "command_type": command_type,
            "entity_id": entity_id,
            "before": before,
            "after": after,
        }
        commands.append({
            **identity,
            "command_id": f"cmd_{_digest(identity)[:16]}",
            "precondition_sha256": _digest(before) if before is not None else None,
            "result_sha256": _digest(after) if after is not None else None,
        })
    return commands


def validate_drawing_commands(
    commands: list[dict[str, Any]],
) -> list[str]:
    """Validate command shape and immutable snapshot hashes."""
    errors: list[str] = []
    seen_ids: set[str] = set()
    for index, command in enumerate(commands, 1):
        label = f"第 {index} 条命令"
        if not isinstance(command, dict):
            errors.append(f"{label}必须是对象")
            continue
        if command.get("contract_version") != COMMAND_CONTRACT_VERSION:
            errors.append(f"{label}协议版本无效")
        command_id = str(command.get("command_id") or "")
        if not command_id or command_id in seen_ids:
            errors.append(f"{label}命令 ID 缺失或重复")
        seen_ids.add(command_id)
        command_type = str(command.get("command_type") or "").upper()
        if command_type not in _COMMAND_TYPES:
            errors.append(f"{label}类型无效：{command_type or '空'}")
            continue
        entity_id = _entity_id(command.get("entity_id"))
        if entity_id is None:
            errors.append(f"{label}图元 ID 无效")
        before = command.get("before")
        after = command.get("after")
        sequence = command.get("sequence")
        if sequence != index:
            errors.append(f"{label}序号无效")
        if command_type == "CREATE" and (before is not None or not isinstance(after, dict)):
            errors.append(f"{label} CREATE 必须只有 after 快照")
        if command_type == "UPDATE" and not (
            isinstance(before, dict) and isinstance(after, dict)
        ):
            errors.append(f"{label} UPDATE 必须包含 before/after 快照")
        if command_type == "DELETE" and (
            not isinstance(before, dict) or after is not None
        ):
            errors.append(f"{label} DELETE 必须只有 before 快照")
        for snapshot_name, snapshot in (("before", before), ("after", after)):
            if snapshot is None:
                continue
            if _entity_id(snapshot.get("id")) != entity_id:
                errors.append(f"{label} {snapshot_name} 图元 ID 不一致")
        expected_before = _digest(before) if before is not None else None
        expected_after = _digest(after) if after is not None else None
        if command.get("precondition_sha256") != expected_before:
            errors.append(f"{label}前置状态哈希不一致")
        if command.get("result_sha256") != expected_after:
            errors.append(f"{label}结果状态哈希不一致")
        identity = {
            "contract_version": COMMAND_CONTRACT_VERSION,
            "sequence": sequence,
            "command_type": command_type,
            "entity_id": entity_id,
            "before": before,
            "after": after,
        }
        if command_id != f"cmd_{_digest(identity)[:16]}":
            errors.append(f"{label}内容与命令 ID 不一致")
    return errors


def execute_drawing_commands(
    source: list[dict[str, Any]],
    commands: list[dict[str, Any]],
) -> dict[str, Any]:
    """Replay a command batch atomically on an isolated working copy."""
    original = deepcopy([item for item in source if isinstance(item, dict)])
    working = deepcopy(original)
    errors = validate_drawing_commands(commands)
    if errors:
        return {
            "ok": False,
            "geometries": original,
            "errors": errors,
            "rolled_back": False,
            "rollback_evidence": build_command_rollback_evidence(
                original, applied_command_count=0, triggered=False,
            ),
        }

    applied_count = 0
    for index, command in enumerate(commands, 1):
        command_type = str(command["command_type"])
        entity_id = int(command["entity_id"])
        position = next(
            (i for i, item in enumerate(working) if _entity_id(item.get("id")) == entity_id),
            None,
        )
        before = command.get("before")
        after = command.get("after")
        if command_type == "CREATE":
            if position is not None:
                errors.append(f"第 {index} 条命令失败：图元 {entity_id} 已存在")
                break
            working.append(deepcopy(after))
        elif command_type == "UPDATE":
            if position is None:
                errors.append(f"第 {index} 条命令失败：图元 {entity_id} 不存在")
                break
            if _digest(working[position]) != command["precondition_sha256"]:
                errors.append(f"第 {index} 条命令失败：图元 {entity_id} 已发生变化")
                break
            working[position] = deepcopy(after)
        else:
            if position is None:
                errors.append(f"第 {index} 条命令失败：图元 {entity_id} 不存在")
                break
            if _digest(working[position]) != command["precondition_sha256"]:
                errors.append(f"第 {index} 条命令失败：图元 {entity_id} 已发生变化")
                break
            working.pop(position)
        applied_count += 1

    if errors:
        return {
            "ok": False,
            "geometries": original,
            "errors": errors,
            "rolled_back": applied_count > 0,
            "rollback_evidence": build_command_rollback_evidence(
                original,
                applied_command_count=applied_count,
                triggered=applied_count > 0,
            ),
        }
    return {
        "ok": True,
        "geometries": working,
        "errors": [],
        "rolled_back": False,
        "applied_count": applied_count,
    }


def build_drawing_command_batch(
    source: list[dict[str, Any]],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build and deterministically verify one replayable command batch."""
    commands = build_drawing_commands(records)
    execution = execute_drawing_commands(source, commands)
    source_snapshot_id = drawing_snapshot_id(source)
    target = execution["geometries"] if execution["ok"] else source
    target_snapshot_id = drawing_snapshot_id(target)
    identity = {
        "contract_version": COMMAND_BATCH_CONTRACT_VERSION,
        "source_snapshot_id": source_snapshot_id,
        "commands": commands,
    }
    counts = {
        command_type.lower(): sum(
            command["command_type"] == command_type for command in commands
        )
        for command_type in ("CREATE", "UPDATE", "DELETE")
    }
    return {
        **identity,
        "batch_id": f"batch_{_digest(identity)[:16]}",
        "target_snapshot_id": target_snapshot_id,
        "commands": commands,
        "counts": counts,
        "verified": bool(execution["ok"]),
        "execution": execution,
    }
