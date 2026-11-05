"""Strict model-output adapter for CAD edit language outside rule coverage."""

from __future__ import annotations

from copy import deepcopy
import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .cad_edit_intent import build_cad_edit_intent


class StructuredCadTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["instance", "logical_object", "semantic", "attribute", "unresolved"]
    instance_ids: list[int] = Field(default_factory=list, max_length=50)
    position: Literal["middle", "left", "right", "top", "bottom"] | None = None
    count: int | None = Field(default=None, ge=1, le=50)
    object_type: Literal[
        "parking_space", "room", "basketball_court", "badminton_court"
    ] | None = None
    semantic: Literal["center_circle", "outer_frame", "center_line"] | None = None
    attribute: Literal["geometry_type", "layer_id", "path_semantic"] | None = None
    value: str | int | None = None

    @model_validator(mode="after")
    def validate_scope_fields(self) -> "StructuredCadTarget":
        if len(self.instance_ids) != len(set(self.instance_ids)) or any(
            value < 1 for value in self.instance_ids
        ):
            raise ValueError("instance IDs must be unique positive integers")
        if self.scope == "instance" and not self.instance_ids:
            raise ValueError("instance target requires instance_ids")
        if self.scope == "logical_object" and self.position is None:
            raise ValueError("logical object target requires position")
        if self.scope == "semantic" and self.semantic is None:
            raise ValueError("semantic target requires semantic")
        if self.scope == "attribute" and (
            self.attribute is None or self.value is None
        ):
            raise ValueError("attribute target requires attribute and value")
        return self


class StructuredCadParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dx_mm: float | None = Field(default=None, ge=-1_000_000, le=1_000_000)
    dy_mm: float | None = Field(default=None, ge=-1_000_000, le=1_000_000)
    coordinate_frame: Literal["drawing", "vehicle", "object_local"] | None = None
    angle_degrees: float | None = Field(default=None, ge=-3600, le=3600)
    pivot: Literal[
        "instance_center", "each_instance_center", "group_center"
    ] | None = None
    factor: float | None = Field(default=None, ge=0.05, le=20)
    dimension: Literal["width", "height", "radius"] | None = None
    value_mm: float | None = Field(default=None, gt=0, le=1_000_000)
    direction: Literal["left", "right", "up", "down"] | None = None
    distance_mm: float | None = Field(default=None, gt=0, le=1_000_000)
    placement: Literal["offset", "gap"] | None = None
    alignment: Literal[
        "left", "right", "top", "bottom", "horizontal_center", "vertical_center"
    ] | None = None
    reference_instance: int | None = Field(default=None, ge=1, le=50)
    mirror_axis: Literal["vertical", "horizontal"] | None = None
    keep_source: bool | None = None
    offset_side: Literal["inside", "outside"] | None = None
    array_mode: Literal["rectangular", "polar"] | None = None
    rows: int | None = Field(default=None, ge=1, le=20)
    columns: int | None = Field(default=None, ge=1, le=20)
    row_spacing_mm: float | None = Field(default=None, gt=0)
    column_spacing_mm: float | None = Field(default=None, gt=0)
    count: int | None = Field(default=None, ge=2, le=50)
    constraint_type: Literal[
        "parallel", "concentric", "tangent", "equal", "perpendicular"
    ] | None = None


class StructuredCadInterpretation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["cad.language-interpretation.v1"]
    is_cad_edit: bool
    operation: Literal[
        "translate", "rotate", "scale", "resize", "duplicate", "align",
        "delete", "retain", "mirror", "offset", "array", "constraint",
    ] | None = None
    target: StructuredCadTarget | None = None
    parameters: StructuredCadParameters = Field(default_factory=StructuredCadParameters)
    assumptions: list[str] = Field(default_factory=list, max_length=10)
    constraints: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    evidence_text: list[str] = Field(min_length=1, max_length=6)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_edit_fields(self) -> "StructuredCadInterpretation":
        if self.is_cad_edit and (self.operation is None or self.target is None):
            raise ValueError("CAD edit requires operation and target")
        return self


_OPERATION_MARKERS = {
    "translate": ("移动", "平移", "挪", "偏移", "移到", "移至"),
    "rotate": ("旋转", "转动"),
    "scale": ("缩放", "放大", "缩小", "扩大", "收缩"),
    "resize": ("宽度", "高度", "半径", "尺寸", "改宽", "改高"),
    "duplicate": ("复制", "拷贝", "再生成一个", "再来一个"),
    "align": ("对齐", "齐平", "排齐"),
    "delete": ("删除", "删掉", "移除", "去掉"),
    "retain": ("只保留", "仅保留"),
    "mirror": ("镜像", "翻转", "翻面", "对称复制"),
    "offset": ("偏移", "等距", "内缩", "外扩"),
    "array": ("阵列", "排成", "排布", "复制成"),
    "constraint": ("同心", "相切", "平行", "垂直", "一样大", "相等"),
}
_FORBIDDEN_GEOMETRY_KEYS = {
    "x", "y", "z", "start", "end", "center", "vertices", "control_points",
    "geometries", "geometry", "drawing", "lines",
}
_CHINESE_DIGITS = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


