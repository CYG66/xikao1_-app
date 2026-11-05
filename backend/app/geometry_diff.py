"""Compare canonical XLine CAD geometries without changing the source drawing."""
from __future__ import annotations

import json
from math import hypot
from copy import deepcopy
from typing import Any

from .drawing_store import preview_paths


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    if isinstance(value, float):
        return round(value, 3)
    return value


def _fingerprint(geometry: dict[str, Any]) -> str:
    return json.dumps(_canonical(geometry), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_geometry_diff(
    source: list[dict[str, Any]], target: list[dict[str, Any]]
) -> dict[str, Any]:
    """Return a stable, ID-aware diff for a source drawing and a variant.

    IDs are preferred because editor-created drawings keep them stable. When an
    ID is missing, exact geometry fingerprints are used so old imported files
    still produce useful results.
    """
    source_items = [deepcopy(item) for item in source if isinstance(item, dict)]
    target_items = [deepcopy(item) for item in target if isinstance(item, dict)]
    source_by_id = {
        str(item["id"]): item
        for item in source_items
        if item.get("id") is not None
    }
    matched_source: set[int] = set()
    matched_target: set[int] = set()
    unchanged: list[dict[str, Any]] = []
    modified: list[dict[str, Any]] = []

    for target_index, item in enumerate(target_items):
        item_id = item.get("id")
        source_item = source_by_id.get(str(item_id)) if item_id is not None else None
        source_index = next(
            (index for index, candidate in enumerate(source_items) if candidate is source_item),
            -1,
        )
        if source_item is None:
            fingerprint = _fingerprint(item)
            for index, candidate in enumerate(source_items):
                if index not in matched_source and _fingerprint(candidate) == fingerprint:
                    source_item = candidate
                    source_index = index
                    break
        if source_item is None:
            continue
        matched_target.add(target_index)
        matched_source.add(source_index)
        if _fingerprint(source_item) == _fingerprint(item):
            unchanged.append(deepcopy(item))
        else:
            modified.append({"before": deepcopy(source_item), "after": deepcopy(item)})

    added = [deepcopy(item) for index, item in enumerate(target_items) if index not in matched_target]
    removed = [deepcopy(item) for index, item in enumerate(source_items) if index not in matched_source]
    return {
        "available": True,
        "source_count": len(source_items),
        "target_count": len(target_items),
        "counts": {
            "added": len(added),
            "removed": len(removed),
            "modified": len(modified),
            "unchanged": len(unchanged),
        },
        "added": added,
        "removed": removed,
        "modified": modified,
        "unchanged": unchanged,
    }


def _path_length(path: list[list[float]]) -> float:
    return sum(
        hypot(float(end[0]) - float(start[0]), float(end[1]) - float(start[1]))
        for start, end in zip(path, path[1:])
    )


def _path_by_geometry(geometries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map printable geometry IDs to their normalized preview path."""
    result: dict[str, dict[str, Any]] = {}
    for geometry in geometries:
        if not isinstance(geometry, dict) or geometry.get("id") is None:
            continue
        paths = preview_paths({"lines": [geometry]})
        if not paths:
            continue
        path = paths[0]
        result[str(geometry["id"])] = {
            "geometry_id": geometry["id"],
            "points": path,
            "point_count": len(path),
            "length_m": round(_path_length(path), 4),
        }
    return result


def build_path_impact(
    source: list[dict[str, Any]], target: list[dict[str, Any]],
) -> dict[str, Any]:
    """Describe which normalized printing paths must be re-planned."""
    before = _path_by_geometry(source)
    after = _path_by_geometry(target)
    affected: list[dict[str, Any]] = []
    for geometry_id in sorted(set(before) | set(after), key=str):
        old_path = before.get(geometry_id)
        new_path = after.get(geometry_id)
        if old_path and new_path:
            if old_path["points"] == new_path["points"]:
                continue
            change = "modified"
        elif new_path:
            change = "added"
        else:
            change = "removed"
        affected.append({
            "geometry_id": new_path["geometry_id"] if new_path else old_path["geometry_id"],
            "change": change,
            "before": old_path,
            "after": new_path,
            "delta": {
                "point_count": (new_path["point_count"] if new_path else 0)
                - (old_path["point_count"] if old_path else 0),
                "length_m": round(
                    (new_path["length_m"] if new_path else 0.0)
                    - (old_path["length_m"] if old_path else 0.0),
                    4,
                ),
            },
            "requires_replan": True,
        })
    risk_level = "high" if any(item["change"] == "removed" for item in affected) else (
        "medium" if affected else "low"
    )
    return {
        "available": True,
        "before_path_count": len(before),
        "after_path_count": len(after),
        "affected_path_count": len(affected),
        "requires_replan": bool(affected),
        "risk_level": risk_level,
        "affected_paths": affected,
    }


def build_diff_preview_paths(geometry_diff: dict[str, Any]) -> list[dict[str, Any]]:
    """Build map-ready paths for a before/after drawing review."""
    paths: list[dict[str, Any]] = []

    def append_geometry(
        geometry: dict[str, Any], diff_kind: str, suffix: str,
    ) -> None:
        for index, points in enumerate(preview_paths({"lines": [geometry]}), 1):
            if len(points) < 2:
                continue
            paths.append({
                "namespace": f"cad_diff_{suffix}_{geometry.get('id', 'unknown')}_{index}",
                "frame_id": "map",
                "route_type": "drawing",
                "diff_kind": diff_kind,
                "geometry_id": geometry.get("id"),
                "points": points,
            })

    for geometry in geometry_diff.get("unchanged") or []:
        if isinstance(geometry, dict):
            append_geometry(geometry, "unchanged", "unchanged")
    for geometry in geometry_diff.get("added") or []:
        if isinstance(geometry, dict):
            append_geometry(geometry, "added", "added")
    for geometry in geometry_diff.get("removed") or []:
        if isinstance(geometry, dict):
            append_geometry(geometry, "removed", "removed")
    for change in geometry_diff.get("modified") or []:
        if not isinstance(change, dict):
            continue
        before = change.get("before")
        after = change.get("after")
        if isinstance(before, dict):
            append_geometry(before, "modified_before", "modified_before")
        if isinstance(after, dict):
            append_geometry(after, "modified", "modified_after")
    return paths


def build_drawing_change_review(
    source_file_name: str,
    target_file_name: str,
    geometry_diff: dict[str, Any],
    path_impact: dict[str, Any],
    feasibility: dict[str, Any],
    *,
    source_sha256: str | None = None,
    source_version: int | None = None,
) -> dict[str, Any]:
    """Build the stable review contract consumed by the App.

    The contract deliberately separates review from execution.  A client can
    render this object directly, but it cannot infer permission to start a
    mission from it.
    """
    counts = dict(geometry_diff.get("counts") or {})
    affected_count = int(path_impact.get("affected_path_count") or 0)
    risk_level = str(path_impact.get("risk_level") or "low")
    warnings = list(dict.fromkeys(
        list(feasibility.get("warnings") or [])
        + (["修改影响喷印路径，必须重新规划"] if path_impact.get("requires_replan") else [])
        + (["存在删除的喷印路径，执行前必须人工确认"] if risk_level == "high" else [])
    ))
    return {
        "contract_version": "1.0",
        "review_only": True,
        "source": {
            "file_name": source_file_name,
            "sha256": source_sha256,
            "version": source_version,
        },
        "result": {
            "file_name": target_file_name,
            "status": "saved_for_review",
            "next_action": "plan_preview",
        },
        "summary": {
            "geometry_added": int(counts.get("added") or 0),
            "geometry_removed": int(counts.get("removed") or 0),
            "geometry_modified": int(counts.get("modified") or 0),
            "geometry_unchanged": int(counts.get("unchanged") or 0),
            "paths_before": int(path_impact.get("before_path_count") or 0),
            "paths_after": int(path_impact.get("after_path_count") or 0),
            "paths_affected": affected_count,
        },
        "geometry_diff": geometry_diff,
        "path_impact": path_impact,
        "feasibility": feasibility,
        "risk": {
            "level": risk_level,
            "warnings": warnings,
        },
        "execution": {
            "requires_replan": bool(path_impact.get("requires_replan")),
            "requires_user_confirmation": True,
            "execution_allowed": False,
        },
    }
