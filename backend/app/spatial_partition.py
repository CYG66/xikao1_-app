from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from typing import Any

from .drawing_store import geometry_preview_paths


PARTITION_SCHEMA = "cad.spatial-partition.v1"
LOCAL_FRAME_SCHEMA = "cad.local-frame.v1"
EXECUTION_SEGMENT_SCHEMA = "cad.execution-segment.v1"
MAX_SEGMENT_GEOMETRIES = 100
MAX_SEGMENT_PRINTING_LENGTH_M = 500.0
ZONE_STATUSES = {
    "not_required",
    "pending",
    "planning",
    "planned",
    "pending_confirmation",
    "executing",
    "paused",
    "completed",
    "failed",
    "cancelled",
}
_EPSILON = 1e-8


def build_spatial_partition(
    variant_id: str,
    geometries: list[dict[str, Any]],
    logical_objects: list[dict[str, Any]] | None,
    topology: dict[str, Any] | None,
    project_scale: dict[str, Any],
) -> dict[str, Any]:
    """Split printable geometry into deterministic, independently executable zones."""
    source_paths = _source_paths(geometries)
    bounds = _path_bounds(source_paths)
    rows = max(1, int(project_scale.get("suggested_rows") or 1))
    columns = max(1, int(project_scale.get("suggested_columns") or 1))
    zones = _empty_zones(bounds, rows, columns)
    max_source_id = max(
        (int(item.get("id")) for item in geometries if isinstance(item.get("id"), int)),
        default=0,
    )
    next_fragment_geometry_id = max_source_id + 1
    fragments_by_source: dict[int, list[dict[str, Any]]] = {}
    source_by_id = {
        int(item["id"]): item
        for item in geometries
        if isinstance(item, dict) and isinstance(item.get("id"), int)
    }

    for source_id in sorted(source_paths):
        path = source_paths[source_id]
        grouped = _split_path(path, bounds, rows, columns)
        fragments: list[dict[str, Any]] = []
        for ordinal, group in enumerate(grouped, start=1):
            fragment_geometry_id = (
                source_id if len(grouped) == 1 else next_fragment_geometry_id
            )
            if len(grouped) != 1:
                next_fragment_geometry_id += 1
            zone_id = _zone_id(group["row"], group["column"])
            fragment_id = f"g{source_id}-f{ordinal:04d}"
            fragment = _fragment_geometry(
                source_by_id[source_id],
                fragment_geometry_id,
                source_id,
                fragment_id,
                zone_id,
                ordinal,
                group["points"],
            )
            record = {
                "fragment_id": fragment_id,
                "geometry_id": fragment_geometry_id,
                "source_geometry_id": source_id,
                "zone_id": zone_id,
                "order": ordinal,
                "points": group["points"],
                "geometry": fragment,
                "incoming_link_ids": [],
                "outgoing_link_ids": [],
            }
            fragments.append(record)
            zone = zones[(group["row"], group["column"])]
            zone["geometries"].append(fragment)
            zone["source_geometry_ids"].add(source_id)
        fragments_by_source[source_id] = fragments

    continuity_links = _continuity_links(fragments_by_source)
    fragment_index = {
        item["fragment_id"]: item
        for fragments in fragments_by_source.values()
        for item in fragments
    }
    for link in continuity_links:
        fragment_index[link["from_fragment_id"]]["outgoing_link_ids"].append(link["id"])
        fragment_index[link["to_fragment_id"]]["incoming_link_ids"].append(link["id"])
    for record in fragment_index.values():
        record["geometry"]["partition_continuity"] = {
            "incoming_link_ids": record["incoming_link_ids"],
            "outgoing_link_ids": record["outgoing_link_ids"],
        }

    ordered_zones = _ordered_zones(zones, logical_objects or [], topology or {})
    source_length = sum(_path_length(path) for path in source_paths.values())
    partition_length = sum(
        _path_length(record["points"])
        for fragments in fragments_by_source.values()
        for record in fragments
    )
    covered_source_ids = sorted(
        {
            int(item["source_geometry_id"])
            for fragments in fragments_by_source.values()
            for item in fragments
        }
    )
    expected_source_ids = sorted(source_paths)
    coverage_verified = (
        expected_source_ids == covered_source_ids
        and abs(source_length - partition_length) <= max(1e-6, source_length * 1e-9)
    )
    coordinate_verified = all(
        _local_projection_verified(zone)
        for zone in ordered_zones
        if zone.get("status") != "not_required"
    )
    contract_verified = coverage_verified and coordinate_verified
    contract = {
        "schema": PARTITION_SCHEMA,
        "status": "ready" if contract_verified else "invalid",
        "variant_id": variant_id,
        "source_sha256": _geometry_sha256(geometries),
        "bounds_m": bounds,
        "grid": {
            "rows": rows,
            "columns": columns,
            "zone_count": rows * columns,
            "construction_zone_count": sum(
                1 for zone in ordered_zones if zone["status"] != "not_required"
            ),
            "work_zone_size_m": float(project_scale.get("work_zone_size_m") or 50.0),
            "order": "serpentine_bottom_to_top",
        },
        "zones": ordered_zones,
        "continuity": {
            "verified": contract_verified,
            "link_count": len(continuity_links),
            "links": continuity_links,
        },
        "coverage": {
            "verified": coverage_verified,
            "source_geometry_ids": expected_source_ids,
            "covered_source_geometry_ids": covered_source_ids,
            "source_length_m": round(source_length, 6),
            "partition_length_m": round(partition_length, 6),
            "length_delta_m": round(partition_length - source_length, 9),
            "duplicate_printing_segments": 0,
            "uncovered_geometry_ids": sorted(
                set(expected_source_ids) - set(covered_source_ids)
            ),
        },
        "coordinate_validation": {
            "verified": coordinate_verified,
            "canonical_space": "zone_local_mm",
            "planner_compatibility_space": "map_mm",
            "round_trip_tolerance_mm": 1e-6,
        },
    }
    return refresh_partition_summary(contract)


