"""P0 exhaustive semantic dispatch and P0' per-object target binding.

This module is measurement-only: it never generates geometry, never edits a
plan, and never trusts a model-declared ``object_id`` as identity.  Target
identity is resolved backend-side:

* primary source: construction result ``logical_objects[*].geometry_refs``;
* corroboration: backend connected components reconstructed from the active
  linework (shared vertex or within-tolerance contact);
* bounds are used only for overlap diagnostics / ordering.

The dispatch table maps each recognized semantic requirement ``kind`` to
exactly one checker channel.  Kinds absent from the table reach the explicit
``unsupported`` branch; there is no default fall-through into the capital-A
checker.
"""
from __future__ import annotations

import math
import re
from typing import Any, Iterable

from shapely.geometry import LineString, Polygon

# Active linework mirrors the other acceptance verifiers: annotations,
# reference geometry and explicitly ignored selections are excluded.
INACTIVE_ROLES = {"annotation", "reference", "ignored"}

CONTACT_TOLERANCE_MM = 0.5

# Exhaustive kind -> channel map.  Every recognized semantic requirement has
# one and only one channel; adding a kind here is the only way a checker can
# receive it.
DISPATCH_CHANNELS: dict[str, str] = {
    "heart_outline_features": "heart_outline",
    "straight_capital_a": "capital_a",
    "triangle_roof_house": "house_outline",
    "house_outline": "house_outline",
}

# Recognized requirement kinds backed by a dedicated verifier special-cased
# outside the channel table.  They are still mandatory: a ``passed`` report
# means fully verified; any other terminal state must not be promoted to a
# summary PASS.
SPECIAL_VERIFIED_KINDS: frozenset[str] = frozenset({
    "astroid_identity",
    "nested_square_frames",
    "regular_polygon",
    "cardioid_identity",
})

# Recognized shapes/profiles with no backend verifier.  These are capability
# gaps: they block PASS and must never be silently treated as "no applicable
# requirement".  No checker and no generator is registered for them here.
UNVERIFIABLE_RECOGNIZED_KINDS: frozenset[str] = frozenset({
    "star_profile",
})

# All mandatory requirement kinds the acceptance contract recognizes.
MANDATORY_REQUIREMENT_KINDS: frozenset[str] = (
    frozenset(DISPATCH_CHANNELS.keys())
    | SPECIAL_VERIFIED_KINDS
    | UNVERIFIABLE_RECOGNIZED_KINDS
)

# Coverage value -> special verified kind.  Branches that return before the
# ``requirements`` list still expose their recognized kind through coverage.
SPECIAL_VERIFIED_COVERAGE_KINDS: dict[str, str] = {
    "astroid_identity_radius_and_four_cusps": "astroid_identity",
    "explicit_nested_square_frames": "nested_square_frames",
    "explicit_regular_polygon_and_concentric_hole": "regular_polygon",
    "cardioid_shape_and_declared_direction": "cardioid_identity",
}

# Generic source-text vocabulary for recognized-but-no-verifier shapes.
# Used ONLY to populate the applicability marker; no verifier, no generator
# is registered.  ``星形线`` (astroid) is a special verified kind and must
# never match the star profile pattern.
UNVERIFIABLE_SHAPE_PATTERNS: dict[str, str] = {
    "star_profile": r"五角星|五芒星|星形轮廓",
}

# Ambiguous source wording that could denote a star but could also denote a
# plain convex polygon / a non-geometric mention.  This is NOT a recognized
# mandatory requirement: the wording alone must never establish a star
# requirement.  It only keeps the case unresolved until the backend profile
# can corroborate it; an ambiguous source that resolves to a non-star outline
# must be released normally.  Astroid wording is excluded here as well.
AMBIGUOUS_SHAPE_PATTERNS: dict[str, str] = {
    "star_profile": r"五角形|星形|星星|星型",
}

# Wording that denotes the verified astroid channel; ambiguous / star gates
# must yield to it.
_ASTROID_TEXT_PATTERN = r"astroid|星形线"

# Contract state vocabulary (terminal report status words are unchanged).
STATE_NO_APPLICABLE_REQUIREMENT = "no_applicable_requirement"
STATE_FULLY_VERIFIED = "fully_verified"
STATE_UNVERIFIED_OR_PARTIAL = "unverified_or_partial"

# Profile gate thresholds (calibrated against synthetic fixtures; see the
# round8 report and machine-readable JSON for per-fixture measurements).
STAR_VALLEY_MIN = 4
STAR_HULL_RATIO_MAX = 0.72
STAR_FOLD_RESIDUAL_MAX = 0.08
HEART_VALLEY_MAX = 1
HEART_HULL_RATIO_MIN = 0.90
HEART_FOLD_RESIDUAL_MIN = 0.15

