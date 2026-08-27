"""Convert common DXF entities into the CAD JSON understood by XLine."""
from __future__ import annotations

from math import cos, pi, sin
from pathlib import Path
from typing import Any


UNIT_FACTORS = {"mm": 1.0, "cm": 10.0, "m": 1000.0}


def parse_dxf(path: Path, unit: str = "mm") -> tuple[dict[str, Any], list[str]]:
    try:
        import ezdxf
    except ImportError as exc:  # pragma: no cover - deployment configuration
        raise RuntimeError("后端未安装 ezdxf，请先安装 CAD 解析依赖。") from exc

    factor = UNIT_FACTORS.get(unit.lower())
    if factor is None:
        raise ValueError("单位只能是 mm、cm 或 m。")
    try:
        document = ezdxf.readfile(path)
    except Exception as exc:
        raise ValueError(f"DXF 文件解析失败：{exc}") from exc

    lines: list[dict[str, Any]] = []
    warnings: list[str] = []
    layers: dict[str, int] = {}

    def layer_id(name: str) -> int:
        if name not in layers:
            layers[name] = len(layers) + 1
        return layers[name]

    def point(value: Any) -> dict[str, float]:
        return {"x": round(float(value[0]) * factor, 3), "y": round(float(value[1]) * factor, 3), "z": 0.0}

    def add(kind: str, entity: Any, geometry: dict[str, Any]) -> None:
        lines.append({"id": len(lines) + 1, "type": kind, "layer_id": layer_id(entity.dxf.layer), **geometry})

    for entity in document.modelspace():
        kind = entity.dxftype()
        if kind == "LINE":
            add("line", entity, {"start": point(entity.dxf.start), "end": point(entity.dxf.end)})
        elif kind in {"LWPOLYLINE", "POLYLINE"}:
            vertices = []
            if kind == "LWPOLYLINE":
                vertices = [point(vertex) for vertex in entity.get_points("xy")]
            else:
                vertices = [point(vertex.dxf.location) for vertex in entity.vertices]
            if len(vertices) >= 2:
                add("polyline", entity, {"vertices": vertices, "closed": bool(entity.closed)})
        elif kind == "CIRCLE":
            add("circle", entity, {"center": point(entity.dxf.center), "radius": round(float(entity.dxf.radius) * factor, 3)})
        elif kind == "ARC":
            add("arc", entity, {"center": point(entity.dxf.center), "radius": round(float(entity.dxf.radius) * factor, 3), "start_angle": float(entity.dxf.start_angle), "end_angle": float(entity.dxf.end_angle)})
        elif kind == "ELLIPSE":
            add("ellipse", entity, {"center": point(entity.dxf.center), "major_axis": point(entity.dxf.major_axis), "ratio": float(entity.dxf.ratio), "start_angle": float(entity.dxf.start_param) * 180 / pi, "end_angle": float(entity.dxf.end_param) * 180 / pi})
        elif kind in {"SPLINE", "3DFACE", "SOLID", "TRACE", "INSERT", "TEXT", "MTEXT"}:
            warnings.append(f"已跳过暂不支持的图元：{kind}")

    if not lines:
        raise ValueError("DXF 中没有可用于规划的线、折线、圆弧或椭圆。")
    payload = {"schema_version": "1.0", "unit": "mm", "source_format": "dxf", "layers": [{"id": value, "name": name} for name, value in layers.items()], "lines": lines}
    return payload, sorted(set(warnings))
