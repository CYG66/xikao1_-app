"""Convert DXF entities into the canonical XLine CAD JSON format.

The importer deliberately keeps non-printing information in the payload while
marking it as reference data.  Only geometries with ``role=printing`` are
eligible for the execution planner.
"""
from __future__ import annotations

from math import cos, pi, sin
from io import StringIO
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable


UNIT_FACTORS = {
    "mm": 1.0,
    "cm": 10.0,
    "m": 1000.0,
    "in": 25.4,
    "inch": 25.4,
    "ft": 304.8,
    "foot": 304.8,
}
DXF_INSUNITS = {
    1: "in",
    2: "ft",
    4: "mm",
    5: "cm",
    6: "m",
}
PRINTING_WORDS = ("draw", "print", "plot", "ink", "喷墨", "喷码", "划线", "打印", "work")
TRAVEL_WORDS = ("travel", "transition", "move", "rapid", "转场", "空驶", "移动")
ANNOTATION_WORDS = ("dimension", "dim", "text", "annotation", "标注", "尺寸", "文字", "注释")
REFERENCE_WORDS = ("auxiliary", "construction", "reference", "辅助", "参考", "中心线", "axis", "guide")
IGNORED_WORDS = ("skip", "hidden", "defpoints", "不打印", "忽略", "ignore", "nonprint")

PATH_SEMANTIC_TO_ROLE = {
    "DRAW": "printing",
    "TRAVEL": "reference",
    "SKIP": "ignored",
    "AUXILIARY": "reference",
}
ROLE_TO_PATH_SEMANTIC = {
    "printing": "DRAW",
    "travel": "TRAVEL",
    "ignored": "SKIP",
    "annotation": "AUXILIARY",
    "reference": "AUXILIARY",
}


def _resolve_converter(configured: str, command: str) -> str | None:
    if configured:
        configured_path = Path(configured).expanduser()
        if configured_path.is_file() and os.access(configured_path, os.X_OK):
            return str(configured_path)
        return shutil.which(configured)
    return shutil.which(command)


def dwg_converter_status() -> dict[str, Any]:
    import_configured = os.getenv("DWG2DXF_BIN", "").strip()
    export_configured = os.getenv("DXF2DWG_BIN", "").strip()
    import_executable = _resolve_converter(import_configured, "dwg2dxf")
    export_executable = _resolve_converter(export_configured, "dxf2dwg")
    return {
        "available": bool(import_executable),
        "engine": "LibreDWG dwg2dxf" if import_executable else None,
        "executable": import_executable,
        "import_available": bool(import_executable),
        "import_executable": import_executable,
        "export_available": bool(export_executable),
        "export_engine": "LibreDWG dxf2dwg" if export_executable else None,
        "export_executable": export_executable,
        "installation_hint": None if import_executable and export_executable else (
            "请在小车 Ubuntu 后端安装 LibreDWG，并补齐缺少的 "
            + "、".join(
                name for name, value in (
                    ("dwg2dxf", import_executable),
                    ("dxf2dwg", export_executable),
                ) if not value
            )
            + "；也可通过 DWG2DXF_BIN、DXF2DWG_BIN 指定可执行文件。"
        ),
    }


