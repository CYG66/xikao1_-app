"""Convert raster line drawings into the canonical XLine drawing schema.

Image interpretation belongs to the drawing layer.  This adapter deliberately
stops at editable geometry; path planning and hardware execution remain in
their existing domain modules.
"""
from __future__ import annotations

import math
import os
import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Iterable


MAX_IMAGE_BYTES = 10 * 1024 * 1024
SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
SOURCE_IMAGE_DIRECTORY = ".image_sources"
_IMPORT_LOCK = threading.Lock()


def _devkit_root() -> Path:
    configured = os.getenv("XLINE_DRAWING_DEVKIT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "xline_drawing_pipeline_devkit_20261015"


def image_vectorizer_status() -> dict[str, Any]:
    root = _devkit_root()
    source = root / "line2semantic" / "src"
    return {
        "available": (source / "line2semantic" / "pipeline.py").is_file(),
        "devkit_root": str(root),
        "engine": "line2semantic",
    }


def validate_image_upload(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_IMAGE_SUFFIXES:
        raise ValueError("仅支持 JPG、PNG 或 WebP 图片。")
    if not content:
        raise ValueError("上传的图片为空。")
    if len(content) > MAX_IMAGE_BYTES:
        raise ValueError("图片超过 10MB，不能导入。")
    signatures = {
        ".png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        ".jpg": content.startswith(b"\xff\xd8\xff"),
        ".jpeg": content.startswith(b"\xff\xd8\xff"),
        ".webp": len(content) >= 12
        and content[:4] == b"RIFF"
        and content[8:12] == b"WEBP",
    }
    if not signatures.get(suffix, False):
        raise ValueError("文件扩展名与图片内容不一致。")
    return suffix


def save_source_image(directory: Path, suffix: str, content: bytes) -> str:
    """Persist a review-only source image beside drawings using an opaque key."""
    normalized_suffix = suffix.lower()
    if normalized_suffix not in SUPPORTED_IMAGE_SUFFIXES:
        raise ValueError("原图格式不受支持。")
    source_directory = directory / SOURCE_IMAGE_DIRECTORY
    source_directory.mkdir(parents=True, exist_ok=True)
    key = f"{uuid.uuid4().hex}{normalized_suffix}"
    temporary = source_directory / f".{key}.tmp"
    target = source_directory / key
    temporary.write_bytes(content)
    temporary.replace(target)
    return key


def resolve_source_image(directory: Path, key: str) -> Path | None:
    """Resolve a stored source image without allowing path traversal."""
    clean_key = Path(key).name
    if clean_key != key or Path(clean_key).suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
        return None
    target = (directory / SOURCE_IMAGE_DIRECTORY / clean_key).resolve()
    source_directory = (directory / SOURCE_IMAGE_DIRECTORY).resolve()
    if target.parent != source_directory or not target.is_file():
        return None
    return target


def _point(value: Iterable[float], scale: float, image_height: float) -> dict[str, float]:
    x, y = value
    return {"x": float(x) * scale, "y": (image_height - float(y)) * scale, "z": 0.0}


def primitives_to_app_lines(
    primitives: Iterable[Any],
    *,
    image_width_px: int,
    image_height_px: int,
    physical_width_mm: float,
) -> list[dict[str, Any]]:
    """Map line2semantic primitives to canonical, editable App geometries."""
    if image_width_px <= 0 or image_height_px <= 0:
        raise ValueError("图片尺寸无效。")
    if not math.isfinite(physical_width_mm) or physical_width_mm <= 0:
        raise ValueError("实际宽度必须是大于 0 的毫米数。")
    scale = physical_width_mm / image_width_px
    lines: list[dict[str, Any]] = []
    for index, primitive in enumerate(primitives, start=1):
        kind = str(getattr(primitive, "type", "")).lower()
        base: dict[str, Any] = {
            "id": index,
            "type": kind,
            "layer_id": 1,
            "role": "printing",
            "path_semantic": "DRAW",
            "label": f"图片图元 {index}",
            "source_primitive_id": str(getattr(primitive, "id", index)),
            "confidence": float(getattr(primitive, "confidence", 0.0)),
        }
        if kind == "line":
            base["start"] = _point(primitive.start, scale, image_height_px)
            base["end"] = _point(primitive.end, scale, image_height_px)
        elif kind == "circle":
            base["center"] = _point((primitive.cx, primitive.cy), scale, image_height_px)
            base["radius"] = float(primitive.radius) * scale
        elif kind == "arc":
            base["center"] = _point(primitive.center, scale, image_height_px)
            base["radius"] = float(primitive.radius) * scale
            span = abs(float(primitive.angular_span))
            if bool(primitive.clockwise):
                start_angle = -float(primitive.start_angle)
            else:
                start_angle = -float(primitive.end_angle)
            base["start_angle"] = start_angle % 360.0
            base["end_angle"] = (start_angle + span) % 360.0
        elif kind == "polyline":
            points = list(getattr(primitive, "points", []))
            if len(points) < 2:
                continue
            base["vertices"] = [_point(point, scale, image_height_px) for point in points]
            base["closed"] = bool(getattr(primitive, "closed", False))
        else:
            continue
        lines.append(base)
    return lines


def suggest_image_instance_groups(
    geometries: list[dict[str, Any]], *, tolerance_mm: float
) -> list[dict[str, Any]]:
    """Suggest complete-shape groups from geometric connectivity.

    These groups are review hints only.  They deliberately stay in
    ``cad_analysis`` until the user confirms or corrects them.
    """
    if not geometries:
        return []
    tolerance = max(0.1, float(tolerance_mm))
    sampled = [_geometry_segments(item) for item in geometries]
    parents = list(range(len(geometries)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    for left in range(len(geometries)):
        for right in range(left + 1, len(geometries)):
            if _segments_touch(sampled[left], sampled[right], tolerance):
                union(left, right)

    components: dict[int, list[int]] = {}
    for index in range(len(geometries)):
        components.setdefault(find(index), []).append(index)

    # Detached symbols such as hoop dots or a center mark still belong to the
    # enclosing court.  Absorb only tiny components whose center is inside a
    # larger component's bounds; separated drawings remain separate groups.
    component_list = list(components.values())
    major = [item for item in component_list if len(item) >= 2]
    absorbed: set[int] = set()
    for component in component_list:
        if len(component) > 2 or not major:
            continue
        bounds = _component_bounds(component, sampled)
        if bounds is None:
            continue
        center = ((bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2)
        candidates: list[tuple[float, list[int]]] = []
        for container in major:
            if container is component or len(container) <= len(component):
                continue
            outer = _component_bounds(container, sampled)
            if outer is None:
                continue
            if (
                outer[0] - tolerance <= center[0] <= outer[2] + tolerance
                and outer[1] - tolerance <= center[1] <= outer[3] + tolerance
            ):
                outer_center = ((outer[0] + outer[2]) / 2, (outer[1] + outer[3]) / 2)
                candidates.append((math.dist(center, outer_center), container))
        if candidates:
            target = min(candidates, key=lambda item: item[0])[1]
            target.extend(component)
            absorbed.add(id(component))

    remaining = [item for item in component_list if id(item) not in absorbed]
    remaining.sort(key=lambda item: _component_sort_key(item, sampled))
    suggestions: list[dict[str, Any]] = []
    for index, component in enumerate(remaining, 1):
        ids = sorted(
            int(geometries[item]["id"])
            for item in set(component)
            if str(geometries[item].get("id", "")).isdigit()
        )
        if not ids:
            continue
        confidence_values = [
            float(geometries[item].get("confidence", 0.0) or 0.0)
            for item in set(component)
        ]
        suggestions.append({
            "candidate_id": f"image-group-{index:03d}",
            "label": f"识别图形 {index}",
            "geometry_ids": ids,
            "confidence": (
                sum(confidence_values) / len(confidence_values)
                if confidence_values else 0.0
            ),
            "source": "image_connectivity",
        })
    return suggestions


def _geometry_segments(
    geometry: dict[str, Any],
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    def point(value: Any) -> tuple[float, float] | None:
        if not isinstance(value, dict):
            return None
        try:
            return float(value["x"]), float(value["y"])
        except (KeyError, TypeError, ValueError):
            return None

    kind = str(geometry.get("type") or "").lower()
    points: list[tuple[float, float]] = []
    if kind == "line":
        points = [value for value in (point(geometry.get("start")), point(geometry.get("end"))) if value]
    elif kind == "polyline":
        points = [value for raw in geometry.get("vertices") or [] if (value := point(raw))]
        if geometry.get("closed") is True and len(points) > 2:
            points.append(points[0])
    elif kind in {"circle", "arc"}:
        center = point(geometry.get("center"))
        try:
            radius = float(geometry.get("radius") or 0.0)
        except (TypeError, ValueError):
            radius = 0.0
        if center is not None and radius > 0:
            if kind == "circle":
                start, sweep, count = 0.0, 360.0, 48
            else:
                start = float(geometry.get("start_angle") or 0.0)
                end = float(geometry.get("end_angle") or 0.0)
                sweep = (end - start) % 360.0 or 360.0
                count = max(8, int(48 * sweep / 360.0))
            points = [
                (
                    center[0] + radius * math.cos(math.radians(start + sweep * index / count)),
                    center[1] + radius * math.sin(math.radians(start + sweep * index / count)),
                )
                for index in range(count + 1)
            ]
    return list(zip(points, points[1:]))


def _segments_touch(
    left: list[tuple[tuple[float, float], tuple[float, float]]],
    right: list[tuple[tuple[float, float], tuple[float, float]]],
    tolerance: float,
) -> bool:
    return any(
        _segment_distance(left_segment, right_segment) <= tolerance
        for left_segment in left
        for right_segment in right
    )


def _segment_distance(
    left: tuple[tuple[float, float], tuple[float, float]],
    right: tuple[tuple[float, float], tuple[float, float]],
) -> float:
    if _segments_intersect(left, right):
        return 0.0
    return min(
        _point_segment_distance(left[0], right),
        _point_segment_distance(left[1], right),
        _point_segment_distance(right[0], left),
        _point_segment_distance(right[1], left),
    )


def _point_segment_distance(
    point: tuple[float, float],
    segment: tuple[tuple[float, float], tuple[float, float]],
) -> float:
    start, end = segment
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared <= 1e-12:
        return math.dist(point, start)
    position = max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared))
    return math.dist(point, (start[0] + position * dx, start[1] + position * dy))


def _segments_intersect(
    left: tuple[tuple[float, float], tuple[float, float]],
    right: tuple[tuple[float, float], tuple[float, float]],
) -> bool:
    def cross(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    a, b = left
    c, d = right
    boxes_overlap = (
        max(min(a[0], b[0]), min(c[0], d[0]))
        <= min(max(a[0], b[0]), max(c[0], d[0])) + 1e-9
        and max(min(a[1], b[1]), min(c[1], d[1]))
        <= min(max(a[1], b[1]), max(c[1], d[1])) + 1e-9
    )
    return (
        boxes_overlap
        and cross(a, b, c) * cross(a, b, d) <= 0
        and cross(c, d, a) * cross(c, d, b) <= 0
    )


def _component_bounds(
    component: list[int],
    sampled: list[list[tuple[tuple[float, float], tuple[float, float]]]],
) -> tuple[float, float, float, float] | None:
    points = [point for index in component for segment in sampled[index] for point in segment]
    if not points:
        return None
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs), max(ys)


def _component_sort_key(
    component: list[int],
    sampled: list[list[tuple[tuple[float, float], tuple[float, float]]]],
) -> tuple[float, float]:
    bounds = _component_bounds(component, sampled)
    return (bounds[0], -bounds[3]) if bounds is not None else (math.inf, math.inf)


def vectorize_image_to_drawing(
    image_path: Path,
    *,
    physical_width_mm: float,
) -> tuple[dict[str, Any], list[str]]:
    if not math.isfinite(physical_width_mm) or not 1.0 <= physical_width_mm <= 1_000_000.0:
        raise ValueError("实际宽度应在 1 至 1000000 毫米之间。")
    status = image_vectorizer_status()
    if not status["available"]:
        raise RuntimeError("图片矢量化组件未安装，请配置 XLINE_DRAWING_DEVKIT。")
    source = Path(status["devkit_root"]) / "line2semantic" / "src"
    with _IMPORT_LOCK:
        source_text = str(source)
        if source_text not in sys.path:
            sys.path.insert(0, source_text)
        try:
            from line2semantic.pipeline import analyze_image
        except ImportError as exc:
            raise RuntimeError(f"图片矢量化依赖未安装：{exc.name or exc}") from exc
        result = analyze_image(image_path, export=False)

    width_px, height_px = result.preprocessing.image_size
    lines = primitives_to_app_lines(
        result.primitives,
        image_width_px=width_px,
        image_height_px=height_px,
        physical_width_mm=physical_width_mm,
    )
    if not lines:
        raise ValueError("图片中没有识别到可编辑线条，请使用对比清晰的线稿图片。")
    scale = physical_width_mm / width_px
    confidences = [float(getattr(item, "confidence", 0.0)) for item in result.primitives]
    mean_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    low_confidence_count = sum(value < 0.65 for value in confidences)
    confidence_level = (
        "high" if mean_confidence >= 0.85 else "medium" if mean_confidence >= 0.65 else "low"
    )
    warnings: list[str] = ["图片转图纸结果需人工核对尺寸和漏线，不能直接视为施工验收结果。"]
    if mean_confidence < 0.65:
        warnings.append("部分线条识别置信度较低，建议在图纸编辑器中校正后再规划。")
    grouping_tolerance_mm = max(0.1, scale * 3.0)
    group_candidates = suggest_image_instance_groups(
        lines, tolerance_mm=grouping_tolerance_mm
    )
    payload: dict[str, Any] = {
        "name": image_path.stem,
        "units": "mm",
        "source_format": "image",
        "lines": lines,
        "layers": [
            {
                "id": 1,
                "name": "IMAGE_VECTOR",
                "role": "printing",
                "path_semantic": "DRAW",
                "visible": True,
            }
        ],
        "cad_analysis": {
            "vectorizer": "line2semantic",
            "physical_width_mm": physical_width_mm,
            "image_width_px": width_px,
            "image_height_px": height_px,
            "scale_mm_per_px": scale,
            "primitive_count": len(lines),
            "primitive_type_counts": result.primitive_type_counts,
            "mean_confidence": mean_confidence,
            "confidence_level": confidence_level,
            "low_confidence_count": low_confidence_count,
            "requires_user_review": True,
            "hardware_ready": False,
            "instance_group_candidates": group_candidates,
            "instance_groups_confirmed": False,
            "requires_instance_group_confirmation": True,
            "grouping_tolerance_mm": grouping_tolerance_mm,
            "review_items": [
                "确认图片实际宽度和图纸比例",
                "检查断线、漏线和误识别线条",
                "确认需要喷墨的图元后再进行路径规划",
            ],
        },
    }
    return payload, warnings
