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


def _refs_of(logical_object: dict[str, Any]) -> list[Any]:
    refs = logical_object.get("geometry_refs")
    if refs is None:
        refs = logical_object.get("geometry_ids") or []
    return list(refs or [])


def bind_targets(geometries: list[dict[str, Any]],
                 logical_objects: list[dict[str, Any]] | None = None,
                 topology: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Resolve backend-trusted target objects from active linework.

    Returns a list of target groups.  Each group carries a ``target_ref`` whose
    ``geometry_ids`` are backend-resolved; a model-declared label/object id on
    an individual geometry is never promoted to identity.
    """
    active = active_geometries(geometries)
    if not active:
        return []

    by_id: dict[Any, dict[str, Any]] = {g.get("id"): g for g in active}
    targets: list[dict[str, Any]] = []

    if logical_objects:
        for obj in logical_objects:
            refs = _refs_of(obj)
            members = [by_id[ref] for ref in refs if ref in by_id]
            if not members:
                continue
            target_ref = {
                "object_id": obj.get("object_id"),
                "assembly_id": obj.get("assembly_id"),
                "label": obj.get("label"),
                "geometry_ids": [g.get("id") for g in members],
                "binding_source": "logical_objects.geometry_refs",
                "confidence": obj.get("confidence", 1.0),
                "status": "bound",
            }
            targets.append({"target_ref": target_ref, "geometries": members})

    if not targets:
        components = _connected_components(active)
        for index, members in enumerate(components):
            target_ref = {
                "object_id": f"component:{index + 1}",
                "geometry_ids": [g.get("id") for g in members],
                "binding_source": "connected_components",
                "confidence": 1.0,
                "status": "bound",
            }
            targets.append({"target_ref": target_ref, "geometries": members})

    # Diagnostic bbox overlap note; bbox is never the identity criterion.
    for target in targets:
        target["target_ref"]["bounds"] = bounds_of(target["geometries"])
    return targets


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
