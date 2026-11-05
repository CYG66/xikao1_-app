"""Stable identity checks for versioned CAD geometries."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def normalize_geometry_identity(
    geometries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None, str | None]:
    """Keep existing IDs, fill legacy gaps, and reject ambiguous identities."""
    normalized = deepcopy(geometries)
    used: set[int] = set()
    numeric_ids = {
        int(item["id"])
        for item in normalized
        if isinstance(item, dict)
        and str(item.get("id", "")).isdigit()
        and int(item["id"]) > 0
    }
    next_id = max(numeric_ids, default=0) + 1
    for item in normalized:
        if not isinstance(item, dict):
            return None, None, "候选包含无效图元，无法建立稳定身份。"
        raw_id = item.get("id")
        if raw_id is None or str(raw_id).strip() == "":
            while next_id in used or next_id in numeric_ids:
                next_id += 1
            item["id"] = next_id
            used.add(next_id)
            next_id += 1
        else:
            try:
                geometry_id = int(raw_id)
            except (TypeError, ValueError):
                return None, None, "图元 ID 必须是正整数，无法保存候选。"
            if geometry_id <= 0 or geometry_id in used:
                return None, None, "候选包含重复或无效图元 ID，已阻止保存。"
            item["id"] = geometry_id
            used.add(geometry_id)
    instance_ids = sorted({
        int(item["template_instance"])
        for item in normalized
        if isinstance(item.get("template_instance"), (int, float))
        and int(item["template_instance"]) > 0
    })
    groups = [
        {
            "instance_id": instance_id,
            "geometry_ids": sorted(
                int(item["id"])
                for item in normalized
                if isinstance(item.get("template_instance"), (int, float))
                and int(item["template_instance"]) == instance_id
            ),
        }
        for instance_id in instance_ids
    ]
    identity = {
        "schema": "cad.identity.v1",
        "geometry_ids": sorted(used),
        "instance_ids": instance_ids,
        "geometry_count": len(normalized),
        "instance_count": len(instance_ids),
        "groups": groups,
        "instances_authoritative": bool(normalized)
        and all(
            isinstance(item.get("template_instance"), (int, float))
            and int(item["template_instance"]) > 0
            for item in normalized
        ),
    }
    return normalized, identity, None


def validate_identity_continuity(
    parent: list[dict[str, Any]], child: list[dict[str, Any]],
) -> str | None:
    """Reject reuse of a stable geometry ID for a different instance."""
    parent_by_id = {
        int(item["id"]): item
        for item in parent
        if isinstance(item, dict) and str(item.get("id", "")).isdigit()
    }
    for item in child:
        geometry_id = int(item["id"])
        previous = parent_by_id.get(geometry_id)
        if previous is None:
            continue
        before = previous.get("template_instance")
        after = item.get("template_instance")
        before_stable = isinstance(before, (int, float)) and int(before) > 0
        after_stable = isinstance(after, (int, float)) and int(after) > 0
        if before_stable and after_stable and int(before) != int(after):
            return (
                f"图元 {geometry_id} 的实例分组从 {before} 变为 {after}，"
                "已阻止不稳定身份写入。"
            )
    return None