def convert_dwg_to_dxf(source: Path, target: Path, timeout: int = 90) -> dict[str, Any]:
    """Convert one DWG to DXF with an installed LibreDWG command."""
    status = dwg_converter_status()
    executable = status.get("executable")
    if not executable:
        raise RuntimeError(str(status["installation_hint"]))
    # LibreDWG 0.14 on Windows does not support ``-o``. It writes
    # ``<source stem>.dxf`` into the working directory instead. Prefer that
    # documented behaviour and retain the explicit-output forms as fallbacks
    # for converter builds that do support them.
    default_output = target.parent / f"{source.stem}.dxf"
    attempts = (
        [str(executable), "-y", str(source)],
        [str(executable), "-o", str(target), str(source)],
        [str(executable), str(source), "-o", str(target)],
    )
    errors: list[str] = []
    for command in attempts:
        target.unlink(missing_ok=True)
        if default_output != target:
            default_output.unlink(missing_ok=True)
        try:
            completed = subprocess.run(
                command,
                cwd=str(target.parent),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(str(exc))
            continue
        if completed.returncode == 0:
            generated = target if target.is_file() else default_output
            if generated.is_file() and generated.stat().st_size > 0:
                if generated != target:
                    generated.replace(target)
                return {
                    "engine": status["engine"],
                    "executable": str(executable),
                    "return_code": completed.returncode,
                }
        detail = (completed.stderr or completed.stdout or "未生成 DXF").strip()
        errors.append(detail[-500:])
    raise RuntimeError("DWG 转换失败：" + "；".join(errors))


def convert_dxf_to_dwg(source: Path, target: Path, timeout: int = 90) -> dict[str, Any]:
    """Convert one validated DXF to DWG with an installed LibreDWG command."""
    status = dwg_converter_status()
    executable = status.get("export_executable")
    if not executable:
        raise RuntimeError(str(status["installation_hint"]))
    attempts = (
        [str(executable), "-o", str(target), str(source)],
        [str(executable), str(source), "-o", str(target)],
    )
    errors: list[str] = []
    for command in attempts:
        target.unlink(missing_ok=True)
        try:
            completed = subprocess.run(
                command,
                cwd=str(target.parent),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(str(exc))
            continue
        if (
            completed.returncode == 0
            and target.is_file()
            and target.stat().st_size > 6
            and target.read_bytes()[:4] == b"AC10"
        ):
            return {
                "engine": status["export_engine"],
                "executable": str(executable),
                "return_code": completed.returncode,
            }
        detail = (completed.stderr or completed.stdout or "未生成 DWG").strip()
        errors.append(detail[-500:])
    raise RuntimeError("DWG 导出转换失败：" + "；".join(errors))


def classify_layer_semantic(name: str, *, visible: bool = True, locked: bool = False) -> str:
    """Classify one DXF layer into the user-facing path semantics."""
    normalized = str(name or "").strip().lower()
    if not visible or any(word in normalized for word in IGNORED_WORDS):
        return "SKIP"
    if any(word in normalized for word in TRAVEL_WORDS):
        return "TRAVEL"
    if any(word in normalized for word in PRINTING_WORDS):
        return "DRAW"
    if (
        locked
        or any(word in normalized for word in ANNOTATION_WORDS)
        or any(word in normalized for word in REFERENCE_WORDS)
    ):
        return "AUXILIARY"
    # Unknown layers are never made executable without human confirmation.
    return "AUXILIARY"


def classify_layer(name: str, *, visible: bool = True, locked: bool = False) -> str:
    """Return the conservative execution role for a DXF layer."""
    semantic = classify_layer_semantic(name, visible=visible, locked=locked)
    if semantic == "AUXILIARY" and any(
        word in str(name or "").strip().lower() for word in ANNOTATION_WORDS
    ):
        return "annotation"
    return PATH_SEMANTIC_TO_ROLE[semantic]


def _layer_properties(document: Any, name: str) -> dict[str, Any]:
    try:
        layer = document.layers.get(name)
        color = int(getattr(layer.dxf, "color", 0) or 0)
        visible = color >= 0
        locked = bool(getattr(layer.dxf, "lock", False))
    except Exception:
        color, visible, locked = 0, True, False
    return {"color": color, "visible": visible, "locked": locked}


def inspect_dxf_layers(path: Path) -> dict[str, Any]:
    """Read a lightweight layer/entity summary without expanding CAD blocks."""
    try:
        import ezdxf
    except ImportError as exc:  # pragma: no cover - deployment configuration
        raise RuntimeError("后端未安装 ezdxf，请先安装 CAD 解析依赖。") from exc
    try:
        document = ezdxf.readfile(path)
    except Exception as exc:
        raise ValueError(f"DXF 文件解析失败：{exc}") from exc

    records: dict[str, dict[str, Any]] = {}
    entity_counts: dict[str, int] = {}
    for entity in document.modelspace():
        kind = entity.dxftype()
        name = str(getattr(entity.dxf, "layer", "0"))
        entity_counts[kind] = entity_counts.get(kind, 0) + 1
        if name not in records:
            props = _layer_properties(document, name)
            semantic = classify_layer_semantic(
                name, visible=props["visible"], locked=props["locked"]
            )
            records[name] = {
                "id": len(records) + 1,
                "name": name,
                "role": classify_layer(
                    name, visible=props["visible"], locked=props["locked"]
                ),
                "path_semantic": semantic,
                "entity_count": 0,
                "requires_confirmation": True,
                **props,
            }
        records[name]["entity_count"] += 1
    return {
        "layers": list(records.values()),
        "entity_counts": entity_counts,
        "estimated_geometry_count": sum(entity_counts.values()),
    }


def parse_dxf(
    path: Path,
    unit: str = "mm",
    *,
    layer_roles: dict[str, str] | None = None,
    excluded_entity_types: set[str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    try:
        import ezdxf
    except ImportError as exc:  # pragma: no cover - deployment configuration
        raise RuntimeError("后端未安装 ezdxf，请先安装 CAD 解析依赖。") from exc

    try:
        document = ezdxf.readfile(path)
    except Exception as exc:
        raise ValueError(f"DXF 文件解析失败：{exc}") from exc

    requested_unit = str(unit or "mm").strip().lower()
    if requested_unit == "auto":
        try:
            insunits = int(document.header.get("$INSUNITS", 0) or 0)
        except (TypeError, ValueError):
            insunits = 0
        resolved_unit = DXF_INSUNITS.get(insunits, "mm")
    else:
        resolved_unit = requested_unit
    factor = UNIT_FACTORS.get(resolved_unit)
    if factor is None:
        raise ValueError("单位只能是 mm、cm、m、in、ft 或 auto。")

    geometries: list[dict[str, Any]] = []
    warnings: list[str] = []
    if requested_unit == "auto" and resolved_unit == "mm":
        try:
            if int(document.header.get("$INSUNITS", 0) or 0) not in DXF_INSUNITS:
                warnings.append("DXF 未声明有效单位，auto 已按 mm 解释")
        except (TypeError, ValueError):
            warnings.append("DXF 单位字段无效，auto 已按 mm 解释")
    layer_ids: dict[str, int] = {}
    layer_records: dict[str, dict[str, Any]] = {}
    entity_counts: dict[str, int] = {}
    skipped_counts: dict[str, int] = {}
    expanded_blocks = 0
    excluded_types = {str(value).upper() for value in (excluded_entity_types or set())}

    def layer_id(name: str) -> int:
        if name not in layer_ids:
            layer_ids[name] = len(layer_ids) + 1
            props = _layer_properties(document, name)
            semantic = classify_layer_semantic(
                name, visible=props["visible"], locked=props["locked"]
            )
            layer_records[name] = {
                "id": layer_ids[name],
                "name": name,
                "role": classify_layer(name, visible=props["visible"], locked=props["locked"]),
                "path_semantic": semantic,
                **props,
            }
        return layer_ids[name]

    def point(value: Any) -> dict[str, float]:
        return {
            "x": round(float(value[0]) * factor, 3),
            "y": round(float(value[1]) * factor, 3),
            "z": round(float(value[2] if len(value) > 2 else 0.0) * factor, 3),
        }

    def add(kind: str, entity: Any, geometry: dict[str, Any], *, role: str | None = None, source: str | None = None) -> None:
        name = str(getattr(entity.dxf, "layer", "0"))
        current_layer_id = layer_id(name)
        record = layer_records.get(name)
        actual_role = (
            record["role"]
            if record and record["role"] != "printing"
            else role or (record["role"] if record else "printing")
        )
        path_semantic = (
            ROLE_TO_PATH_SEMANTIC.get(actual_role, "AUXILIARY")
            if role is not None
            else record.get("path_semantic", "AUXILIARY") if record else "AUXILIARY"
        )
        item = {
            "id": len(geometries) + 1,
            "type": kind,
            "layer_id": current_layer_id,
            "role": actual_role,
            "path_semantic": path_semantic,
            **geometry,
        }
        if actual_role != "printing":
            item["selected"] = False
        if source:
            item["source_block"] = source
        geometries.append(item)

    def count(kind: str) -> None:
        entity_counts[kind] = entity_counts.get(kind, 0) + 1

    def skip(kind: str, reason: str) -> None:
        skipped_counts[kind] = skipped_counts.get(kind, 0) + 1
        warnings.append(f"已跳过 {kind}：{reason}")

    def bulge_arc(start: dict[str, float], end: dict[str, float], bulge: float) -> dict[str, Any] | None:
        # A bulge is tan(included_angle / 4).  Convert it to a canonical arc.
        if abs(bulge) < 1e-12:
            return None
        x1, y1, x2, y2 = start["x"], start["y"], end["x"], end["y"]
        chord = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        if chord <= 1e-9:
            return None
        theta = 4.0 * __import__("math").atan(bulge)
        radius = abs(chord * (1 + bulge * bulge) / (4 * bulge))
        midpoint = ((x1 + x2) / 2, (y1 + y2) / 2)
        normal = (-(y2 - y1) / chord, (x2 - x1) / chord)
        offset = chord * (1 - bulge * bulge) / (4 * bulge)
        center = {"x": midpoint[0] + normal[0] * offset, "y": midpoint[1] + normal[1] * offset, "z": 0.0}
        start_angle = __import__("math").degrees(__import__("math").atan2(y1 - center["y"], x1 - center["x"]))
        end_angle = start_angle + __import__("math").degrees(theta)
        return {"center": center, "radius": round(radius, 3), "start_angle": start_angle, "end_angle": end_angle}

    def add_polyline(
        entity: Any,
        vertices: list[dict[str, float]],
        bulges: list[float],
        closed: bool,
        *,
        source_block: str | None,
    ) -> bool:
        """Preserve bulge segments as arcs instead of also printing their chords."""
        if len(vertices) < 2:
            return False
        segment_count = len(vertices) if closed else len(vertices) - 1
        has_bulge = any(abs(value) > 1e-12 for value in bulges[:segment_count])
        if not has_bulge:
            add(
                "polyline",
                entity,
                {"vertices": vertices, "closed": closed},
                source=source_block,
            )
            return True
        for index in range(segment_count):
            start = vertices[index]
            end = vertices[(index + 1) % len(vertices)]
            bulge = bulges[index] if index < len(bulges) else 0.0
            arc = bulge_arc(start, end, bulge)
            if arc:
                add("arc", entity, arc, source=source_block)
            else:
                add("line", entity, {"start": start, "end": end}, source=source_block)
        return True

    def parse_entity(entity: Any, *, source_block: str | None = None) -> bool:
        nonlocal expanded_blocks
        kind = entity.dxftype()
        count(kind)
        name = str(getattr(entity.dxf, "layer", "0"))
        selected_semantic = (layer_roles or {}).get(name)
        if selected_semantic == "SKIP" or kind in excluded_types:
            skip(kind, "已按导入筛选设置关闭")
            return False
        if kind == "LINE":
            add("line", entity, {"start": point(entity.dxf.start), "end": point(entity.dxf.end)}, source=source_block)
            return True
        if kind == "LWPOLYLINE":
            raw = list(entity.get_points("xyseb"))
            elevation = float(getattr(entity.dxf, "elevation", 0.0) or 0.0)
            vertices = [point((vertex[0], vertex[1], elevation)) for vertex in raw]
            if len(vertices) < 2:
                skip(kind, "顶点少于 2 个")
                return False
            bulges = [float(vertex[4] or 0.0) for vertex in raw]
            return add_polyline(
                entity,
                vertices,
                bulges,
                bool(entity.closed),
                source_block=source_block,
            )
        if kind == "POLYLINE":
            if bool(getattr(entity, "is_poly_face_mesh", False)) or bool(
                getattr(entity, "is_polygon_mesh", False)
            ):
                skip(kind, "多边形网格或多面网格不能安全转换为二维路径")
                return False
            vertex_entities = list(entity.vertices)
            vertices = [point(vertex.dxf.location) for vertex in vertex_entities]
            if len(vertices) >= 2:
                bulges = [float(getattr(vertex.dxf, "bulge", 0.0) or 0.0) for vertex in vertex_entities]
                return add_polyline(
                    entity,
                    vertices,
                    bulges,
                    bool(entity.is_closed),
                    source_block=source_block,
                )
            skip(kind, "顶点少于 2 个")
            return False
        if kind == "CIRCLE":
            add("circle", entity, {"center": point(entity.dxf.center), "radius": round(float(entity.dxf.radius) * factor, 3)}, source=source_block)
            return True
        if kind == "ARC":
            add("arc", entity, {"center": point(entity.dxf.center), "radius": round(float(entity.dxf.radius) * factor, 3), "start_angle": float(entity.dxf.start_angle), "end_angle": float(entity.dxf.end_angle)}, source=source_block)
            return True
        if kind == "ELLIPSE":
            ratio = float(entity.dxf.ratio)
            major_axis = point(entity.dxf.major_axis)
            axis_length = (major_axis["x"] ** 2 + major_axis["y"] ** 2) ** 0.5
            if not 0 < ratio <= 1 or axis_length <= 1e-9:
                skip(kind, "椭圆轴或比例无效")
                return False
            add("ellipse", entity, {"center": point(entity.dxf.center), "major_axis": major_axis, "ratio": ratio, "start_angle": float(entity.dxf.start_param) * 180 / pi, "end_angle": float(entity.dxf.end_param) * 180 / pi}, source=source_block)
            return True
        if kind == "SPLINE":
            raw_points = list(entity.control_points) or list(entity.fit_points)
            control_points = [point(value) for value in raw_points]
            if len(control_points) < 2:
                skip(kind, "控制点少于 2 个")
                return False
            add("spline", entity, {
                "degree": int(entity.dxf.degree),
                "control_points": control_points,
                "knots": [float(value) for value in entity.knots],
                "weights": [float(value) for value in entity.weights] if entity.weights else [],
                "closed": bool(getattr(entity, "closed", False)),
                "periodic":bool(int(entity.dxf.flags)&2),
            }, source=source_block)
            return True
        if kind in {"TEXT", "MTEXT"}:
            text = str(entity.dxf.text if kind == "TEXT" else entity.text)
            insert = entity.dxf.insert
            align = {"horizontal": "left", "vertical": "baseline"}
            add("text", entity, {
                "position": point(insert),
                "content": text,
                "height": round(float(getattr(entity.dxf, "height", 50.0)) * factor, 3),
                "rotation": float(getattr(entity.dxf, "rotation", 0.0)),
                "style": str(getattr(entity.dxf, "style", "Standard")),
                "width_factor": float(getattr(entity.dxf, "width_factor", 1.0)),
                "subtype": "mtext" if kind == "MTEXT" else "text",
                "align": align,
            }, role="annotation", source=source_block)
            return True
        if kind == "INSERT":
            block_name = str(entity.dxf.name)
            try:
                virtual = list(entity.virtual_entities())
            except Exception:
                virtual = []
            if virtual:
                expanded_blocks += 1
                for child in virtual:
                    parse_entity(child, source_block=block_name)
                return True
            skip(kind, f"块 {block_name} 无法展开")
            return False
        if kind in {"DIMENSION", "LEADER"}:
            try:
                virtual = list(entity.virtual_entities())
            except Exception:
                virtual = []
            if virtual:
                for child in virtual:
                    child_kind = child.dxftype()
                    before = len(geometries)
                    parse_entity(child, source_block=kind)
                    for item in geometries[before:]:
                        item["role"] = "annotation" if kind == "DIMENSION" else "reference"
                        item["selected"] = False
                return True
            vertices = [point(value) for value in getattr(entity, "vertices", [])]
            if len(vertices) >= 2:
                add("polyline", entity, {"vertices": vertices, "closed": False}, role="reference")
                return True
            skip(kind, "没有可提取的二维参考几何")
            return False
        if kind in {"SOLID", "TRACE"}:
            vertices = []
            for index in range(4):
                value = getattr(entity.dxf, f"vtx{index}", None)
                if value is not None:
                    vertices.append(point(value))
            if len(vertices) >= 3:
                add("polyline", entity, {"vertices": vertices, "closed": True}, role="reference")
                return True
            skip(kind, "填充边界无法转换为二维参考轮廓")
            return False
        if kind == "HATCH":
            converted = 0
            for boundary in getattr(entity, "paths", []):
                raw_vertices = list(getattr(boundary, "vertices", []) or [])
                vertices = [point(value[:2]) for value in raw_vertices]
                if len(vertices) >= 2:
                    add("polyline", entity, {"vertices": vertices, "closed": True}, role="reference")
                    converted += 1
            if converted:
                warnings.append(f"HATCH 已提取 {converted} 个边界并设为 reference，未将填充区域作为喷墨路径")
                return True
            skip(kind, "复杂填充边界无法安全提取")
            return False
        if kind == "3DFACE":
            skip(kind, "三维实体不能转换为二维喷墨路径")
            return False
        skip(kind, "当前版本没有安全的路径转换器")
        return False

    for entity in document.modelspace():
        parse_entity(entity)

    if layer_roles:
        for name, record in layer_records.items():
            semantic = layer_roles.get(name)
            if semantic in PATH_SEMANTIC_TO_ROLE:
                record["path_semantic"] = semantic
                record["role"] = PATH_SEMANTIC_TO_ROLE[semantic]
        for item in geometries:
            layer_name = next(
                (name for name, value in layer_ids.items() if value == item.get("layer_id")),
                None,
            )
            semantic = layer_roles.get(layer_name or "")
            if semantic in PATH_SEMANTIC_TO_ROLE:
                item["path_semantic"] = semantic
                item["role"] = PATH_SEMANTIC_TO_ROLE[semantic]
                item["selected"] = semantic == "DRAW"

    if not geometries:
        raise ValueError("DXF 中没有可用于分析的几何或参考内容。")
    unknown_layers = [name for name, record in layer_records.items() if record["path_semantic"] == "AUXILIARY" and not any(word in name.lower() for word in ANNOTATION_WORDS + REFERENCE_WORDS)]
    if unknown_layers:
        warnings.append("存在未明确命名的图层，已按 AUXILIARY 保留，确认前不会喷墨：" + ", ".join(sorted(unknown_layers)))
    for record in layer_records.values():
        layer_value = record["id"]
        record["entity_count"] = sum(
            item.get("layer_id") == layer_value for item in geometries
        )
        record["requires_confirmation"] = True
    payload = {
        "schema_version": "1.1",
        "unit": "mm",
        "source_format": "dxf",
        "layers": list(layer_records.values()),
        "lines": geometries,
        "cad_analysis": {
            "entity_counts": entity_counts,
            "skipped_counts": skipped_counts,
            "expanded_blocks": expanded_blocks,
            "source_unit": resolved_unit,
            "unit_factor_to_mm": factor,
            "printing_geometry_count": sum(item.get("role") == "printing" for item in geometries),
            "reference_geometry_count": sum(item.get("role") != "printing" for item in geometries),
            "path_semantic_counts": {
                semantic: sum(item.get("path_semantic") == semantic for item in geometries)
                for semantic in PATH_SEMANTIC_TO_ROLE
            },
            "layer_roles_confirmed": False,
        },
    }
    return payload, sorted(set(warnings))


def export_dxf(payload: dict[str, Any]) -> tuple[bytes, list[str]]:
    """Write the canonical drawing back to an ASCII DXF.

    The internal drawing coordinates are millimetres, so the generated DXF
    explicitly declares millimetres. Unsupported metadata is reported rather
    than silently presented as a lossless round trip.
    """
    try:
        import ezdxf
    except ImportError as exc:  # pragma: no cover - deployment configuration
        raise RuntimeError("后端未安装 ezdxf，请先安装 CAD 解析依赖。") from exc

    document = ezdxf.new("R2018")
    document.header["$INSUNITS"] = 4
    modelspace = document.modelspace()
    layers = payload.get("layers") if isinstance(payload.get("layers"), list) else []
    layer_names: dict[str, str] = {}
    for item in layers:
        if not isinstance(item, dict):
            continue
        layer_id = str(item.get("id") or "")
        raw_name = str(item.get("name") or f"XLINE_{layer_id or '0'}")
        safe_name = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]", "_", raw_name)[:240] or "XLINE_0"
        if safe_name not in document.layers:
            document.layers.add(safe_name)
        layer_names[layer_id] = safe_name
    if "XLINE_0" not in document.layers:
        document.layers.add("XLINE_0")

    warnings: list[str] = []
    geometries = payload.get("lines")
    if not isinstance(geometries, list):
        raise ValueError("图纸没有可导出的几何数据。")

    def point(value: Any) -> tuple[float, float, float]:
        if not isinstance(value, dict):
            raise ValueError("图元点坐标无效。")
        return (float(value.get("x", 0.0)), float(value.get("y", 0.0)), float(value.get("z", 0.0)))

    for geometry in geometries:
        if not isinstance(geometry, dict):
            continue
        layer = layer_names.get(str(geometry.get("layer_id") or ""), "XLINE_0")
        kind = str(geometry.get("type") or "").lower()
        try:
            if kind == "line":
                entity = modelspace.add_line(point(geometry.get("start")), point(geometry.get("end")), dxfattribs={"layer": layer})
            elif kind == "circle":
                entity = modelspace.add_circle(point(geometry.get("center")), float(geometry["radius"]), dxfattribs={"layer": layer})
            elif kind == "arc":
                entity = modelspace.add_arc(point(geometry.get("center")), float(geometry["radius"]), float(geometry.get("start_angle", 0.0)), float(geometry.get("end_angle", 360.0)), dxfattribs={"layer": layer})
            elif kind in {"polyline", "lwpolyline"}:
                vertices = [point(value) for value in geometry.get("vertices", [])]
                if len(vertices) < 2:
                    raise ValueError("折线顶点少于 2 个")
                entity = modelspace.add_polyline3d(vertices, dxfattribs={"layer": layer})
                if bool(geometry.get("closed")):
                    entity.close(True)
            elif kind == "ellipse":
                entity = modelspace.add_ellipse(point(geometry.get("center")), point(geometry.get("major_axis")), float(geometry.get("ratio", 1.0)), dxfattribs={"layer": layer})
                entity.dxf.start_param = float(geometry.get("start_angle", 0.0)) * pi / 180.0
                entity.dxf.end_param = float(geometry.get("end_angle", 360.0)) * pi / 180.0
            elif kind == "spline":
                points = [point(value) for value in geometry.get("control_points", [])]
                if len(points) < 2:
                    raise ValueError("样条控制点少于 2 个")
                degree=int(geometry.get('degree',3))
                if geometry.get('closed') and geometry.get('periodic'):
                    knots=geometry.get('knots') or []
                    if len(knots)==len(points)+degree+1:
                        entity=modelspace.add_open_spline(control_points=points,degree=degree,knots=knots,dxfattribs={"layer":layer})
                        entity.dxf.flags=int(entity.dxf.flags)|3
                    else:
                        entity=modelspace.add_spline(dxfattribs={"layer":layer})
                        entity.set_closed(points,degree=degree)
                else:
                    entity=modelspace.add_open_spline(control_points=points,degree=degree,
                        knots=geometry.get('knots') or None,dxfattribs={"layer":layer})
                if len(geometry.get('weights') or [])==len(entity.control_points):entity.weights=geometry['weights']
            elif kind == "text":
                entity = modelspace.add_text(str(geometry.get("content") or ""), dxfattribs={"layer": layer, "height": float(geometry.get("height", 50.0)), "rotation": float(geometry.get("rotation", 0.0))})
                entity.dxf.insert = point(geometry.get("position"))
            else:
                warnings.append(f"图元 {geometry.get('id', '?')} 类型 {kind or 'unknown'} 未导出")
                continue
            entity.dxf.layer = layer
        except (KeyError, TypeError, ValueError) as exc:
            warnings.append(f"图元 {geometry.get('id', '?')} 导出失败：{exc}")

    stream = StringIO()
    document.write(stream)
    return stream.getvalue().encode("utf-8"), sorted(set(warnings))