def _numbered_instances(text: str) -> set[int]:
    result: set[int] = set()
    for raw in re.findall(r"第\s*(\d+|[一二两三四五六七八九十]+)\s*(?:个|组|座|块|片|条)?", text):
        if raw.isdigit():
            result.add(int(raw))
        elif raw == "十":
            result.add(10)
        elif raw.startswith("十") and len(raw) == 2:
            result.add(10 + _CHINESE_DIGITS.get(raw[1], 0))
        elif raw.endswith("十") and len(raw) == 2:
            result.add(_CHINESE_DIGITS.get(raw[0], 0) * 10)
        elif len(raw) == 1 and raw in _CHINESE_DIGITS:
            result.add(_CHINESE_DIGITS[raw])
    return result


def _distance_values_mm(text: str) -> list[float]:
    scales = {"米": 1000.0, "m": 1000.0, "厘米": 10.0, "cm": 10.0,
              "毫米": 1.0, "mm": 1.0}
    return [
        float(number) * scales[unit.lower()]
        for number, unit in re.findall(
            r"(\d+(?:\.\d+)?)\s*(厘米|毫米|cm|mm|米|m)", text.lower()
        )
    ]


def _contains_number(values: list[float], expected: float) -> bool:
    return any(math.isclose(abs(value), abs(expected), abs_tol=1e-6) for value in values)


def _direction_grounded(text: str, parameters: dict[str, Any]) -> bool:
    dx = parameters.get("dx_mm")
    dy = parameters.get("dy_mm")
    if not isinstance(dx, (int, float)) or not isinstance(dy, (int, float)):
        return True
    frame = parameters.get("coordinate_frame", "drawing")
    compact = "".join(text.lower().split())
    if frame == "vehicle":
        x_positive = ("前" in compact)
        x_negative = ("后" in compact)
    else:
        x_positive = any(value in compact for value in (
            "向右", "往右", "右移", "向东", "往东", "水平正向", "水平方向正向",
        ))
        x_negative = any(value in compact for value in (
            "向左", "往左", "左移", "向西", "往西", "水平负向", "水平方向负向",
        ))
    y_positive = any(value in compact for value in (
        "向上", "往上", "上移", "向北", "往北", "垂直正向", "竖直正向",
    ))
    y_negative = any(value in compact for value in (
        "向下", "往下", "下移", "向南", "往南", "垂直负向", "竖直负向",
    ))
    return (
        (math.isclose(float(dx), 0.0) or (x_positive if dx > 0 else x_negative))
        and (math.isclose(float(dy), 0.0) or (y_positive if dy > 0 else y_negative))
    )


def _ground_interpretation(
    parsed: StructuredCadInterpretation, source_text: str
) -> dict[str, Any]:
    target = parsed.target
    parameters = parsed.parameters.model_dump(mode="python", exclude_none=True)
    checks: list[dict[str, Any]] = []

    def check(claim: str, ok: bool, observed: Any) -> None:
        checks.append({"claim": claim, "verified": ok, "observed": observed})

    explicit_instances = _numbered_instances(source_text)
    if target is not None:
        check(
            "target.resolved",
            target.scope != "unresolved",
            target.scope,
        )
    if target is not None and target.instance_ids:
        check(
            "target.instance_ids",
            set(target.instance_ids).issubset(explicit_instances),
            sorted(explicit_instances),
        )
    if target is not None and target.scope == "logical_object":
        aliases = {
            "middle": ("中间", "中央", "正中"),
            "left": ("左侧", "左边", "最左"),
            "right": ("右侧", "右边", "最右"),
            "top": ("上方", "上面", "最上"),
            "bottom": ("下方", "下面", "最下"),
        }
        check(
            "target.position",
            any(value in source_text for value in aliases.get(str(target.position), ())),
            target.position,
        )
    if target is not None and target.scope == "semantic":
        aliases = {
            "center_circle": ("中心圆", "中圈", "中心的圆"),
            "outer_frame": ("外框", "边框", "外围轮廓"),
            "center_line": ("中线", "中心线"),
        }
        check(
            "target.semantic",
            any(value in source_text for value in aliases.get(str(target.semantic), ())),
            target.semantic,
        )
    if target is not None and target.scope == "attribute":
        attribute_evidence = {
            "layer_id": "图层" in source_text,
            "geometry_type": any(value in source_text for value in (
                "直线", "线段", "折线", "多段线", "圆", "圆弧", "椭圆", "样条", "文字",
            )),
            "path_semantic": any(value in source_text for value in (
                "喷墨", "喷涂", "打印路径", "参考线", "辅助线", "标注",
            )),
        }
        check(
            "target.attribute", attribute_evidence.get(str(target.attribute), False),
            target.attribute,
        )

    distances = _distance_values_mm(source_text)
    if parsed.operation == "translate":
        nonzero = [
            float(value) for value in (parameters.get("dx_mm"), parameters.get("dy_mm"))
            if isinstance(value, (int, float)) and not math.isclose(float(value), 0.0)
        ]
        if nonzero:
            check(
                "parameters.translation_distance",
                all(_contains_number(distances, value) for value in nonzero),
                distances,
            )
            check(
                "parameters.translation_direction",
                _direction_grounded(source_text, parameters),
                {"dx_mm": parameters.get("dx_mm"), "dy_mm": parameters.get("dy_mm")},
            )
    if parsed.operation == "rotate" and parameters.get("angle_degrees") is not None:
        angles = [float(value) for value in re.findall(r"(\d+(?:\.\d+)?)\s*度", source_text)]
        check(
            "parameters.angle_degrees",
            _contains_number(angles, float(parameters["angle_degrees"])),
            angles,
        )
    if parsed.operation == "scale" and parameters.get("factor") is not None:
        factors = [float(value) for value in re.findall(r"(\d+(?:\.\d+)?)\s*倍", source_text)]
        check("parameters.factor", _contains_number(factors, float(parameters["factor"])), factors)
    if parsed.operation == "resize" and parameters.get("value_mm") is not None:
        check(
            "parameters.value_mm",
            _contains_number(distances, float(parameters["value_mm"])),
            distances,
        )
    if parsed.operation == "duplicate" and parameters.get("distance_mm") is not None:
        check(
            "parameters.distance_mm",
            _contains_number(distances, float(parameters["distance_mm"])),
            distances,
        )
    if parsed.operation == "align" and parameters.get("reference_instance") is not None:
        check(
            "parameters.reference_instance",
            int(parameters["reference_instance"]) in explicit_instances,
            sorted(explicit_instances),
        )
    failures = [item for item in checks if item["verified"] is not True]
    return {"verified": not failures, "checks": checks, "failures": failures}