def next_partition_zone(partition: dict[str, Any]) -> dict[str, Any] | None:
    for zone in partition.get("zones") or []:
        if (
            isinstance(zone, dict)
            and zone.get("status") not in {"not_required", "completed"}
        ):
            return deepcopy(zone)
    return None


def next_partition_segment(zone: dict[str, Any]) -> dict[str, Any] | None:
    for segment in zone.get("execution_segments") or []:
        if (
            isinstance(segment, dict)
            and segment.get("status") not in {"completed", "not_required"}
        ):
            return deepcopy(segment)
    return None


def update_partition_zone(
    partition: dict[str, Any],
    zone_id: str,
    status: str,
    **updates: Any,
) -> dict[str, Any]:
    if status not in ZONE_STATUSES:
        raise ValueError(f"unsupported partition zone status: {status}")
    result = deepcopy(partition)
    found = False
    for zone in result.get("zones") or []:
        if not isinstance(zone, dict) or zone.get("id") != zone_id:
            continue
        zone["status"] = status
        for key, value in updates.items():
            if value is not None:
                zone[key] = deepcopy(value)
        progress = dict(zone.get("progress") or {})
        total = int(progress.get("geometry_total") or len(zone.get("geometries") or []))
        if status == "completed":
            progress["geometry_completed"] = total
            progress["ratio"] = 1.0
        elif "geometry_completed" in updates:
            completed = max(0, min(total, int(updates["geometry_completed"])))
            progress["geometry_completed"] = completed
            progress["ratio"] = round(completed / total, 4) if total else 1.0
        zone["progress"] = progress
        for segment in zone.get("execution_segments") or []:
            if not isinstance(segment, dict):
                continue
            segment["status"] = status
            if status == "completed":
                segment_progress = dict(segment.get("progress") or {})
                segment_total = int(
                    segment_progress.get("geometry_total")
                    or len(segment.get("geometry_ids") or [])
                )
                segment_progress.update({
                    "geometry_completed": segment_total,
                    "ratio": 1.0,
                })
                segment["progress"] = segment_progress
        if zone.get("execution_segments"):
            _refresh_zone_from_segments(zone)
        found = True
        break
    if not found:
        raise ValueError(f"partition zone does not exist: {zone_id}")
    return refresh_partition_summary(result)