# Inherited 423E heart feature thresholds, scoped to the bound object's own
# bounds.  Values are unchanged; only the measurement scope changed.
HEART_FEATURE_RULES = {
    "center_notch": {"x_band": 0.03, "y_low": 0.5, "y_high": 0.9},
    "left_upper_lobe": {"x_max": 0.45, "y_min": 0.85},
    "right_upper_lobe": {"x_min": 0.55, "y_min": 0.85},
    "lower_tip": {"x_band": 0.10, "y_max": 0.01},
}


# ---------------------------------------------------------------------------
# Geometry extraction and active filtering
# ---------------------------------------------------------------------------

def active_geometries(geometries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [g for g in geometries
            if g.get("selected") is not False
            and g.get("role") not in INACTIVE_ROLES]


def _outline_points(g: dict[str, Any]) -> list[tuple[float, float]]:
    if g.get("type") == "line":
        start, end = g.get("start"), g.get("end")
        if start and end:
            return [(float(start["x"]), float(start["y"])),
                    (float(end["x"]), float(end["y"]))]
        return []
    if g.get("type") == "polyline":
        pts = [(float(p["x"]), float(p["y"])) for p in g.get("vertices", [])]
        if len(pts) > 1 and g.get("closed") and math.dist(pts[0], pts[-1]) < 1e-6:
            pts.pop()
        return pts
    return []


def _line_string(g: dict[str, Any]) -> LineString | None:
    pts = _outline_points(g)
    if len(pts) < 2:
        return None
    line = LineString(pts)
    return line if not line.is_empty else None


def bounds_of(geometries: list[dict[str, Any]]) -> dict[str, float] | None:
    pts: list[tuple[float, float]] = []
    for g in geometries:
        pts.extend(_outline_points(g))
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return {"min_x": min(xs), "max_x": max(xs), "min_y": min(ys), "max_y": max(ys)}


# ---------------------------------------------------------------------------
# Backend target binding
# ---------------------------------------------------------------------------

def _connected_components(geoms: list[dict[str, Any]],
                          tolerance: float = CONTACT_TOLERANCE_MM) -> list[list[dict[str, Any]]]:
    """Group active linework into backend connected components.

    Two geometries belong to the same component when they share a vertex or
    their LineStrings touch within ``tolerance``.  Circles and isolated closed
    outlines each form their own component.
    """
    n = len(geoms)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    lines: list[LineString | None] = [_line_string(g) for g in geoms]
    for i in range(n):
        for j in range(i + 1, n):
            li, lj = lines[i], lines[j]
            if li is None or lj is None:
                # Circles / point-like primitives never merge by contact here.
                continue
            if li.distance(lj) <= tolerance:
                union(i, j)

    groups: dict[int, list[dict[str, Any]]] = {}
    for i, g in enumerate(geoms):
        groups.setdefault(find(i), []).append(g)
    return list(groups.values())


def _refs_of(logical_object: dict[str, Any]) -> Any:
    refs = logical_object.get("geometry_refs")
    if refs is None:
        refs = logical_object.get("geometry_ids")
    return refs


def _positive_int_ref(value: Any) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _declared_shared_map(topology: dict[str, Any] | None) -> dict[int, set[str]]:
    value = topology if isinstance(topology, dict) else {}
    raw = value.get("shared_geometries") or []
    declared: dict[int, set[str]] = {}
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            gid = _positive_int_ref(item.get("geometry_id"))
            owners = item.get("object_ids")
            if gid is not None and isinstance(owners, list):
                declared[gid] = {str(owner) for owner in owners}
    return declared


def _spatial_contact(a: list[dict[str, Any]], b: list[dict[str, Any]],
                     tolerance: float = CONTACT_TOLERANCE_MM) -> str | None:
    """Diagnostic-only contact/overlap note between two distinct bound objects.

    This never merges or splits objects; it only records how the two backend
    groups relate spatially.
    """
    lines_a = [line for line in (_line_string(g) for g in a) if line is not None]
    lines_b = [line for line in (_line_string(g) for g in b) if line is not None]
    for left in lines_a:
        for right in lines_b:
            if left.intersects(right):
                return "intersects"
            if left.distance(right) <= tolerance:
                return "touching"
    bounds_a, bounds_b = bounds_of(a), bounds_of(b)
    if bounds_a and bounds_b:
        overlap_x = min(bounds_a["max_x"], bounds_b["max_x"]) - max(bounds_a["min_x"], bounds_b["min_x"])
        overlap_y = min(bounds_a["max_y"], bounds_b["max_y"]) - max(bounds_a["min_y"], bounds_b["min_y"])
        if overlap_x >= -tolerance and overlap_y >= -tolerance:
            return "bounds_overlap"
    return None


def validate_target_binding(geometries: list[dict[str, Any]],
                            logical_objects: list[dict[str, Any]] | None = None,
                            topology: dict[str, Any] | None = None) -> dict[str, Any]:
    """Strictly validate the backend-resolved target binding payload.

    Identity basis: only ``geometry_refs`` resolved against the active geometry
    list are trusted.  A model-declared ``object_id`` / ``label`` is recorded
    as a declaration only and is never promoted to identity.

    Returns a dict with:
      ``status``: ``bound`` | ``unresolved``
      ``binding_source``: ``logical_objects.geometry_refs`` | ``connected_components``
      ``auxiliary``: True when identity rests on connected components only
      ``targets``: resolved target groups (empty when unresolved)
      ``errors``: machine-readable binding errors
      ``warnings``: non-fatal diagnostics
      ``unowned_geometry_ids``: active geometries not referenced by any object
      ``shared_geometry_owners``: geometry id -> owner object ids
    """
    active = active_geometries(geometries)
    active_ids = {g.get("id") for g in active}
    by_id_all: dict[Any, dict[str, Any]] = {g.get("id"): g for g in geometries}
    excluded = [{"id": g.get("id"), "role": g.get("role"),
                 "selected": g.get("selected", True)}
                for g in geometries if g.get("id") not in active_ids]
    base: dict[str, Any] = {
        "status": "unresolved",
        "binding_source": None,
        "auxiliary": False,
        "targets": [],
        "errors": [],
        "warnings": [],
        "unowned_geometry_ids": [],
        "shared_geometry_owners": {},
        "excluded_geometry_ids": [item["id"] for item in excluded],
        "excluded_geometries": excluded,
    }
    if not active:
        base["errors"].append({"code": "no_active_geometry",
                               "message": "无活动几何可绑定",
                               "excluded_geometries": excluded})
        return base

    by_id: dict[Any, dict[str, Any]] = {g.get("id"): g for g in active}

    # Fallback: payload missing -> connected components as finite auxiliary
    # evidence only; it must never be the sole identity basis for arbitrary
    # multi-object designs.
    if logical_objects is None or logical_objects == []:
        components = _connected_components(active)
        targets: list[dict[str, Any]] = []
        for index, members in enumerate(components):
            targets.append({
                "target_ref": {
                    "object_id": f"component:{index + 1}",
                    "geometry_ids": [g.get("id") for g in members],
                    "binding_source": "connected_components",
                    "binding_auxiliary": True,
                    "identity_basis": "backend_connected_components_auxiliary",
                    "status": "bound",
                },
                "geometries": members,
            })
        base.update({
            "status": "bound",
            "binding_source": "connected_components",
            "auxiliary": True,
            "targets": targets,
            "warnings": [{
                "code": "binding_fallback_components",
                "message": "未提供 logical_objects；身份仅由后端连通分量辅助推断，不得作为任意多对象的唯一身份依据",
            }],
            "unowned_geometry_ids": [g.get("id") for g in active],
        })
        for target in targets:
            target["target_ref"]["bounds"] = bounds_of(target["geometries"])
        return base

    if not isinstance(logical_objects, list):
        base["errors"].append({"code": "invalid_logical_objects_payload",
                               "message": "logical_objects 必须为列表"})
        return base

    errors: list[dict[str, Any]] = []
    seen_object_ids: set[str] = set()
    owners: dict[Any, list[str]] = {}
    bound_entries: list[dict[str, Any]] = []
    declared_shared = _declared_shared_map(topology)

    for index, obj in enumerate(logical_objects):
        prefix = f"logical_objects[{index}]"
        if not isinstance(obj, dict):
            errors.append({"code": "invalid_logical_object_entry",
                           "message": f"{prefix} 不是字典", "object_index": index})
            continue
        object_id = str(obj.get("object_id") or "").strip()
        if not object_id:
            errors.append({"code": "invalid_object_id",
                           "message": f"{prefix} 缺少 object_id", "object_index": index})
        elif object_id in seen_object_ids:
            errors.append({"code": "duplicate_object_id",
                           "message": f"object_id 重复: {object_id}", "object_id": object_id})
        seen_object_ids.add(object_id)

        raw_refs = _refs_of(obj)
        if raw_refs is None or not isinstance(raw_refs, list):
            errors.append({"code": "missing_geometry_refs",
                           "message": f"{prefix} 缺少 geometry_refs 列表",
                           "object_id": object_id})
            continue
        if len(raw_refs) == 0:
            errors.append({"code": "missing_geometry_refs",
                           "message": f"{prefix} geometry_refs 为空",
                           "object_id": object_id})
            continue
        normalized = [_positive_int_ref(ref) for ref in raw_refs]
        if any(ref is None for ref in normalized):
            errors.append({"code": "invalid_geometry_refs",
                           "message": f"{prefix} 含非正整数几何引用", "object_id": object_id,
                           "geometry_refs": list(raw_refs)})
            continue
        if len(set(normalized)) != len(normalized):
            errors.append({"code": "duplicate_geometry_refs",
                           "message": f"{prefix} 引用重复几何 id", "object_id": object_id,
                           "geometry_refs": list(raw_refs)})
            continue
        missing = [ref for ref in normalized if ref not in by_id]
        excluded_refs = sorted(ref for ref in missing if ref in by_id_all)
        dangling = sorted(ref for ref in missing if ref not in by_id_all)
        if excluded_refs:
            errors.append({"code": "excluded_geometry_ref",
                           "message": f"{prefix} 引用的几何被角色/选中状态排除在活动几何之外",
                           "object_id": object_id, "geometry_ids": excluded_refs,
                           "excluded_roles": [by_id_all[ref].get("role") for ref in excluded_refs]})
        if dangling:
            errors.append({"code": "dangling_geometry_refs",
                           "message": f"{prefix} 引用了不存在的几何 id", "object_id": object_id,
                           "geometry_ids": dangling})
        if missing:
            continue
        members = [by_id[ref] for ref in normalized]
        for ref in normalized:
            owners.setdefault(ref, []).append(object_id)
        bound_entries.append({"obj": obj, "object_id": object_id,
                              "members": members, "refs": normalized})

    # Shared-geometry reconciliation against topology declarations.
    for gid, owner_ids in owners.items():
        if len(set(owner_ids)) > 1:
            declared = declared_shared.get(gid)
            if declared is None:
                errors.append({"code": "undeclared_shared_geometry",
                               "message": "多对象共用几何但拓扑未声明共享",
                               "geometry_ids": [gid], "object_ids": sorted(set(owner_ids))})
            elif declared != set(owner_ids):
                errors.append({"code": "shared_ownership_mismatch",
                               "message": "共享几何的声明归属与对象引用不一致",
                               "geometry_ids": [gid],
                               "object_ids": sorted(declared ^ set(owner_ids))})

    if errors:
        base["errors"] = errors
        base["binding_source"] = "logical_objects.geometry_refs"
        base["reason"] = "invalid_target_binding"
        return base

    targets = []
    for entry in bound_entries:
        members = entry["members"]
        target_ref = {
            "object_id": entry["object_id"],
            "assembly_id": entry["obj"].get("assembly_id"),
            "label": entry["obj"].get("label"),
            "geometry_ids": [g.get("id") for g in members],
            "binding_source": "logical_objects.geometry_refs",
            "binding_auxiliary": False,
            "identity_basis": "backend_resolved_geometry_refs",
            "model_declared_object_id_trusted_as_identity": False,
            "confidence": entry["obj"].get("confidence", 1.0),
            "status": "bound",
        }
        targets.append({"target_ref": target_ref, "geometries": members})

    # A single logical object may group several disconnected pieces; it stays
    # one acceptance target and is never split by connectivity.  The component
    # split is recorded only as a diagnostic.
    for target in targets:
        components = _connected_components(target["geometries"])
        if len(components) > 1:
            base["warnings"].append({
                "code": "disconnected_members",
                "message": "同一逻辑对象含多段不连通几何；保持为一个对象验收，未按连通性拆分",
                "geometry_ids": target["target_ref"]["geometry_ids"],
                "component_count": len(components),
            })

    # Contact / overlap between distinct bound objects is diagnostic only;
    # shared vertices or touching outlines must NOT merge two objects.
    for i, left in enumerate(targets):
        for right in targets[i + 1:]:
            relation = _spatial_contact(left["geometries"], right["geometries"])
            if relation:
                base["warnings"].append({
                    "code": "contact_or_overlap_between_distinct_objects",
                    "message": "两个已绑定对象几何接触/重叠/共享结点；保持为独立对象，未合并",
                    "geometry_ids": [left["target_ref"]["geometry_ids"],
                                     right["target_ref"]["geometry_ids"]],
                    "relation": relation,
                })

    owned_ids = {g.get("id") for entry in bound_entries for g in entry["members"]}
    base.update({
        "status": "bound",
        "binding_source": "logical_objects.geometry_refs",
        "auxiliary": False,
        "targets": targets,
        "unowned_geometry_ids": [g.get("id") for g in active if g.get("id") not in owned_ids],
        "shared_geometry_owners": {
            str(gid): owners[gid] for gid in owners if len(set(owners[gid])) > 1
        },
    })
    for target in targets:
        target["target_ref"]["bounds"] = bounds_of(target["geometries"])
    return base


def bind_targets(geometries: list[dict[str, Any]],
                 logical_objects: list[dict[str, Any]] | None = None,
                 topology: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Backward-compatible target list; see :func:`validate_target_binding`."""
    return validate_target_binding(geometries, logical_objects, topology)["targets"]


# ---------------------------------------------------------------------------
# Profile classification (star negative gate + heart shape support)
# ---------------------------------------------------------------------------

def _closed_outline(geoms: list[dict[str, Any]]) -> list[tuple[float, float]]:
    """Pick the largest closed outline among the target's geometries."""
    candidates: list[tuple[list[tuple[float, float]], float]] = []
    for g in geoms:
        if g.get("type") != "polyline" or not g.get("closed"):
            continue
        pts = _outline_points(g)
        if len(pts) >= 3:
            poly = Polygon(pts)
            area = poly.area if poly.is_valid else 0.0
            candidates.append((pts, area))
    if not candidates:
        return []
    candidates.sort(key=lambda item: item[1], reverse=True)
    return candidates[0][0]


def _cross_sign(pts: list[tuple[float, float]]) -> list[int]:
    signs: list[int] = []
    n = len(pts)
    for i, p in enumerate(pts):
        a, b = pts[i - 1], pts[(i + 1) % n]
        cross = (p[0] - a[0]) * (b[1] - a[1]) - (p[1] - a[1]) * (b[0] - a[0])
        signs.append(1 if cross > 1e-9 else -1 if cross < -1e-9 else 0)
    return signs


def _fivefold_residual(pts: list[tuple[float, float]]) -> float:
    """Mean nearest-neighbor residual after 72-degree rotation, normalized by diameter."""
    if len(pts) < 5:
        return 1.0
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    diameter = max(math.dist(a, b) for a in pts for b in pts)
    if diameter <= 1e-9:
        return 1.0

    def rotate(point: tuple[float, float], angle: float) -> tuple[float, float]:
        x, y = point[0] - cx, point[1] - cy
        ca, sa = math.cos(angle), math.sin(angle)
        return (cx + x * ca - y * sa, cy + x * sa + y * ca)

    residuals: list[float] = []
    for step in range(1, 5):
        angle = step * math.tau / 5
        rotated = [rotate(p, angle) for p in pts]
        for r in rotated:
            residuals.append(min(math.dist(r, p) for p in pts))
    return sum(residuals) / len(residuals) / diameter


def classify_profile(geoms: list[dict[str, Any]]) -> dict[str, Any]:
    """Classify a target outline as ``star`` / ``heart_like`` / ``other``.

    Star votes: >=4 deep valleys, convex-hull area ratio <0.72, near-zero
    5-fold rotational residual.  Heart votes: <=1 deep valley, hull ratio
    >0.90, large rotational residual.  At least two agreeing votes decide the
    profile; otherwise the outline is ``other``.
    """
    pts = _closed_outline(geoms)
    if len(pts) < 3:
        return {"profile": "degenerate", "votes": {}, "measurements": {}}

    poly = Polygon(pts)
    if not poly.is_valid:
        poly = poly.buffer(0)
    hull = poly.convex_hull
    hull_ratio = (poly.area / hull.area) if hull.area > 1e-9 else 1.0

    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    radii = [math.dist(p, (cx, cy)) for p in pts]
    median_r = sorted(radii)[len(radii) // 2] or 1.0
    signs = _cross_sign(pts)
    signed_area = sum(pts[i][0] * pts[(i + 1) % len(pts)][1]
                      - pts[(i + 1) % len(pts)][0] * pts[i][1]
                      for i in range(len(pts)))
    convex_sign = 1 if signed_area >= 0 else -1
    valleys = [i for i, s in enumerate(signs)
               if s == -convex_sign and radii[i] < 0.85 * median_r]

    fold_residual = _fivefold_residual(pts)

    votes = {
        "valley_count_star": len(valleys) >= STAR_VALLEY_MIN,
        "hull_ratio_star": hull_ratio < STAR_HULL_RATIO_MAX,
        "fivefold_star": fold_residual < STAR_FOLD_RESIDUAL_MAX,
        "valley_count_heart": len(valleys) <= HEART_VALLEY_MAX,
        "hull_ratio_heart": hull_ratio > HEART_HULL_RATIO_MIN,
        "fivefold_heart": fold_residual > HEART_FOLD_RESIDUAL_MIN,
    }
    star_votes = sum(votes[k] for k in ("valley_count_star", "hull_ratio_star", "fivefold_star"))
    heart_votes = sum(votes[k] for k in ("valley_count_heart", "hull_ratio_heart", "fivefold_heart"))

    if star_votes >= 2:
        profile = "star"
    elif heart_votes >= 2:
        profile = "heart_like"
    else:
        profile = "other"

    measurements = {
        "corner_count": len(pts),
        "deep_valley_count": len(valleys),
        "convex_hull_area_ratio": round(hull_ratio, 4),
        "fivefold_rotation_residual": round(fold_residual, 4),
        "centroid_mm": [round(cx, 3), round(cy, 3)],
    }
    return {"profile": profile, "votes": votes, "measurements": measurements}


# ---------------------------------------------------------------------------
# Heart feature measurement (scoped to one bound object)
# ---------------------------------------------------------------------------

def heart_features(geoms: list[dict[str, Any]]) -> dict[str, Any]:
    """Measure the four inherited heart features against the object's own bounds."""
    pts = _closed_outline(geoms)
    if not pts:
        return {"features": {}, "normalization": None, "points": []}
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    width, height = max(xs) - min(xs), max(ys) - min(ys)
    if width <= 0 or height <= 0:
        return {"features": {}, "normalization": "degenerate_bounds", "points": pts}
    normalized = [((x - min(xs)) / width, (y - min(ys)) / height) for x, y in pts]
    rules = HEART_FEATURE_RULES
    features = {
        "center_notch": any(abs(x - 0.5) < rules["center_notch"]["x_band"]
                             and rules["center_notch"]["y_low"] < y < rules["center_notch"]["y_high"]
                             for x, y in normalized),
        "left_upper_lobe": any(x < rules["left_upper_lobe"]["x_max"]
                               and y > rules["left_upper_lobe"]["y_min"] for x, y in normalized),
        "right_upper_lobe": any(x > rules["right_upper_lobe"]["x_min"]
                                and y > rules["right_upper_lobe"]["y_min"] for x, y in normalized),
        "lower_tip": any(abs(x - 0.5) < rules["lower_tip"]["x_band"]
                         and y < rules["lower_tip"]["y_max"] for x, y in normalized),
    }
    return {
        "features": features,
        "normalization": "x/y normalized independently to this object's bounds [0,1]",
        "points": normalized,
        "bounds_mm": {"min_x": min(xs), "max_x": max(xs), "min_y": min(ys), "max_y": max(ys)},
    }


# ---------------------------------------------------------------------------
# Semantic coverage completeness contract (single source of truth)
# ---------------------------------------------------------------------------
#
# This section is measurement-only.  It does not generate geometry, does not
# edit a plan, and does not change any existing terminal report status word
# (``partial`` / ``not_checked`` / ``unverified`` /
# ``coverage=unsupported_semantic_kind`` keep their inherited meaning).
#
# The summary layer must classify a semantic report through
# :func:`semantic_requirement_state` only; it must not re-derive applicability
# from ``coverage`` or ``review_required``.


def classify_requirement_kind(kind: Any) -> str | None:
    """Return the registry category of a requirement kind.

    ``dispatch_channel``  -> registered in ``DISPATCH_CHANNELS``;
    ``special_verified``   -> dedicated verifier outside the channel table;
    ``unverifiable_recognized`` -> recognized, no backend verifier;
    ``None`` -> unknown / not a recognized mandatory kind.
    """
    if not isinstance(kind, str) or not kind:
        return None
    if kind in DISPATCH_CHANNELS:
        return "dispatch_channel"
    if kind in SPECIAL_VERIFIED_KINDS:
        return "special_verified"
    if kind in UNVERIFIABLE_RECOGNIZED_KINDS:
        return "unverifiable_recognized"
    return None


def recognized_unverifiable_kinds_from_text(source: str | None) -> list[str]:
    """Generic text scan for recognized-but-no-verifier shape vocabulary.

    Returns only kinds registered in ``UNVERIFIABLE_RECOGNIZED_KINDS``; this
    is an applicability annotation, never a recognition verdict for acceptance.
    """
    if not source:
        return []
    found: list[str] = []
    for kind, pattern in UNVERIFIABLE_SHAPE_PATTERNS.items():
        if kind in UNVERIFIABLE_RECOGNIZED_KINDS and re.search(pattern, source, re.I):
            found.append(kind)
    return found


def ambiguous_requirement_kinds_from_text(source: str | None) -> list[str]:
    """Scan wording that may denote a recognized shape but is ambiguous.

    An ambiguous match does NOT establish a mandatory requirement.  It marks
    the case as unresolved: the summary layer must keep it out of PASS until
    the backend profile corroborates a star outline, or the ambiguity is
    resolved against a non-star outline.  Astroid wording and already-explicit
    star wording are excluded.
    """
    if not source:
        return []
    if re.search(_ASTROID_TEXT_PATTERN, source, re.I):
        return []
    explicit = set(recognized_unverifiable_kinds_from_text(source))
    found: list[str] = []
    for kind, pattern in AMBIGUOUS_SHAPE_PATTERNS.items():
        if kind in UNVERIFIABLE_RECOGNIZED_KINDS and kind not in explicit \
                and re.search(pattern, source, re.I):
            found.append(kind)
    return found


def collect_applicable_requirement_kinds(
    report: dict[str, Any] | None,
    source: str | None = None,
) -> list[str]:
    """Collect mandatory requirement kinds recognized from a semantic report.

    Evidence sources, in order:
      1. top-level ``requirements`` entries (``kind``);
      2. top-level ``unsupported_kind``;
      3. special verified branches identified by their ``coverage`` value;
      4. object-level entries whose generic classifier profile has no verifier;
      5. the report's own ``applicable_requirement_kinds`` marker;
      6. optional source-text backstop for recognized unverifiable shapes.

    The list is de-duplicated, stable-ordered.  Unknown parsed kinds are kept
    here too: they are flagged separately as ``recognized_unknown_kinds`` by
    :func:`semantic_requirement_state`, so the caller can report the gap.
    """
    kinds: list[str] = []

    def add(kind: Any) -> None:
        if isinstance(kind, str) and kind and kind not in kinds:
            kinds.append(kind)

    if isinstance(report, dict):
        for entry in report.get("requirements") or []:
            if isinstance(entry, dict):
                add(entry.get("kind"))
        add(report.get("unsupported_kind"))
        coverage = report.get("coverage")
        if isinstance(coverage, str) and coverage in SPECIAL_VERIFIED_COVERAGE_KINDS:
            add(SPECIAL_VERIFIED_COVERAGE_KINDS[coverage])
        for entry in report.get("object_acceptance") or []:
            if not isinstance(entry, dict):
                continue
            if entry.get("profile") == "star" or entry.get("reason") == "no_verifier_for_star_profile":
                add("star_profile")
        for kind in report.get("applicable_requirement_kinds") or []:
            add(kind)
    for kind in recognized_unverifiable_kinds_from_text(source):
        add(kind)
    return kinds


def collect_ambiguous_requirement_kinds(
    report: dict[str, Any] | None,
    source: str | None = None,
) -> list[str]:
    """Collect unresolved ambiguous requirement kinds from report and source.

    These are NOT established applicable requirements; they are signals that
    the wording could denote a recognized shape but cannot be resolved from
    text alone.  The list is de-duplicated, stable-ordered.
    """
    kinds: list[str] = []

    def add(kind: Any) -> None:
        if isinstance(kind, str) and kind and kind not in kinds:
            kinds.append(kind)

    if isinstance(report, dict):
        for kind in report.get("ambiguous_requirement_kinds") or []:
            add(kind)
    for kind in ambiguous_requirement_kinds_from_text(source):
        add(kind)
    return kinds


def semantic_requirement_state(
    report: dict[str, Any] | None,
    source: str | None = None,
) -> dict[str, Any]:
    """Classify one semantic acceptance report into the three contract states.

    States
    ------
    ``no_applicable_requirement``
        The request carries no recognized mandatory semantic requirement.
        Object-level ``not_checked`` must not be judged a failure here, and
        no review may be forced on this account.
    ``fully_verified``
        A mandatory requirement exists and every object-level check passed;
        the report itself is ``passed`` with no outstanding gap.
    ``unverified_or_partial``
        A mandatory requirement exists but it is unverified, partial, any
        object is ``not_checked`` / unresolved, an unknown kind appeared, or
        an applicable report is still ``not_checked``.  The summary layer must
        not record this report as a complete acceptance PASS.

    Sub-reason codes
    ----------------
    ``partial_overall``        top-level status is ``partial`` (never upgraded
                              by ``review_required=False``);
    ``partial_objects``       at least one object-level entry did not pass;
    ``object_not_checked``     an object entry is ``not_checked``;
    ``no_verifier``            recognized kind/profile with no backend verifier;
    ``unknown_kind``           parsed/unsupported kind not in the mandatory
                              registry;
    ``report_unverified``      top-level status in unverified/unresolved/failed;
    ``report_unchecked_applicable``  report is ``not_checked`` but carries a
                              recognized mandatory kind;
    ``ambiguous_requirement``  wording may denote a recognized shape but the
                              requirement is unresolved; never classified as
                              "no applicable requirement";
    ``object_unresolved``      object entry is unresolved/unverified;
    ``report_unavailable``    the report itself is missing or not a dict.
    """
    if not isinstance(report, dict):
        return {
            "state": STATE_UNVERIFIED_OR_PARTIAL,
            "applicable_requirement_kinds": [],
            "recognized_unknown_kinds": [],
            "review_required": True,
            "reasons": ["report_unavailable"],
            "affected": [],
        }

    applicable = collect_applicable_requirement_kinds(report, source)
    ambiguous = collect_ambiguous_requirement_kinds(report, source)
    registry = {kind: classify_requirement_kind(kind) for kind in applicable}
    unknown_kinds = [kind for kind, category in registry.items() if category is None]
    # An ambiguity resolved by the backend profile against a non-star outline
    # must not keep blocking; an unresolved ambiguity can never fall into the
    # "no applicable requirement" state.
    resolved_non_star = isinstance(report, dict) and \
        report.get("ambiguity_resolution") == "resolved_non_star"

    object_entries = [entry for entry in (report.get("object_acceptance") or [])
                      if isinstance(entry, dict)]
    reasons: set[str] = set()
    affected: list[dict[str, Any]] = []

    status = report.get("status")
    review_required = report.get("review_required") is True

    for entry in object_entries:
        ref = entry.get("target_ref") or {}
        object_id = ref.get("object_id")
        geometry_ids = ref.get("geometry_ids") or entry.get("geometry_ids") or []
        entry_status = entry.get("status")
        entry_reason = entry.get("reason")
        if entry_status == "passed":
            continue
        reasons.add("partial_objects")
        affected.append({
            "object_id": object_id,
            "geometry_ids": geometry_ids,
            "status": entry_status,
            "reason": entry_reason,
            "profile": entry.get("profile"),
        })
        if entry_status == "not_checked":
            reasons.add("object_not_checked")
        if entry_reason == "no_verifier_for_star_profile":
            reasons.add("no_verifier")
        if entry_status in ("unresolved", "unverified"):
            reasons.add("object_unresolved")

    if report.get("unsupported_kind"):
        reasons.add("no_verifier")
    if report.get("reason") == "no_verifier_for_kind":
        reasons.add("no_verifier")
    if unknown_kinds:
        reasons.add("unknown_kind")
    if status == "partial":
        reasons.add("partial_overall")
    if status in ("unverified", "unresolved", "failed", "review_required"):
        reasons.add("report_unverified")
    if status == "not_checked" and applicable:
        reasons.add("report_unchecked_applicable")
    if ambiguous and not resolved_non_star:
        reasons.add("ambiguous_requirement")

    has_applicable = bool(applicable)
    if not has_applicable and not unknown_kinds and not reasons:
        state = STATE_NO_APPLICABLE_REQUIREMENT
    elif status == "passed" and not reasons:
        state = STATE_FULLY_VERIFIED
    else:
        state = STATE_UNVERIFIED_OR_PARTIAL

    return {
        "state": state,
        "applicable_requirement_kinds": applicable,
        "ambiguous_requirement_kinds": ambiguous,
        "recognized_unknown_kinds": unknown_kinds,
        "review_required": review_required or state == STATE_UNVERIFIED_OR_PARTIAL,
        "reasons": sorted(reasons),
        "affected": affected,
    }


def state_allows_summary_passed(verdict: dict[str, Any] | None) -> bool:
    """Whether the summary layer may treat this semantic verdict as complete.

    Only ``fully_verified`` and ``no_applicable_requirement`` allow a PASS;
    ``unverified_or_partial`` never does, regardless of ``review_required``.
    """
    return isinstance(verdict, dict) and verdict.get("state") in (
        STATE_FULLY_VERIFIED,
        STATE_NO_APPLICABLE_REQUIREMENT,
    )