def _contains_forbidden_geometry(value: Any) -> bool:
    if isinstance(value, dict):
        if any(str(key).lower() in _FORBIDDEN_GEOMETRY_KEYS for key in value):
            return True
        return any(_contains_forbidden_geometry(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_forbidden_geometry(item) for item in value)
    return False


def _legacy_target(target: StructuredCadTarget) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if target.instance_ids:
        if len(target.instance_ids) == 1:
            result["instance"] = target.instance_ids[0]
        else:
            result["instances"] = list(target.instance_ids)
    if target.scope == "logical_object":
        result["logical_object_selector"] = {
            "position": target.position,
            **({"count": target.count} if target.count is not None else {}),
            **({"object_type": target.object_type} if target.object_type else {}),
        }
    elif target.scope == "semantic":
        semantic = {
            "center_circle": "中心圆",
            "outer_frame": "外框",
            "center_line": "中线",
        }[str(target.semantic)]
        result["selector"] = {
            "kind": "semantic_within_target",
            "semantic": semantic,
        }
    elif target.scope == "attribute":
        attribute = str(target.attribute)
        result["selector"] = {
            "kind": "attribute",
            "attribute": "semantic" if attribute == "path_semantic" else attribute,
            "value": target.value,
        }
    return result


def parse_structured_cad_interpretation(
    payload: dict[str, Any], source_text: str
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Validate model output and convert it to the deterministic executor shape."""
    try:
        parsed = StructuredCadInterpretation.model_validate(payload)
    except (TypeError, ValueError):
        return None
    if not parsed.is_cad_edit or parsed.operation is None or parsed.target is None:
        return None
    compact_source = "".join(source_text.lower().split())
    evidence = ["".join(value.lower().split()) for value in parsed.evidence_text]
    if any(not value or value not in compact_source for value in evidence):
        return None
    if not any(marker in source_text for marker in _OPERATION_MARKERS[parsed.operation]):
        return None
    raw = parsed.model_dump(mode="python", exclude_none=True)
    if _contains_forbidden_geometry(raw.get("constraints")):
        return None
    parameters = raw.get("parameters") or {}
    dimension_map = {"width": "宽度", "height": "高度", "radius": "半径"}
    direction_map = {"left": "左", "right": "右", "up": "上", "down": "下"}
    alignment_map = {
        "left": "左", "right": "右", "top": "顶部", "bottom": "底部",
        "horizontal_center": "水平居中", "vertical_center": "垂直居中",
    }
    if parameters.get("dimension") in dimension_map:
        parameters["dimension"] = dimension_map[parameters["dimension"]]
    if parameters.get("direction") in direction_map:
        parameters["direction"] = direction_map[parameters["direction"]]
    if parameters.get("alignment") in alignment_map:
        parameters["alignment"] = alignment_map[parameters["alignment"]]
    edit = {
        "operation": parsed.operation,
        **_legacy_target(parsed.target),
        **deepcopy(parameters),
        "assumptions": list(parsed.assumptions),
        "constraints": deepcopy(parsed.constraints),
    }
    intent = build_cad_edit_intent(source_text, edit)
    grounding = _ground_interpretation(parsed, source_text)
    intent["confidence"] = (
        min(float(parsed.confidence), float(intent["confidence"]))
        if grounding["verified"] else 0.0
    )
    intent["parser"] = "model_structured_fallback"
    intent["evidence_text"] = list(parsed.evidence_text)
    intent["grounding"] = grounding
    return edit, intent