def update_partition_segment(
    partition: dict[str, Any],
    zone_id: str,
    segment_id: str,
    status: str,
    **updates: Any,
) -> dict[str, Any]:
    if status not in ZONE_STATUSES:
        raise ValueError(f"unsupported partition segment status: {status}")
    result = deepcopy(partition)
    for zone in result.get("zones") or []:
        if not isinstance(zone, dict) or zone.get("id") != zone_id:
            continue
        segments = zone.get("execution_segments") or []
        target = next(
            (
                item for item in segments
                if isinstance(item, dict) and item.get("id") == segment_id
            ),
            None,
        )
        if target is None:
            raise ValueError(f"partition segment does not exist: {segment_id}")
        target["status"] = status
        for key, value in updates.items():
            if value is not None:
                target[key] = deepcopy(value)
        target_progress = dict(target.get("progress") or {})
        geometry_total = int(
            target_progress.get("geometry_total")
            or len(target.get("geometry_ids") or [])
        )
        if status == "completed":
            target_progress.update({
                "geometry_completed": geometry_total,
                "ratio": 1.0,
            })
        elif "geometry_completed" in updates:
            completed = max(
                0, min(geometry_total, int(updates["geometry_completed"]))
            )
            target_progress.update({
                "geometry_completed": completed,
                "ratio": round(completed / geometry_total, 4)
                if geometry_total else 1.0,
            })
        target["progress"] = target_progress
        _refresh_zone_from_segments(zone)
        return refresh_partition_summary(result)
    raise ValueError(f"partition zone does not exist: {zone_id}")


def refresh_partition_summary(partition: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(partition)
    zones = [item for item in result.get("zones") or [] if isinstance(item, dict)]
    construction = [item for item in zones if item.get("status") != "not_required"]
    counts: dict[str, int] = {}
    for zone in zones:
        status = str(zone.get("status") or "pending")
        counts[status] = counts.get(status, 0) + 1
    completed = counts.get("completed", 0)
    execution_segments = [
        segment
        for zone in construction
        for segment in zone.get("execution_segments") or []
        if isinstance(segment, dict)
    ]
    completed_segments = sum(
        1 for segment in execution_segments if segment.get("status") == "completed"
    )
    result["summary"] = {
        "zone_status_counts": counts,
        "construction_zone_count": len(construction),
        "completed_zone_count": completed,
        "remaining_zone_count": max(0, len(construction) - completed),
        "progress": round(completed / len(construction), 4) if construction else 1.0,
        "all_completed": bool(construction) and completed == len(construction),
        "execution_segment_count": len(execution_segments),
        "completed_execution_segment_count": completed_segments,
        "remaining_execution_segment_count": max(
            0, len(execution_segments) - completed_segments
        ),
    }
    return result


def _source_paths(geometries: list[dict[str, Any]]) -> dict[int, list[list[float]]]:
    result: dict[int, list[list[float]]] = {}
    for geometry in geometries:
        source_id = geometry.get("id") if isinstance(geometry, dict) else None
        if not isinstance(source_id, int) or source_id <= 0:
            continue
        previews = geometry_preview_paths({"lines": [geometry]})
        if previews and isinstance(previews[0].get("points"), list):
            points = [
                [float(point[0]), float(point[1])]
                for point in previews[0]["points"]
                if isinstance(point, list) and len(point) >= 2
            ]
            if len(points) >= 2:
                result[source_id] = points
    return result


def _path_bounds(paths: dict[int, list[list[float]]]) -> dict[str, float]:
    points = [point for path in paths.values() for point in path]
    if not points:
        return {"min_x": 0.0, "min_y": 0.0, "max_x": 0.0, "max_y": 0.0}
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return {
        "min_x": min(xs),
        "min_y": min(ys),
        "max_x": max(xs),
        "max_y": max(ys),
    }


def _empty_zones(
    bounds: dict[str, float], rows: int, columns: int
) -> dict[tuple[int, int], dict[str, Any]]:
    width = max(0.0, bounds["max_x"] - bounds["min_x"])
    height = max(0.0, bounds["max_y"] - bounds["min_y"])
    zone_width = width / columns if columns else 0.0
    zone_height = height / rows if rows else 0.0
    result: dict[tuple[int, int], dict[str, Any]] = {}
    sequence = 0
    for row in range(rows):
        columns_in_order = range(columns) if row % 2 == 0 else range(columns - 1, -1, -1)
        for column in columns_in_order:
            sequence += 1
            min_x = bounds["min_x"] + column * zone_width
            max_x = bounds["max_x"] if column == columns - 1 else min_x + zone_width
            min_y = bounds["min_y"] + row * zone_height
            max_y = bounds["max_y"] if row == rows - 1 else min_y + zone_height
            result[(row, column)] = {
                "id": _zone_id(row, column),
                "row": row + 1,
                "column": column + 1,
                "sequence": sequence,
                "bounds_m": {
                    "min_x": round(min_x, 9),
                    "min_y": round(min_y, 9),
                    "max_x": round(max_x, 9),
                    "max_y": round(max_y, 9),
                },
                "status": "pending",
                "geometries": [],
                "source_geometry_ids": set(),
            }
    return result


def _split_path(
    points: list[list[float]],
    bounds: dict[str, float],
    rows: int,
    columns: int,
) -> list[dict[str, Any]]:
    width = bounds["max_x"] - bounds["min_x"]
    height = bounds["max_y"] - bounds["min_y"]
    verticals = [bounds["min_x"] + width * index / columns for index in range(1, columns)]
    horizontals = [bounds["min_y"] + height * index / rows for index in range(1, rows)]
    pieces: list[dict[str, Any]] = []
    for start, end in zip(points, points[1:]):
        if _same_point(start, end):
            continue
        parameters = [0.0, 1.0]
        dx, dy = end[0] - start[0], end[1] - start[1]
        if abs(dx) > _EPSILON:
            parameters.extend(
                (value - start[0]) / dx
                for value in verticals
                if _EPSILON < (value - start[0]) / dx < 1.0 - _EPSILON
            )
        if abs(dy) > _EPSILON:
            parameters.extend(
                (value - start[1]) / dy
                for value in horizontals
                if _EPSILON < (value - start[1]) / dy < 1.0 - _EPSILON
            )
        parameters = sorted(set(round(value, 12) for value in parameters))
        for first, second in zip(parameters, parameters[1:]):
            segment_start = [start[0] + dx * first, start[1] + dy * first]
            segment_end = [start[0] + dx * second, start[1] + dy * second]
            midpoint = [
                (segment_start[0] + segment_end[0]) / 2.0,
                (segment_start[1] + segment_end[1]) / 2.0,
            ]
            row, column = _point_zone(midpoint, bounds, rows, columns)
            pieces.append({
                "row": row,
                "column": column,
                "points": [segment_start, segment_end],
            })
    grouped: list[dict[str, Any]] = []
    for piece in pieces:
        if (
            grouped
            and grouped[-1]["row"] == piece["row"]
            and grouped[-1]["column"] == piece["column"]
            and _same_point(grouped[-1]["points"][-1], piece["points"][0])
        ):
            grouped[-1]["points"].append(piece["points"][1])
        else:
            grouped.append(deepcopy(piece))
    return grouped


def _point_zone(
    point: list[float], bounds: dict[str, float], rows: int, columns: int
) -> tuple[int, int]:
    width = bounds["max_x"] - bounds["min_x"]
    height = bounds["max_y"] - bounds["min_y"]
    column = 0 if width <= _EPSILON else math.floor(
        (point[0] - bounds["min_x"]) / width * columns
    )
    row = 0 if height <= _EPSILON else math.floor(
        (point[1] - bounds["min_y"]) / height * rows
    )
    return max(0, min(rows - 1, row)), max(0, min(columns - 1, column))


def _fragment_geometry(
    source: dict[str, Any],
    geometry_id: int,
    source_geometry_id: int,
    fragment_id: str,
    zone_id: str,
    ordinal: int,
    points: list[list[float]],
) -> dict[str, Any]:
    metadata_keys = {
        "layer_id", "layer", "role", "path_semantic", "selected", "label", "name",
        "template_instance", "template_type", "line_type", "line_width", "color",
    }
    result = {key: deepcopy(value) for key, value in source.items() if key in metadata_keys}
    result.update({
        "id": geometry_id,
        "type": "polyline",
        "vertices": [
            {"x": round(point[0] * 1000.0, 6), "y": round(point[1] * 1000.0, 6), "z": 0.0}
            for point in points
        ],
        "closed": False,
        "source_geometry_id": source_geometry_id,
        "partition_fragment_id": fragment_id,
        "partition_zone_id": zone_id,
        "fragment_order": ordinal,
    })
    return result


def _continuity_links(
    fragments_by_source: dict[int, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for source_id, fragments in fragments_by_source.items():
        pairs = list(zip(fragments, fragments[1:]))
        if (
            len(fragments) > 1
            and _same_point(fragments[-1]["points"][-1], fragments[0]["points"][0])
        ):
            pairs.append((fragments[-1], fragments[0]))
        link_ordinal = 0
        for before, after in pairs:
            if before["zone_id"] == after["zone_id"]:
                continue
            if not _same_point(before["points"][-1], after["points"][0]):
                continue
            link_ordinal += 1
            links.append({
                "id": f"g{source_id}-link-{link_ordinal:04d}",
                "source_geometry_id": source_id,
                "from_zone_id": before["zone_id"],
                "from_fragment_id": before["fragment_id"],
                "to_zone_id": after["zone_id"],
                "to_fragment_id": after["fragment_id"],
                "point_m": [
                    round(before["points"][-1][0], 9),
                    round(before["points"][-1][1], 9),
                ],
            })
    return links


def _ordered_zones(
    zones: dict[tuple[int, int], dict[str, Any]],
    logical_objects: list[dict[str, Any]],
    topology: dict[str, Any],
) -> list[dict[str, Any]]:
    shared_by_source = {
        int(item["geometry_id"]): list(item.get("object_ids") or [])
        for item in topology.get("shared_geometries") or []
        if isinstance(item, dict) and isinstance(item.get("geometry_id"), int)
    }
    ordered = sorted(zones.values(), key=lambda item: int(item["sequence"]))
    for zone in ordered:
        geometries = zone["geometries"]
        source_to_fragments: dict[int, list[int]] = {}
        for geometry in geometries:
            source_to_fragments.setdefault(int(geometry["source_geometry_id"]), []).append(
                int(geometry["id"])
            )
        zone_objects = []
        for logical_object in logical_objects:
            refs = {
                int(value)
                for value in logical_object.get("geometry_refs") or []
                if isinstance(value, int)
            }
            fragment_refs = sorted(
                fragment_id
                for source_id in refs
                for fragment_id in source_to_fragments.get(source_id, [])
            )
            if not fragment_refs:
                continue
            item = deepcopy(logical_object)
            item["source_object_id"] = logical_object.get("object_id")
            item["geometry_refs"] = fragment_refs
            zone_objects.append(item)
        shared = []
        for source_id, object_ids in shared_by_source.items():
            for fragment_id in source_to_fragments.get(source_id, []):
                shared.append({
                    "geometry_id": fragment_id,
                    "source_geometry_id": source_id,
                    "object_ids": object_ids,
                })
        zone["logical_objects"] = zone_objects
        zone["topology"] = {
            "schema_version": "cad.topology.v1",
            "shared_geometries": shared,
            "relations": [],
        }
        zone["source_geometry_ids"] = sorted(zone["source_geometry_ids"])
        zone["preview_paths"] = geometry_preview_paths({"lines": geometries})
        zone["local_frame"] = _local_frame(zone)
        zone["local_geometries"] = [
            _geometry_to_local(geometry, zone["local_frame"])
            for geometry in geometries
        ]
        zone["execution_segments"] = _execution_segments(zone)
        if geometries:
            _refresh_zone_from_segments(zone)
        else:
            zone["status"] = "not_required"
            zone["progress"] = {
                "geometry_total": 0,
                "geometry_completed": 0,
                "ratio": 1.0,
                "segment_total": 0,
                "segment_completed": 0,
            }
    return ordered


def _local_frame(zone: dict[str, Any]) -> dict[str, Any]:
    bounds = zone["bounds_m"]
    origin_x = float(bounds["min_x"])
    origin_y = float(bounds["min_y"])
    return {
        "schema": LOCAL_FRAME_SCHEMA,
        "frame_id": f"{zone['id']}-local",
        "parent_frame_id": "map",
        "origin_map_m": {"x": origin_x, "y": origin_y, "z": 0.0},
        "yaw_degrees": 0.0,
        "transform": {
            "type": "translation",
            "local_to_map_m": {"x": origin_x, "y": origin_y, "z": 0.0},
            "map_to_local_m": {"x": -origin_x, "y": -origin_y, "z": 0.0},
        },
        "canonical_geometry_space": "local_mm",
        "planner_compatibility_projection": "map_mm",
    }


def _geometry_to_local(
    geometry: dict[str, Any], local_frame: dict[str, Any]
) -> dict[str, Any]:
    result = deepcopy(geometry)
    origin = local_frame["origin_map_m"]
    dx_mm = float(origin["x"]) * 1000.0
    dy_mm = float(origin["y"]) * 1000.0

    def translate_point(value: Any) -> None:
        if not isinstance(value, dict):
            return
        if isinstance(value.get("x"), (int, float)):
            value["x"] = round(float(value["x"]) - dx_mm, 6)
        if isinstance(value.get("y"), (int, float)):
            value["y"] = round(float(value["y"]) - dy_mm, 6)

    for key in ("start", "end", "center", "position"):
        translate_point(result.get(key))
    for key in ("vertices", "control_points"):
        values = result.get(key)
        if isinstance(values, list):
            for value in values:
                translate_point(value)
    result["coordinate_frame"] = str(local_frame["frame_id"])
    result["map_projection"] = {
        "origin_x_m": float(origin["x"]),
        "origin_y_m": float(origin["y"]),
    }
    return result


def _local_projection_verified(zone: dict[str, Any]) -> bool:
    frame = zone.get("local_frame") or {}
    origin = frame.get("origin_map_m") or {}
    try:
        dx_mm = float(origin["x"]) * 1000.0
        dy_mm = float(origin["y"]) * 1000.0
    except (KeyError, TypeError, ValueError):
        return False
    global_by_id = {
        int(item["id"]): item
        for item in zone.get("geometries") or []
        if isinstance(item, dict) and isinstance(item.get("id"), int)
    }
    local_by_id = {
        int(item["id"]): item
        for item in zone.get("local_geometries") or []
        if isinstance(item, dict) and isinstance(item.get("id"), int)
    }
    if set(global_by_id) != set(local_by_id):
        return False

    def points(geometry: dict[str, Any]) -> list[tuple[float, float]]:
        result: list[tuple[float, float]] = []
        for key in ("start", "end", "center", "position"):
            value = geometry.get(key)
            if isinstance(value, dict):
                result.append((float(value.get("x", 0.0)), float(value.get("y", 0.0))))
        for key in ("vertices", "control_points"):
            for value in geometry.get(key) or []:
                if isinstance(value, dict):
                    result.append((float(value.get("x", 0.0)), float(value.get("y", 0.0))))
        return result

    for geometry_id, global_geometry in global_by_id.items():
        global_points = points(global_geometry)
        local_points = points(local_by_id[geometry_id])
        if len(global_points) != len(local_points):
            return False
        for global_point, local_point in zip(global_points, local_points):
            if (
                abs(global_point[0] - (local_point[0] + dx_mm)) > 1e-6
                or abs(global_point[1] - (local_point[1] + dy_mm)) > 1e-6
            ):
                return False
    return True


def _execution_segments(zone: dict[str, Any]) -> list[dict[str, Any]]:
    global_by_id = {
        int(item["id"]): item
        for item in zone.get("geometries") or []
        if isinstance(item, dict) and isinstance(item.get("id"), int)
    }
    local_by_id = {
        int(item["id"]): item
        for item in zone.get("local_geometries") or []
        if isinstance(item, dict) and isinstance(item.get("id"), int)
    }
    ordered_ids = sorted(
        global_by_id,
        key=lambda geometry_id: (
            int(global_by_id[geometry_id].get("source_geometry_id") or geometry_id),
            int(global_by_id[geometry_id].get("fragment_order") or 0),
            geometry_id,
        ),
    )
    groups: list[list[int]] = []
    current: list[int] = []
    current_length = 0.0
    for geometry_id in ordered_ids:
        geometry_length = sum(
            _path_length(path["points"])
            for path in geometry_preview_paths({"lines": [global_by_id[geometry_id]]})
            if isinstance(path.get("points"), list)
        )
        if current and (
            len(current) >= MAX_SEGMENT_GEOMETRIES
            or current_length + geometry_length > MAX_SEGMENT_PRINTING_LENGTH_M
        ):
            groups.append(current)
            current = []
            current_length = 0.0
        current.append(geometry_id)
        current_length += geometry_length
    if current:
        groups.append(current)

    segments: list[dict[str, Any]] = []
    for index, geometry_ids in enumerate(groups, start=1):
        global_geometries = [deepcopy(global_by_id[value]) for value in geometry_ids]
        local_geometries = [deepcopy(local_by_id[value]) for value in geometry_ids]
        length_m = sum(
            _path_length(path["points"])
            for geometry in global_geometries
            for path in geometry_preview_paths({"lines": [geometry]})
            if isinstance(path.get("points"), list)
        )
        segments.append({
            "schema": EXECUTION_SEGMENT_SCHEMA,
            "id": f"{zone['id']}-segment-{index:04d}",
            "sequence": index,
            "status": "pending",
            "geometry_ids": geometry_ids,
            "source_geometry_ids": sorted({
                int(item.get("source_geometry_id") or item["id"])
                for item in global_geometries
            }),
            "printing_length_m": round(length_m, 6),
            "global_geometries": global_geometries,
            "local_geometries": local_geometries,
            "local_frame_id": zone["local_frame"]["frame_id"],
            "progress": {
                "geometry_total": len(geometry_ids),
                "geometry_completed": 0,
                "ratio": 0.0,
            },
        })
    return segments


def _refresh_zone_from_segments(zone: dict[str, Any]) -> None:
    segments = [
        item for item in zone.get("execution_segments") or []
        if isinstance(item, dict)
    ]
    statuses = [str(item.get("status") or "pending") for item in segments]
    completed = sum(status == "completed" for status in statuses)
    if segments and completed == len(segments):
        zone["status"] = "completed"
    elif "executing" in statuses:
        zone["status"] = "executing"
    elif "paused" in statuses:
        zone["status"] = "paused"
    elif "pending_confirmation" in statuses:
        zone["status"] = "pending_confirmation"
    elif "planned" in statuses:
        zone["status"] = "planned"
    elif "planning" in statuses:
        zone["status"] = "planning"
    elif "failed" in statuses:
        zone["status"] = "failed"
    elif "cancelled" in statuses:
        zone["status"] = "cancelled"
    else:
        zone["status"] = "pending"
    total_geometries = sum(
        int((item.get("progress") or {}).get("geometry_total") or 0)
        for item in segments
    )
    completed_geometries = sum(
        int((item.get("progress") or {}).get("geometry_completed") or 0)
        for item in segments
    )
    zone["progress"] = {
        "geometry_total": total_geometries,
        "geometry_completed": completed_geometries,
        "ratio": round(completed_geometries / total_geometries, 4)
        if total_geometries else 1.0,
        "segment_total": len(segments),
        "segment_completed": completed,
    }


def _zone_id(row: int, column: int) -> str:
    return f"zone-r{row + 1:03d}-c{column + 1:03d}"


def _same_point(first: list[float], second: list[float]) -> bool:
    return abs(first[0] - second[0]) <= _EPSILON and abs(first[1] - second[1]) <= _EPSILON


def _path_length(points: list[list[float]]) -> float:
    return sum(
        math.hypot(end[0] - start[0], end[1] - start[1])
        for start, end in zip(points, points[1:])
    )


def _geometry_sha256(geometries: list[dict[str, Any]]) -> str:
    canonical = json.dumps(
        geometries, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
