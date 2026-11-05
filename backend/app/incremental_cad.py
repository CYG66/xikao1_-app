"""Conservative, instance-scoped edits on an existing CAD candidate."""

from __future__ import annotations

import re
import math
from copy import deepcopy
from typing import Any

from .cad_target_resolver import bind_resolved_target, resolve_cad_target
from .geometry_catalog import build_geometry_catalog


_ORDINALS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5}
_DISTANCE = r"(\d+(?:\.\d+)?)\s*(毫米|厘米|米|mm|cm|m)(?![a-zA-Z])"


def _attribute_or_spatial_selector(text: str) -> dict[str, Any] | None:
    layer = re.search(r"(?:第\s*)?(\d+)\s*(?:号)?图层|图层\s*(\d+)", text)
    if layer:
        return {"kind": "attribute", "attribute": "layer_id",
                "value": int(layer.group(1) or layer.group(2))}
    same_layer = re.search(
        r"(?:与|和)?第\s*(\d+|[一二两三四五])\s*个?(?:图形|实例)?同图层",
        text,
    )
    if same_layer:
        raw = same_layer.group(1)
        return {"kind": "attribute", "attribute": "same_layer_as_instance",
                "reference_instance": int(raw) if raw.isdigit() else _ORDINALS[raw]}
    semantics = {
        "printing": ("喷墨线", "喷涂线", "划线路径", "打印路径"),
        "reference": ("参考线", "参考图元"),
        "annotation": ("标注线", "标注图元", "尺寸标注"),
        "ignored": ("忽略线", "忽略图元"),
        "auxiliary": ("辅助线", "辅助图元"),
    }
    for value, words in semantics.items():
        if any(word in text for word in words):
            return {"kind": "attribute", "attribute": "semantic", "value": value}
    geometry_types = {
        "line": ("所有直线", "全部直线", "所有线段", "全部线段"),
        "polyline": ("所有折线", "全部折线", "所有多段线", "全部多段线"),
        "arc": ("所有圆弧", "全部圆弧"),
        "circle": ("所有圆形", "全部圆形", "所有圆", "全部圆"),
        "ellipse": ("所有椭圆", "全部椭圆"),
        "spline": ("所有样条", "全部样条", "所有曲线", "全部曲线"),
        "text": ("所有文字", "全部文字", "所有文本", "全部文本"),
    }
    for value, words in geometry_types.items():
        if any(word in text for word in words):
            return {"kind": "attribute", "attribute": "geometry_type", "value": value}
    spatial = re.search(
        r"第\s*(\d+|[一二两三四五])\s*个?(?:图形|实例)?(?:的)?"
        r"(左侧|左边|右侧|右边|上方|上面|下方|下面)(?:的)?"
        r"(?:(所有|全部|\d+个|[一二两三四五]个))?(?:图形|实例)",
        text,
    )
    if spatial:
        raw = spatial.group(1)
        relation = {
            "左侧": "left_of", "左边": "left_of",
            "右侧": "right_of", "右边": "right_of",
            "上方": "above", "上面": "above",
            "下方": "below", "下面": "below",
        }[spatial.group(2)]
        count_text = spatial.group(3) or ""
        count_value = count_text.removesuffix("个")
        count = (int(count_value) if count_value.isdigit()
                 else _ORDINALS.get(count_value))
        return {"kind": "spatial", "relation": relation,
                "reference_instance": int(raw) if raw.isdigit() else _ORDINALS[raw],
                **({"count": count} if count is not None else {})}
    nearest = re.search(
        r"(?:离|距)?第\s*(\d+|[一二两三四五])\s*个?(?:图形|实例)?(?:距离)?最近的(?:图形|实例)",
        text,
    )
    if nearest:
        raw = nearest.group(1)
        return {"kind": "spatial", "relation": "nearest",
                "reference_instance": int(raw) if raw.isdigit() else _ORDINALS[raw]}
    return None


def _millimeters(value: str, unit: str) -> float:
    return float(value) * {"米": 1000, "m": 1000, "厘米": 10, "cm": 10, "毫米": 1, "mm": 1}[unit]


def _instance_prefix(instance_ids: list[int]) -> str:
    return "、".join(f"第{value}个图形" for value in instance_ids)


def _translation_instruction(
    prefix: str, dx_mm: float, dy_mm: float, *, frame: str = "drawing"
) -> str | None:
    """Serialize both translation components without dropping a diagonal axis."""
    if not all(math.isfinite(float(value)) for value in (dx_mm, dy_mm)):
        return None
    parts: list[str] = []
    if not math.isclose(float(dx_mm), 0.0, abs_tol=1e-9):
        direction = (
            "前" if frame == "vehicle" and dx_mm > 0
            else "后" if frame == "vehicle"
            else "右" if dx_mm > 0
            else "左"
        )
        parts.append(f"向{direction}移动{abs(float(dx_mm)):g}毫米")
    if not math.isclose(float(dy_mm), 0.0, abs_tol=1e-9):
        parts.append(
            f"向{'上' if dy_mm > 0 else '下'}移动{abs(float(dy_mm)):g}毫米"
        )
    if not parts:
        return None
    return prefix + "并".join(parts)


def _compound_translation(text: str) -> tuple[float, float, str] | None:
    """Parse explicit horizontal and vertical displacement clauses."""
    matches = re.findall(
        r"(?:向|往)?(左|右|上|下|东|西|南|北|前|后)"
        r"(?:侧|方)?\s*(?:平移|移动|挪动|挪|移)?\s*" + _DISTANCE,
        text,
    )
    if len(matches) < 2:
        return None
    dx = 0.0
    dy = 0.0
    has_x = False
    has_y = False
    vehicle_frame = False
    for direction, value, unit in matches:
        distance = _millimeters(value, unit)
        if direction in {"左", "西", "右", "东", "前", "后"}:
            has_x = True
            vehicle_frame = vehicle_frame or direction in {"前", "后"}
            dx += distance * (-1 if direction in {"左", "西", "后"} else 1)
        else:
            has_y = True
            dy += distance * (-1 if direction in {"下", "南"} else 1)
    if not has_x or not has_y or (math.isclose(dx, 0.0) and math.isclose(dy, 0.0)):
        return None
    return dx, dy, "vehicle" if vehicle_frame else "drawing"


def _instance_numbers(text: str) -> list[int]:
    numbered_text = re.sub(
        r"([、,，和及与])\s*(?!第)(\d+|[一二两三四五])(?=\s*(?:个|片|座|组|块|图形|实例))",
        r"\1第\2",
        text,
    )
    values = [
        int(value) if value.isdigit() else _ORDINALS[value]
        for value in re.findall(
            r"第\s*(\d+|[一二两三四五])\s*(?:个|片|座|组|块)?",
            numbered_text,
        )
    ]
    return list(dict.fromkeys(values))


def _batch_rotation_pivot(text: str) -> str | None:
    if any(word in text for word in ("各自中心", "分别旋转", "分别绕")):
        return "each_instance_center"
    if any(word in text for word in ("组合中心", "整体中心", "整组中心", "作为整体")):
        return "group_center"
    return None


def _batch_scale_pivot(text: str) -> str | None:
    if any(word in text for word in ("各自中心", "分别缩放", "分别放大", "分别缩小")):
        return "each_instance_center"
    if any(word in text for word in (
        "组合中心", "整体中心", "整组中心", "作为整体", "整体缩放",
    )):
        return "group_center"
    return None


def _scale_factor(text: str) -> float | None:
    normalized = re.sub(r"[\s，。！？、,!?；;：:]+", "", text.lower())
    normalized=re.sub(r'(到|为)原来(?:的)?',r'\1',normalized)
    if "缩小一半" in normalized or "缩小到一半" in normalized:
        return 0.5
    percent = re.search(r"(等比例缩放|缩放|扩大|放大|缩小)(到|为)?(\d+(?:\.\d+)?)%", normalized)
    if percent:
        value = float(percent.group(3)) / 100.0
        if percent.group(1) in {"等比例缩放", "缩放"} or percent.group(2):
            return value
        return 1.0 - value if percent.group(1) == "缩小" else 1.0 + value
    multiple = re.search(
        r"(等比例缩放|缩放|扩大|放大|缩小)(到|为)?(\d+(?:\.\d+)?|一|二|两|三)倍",
        normalized,
    )
    if not multiple:
        return None
    chinese_numbers = {"一": 1.0, "二": 2.0, "两": 2.0, "三": 3.0}
    raw = multiple.group(3)
    value = float(raw) if raw[0].isdigit() else chinese_numbers.get(raw, 0.0)
    if value <= 0:
        return None
    action = multiple.group(1)
    if action == "缩小":
        if multiple.group(2) or value < 1.0:
            return value
        return 1.0 / (2.0 if value == 1.0 else value)
    if action in {"等比例缩放", "缩放"}:
        return value
    return 2.0 if value == 1.0 else value


def _rotation_prefix(pivot: str | None) -> str:
    return {
        "each_instance_center": "分别绕各自中心",
        "group_center": "作为整体绕组合中心",
    }.get(pivot, "")


def _scale_prefix(pivot: str | None) -> str:
    return {
        "each_instance_center": "分别以各自中心等比例缩放到",
        "group_center": "以组合中心整体缩放到",
        "instance_center": "以自身中心等比例缩放到",
    }.get(pivot, "等比例缩放到")


def _legacy_previous_edit(previous: dict[str, Any] | None) -> dict[str, Any] | None:
    """Expose a v2 contract through the legacy follow-up fields."""
    if not isinstance(previous, dict) or previous.get("schema") != "cad.edit.v2":
        return previous
    target = previous.get("target")
    if not isinstance(target, dict):
        return None
    instance_ids = target.get("instance_ids")
    if target.get("scope") != "instance" or not isinstance(instance_ids, list) or not instance_ids:
        return None
    normalized = {
        "operation": previous.get("operation"),
        "parameters": dict(previous.get("parameters") or {}),
        "coordinate_frame": previous.get("coordinate_frame", "drawing"),
        "target_instance_id": instance_ids[0],
        **({"target_instance_ids": instance_ids} if len(instance_ids) > 1 else {}),
        **({"reference_instance_id": previous["reference_instance_id"]}
           if previous.get("reference_instance_id") is not None else {}),
        **({"created_instance_id": previous["created_instance_id"]}
           if previous.get("created_instance_id") is not None else {}),
    }
    for key in ("project_id", "variant_id", "parent_variant_id", "recorded_at"):
        if previous.get(key) is not None:
            normalized[key] = previous[key]
    return normalized


def resolve_incremental_correction(
    message: str,
    previous: dict[str, Any] | None,
    available_instance_ids: list[int] | None = None,
) -> str | None:
    """Rewrite a correction against the parent of the last persisted edit."""
    previous = _legacy_previous_edit(previous)
    if not isinstance(previous, dict) or not any(
        marker in message for marker in ("不是", "说错了", "改成", "应该是", "应为")
    ):
        return None
    operation = previous.get("operation")
    if operation not in {"translate", "rotate", "scale", "resize"}:
        return None
    single = previous.get("target_instance_id")
    batch = previous.get("target_instance_ids")
    target_ids = (
        sorted(set(batch))
        if isinstance(batch, list) and len(batch) > 1
        and all(isinstance(value, int) and value > 0 for value in batch)
        else [single] if isinstance(single, int) and single > 0 else []
    )
    if not target_ids or any(
        value not in (available_instance_ids or target_ids) for value in target_ids
    ):
        return None
    tail_parts = re.split(r"(?:而?是|应该是|应为|改成|改为)", message)
    tail = tail_parts[-1].strip() if len(tail_parts) > 1 else message.strip()
    corrected_targets = _instance_numbers(tail)
    if corrected_targets:
        if any(value not in (available_instance_ids or []) for value in corrected_targets):
            return None
        target_ids = corrected_targets
    prefix = _instance_prefix(target_ids)
    parameters = previous.get("parameters") or {}

    if operation == "translate":
        dx, dy = parameters.get("dx_mm"), parameters.get("dy_mm")
        if not isinstance(dx, (int, float)) or not isinstance(dy, (int, float)):
            return None
        compound = _compound_translation(tail)
        if compound is not None:
            compound_dx, compound_dy, frame = compound
            return _translation_instruction(
                prefix, compound_dx, compound_dy, frame=frame
            )
        directions = re.findall(r"(?:向|往)?(左|右|上|下|东|西|南|北)", tail)
        frame = previous.get("coordinate_frame", "drawing")
        direction = directions[-1] if directions else (
            "前" if frame == "vehicle" and dx > 0
            else "后" if frame == "vehicle" and dx < 0
            else "右" if dx > 0 else "左" if dx < 0
            else "上" if dy > 0 else "下"
        )
        distances = re.findall(_DISTANCE, tail)
        distance = (
            _millimeters(*distances[-1]) if distances
            else abs(dx) if direction in {"左", "右", "东", "西"} else abs(dy)
        )
        if distance <= 0:
            return None
        return f"{prefix}向{direction}移动{distance:g}毫米"

    if operation == "rotate":
        angle = parameters.get("angle_degrees")
        if not isinstance(angle, (int, float)) or angle == 0:
            return None
        directions = re.findall(r"(顺时针|逆时针)", tail)
        direction = directions[-1] if directions else (
            "顺时针" if angle < 0 else "逆时针"
        )
        angles = re.findall(r"(\d+(?:\.\d+)?)\s*度", tail)
        degrees = float(angles[-1]) if angles else abs(angle)
        pivot = parameters.get("pivot")
        if len(target_ids) > 1 and pivot not in {
            "each_instance_center", "group_center",
        }:
            return None
        return f"{prefix}{_rotation_prefix(pivot)}{direction}旋转{degrees:g}度"

    if operation == "scale":
        factor = _scale_factor(tail)
        if factor is None:
            factor = parameters.get("factor")
        pivot = parameters.get("pivot")
        if (
            not isinstance(factor, (int, float))
            or not 0.05 <= factor <= 20
            or len(target_ids) > 1 and pivot not in {
                "each_instance_center", "group_center",
            }
        ):
            return None
        return f"{prefix}{_scale_prefix(pivot)}{factor:g}倍"

    dimension = parameters.get("dimension")
    value = parameters.get("value_mm")
    dimensions = re.findall(r"(宽度|高度|半径)", tail)
    distances = re.findall(_DISTANCE, tail)
    if dimensions:
        dimension = dimensions[-1]
    if distances:
        value = _millimeters(*distances[-1])
    if dimension not in {"宽度", "高度", "半径"} or not isinstance(value, (int, float)) or value <= 0:
        return None
    return f"{prefix}{dimension}改为{value:g}毫米"


def resolve_incremental_followup(
    message: str,
    previous: dict[str, Any] | None,
    available_instance_ids: list[int] | None = None,
) -> str | None:
    """Expand a short follow-up only from a successfully persisted instance edit."""
    previous = _legacy_previous_edit(previous)
    if not isinstance(previous, dict):
        return None
    single_target = previous.get("target_instance_id")
    batch_targets = previous.get("target_instance_ids")
    valid_batch = (
        isinstance(batch_targets, list)
        and len(batch_targets) > 1
        and all(isinstance(value, int) and value > 0 for value in batch_targets)
    )
    if not isinstance(single_target, int) and not valid_batch:
        return None
    text = message.strip().lower()
    repeat_previous = any(word in text for word in (
        "再来一次", "再做一次", "重复一次", "重复刚才", "按刚才再来",
    ))
    copied_reference = any(word in text for word in (
        "刚才复制的那个", "刚复制的那个", "刚才复制的图形", "刚复制的图形",
    ))
    remainder_reference = bool(re.search(
        r"(?:剩余|剩下的|其余|其他)\s*(?:\d+|[一二两三四五])?\s*个?图形",
        text,
    ))
    other_reference = remainder_reference or any(word in text for word in (
        "另一个图形", "另外一个图形", "另一个实例",
    ))
    batch_marker = any(word in text for word in (
        "整体", "一起", "同时", "全部", "分别", "各自中心",
        "组合中心", "整组中心", "作为整体",
    ))
    if not repeat_previous and not copied_reference and not other_reference and not any(word in text for word in (
        "它", "刚才那个", "刚才选中", "刚才选择", "刚才点选", "刚才选的",
        "之前选中", "之前选择", "刚刚选中", "刚刚选择",
        "同样距离", "相同距离", "同样角度", "相同角度",
    )):
        return None
    if any(word in text for word in ("小车", "底盘", "喷墨", "喷码", "任务")):
        return None
    target_ids = sorted(set(batch_targets)) if valid_batch else [single_target]
    if remainder_reference and batch_marker and isinstance(single_target, int):
        candidates = sorted({
            value for value in (available_instance_ids or [])
            if isinstance(value, int) and value > 0 and value != single_target
        })
        count = re.search(r"(?:剩余|剩下的|其余|其他)\s*(\d+|[一二两三四五])\s*个?", text)
        expected = None
        if count:
            expected = int(count.group(1)) if count.group(1).isdigit() else _ORDINALS[count.group(1)]
        if len(candidates) < 2 or (expected is not None and expected != len(candidates)):
            return None
        target_ids = candidates
    instance = target_ids[0]
    if copied_reference:
        if not isinstance(single_target, int):
            return None
        created = previous.get("created_instance_id")
        if previous.get("operation") != "duplicate" or not isinstance(created, int):
            return None
        instance = created
        target_ids = [instance]
    elif other_reference:
        if not isinstance(single_target, int):
            return None
        candidates = sorted({
            value for value in (available_instance_ids or [])
            if isinstance(value, int) and value > 0 and value != single_target
        })
        if len(candidates) != 1 and not (remainder_reference and batch_marker):
            return None
        if len(candidates) == 1:
            instance = candidates[0]
            target_ids = [instance]
    if len(target_ids) > 1 and not (repeat_previous or remainder_reference):
        return None
    prefix = _instance_prefix(target_ids)
    parameters = previous.get("parameters") or {}
    if repeat_previous:
        operation = previous.get("operation")
        if operation == "translate":
            dx, dy = parameters.get("dx_mm"), parameters.get("dy_mm")
            if not isinstance(dx, (int, float)) or not isinstance(dy, (int, float)):
                return None
            frame = previous.get("coordinate_frame", "drawing")
            return _translation_instruction(prefix, dx, dy, frame=frame)
        if operation == "rotate":
            angle = parameters.get("angle_degrees")
            if not isinstance(angle, (int, float)) or angle == 0:
                return None
            pivot = parameters.get("pivot")
            if len(target_ids) > 1 and pivot not in {
                "each_instance_center", "group_center",
            }:
                return None
            direction = "顺时针" if angle < 0 else "逆时针"
            return f"{prefix}{_rotation_prefix(pivot)}{direction}旋转{abs(angle):g}度"
        if operation == "resize":
            dimension = parameters.get("dimension")
            value = parameters.get("value_mm")
            if dimension not in {"宽度", "高度", "半径"} or not isinstance(value, (int, float)) or value <= 0:
                return None
            return f"{prefix}{dimension}改为{value:g}毫米"
        if operation == "scale":
            factor = parameters.get("factor")
            pivot = parameters.get("pivot")
            if (
                not isinstance(factor, (int, float))
                or not 0.05 <= factor <= 20
                or len(target_ids) > 1 and pivot not in {
                    "each_instance_center", "group_center",
                }
            ):
                return None
            return f"{prefix}{_scale_prefix(pivot)}{factor:g}倍"
        return None
    distance = re.search(r"(左|右|上|下|东|西|南|北)(?:侧|方)?\s*(?:平移|移动|挪动|挪|移)\s*" + _DISTANCE, text)
    if distance:
        return f"{prefix}向{distance.group(1)}移动{distance.group(2)}{distance.group(3)}"
    if any(word in text for word in ("同样距离", "相同距离")):
        if previous.get("operation") != "translate":
            return None
        dx, dy = parameters.get("dx_mm"), parameters.get("dy_mm")
        if not isinstance(dx, (int, float)) or not isinstance(dy, (int, float)):
            return None
        direction = re.search(r"向\s*(左|右|上|下|东|西|南|北)", text)
        frame = previous.get("coordinate_frame", "drawing")
        axis = direction.group(1) if direction else (
            "前" if frame == "vehicle" and dx > 0
            else "后" if frame == "vehicle" and dx < 0
            else "右" if dx > 0 else "左" if dx < 0
            else "上" if dy > 0 else "下"
        )
        length = abs(dx) if axis in {"左", "右", "东", "西"} else abs(dy)
        if length <= 0:
            return None
        return f"{prefix}向{axis}移动{length:g}毫米"
    rotation = re.search(r"(顺时针|逆时针)(?:方向)?\s*(?:再)?旋转\s*(\d+(?:\.\d+)?)\s*度", text)
    if rotation:
        pivot = _batch_rotation_pivot(text) if len(target_ids) > 1 else None
        if len(target_ids) > 1 and pivot is None:
            return None
        return f"{prefix}{_rotation_prefix(pivot)}{rotation.group(1)}旋转{rotation.group(2)}度"
    if any(word in text for word in ("同样角度", "相同角度")):
        angle = parameters.get("angle_degrees")
        if previous.get("operation") != "rotate" or not isinstance(angle, (int, float)) or angle == 0:
            return None
        pivot = parameters.get("pivot")
        if len(target_ids) > 1 and pivot not in {
            "each_instance_center", "group_center",
        }:
            return None
        direction = "顺时针" if angle < 0 else "逆时针"
        return f"{prefix}{_rotation_prefix(pivot)}{direction}旋转{abs(angle):g}度"
    factor = _scale_factor(text)
    if factor is not None:
        pivot = _batch_scale_pivot(text) if len(target_ids) > 1 else "instance_center"
        if len(target_ids) > 1 and pivot is None:
            return None
        return f"{prefix}{_scale_prefix(pivot)}{factor:g}倍"
    return None


def parse_incremental_edit(message: str) -> dict[str, Any] | None:
    text = message.lower()
    # The advanced UI prefixes edits with the selected candidate title. That
    # title may contain stale ordinals such as "第 2 个图形平移" and must not
    # override the target explicitly named after "修改目标".
    target_clause = re.search(r"修改目标\s*[:：]\s*(.+)$", text, re.DOTALL)
    if target_clause:
        text = target_clause.group(1).strip()
    if not any(token in text for token in (
        "图形", "图纸", "篮球场", "羽毛球场", "场地", "实例", "车位",
        "直线", "线段", "折线", "多段线", "圆", "圆形", "圆弧", "椭圆", "样条",
        "图层", "喷墨线", "喷涂线", "打印路径", "参考线", "标注", "辅助线",
        "中心圆", "中圈", "外框", "边框", "外围轮廓", "中线", "中心线", "图元",
    )):
        return None
    if any(token in text for token in ("小车", "底盘", "喷码", "启动任务")) or (
        "喷墨" in text and not any(word in text for word in ("喷墨线", "喷墨路径"))
    ):
        return None
    position_ordinal_match = re.search(
        r"(左侧|左边|右侧|右边|上方|上面|下方|下面|中间|中央|正中)"
        r"(?:的)?第\s*(\d+|[一二两三四五])\s*(?:个|片|座|组|块|条)?(?:图形|实例)",
        text,
    )
    position_ordinal_selector = None
    if position_ordinal_match:
        instance = None
        position_ordinal_selector = {
            "kind": "position_ordinal",
            "position": {
                "左侧": "left", "左边": "left", "右侧": "right", "右边": "right",
                "上方": "top", "上面": "top", "下方": "bottom", "下面": "bottom",
                "中间": "middle", "中央": "middle", "正中": "middle",
            }[position_ordinal_match.group(1)],
            "ordinal": (
                int(position_ordinal_match.group(2))
                if position_ordinal_match.group(2).isdigit()
                else _ORDINALS[position_ordinal_match.group(2)]
            ),
        }
    else:
        ordinal = re.search(r"第\s*(\d+|[一二两三四五])\s*(?:个|片|座|组|块|条)?", text)
        instance = (int(ordinal.group(1)) if ordinal.group(1).isdigit()
                    else _ORDINALS[ordinal.group(1)]) if ordinal else None
    whole_group = bool(re.search(
        r"(?:整个|全部|所有|整体)(?:的)?(?:图形|实例|图纸|方案|候选|"
        r"篮球场|羽毛球场|场地|停车位|车位)", text,
    ))
    # A named design object without a narrower selector denotes the visible
    # candidate itself (for example, "将篮球场扩大一倍").  Keep that meaning in
    # the parser so whole-candidate scaling uses the same CadEditCommand path
    # as every other edit instead of requiring a post-routing shortcut.
    whole_candidate = bool(re.search(
        r"(?:图纸|方案|候选|篮球场|羽毛球场|场地|停车位|车位)", text,
    ))
    numbers = _instance_numbers(text)
    multiple_instances = list(dict.fromkeys(numbers)) if len(set(numbers)) > 1 else None
    selector = _attribute_or_spatial_selector(text)
    if position_ordinal_selector is not None:
        selector = position_ordinal_selector
    explicit_geometry_ids = list(dict.fromkeys(
        int(value) for value in re.findall(
            r"(?:选择)?图元\s*(?:id)?\s*[:：#]?\s*(\d+)", text,
        )
    ))

    def selected(edit: dict[str, Any]) -> dict[str, Any]:
        if any(marker in text for marker in (
            "拆分共享边界", "拆开共享边界", "分离共享边界",
            "重建外框", "允许独立移动", "允许单独移动",
        )):
            edit["boundary_policy"] = "split_shared"
        if explicit_geometry_ids:
            edit.pop("instance", None)
            edit.pop("instances", None)
            edit.pop("selector", None)
            edit["geometry_ids"] = explicit_geometry_ids
        elif selector is not None:
            edit["selector"] = selector
            if selector.get("kind") in ("spatial", "position_ordinal"):
                edit.pop("instance", None)
                edit.pop("instances", None)
        if (
            (whole_group or (
                edit.get("operation") == "scale" and whole_candidate
            ))
            and not edit.get("instance")
            and not edit.get("instances")
            and not edit.get("selector")
            and not edit.get("geometry_ids")
        ):
            edit["instances"] = "all"
        return edit
    position_names = {
        "上方": "top", "上面": "top", "上边": "top", "顶部": "top",
        "下方": "bottom", "下面": "bottom", "下边": "bottom", "底部": "bottom",
        "左侧": "left", "左边": "left", "右侧": "right", "右边": "right",
    }
    named_position = next(
        (
            position_names[word]
            for word in position_names
            if re.search(
                rf"{re.escape(word)}(?:的)?(?:篮球场|羽毛球场|图形|实例|场地)",
                text,
            )
        ),
        None,
    )
    logical_position_match = re.search(
        r"(中间|中央|正中|左侧|左边|最左|右侧|右边|最右|上方|上面|最上|下方|下面|最下)"
        r"(?:的)?(?:(\d+|[一二两三四五六七八九十])\s*(?:个|间|座|组)?)?"
        r"(?:篮球场|羽毛球场|场地|停车位|车位|房间|图形|实例)",
        text,
    )
    logical_object_selector = None
    if logical_position_match:
        position = {
            "中间": "middle", "中央": "middle", "正中": "middle",
            "左侧": "left", "左边": "left", "最左": "left",
            "右侧": "right", "右边": "right", "最右": "right",
            "上方": "top", "上面": "top", "最上": "top",
            "下方": "bottom", "下面": "bottom", "最下": "bottom",
        }[logical_position_match.group(1)]
        matched_text = logical_position_match.group(0)
        raw_count = logical_position_match.group(2)
        count = (
            int(raw_count) if raw_count and raw_count.isdigit()
            else _ORDINALS.get(raw_count, 1)
            if raw_count else 1
        )
        object_type = (
            "basketball" if "篮球场" in matched_text
            else "badminton" if "羽毛球场" in matched_text
            else "parking_space" if "车位" in matched_text
            else "room" if "房间" in matched_text
            else None
        )
        logical_object_selector = {
            "position": position,
            **({"count": count} if count != 1 else {}),
            **({"object_type": object_type} if object_type else {}),
        }
    if re.search(r"(?:中心|中间)(?:的)?(?:圆|圆形|圆弧)", text):
        selector = {
            "kind": "geometry_within_target",
            "geometry_type": "circle",
            "spatial_role": "center",
        }
    semantic_features = {
        "中心圆": ("中心圆", "中圈"),
        "外框": ("外框", "边框", "外围轮廓", "外轮廓"),
        "中线": ("中线", "中心线"),
    }
    for semantic_name, aliases in semantic_features.items():
        if any(alias in text for alias in aliases):
            selector = {
                "kind": "semantic_within_target",
                "semantic": semantic_name,
            }
            break
    extreme = re.search(
        r"最\s*(上方|上面|上边|顶部|下方|下面|下边|底部|左侧|左边|右侧|右边)"
        r"(?:的)?\s*(?:(\d+|[一二两三四五])\s*个?)?"
        r"(?:篮球场|羽毛球场|场地|车位|图形|实例)",
        text,
    )
    extreme_selector = None
    if extreme:
        raw_count = extreme.group(2)
        extreme_selector = {
            "kind": "extreme",
            "position": position_names[extreme.group(1)],
            "count": (
                int(raw_count) if raw_count and raw_count.isdigit()
                else _ORDINALS.get(raw_count, 1)
            ),
        }
        selector = extreme_selector
    position_pattern = "(" + "|".join(position_names) + ")"
    delete_clause = re.search(
        r"(?:删除|删掉|去掉|移除)[^，。；;]{0,16}?" + position_pattern,
        text,
    )
    retain_clause = re.search(
        r"只保留[^，。；;]{0,16}?" + position_pattern,
        text,
    )
    has_delete = any(word in text for word in ("删除", "删掉", "去掉", "移除")) and '镜像' not in text
    generic_delete = bool(re.search(
        r"(?:删除|删掉|去掉|移除)\s*(?:其他|其余|剩余|剩下的)(?:图形|实例)?",
        text,
    ))
    delete_text, _, retain_text = text.partition("只保留")
    delete_numbers = _instance_numbers(delete_text)
    retain_numbers = _instance_numbers(retain_text)
    if (retain_clause or "只保留" in text) and (not has_delete or generic_delete):
        retain_targets = retain_numbers or numbers
        retain_multiple = retain_targets if len(retain_targets) > 1 else None
        retain_instance = retain_targets[0] if len(retain_targets) == 1 else None
        return selected({"operation": "retain", "instance": retain_instance,
                **({"instances": retain_multiple} if retain_multiple else {}),
                "position": position_names.get(retain_clause.group(1)) if retain_clause else None})
    if has_delete and (delete_clause or instance is not None):
        delete_targets = delete_numbers or numbers
        delete_multiple = delete_targets if len(delete_targets) > 1 else None
        delete_instance = delete_targets[0] if len(delete_targets) == 1 else None
        return selected({"operation": "delete", "instance": delete_instance,
                **({"instances": delete_multiple} if delete_multiple else {}),
                "position": position_names.get(delete_clause.group(1)) if delete_clause else None})
    if retain_clause or "只保留" in text:
        retain_targets = retain_numbers or numbers
        retain_multiple = retain_targets if len(retain_targets) > 1 else None
        retain_instance = retain_targets[0] if len(retain_targets) == 1 else None
        return selected({"operation": "retain", "instance": retain_instance,
                **({"instances": retain_multiple} if retain_multiple else {}),
                "position": position_names.get(retain_clause.group(1)) if retain_clause else None})
    if has_delete:
        return selected({"operation": "delete", "instance": instance, "position": None})
    if "旋转" in text:
        angle = re.search(r"(?:(顺时针|逆时针)(?:方向)?)?\s*旋转\s*(\d+(?:\.\d+)?)\s*度", text)
        if angle:
            pivot = (
                _batch_rotation_pivot(text)
                if multiple_instances or selector and selector.get("kind") == "spatial"
                else "instance_center"
            )
            return selected({"operation": "rotate", "instance": None if multiple_instances else instance,
                    **({"instances": multiple_instances} if multiple_instances else {}),
                    "angle_degrees": (float(angle.group(2)) * (-1 if angle.group(1) == "顺时针" else 1)
                                      if angle.group(1) else None),
                    "pivot": pivot})
    factor = _scale_factor(text)
    if factor is not None:
        pivot = (
            _batch_scale_pivot(text)
            if multiple_instances or selector and selector.get("kind") == "spatial"
            else "instance_center"
        )
        return selected({
            "operation": "scale",
            "instance": None if multiple_instances else instance,
            **({"instances": multiple_instances} if multiple_instances else {}),
            **({"position": named_position}
               if instance is None and not multiple_instances and named_position else {}),
            "factor": factor,
            "pivot": pivot,
        })
    if "复制" in text and not any(word in text for word in ('镜像','对称复制','阵列','复制成')):
        direction = re.search(r"(?:向|往|到)?(左|右|上|下)(?:侧|方|边)?\s*(?:移动|平移|复制)?\s*" + _DISTANCE, text)
        gap = re.search(r"(?:间距|相距)\s*(?:为|是)?\s*" + _DISTANCE, text)
        side = re.search(r"(?:向|往|到)(左|右|上|下)(?:侧|方)?", text)
        if direction or (gap and side):
            match = direction or gap
            axis = (direction or side).group(1)
            return selected({"operation": "duplicate", "instance": None if multiple_instances else instance,
                    **({"instances": multiple_instances} if multiple_instances else {}), "direction": axis,
                    "distance_mm": _millimeters(match.group(2 if direction else 1),
                                                   match.group(3 if direction else 2)),
                    "placement": "offset" if direction else "gap"})
        return selected({"operation": "duplicate", "instance": None if multiple_instances else instance,
                **({"instances": multiple_instances} if multiple_instances else {})})
    if "对齐" in text:
        alignment = re.search(r"(左|右|顶部|底部|上|下|水平居中|垂直居中)对齐", text)
        explicit_reference = re.search(
            r"第\s*(?:\d+|[一二两三四五])\s*(?:个|片|座|组|块)?[^，。]*?与\s*第",
            text,
        )
        parallel_pair = re.search(
            r"第\s*(?:\d+|[一二两三四五])\s*(?:个|片|座|组|块)?\s*(?:和|及)\s*第",
            text,
        )
        target = numbers[1] if len(numbers) > 1 and parallel_pair else instance
        reference = (numbers[0] if len(numbers) > 1 and parallel_pair
                     else numbers[1] if len(numbers) > 1 and explicit_reference else None)
        return selected({"operation": "align", "instance": target,
                "reference_instance": reference,
                "alignment": alignment.group(1) if alignment else None})
    # ---- parametric constraint (AutoCAD-style geometry constraints) ----
    constraint_pattern = r"(同心|同轴|圆心重合|相切|平行|垂直|一样大|同样大|相等|相同尺寸|相同大小|尺寸一致)"
    constraint_line = next((line for line in reversed(text.splitlines()) if re.search(constraint_pattern, line)), "")
    # Only explicit replacement markers discard earlier clauses within a turn.
    constraint_line = re.split(r"改为|改成|更正为|只要|只执行", constraint_line)[-1]
    constraint_clause = re.search(constraint_pattern, constraint_line)
    if constraint_clause:
        constraint_word = constraint_clause.group(1)
        if constraint_word == "垂直" and "垂直居中" in text:
            constraint_word = None
        if constraint_word is not None:
            parallel_pair = re.search(
                r"第\s*(?:\d+|[一二两三四五])\s*(?:个|片|座|组|块)?\s*(?:和|及|与|跟)\s*第\s*(?:\d+|[一二两三四五])",
                text,
            )
            explicit_reference = re.search(
                r"(?:与|和|跟|参照|参考)\s*第\s*(?:\d+|[一二两三四五])\s*(?:个|片|座|组|块)?",
                text,
            )
            reference = None
            if len(numbers) > 1:
                reference = numbers[1]
            elif parallel_pair or explicit_reference:
                raw = (parallel_pair or explicit_reference).group(0)
                second = re.search(r"第\s*(\d+|[一二两三四五])", raw[::-1])
                if second:
                    digits = second.group(1)[::-1]
                    reference = int(digits) if digits.isdigit() else _ORDINALS.get(digits)
            mapping = {
                "同心": "concentric", "同轴": "concentric", "圆心重合": "concentric",
                "相切": "tangent",
                "平行": "parallel",
                "垂直": "perpendicular",
                "一样大": "equal", "同样大": "equal", "相等": "equal",
                "相同尺寸": "equal", "相同大小": "equal", "尺寸一致": "equal",
            }
            matches = list(re.finditer(constraint_pattern, constraint_line))
            kinds = {mapping[m[1]] for m in matches}
            metrics = set(re.findall(r"宽度|高度|半径|面积|周长", constraint_line))
            negated = any(re.search(r"(?:不|不要|不用|取消)\s*$", constraint_line[:m.start()]) for m in matches)
            if len(kinds) > 1 or (kinds == {"equal"} and len(metrics) > 1) or negated:
                return selected({"operation": "constraint", "instance": instance, "constraint_conflict": True})
            constraint_type = mapping[constraint_word]
            metric_source = re.sub(r'(?:宽度|高度|半径)[^，。；;\n]{0,12}(?:保持|不变|原值)', '', text)
            dimensions = re.findall(r"宽度|高度|半径|面积|周长", metric_source)
            metric = dimensions[-1] if dimensions else None
            constraint_parameters = {"dimension": metric} if constraint_type == "equal" and metric else {}
            if reference is None:
                return selected({"operation": "constraint", "instance": instance,
                        **constraint_parameters,
                        "constraint_type": constraint_type})
            return selected({"operation": "constraint", "instance": instance,
                    **constraint_parameters,
                    "reference_instance": reference,
                    "constraint_type": constraint_type})
    # ---- mirror ----
    if any(word in text for word in ("镜像", "翻面", "翻转", "对称复制")):
        axis = None
        if any(word in text for word in ("左右", "水平", "横向", "横着")) or re.search(r'关于[^，。]{0,8}竖直|竖直[^，。]{0,4}轴',text):
            axis = "vertical"
        elif any(word in text for word in ("上下", "竖直", "竖向", "纵向", "垂直翻转")):
            axis = "horizontal"
        keep_source = not any(word in text for word in ("删除原", "不保留原", "移除原", "只保留镜像"))
        coordinate=None
        explicit=list(re.finditer(r'([xy])\s*[=＝]\s*([-+]?\d+(?:\.\d+)?)\s*(毫米|厘米|米|mm|cm|m)',text,re.I))
        if explicit:
            match=explicit[-1];axis='vertical' if match[1].lower()=='x' else 'horizontal'
            coordinate=float(match[2])*{'毫米':1,'厘米':10,'米':1000,'mm':1,'cm':10,'m':1000}[match[3].lower()]
        elif re.search(r'(?:关于|沿|以|镜像轴.*?)[\s]*[xyXY]轴',text):
            axis='horizontal' if re.search(r'[xX]轴',text) else 'vertical';coordinate=0.0
        return selected({"operation": "mirror", "instance": None if multiple_instances else instance,
                **({"instances": multiple_instances} if multiple_instances else {}),
                **({"mirror_axis": axis} if axis else {}),
                **({'mirror_coordinate_mm':coordinate} if coordinate is not None else {}), "keep_source": keep_source})
    # ---- offset (equal-distance parallel copy) ----
    offset_clause = re.search(
        r"(?:向内|向外|往内|往外|内侧|外侧)?偏移\s*(?:的)?\s*" + _DISTANCE,
        text,
    )
    if offset_clause:
        side = "inside" if any(word in text for word in ("向内", "往内", "内缩", "内侧")) else "outside"
        return selected({"operation": "offset", "instance": None if multiple_instances else instance,
                **({"instances": multiple_instances} if multiple_instances else {}),
                "offset_side": side,
                "distance_mm": _millimeters(offset_clause.group(1), offset_clause.group(2))})
    # ---- array ----
    if any(word in text for word in ("阵列", "排成", "排布", "复制成")):
        rows = re.search(r"(?:\d+|[一二两三四五六七八九十])\s*行", text)
        columns = re.search(r"(?:\d+|[一二两三四五六七八九十])\s*列", text)
        row_spacing = re.search(r"(?:行间距|行距|上下间距|行间隔)\s*(?:为|是)?\s*" + _DISTANCE, text)
        column_spacing = re.search(r"(?:列间距|列距|左右间距|列间隔)\s*(?:为|是)?\s*" + _DISTANCE, text)
        if any(word in text for word in ("环形", "圆周", "围绕", "绕中心")) or ('圆形阵列' in text and not (rows and columns)):
            count = re.search(r"(?:\d+|[一二两三四五六七八九十]+)\s*(?:个|份)?", text)
            polar_count = None
            if count:
                raw = count.group(0).rstrip("个份").strip()
                polar_count = int(raw) if raw.isdigit() else _ORDINALS.get(raw)
            angle = re.search(r"每\s*([\d.]+)\s*度", text)
            return selected({"operation": "array", "instance": None if multiple_instances else instance,
                    **({"instances": multiple_instances} if multiple_instances else {}),
                    "array_mode": "polar",
                    **({"count": polar_count} if polar_count else {}),
                    **({"angle_degrees": float(angle.group(1))} if angle else {})})
        if rows and columns:
            row_count = rows.group(0)[:-1].strip()
            column_count = columns.group(0)[:-1].strip()
            return selected({"operation": "array", "instance": None if multiple_instances else instance,
                    **({"instances": multiple_instances} if multiple_instances else {}),
                    "array_mode": "rectangular",
                    "rows": int(row_count) if row_count.isdigit() else _ORDINALS.get(row_count),
                    "columns": int(column_count) if column_count.isdigit() else _ORDINALS.get(column_count),
                    **({"row_spacing_mm": _millimeters(row_spacing.group(1), row_spacing.group(2))} if row_spacing else {}),
                    **({"column_spacing_mm": _millimeters(column_spacing.group(1), column_spacing.group(2))} if column_spacing else {})})
        return selected({"operation": "array", "instance": None if multiple_instances else instance,
                **({"instances": multiple_instances} if multiple_instances else {})})
    local_move = re.search(
        r"沿(?:图形)?(长边|短边)(?:(正方向|负方向|向前|向后))?"
        r"\s*(?:平移|移动|挪动|挪|移)\s*" + _DISTANCE,
        text,
    )
    if local_move:
        distance = _millimeters(local_move.group(3), local_move.group(4))
        sign = -1 if local_move.group(2) in {"负方向", "向后"} else 1
        return selected({
            "operation": "translate", "instance": instance,
            "coordinate_frame": "object_local",
            "local_axis": "long" if local_move.group(1) == "长边" else "short",
            "local_direction_explicit": local_move.group(2) is not None,
            "dx_mm": sign * distance, "dy_mm": 0,
        })
    compound_move = _compound_translation(text)
    if compound_move is not None:
        dx, dy, coordinate_frame = compound_move
        targets = multiple_instances
        return selected({
            "operation": "translate", "instance": None if targets else instance,
            **({"instances": targets} if targets else {}),
            **({"logical_object_selector": logical_object_selector}
               if instance is None and not targets and logical_object_selector else {}),
            **({"position": logical_object_selector["position"]}
               if instance is None and not targets and logical_object_selector
               and logical_object_selector.get("position") in {
                   "middle", "top", "bottom", "left", "right"
               } else {}),
            **({"object_type": logical_object_selector["object_type"]}
               if instance is None and not targets and logical_object_selector
               and logical_object_selector.get("object_type") else {}),
            **({"position": named_position}
               if instance is None and not targets and named_position
               and logical_object_selector is None else {}),
            "coordinate_frame": coordinate_frame,
            "dx_mm": dx, "dy_mm": dy,
        })
    # “上边的篮球场向前平移 2m” contains two different concepts:
    # the position phrase selects the upper instance, while “向前” is the
    # requested motion direction. Keep both instead of treating the sentence
    # as an unscoped natural-language description.
    move = re.search(
        r"(?:向|往)?(左|右|上|下|东|西|南|北|前|后)"
        r"(?:侧|方)?\s*(?:平移|移动|挪动|挪|移)\s*" + _DISTANCE,
        text,
    )
    if move:
        dx, dy = {
            "左": (-1, 0), "西": (-1, 0), "右": (1, 0), "东": (1, 0),
            "上": (0, 1), "北": (0, 1), "前": (1, 0),
            "下": (0, -1), "南": (0, -1), "后": (-1, 0),
        }[move.group(1)]
        distance = _millimeters(move.group(2), move.group(3))
        targets = multiple_instances
        return selected({
            "operation": "translate", "instance": None if targets else instance,
            **({"instances": targets} if targets else {}),
            **({"logical_object_selector": logical_object_selector}
               if instance is None and not targets and logical_object_selector else {}),
            **({"position": logical_object_selector["position"]}
               if instance is None and not targets and logical_object_selector
               and logical_object_selector.get("position") in {
                   "middle", "top", "bottom", "left", "right"
               } else {}),
            **({"object_type": logical_object_selector["object_type"]}
               if instance is None and not targets and logical_object_selector
               and logical_object_selector.get("object_type") else {}),
            **({"position": named_position}
               if instance is None and not targets and named_position
               and logical_object_selector is None else {}),
            "coordinate_frame": (
                "screen" if "屏幕" in text
                else "vehicle" if move.group(1) in {"前", "后"}
                else "drawing"
            ),
            "dx_mm": dx * distance, "dy_mm": dy * distance,
        })
    size = re.search(r"(宽度|高度|半径)\s*(?:改成|改为|调整为|调成|设为|设置为|变成|为)\s*" + _DISTANCE, text)
    if size:
        return selected({"operation": "resize", "instance": None if multiple_instances else instance,
                **({"instances": multiple_instances} if multiple_instances else {}),
                "dimension": size.group(1),
                "value_mm": _millimeters(size.group(2), size.group(3))})
    return None


def parse_constrained_addition(message: str) -> dict[str, Any] | None:
    """Parse one supported multi-object relation request without inventing coordinates."""
    text = re.sub(r"\s+", "", message.lower())
    if not any(word in text for word in ("添加", "增加", "放置", "加上", "放一个")):
        return None
    if not any(word in text for word in ("矩形", "长方形")):
        return None
    bilateral = (
        "上下" in text
        or (any(word in text for word in ("上方", "上面", "上边"))
            and any(word in text for word in ("下方", "下面", "下边")))
    )
    connected = any(word in text for word in ("相连", "连接", "贴着", "接触"))
    on_circle = "圆上" in text and any(
        word in text for word in ("两个顶点", "两顶点", "两个端点", "两端点")
    )
    if not (bilateral and connected and on_circle):
        return None
    automatic = any(word in text for word in (
        "大小合适", "尺寸合适", "自动", "自己判断", "由你判断", "你判断",
    ))
    return {
        "operation": "add_constrained",
        "object_type": "rectangle",
        "quantity": 2,
        "placements": ["above", "below"],
        "relations": ["adjacent_to_target", "outer_vertices_on_circle"],
        "dimension_mode": "maximize_area" if automatic else "maximize_area",
        "assumptions": [
            "上下矩形关于目标场地水平中轴对称",
            "矩形以内侧边与目标场地边界相接",
            "未指定尺寸时在约束范围内取最大面积解",
        ],
    }


def add_symmetric_rectangles_on_circle(
    geometries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Solve two attached rectangles whose outer corners lie on the largest circle."""
    circles = [
        item for item in geometries
        if item.get("type") == "circle"
        and isinstance(item.get("center"), dict)
        and isinstance(item.get("radius"), (int, float))
    ]
    borders = [
        item for item in geometries
        if item.get("type") == "polyline"
        and item.get("closed") is True
        and isinstance(item.get("vertices"), list)
    ]
    if not circles:
        return {"ok": False, "message": "当前候选没有可用于约束求解的外圆。"}
    if not borders:
        return {"ok": False, "message": "当前候选没有可识别的场地外边界。"}
    circle = max(circles, key=lambda item: float(item["radius"]))
    center = circle["center"]
    cx, cy = float(center["x"]), float(center["y"])
    radius = float(circle["radius"])

    def border_bounds(item: dict[str, Any]) -> tuple[float, float, float, float]:
        points = item.get("vertices") or []
        xs = [float(point["x"]) for point in points]
        ys = [float(point["y"]) for point in points]
        return min(xs), min(ys), max(xs), max(ys)

    containing = []
    for border in borders:
        bounds = border_bounds(border)
        if bounds[0] <= cx <= bounds[2] and bounds[1] <= cy <= bounds[3]:
            containing.append((border, bounds))
    if not containing:
        return {"ok": False, "message": "外圆中心不在任何已识别场地边界内。"}
    border, bounds = max(
        containing,
        key=lambda value: (value[1][2] - value[1][0]) * (value[1][3] - value[1][1]),
    )
    min_x, min_y, max_x, max_y = bounds
    half_width = min(cx - min_x, max_x - cx)
    top_offset, bottom_offset = max_y - cy, cy - min_y
    if min(half_width, top_offset, bottom_offset, radius) <= 1.0:
        return {"ok": False, "message": "场地或外圆尺寸无效，无法求解新增矩形。"}
    if abs(top_offset - bottom_offset) > 1.0:
        return {"ok": False, "message": "目标场地与外圆不同心，无法生成上下对称矩形。"}
    edge_offset = (top_offset + bottom_offset) / 2.0
    if edge_offset >= radius - 1.0:
        return {"ok": False, "message": "外圆没有留出可放置矩形的有效区域。"}

    outer_y = (edge_offset + math.sqrt(edge_offset * edge_offset + 8 * radius * radius)) / 4
    half_rectangle_width = math.sqrt(max(0.0, radius * radius - outer_y * outer_y))
    half_rectangle_width = min(half_rectangle_width, half_width)
    outer_y = math.sqrt(max(0.0, radius * radius - half_rectangle_width ** 2))
    rectangle_height = outer_y - edge_offset
    if half_rectangle_width <= 1.0 or rectangle_height <= 1.0:
        return {"ok": False, "message": "约束只能得到零面积矩形，请调整外圆或场地尺寸。"}

    used_ids = {
        int(item["id"]) for item in geometries
        if str(item.get("id", "")).isdigit()
    }
    next_id = max(used_ids, default=0) + 1
    # These are child objects of the same basketball-court assembly, not two
    # additional basketball instances. Stable logical object IDs distinguish
    # them without corrupting the parent template quantity contract.
    parent_instance = int(border.get("template_instance") or 1)
    left, right = cx - half_rectangle_width, cx + half_rectangle_width
    top_outer, bottom_outer = cy + outer_y, cy - outer_y
    additions = [
        {
            "id": next_id,
            "type": "polyline",
            "layer_id": 1,
            "vertices": [
                {"x": left, "y": max_y, "z": 0.0},
                {"x": left, "y": top_outer, "z": 0.0},
                {"x": right, "y": top_outer, "z": 0.0},
                {"x": right, "y": max_y, "z": 0.0},
            ],
            "closed": False,
            "template_instance": parent_instance,
            "template_type": "constrained_rectangle",
            "label": "上方约束矩形",
            "role": "printing",
            "path_semantic": "DRAW",
        },
        {
            "id": next_id + 1,
            "type": "polyline",
            "layer_id": 1,
            "vertices": [
                {"x": left, "y": min_y, "z": 0.0},
                {"x": left, "y": bottom_outer, "z": 0.0},
                {"x": right, "y": bottom_outer, "z": 0.0},
                {"x": right, "y": min_y, "z": 0.0},
            ],
            "closed": False,
            "template_instance": parent_instance,
            "template_type": "constrained_rectangle",
            "label": "下方约束矩形",
            "role": "printing",
            "path_semantic": "DRAW",
        },
    ]
    tolerance = max(1.0, radius * 1e-6)
    on_circle = all(
        abs(math.hypot(point["x"] - cx, point["y"] - cy) - radius) <= tolerance
        for addition in additions
        for point in addition["vertices"][1:3]
    )
    verified = (
        on_circle
        and abs(additions[0]["vertices"][0]["y"] - max_y) <= tolerance
        and abs(additions[1]["vertices"][0]["y"] - min_y) <= tolerance
    )
    return {
        "ok": verified,
        "message": "约束求解完成。" if verified else "新增矩形未通过圆周和相接关系验证。",
        "geometries": [*deepcopy(geometries), *additions] if verified else geometries,
        "added_geometries": additions if verified else [],
        "target_geometry_id": int(border["id"]),
        "circle_geometry_id": int(circle["id"]),
        "width_mm": round(half_rectangle_width * 2, 3),
        "height_mm": round(rectangle_height, 3),
        "validation": {
            "verified": verified,
            "added_rectangle_count": len(additions) if verified else 0,
            "outer_vertices_on_circle": on_circle,
            "attached_to_target": verified,
            "symmetric": verified,
            "source_geometry_unchanged": True,
            "tolerance_mm": tolerance,
        },
    }


def _split_shared_boundaries_for_edit(
    geometries: list[dict[str, Any]],
    selected_ids: set[int],
    shared_ids: set[int],
    *,
    operation: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[int]] | tuple[None, None, None]:
    """Clone only the selected side of declared shared boundaries."""
    if operation != "translate" or not shared_ids:
        return geometries, [item for item in geometries if int(item.get("id", -1)) in selected_ids], []
    used = {int(item["id"]) for item in geometries if str(item.get("id", "")).isdigit()}
    next_id = max(used, default=0) + 1
    output = deepcopy(geometries)
    selected: list[dict[str, Any]] = [
        item for item in output
        if isinstance(item.get("id"), int)
        and item["id"] in selected_ids
        and item["id"] not in shared_ids
    ]
    created: list[int] = []
    by_id = {
        int(item["id"]): item for item in output
        if str(item.get("id", "")).isdigit()
    }
    for shared_id in sorted(shared_ids):
        item = by_id.get(shared_id)
        if item is None or shared_id not in selected_ids:
            return None, None, None
        clone = deepcopy(item)
        while next_id in used:
            next_id += 1
        clone["id"] = next_id
        used.add(next_id)
        created.append(next_id)
        output.append(clone)
        selected.append(clone)
    if not created:
        return None, None, None
    return output, selected, created


def _points(geometry: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for key in ("start", "end", "center", "position"):
        if isinstance(geometry.get(key), dict):
            result.append(geometry[key])
    for key in ("vertices", "control_points"):
        if isinstance(geometry.get(key), list):
            result.extend(item for item in geometry[key] if isinstance(item, dict))
    return result


def _bounds(items: list[dict[str, Any]]) -> tuple[float, float, float, float] | None:
    xs: list[float] = []
    ys: list[float] = []
    for item in items:
        for point in _points(item):
            xs.append(float(point["x"]))
            ys.append(float(point["y"]))
        if item.get("type") in {"circle", "arc", "ellipse"}:
            center = item.get("center")
            if not isinstance(center, dict):
                continue
            if item.get("type") == "ellipse":
                axis = item.get("major_axis") or {}
                radius = math.hypot(float(axis.get("x", 0)), float(axis.get("y", 0))) * max(1, float(item.get("ratio", 1)))
            else:
                radius = float(item.get("radius", 0))
            xs.extend([float(center["x"]) - radius, float(center["x"]) + radius])
            ys.extend([float(center["y"]) - radius, float(center["y"]) + radius])
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def _translate(items: list[dict[str, Any]], dx: float, dy: float) -> None:
    for geometry in items:
        for point in _points(geometry):
            point["x"] = float(point["x"]) + dx
            point["y"] = float(point["y"]) + dy


def _rotate(items: list[dict[str, Any]], degrees: float, cx: float, cy: float) -> None:
    angle = math.radians(degrees)
    cosine, sine = math.cos(angle), math.sin(angle)
    for geometry in items:
        for point in _points(geometry):
            x, y = float(point["x"]) - cx, float(point["y"]) - cy
            point["x"] = round(cx + x * cosine - y * sine, 8)
            point["y"] = round(cy + x * sine + y * cosine, 8)
        if geometry.get("type") == "ellipse" and isinstance(geometry.get("major_axis"), dict):
            axis = geometry["major_axis"]
            x, y = float(axis["x"]), float(axis["y"])
            axis["x"] = round(x * cosine - y * sine, 8)
            axis["y"] = round(x * sine + y * cosine, 8)
        if geometry.get("type") == "arc":
            for key in ("start_angle", "end_angle", "startAngle", "endAngle"):
                if key in geometry:
                    geometry[key] = (float(geometry[key]) + degrees) % 360


def _scale(items: list[dict[str, Any]], factor: float, cx: float, cy: float) -> None:
    for geometry in items:
        for point in _points(geometry):
            point["x"] = round(cx + (float(point["x"]) - cx) * factor, 8)
            point["y"] = round(cy + (float(point["y"]) - cy) * factor, 8)
        geometry_type = str(geometry.get("type") or "").lower()
        if geometry_type == "ellipse" and isinstance(geometry.get("major_axis"), dict):
            axis = geometry["major_axis"]
            axis["x"] = round(float(axis["x"]) * factor, 8)
            axis["y"] = round(float(axis["y"]) * factor, 8)
        if geometry_type in {"circle", "arc"} and isinstance(
            geometry.get("radius"), (int, float)
        ):
            geometry["radius"] = round(float(geometry["radius"]) * factor, 8)
        if geometry_type == "text" and isinstance(
            geometry.get("height"), (int, float)
        ):
            geometry["height"] = round(float(geometry["height"]) * factor, 8)



def _geometry_signature(geometry: dict[str, Any]) -> tuple[Any, ...]:
    """Order-independent signature used to detect fully coincident copies."""
    points: list[tuple[float, float]] = []
    for key in ("start", "end", "center", "position"):
        point = geometry.get(key)
        if isinstance(point, dict):
            points.append((
                round(float(point.get("x", 0)), 6),
                round(float(point.get("y", 0)), 6),
            ))
    for key in ("vertices", "control_points"):
        for point in geometry.get(key) or []:
            if isinstance(point, dict):
                points.append((
                    round(float(point.get("x", 0)), 6),
                    round(float(point.get("y", 0)), 6),
                ))
    points.sort()
    radius = geometry.get("radius")
    return (
        geometry.get("type"),
        tuple(points),
        round(float(radius), 6) if isinstance(radius, (int, float)) else None,
        tuple((key,round(float(geometry[key]),6) if isinstance(geometry[key],(int,float)) else geometry[key])
              for key in ('closed','degree','start_angle','end_angle','ratio','rotation','content','height') if key in geometry),
        tuple(round(float((geometry.get('major_axis') or {}).get(key,0)),6) for key in ('x','y'))
              if geometry.get('type')=='ellipse' else (),
    )


def _mirror_transform(items: list[dict[str, Any]], axis: str, coordinate: float | None = None) -> None:
    """Flip every point across the selected items' own bounding-box axis."""
    bounds = _bounds(items)
    if bounds is None:
        return
    cx = (bounds[0] + bounds[2]) / 2
    cy = (bounds[1] + bounds[3]) / 2
    if coordinate is not None:
        if axis=='vertical':cx=coordinate
        else:cy=coordinate
    for geometry in items:
        for point in _points(geometry):
            if axis == "vertical":
                point["x"] = round(2 * cx - float(point["x"]), 8)
            else:
                point["y"] = round(2 * cy - float(point["y"]), 8)
        geometry_type = str(geometry.get("type") or "").lower()
        if geometry_type == "ellipse" and isinstance(geometry.get("major_axis"), dict):
            major_axis = geometry["major_axis"]
            if axis == "vertical":
                major_axis["x"] = round(-float(major_axis.get("x", 0)), 8)
            else:
                major_axis["y"] = round(-float(major_axis.get("y", 0)), 8)
            for start_key, end_key in (("start_angle", "end_angle"), ("startAngle", "endAngle")):
                if start_key in geometry and end_key in geometry:
                    start = -float(geometry[start_key])
                    end = -float(geometry[end_key])
                    geometry[start_key], geometry[end_key] = end % 360.0, start % 360.0
        elif geometry_type == "arc":
            for start_key, end_key in (("start_angle", "end_angle"), ("startAngle", "endAngle")):
                if start_key not in geometry or end_key not in geometry:
                    continue
                start = float(geometry[start_key])
                end = float(geometry[end_key])
                if axis == "vertical":
                    reflected_start, reflected_end = 180.0 - end, 180.0 - start
                else:
                    reflected_start, reflected_end = -end, -start
                geometry[start_key] = reflected_start % 360.0
                geometry[end_key] = reflected_end % 360.0
        elif geometry_type == "text":
            for key in ("rotation", "Rotation"):
                if key not in geometry:
                    continue
                angle = float(geometry[key])
                geometry[key] = ((180.0 - angle) if axis == "vertical" else -angle) % 360.0


def _line_direction(items: list[dict[str, Any]]) -> float | None:
    """Direction (radians) of the first non-degenerate line; fallback to long axis."""
    for item in items:
        if item.get("type") == "line":
            start, end = item.get("start"), item.get("end")
            if not isinstance(start, dict) or not isinstance(end, dict):
                continue
            dx = float(end["x"]) - float(start["x"])
            dy = float(end["y"]) - float(start["y"])
            if math.hypot(dx, dy) > 1e-6:
                return math.atan2(dy, dx)
    bounds = _bounds(items)
    if bounds is None:
        return None
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    return 0.0 if width >= height else math.pi / 2


def _is_closed_loop(items: list[dict[str, Any]]) -> bool:
    """True when the line items form one single closed outline (e.g. rectangle)."""
    lines = [item for item in items if item.get("type") == "line"]
    if len(lines) < 3:
        return False
    neighbors: dict[tuple[float, float], list[tuple[float, float]]] = {}
    for line in lines:
        start, end = line.get("start"), line.get("end")
        if not isinstance(start, dict) or not isinstance(end, dict):
            return False
        a = (round(float(start["x"]), 6), round(float(start["y"]), 6))
        b = (round(float(end["x"]), 6), round(float(end["y"]), 6))
        if a == b:
            return False
        neighbors.setdefault(a, []).append(b)
        neighbors.setdefault(b, []).append(a)
    if any(len(value) != 2 for value in neighbors.values()):
        return False
    origin = next(iter(neighbors))
    previous = origin
    current = neighbors[origin][0]
    steps = 1
    while current != origin:
        options = [point for point in neighbors[current] if point != previous]
        if len(options) != 1:
            return False
        previous, current = current, options[0]
        steps += 1
        if steps > len(lines):
            return False
    return steps == len(lines)


def _array_rectangular_copies(
    selected: list[dict[str, Any]],
    used_ids: set[str],
    next_id: int,
    new_instance: int,
    rows: int,
    columns: int,
    row_spacing_mm: float,
    column_spacing_mm: float,
) -> list[dict[str, Any]]:
    copies: list[dict[str, Any]] = []
    current = new_instance
    for row in range(rows):
        for column in range(columns):
            if row == 0 and column == 0:
                continue
            for item in selected:
                copied = deepcopy(item)
                while str(next_id) in used_ids:
                    next_id += 1
                copied["id"] = next_id
                used_ids.add(str(next_id))
                next_id += 1
                copied["template_instance"] = current
                _translate(
                    [copied],
                    column * column_spacing_mm,
                    row * row_spacing_mm,
                )
                copies.append(copied)
            current += 1
    return copies


def _array_polar_copies(
    selected: list[dict[str, Any]],
    used_ids: set[str],
    next_id: int,
    new_instance: int,
    count: int,
    angle_degrees: float,
    cx: float,
    cy: float,
) -> list[dict[str, Any]]:
    copies: list[dict[str, Any]] = []
    current = new_instance
    for step in range(1, count):
        for item in selected:
            copied = deepcopy(item)
            while str(next_id) in used_ids:
                next_id += 1
            copied["id"] = next_id
            used_ids.add(str(next_id))
            next_id += 1
            copied["template_instance"] = current
            _rotate([copied], angle_degrees * step, cx, cy)
            copies.append(copied)
        current += 1
    return copies


def _apply_constraint_edit(
    geometries: list[dict[str, Any]],
    edit: dict[str, Any],
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Deterministically apply one AutoCAD-style parametric constraint."""
    instance = edit.get("instance")
    reference = edit.get("reference_instance")
    constraint_type = edit.get("constraint_type")
    if instance is None or reference is None or instance == reference:
        return None, "参数化约束需要两个不同的图形实例。"
    if constraint_type not in {"parallel", "concentric", "tangent", "equal", "perpendicular"}:
        return None, "暂不支持的约束类型。"
    groups = {item["template_instance"] for item in geometries}
    if instance not in groups or reference not in groups:
        return None, "约束的目标实例或参考实例不存在。"
    selected = [item for item in geometries if item["template_instance"] == instance]
    reference_items = [item for item in geometries if item["template_instance"] == reference]
    source_bounds = _bounds(selected)
    target_bounds = _bounds(reference_items)
    if source_bounds is None or target_bounds is None:
        return None, "无法计算约束图形的边界。"
    scx = (source_bounds[0] + source_bounds[2]) / 2
    scy = (source_bounds[1] + source_bounds[3]) / 2
    tcx = (target_bounds[0] + target_bounds[2]) / 2
    tcy = (target_bounds[1] + target_bounds[3]) / 2
    if constraint_type == "concentric":
        _translate(selected, tcx - scx, tcy - scy)
        return geometries, None
    if constraint_type in {"parallel", "perpendicular"}:
        source_direction = _line_direction(selected)
        target_direction = _line_direction(reference_items)
        if source_direction is None or target_direction is None:
            return None, "平行或垂直约束需要两个可确定方向的图形。"
        delta = math.degrees(target_direction - source_direction)
        if constraint_type == "perpendicular":
            delta -= 90.0
        _rotate(selected, delta, scx, scy)
        return geometries, None
    if constraint_type == "equal":
        dimension = edit.get("dimension")
        if dimension not in {"半径", "宽度", "高度"}:
            return None, "请明确一样大是指宽度、高度、半径还是面积相等；不会默认按高度修改。"
        if dimension == "半径":
            source_circles = [
                item for item in selected if item.get("type") in {"circle", "arc"}
            ]
            target_circles = [
                item for item in reference_items if item.get("type") in {"circle", "arc"}
            ]
            if len(source_circles) != 1 or len(target_circles) != 1:
                return None, "相等约束（半径）需要目标与参考各一个圆形。"
            source_circles[0]["radius"] = float(target_circles[0]["radius"])
            return geometries, None
        axis = "x" if dimension == "宽度" else "y"
        source_coords = [
            float(point[axis]) for item in selected for point in _points(item)
        ]
        target_coords = [
            float(point[axis]) for item in reference_items for point in _points(item)
        ]
        if not source_coords or not target_coords:
            return None, "相等约束无法读取图形尺寸。"
        source_span = max(source_coords) - min(source_coords)
        target_span = max(target_coords) - min(target_coords)
        if source_span <= 1e-9 or target_span <= 1e-9:
            return None, "图形尺寸过小，无法执行相等约束。"
        center = (max(source_coords) + min(source_coords)) / 2
        factor = target_span / source_span
        for item in selected:
            for point in _points(item):
                point[axis] = center + (float(point[axis]) - center) * factor
        return geometries, None
    if constraint_type == "tangent":
        source_circles = [
            item for item in selected if item.get("type") in {"circle", "arc"}
        ]
        target_circles = [
            item for item in reference_items if item.get("type") in {"circle", "arc"}
        ]
        if len(source_circles) == 1 and len(target_circles) == 1:
            radius = float(source_circles[0]["radius"])
            reference_radius = float(target_circles[0]["radius"])
            dx, dy = tcx - scx, tcy - scy
            length = math.hypot(dx, dy)
            if length < 1e-9:
                return None, "两个圆心重合，无法确定相切方向。"
            distance = radius + reference_radius
            _translate(
                selected,
                (dx / length) * (length - distance),
                (dy / length) * (length - distance),
            )
            return geometries, None
        line = next(
            (item for item in reference_items if item.get("type") == "line"), None
        )
        if line is not None and len(source_circles) == 1:
            start, end = line.get("start"), line.get("end")
            if not isinstance(start, dict) or not isinstance(end, dict):
                return None, "参考线段坐标无效。"
            lx = float(end["x"]) - float(start["x"])
            ly = float(end["y"]) - float(start["y"])
            length = math.hypot(lx, ly)
            if length < 1e-9:
                return None, "参考线段长度无效。"
            nx, ny = -ly / length, lx / length
            signed_distance = (scx - float(start["x"])) * nx + (scy - float(start["y"])) * ny
            radius = float(source_circles[0]["radius"])
            _translate(selected, (radius - signed_distance) * nx, (radius - signed_distance) * ny)
            return geometries, None
        return None, "相切约束需要圆与圆或圆与直线组合。"
    return None, "暂不支持的约束类型。"

def _resize_selected_geometry(
    geometries: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    edit: dict[str, Any],
) -> tuple[list[dict[str, Any]] | None, str | None]:
    dimension = edit.get("dimension")
    try:
        target = float(edit["value_mm"])
    except (KeyError, TypeError, ValueError):
        return None, "请明确要调整到的尺寸。"
    if dimension not in {"宽度", "高度", "半径"} or target <= 0:
        return None, "尺寸必须大于零。"
    if dimension == "半径":
        circles = [item for item in selected if item.get("type") in {"circle", "arc"}]
        if len(selected) != 1 or len(circles) != 1:
            return None, "半径修改需要明确选择单个圆形。"
        circles[0]["radius"] = target
        return geometries, None
    if any(item.get("type") in {"circle", "arc", "ellipse"} for item in selected):
        return None, "圆弧或椭圆不能使用单轴尺寸修改，请改用等比例缩放。"
    axis = "x" if dimension == "宽度" else "y"
    coordinates = [float(point[axis]) for item in selected for point in _points(item)]
    if not coordinates or max(coordinates) <= min(coordinates):
        return None, "选中图元没有可修改的宽高。"
    center = (max(coordinates) + min(coordinates)) / 2
    factor = target / (max(coordinates) - min(coordinates))
    for item in selected:
        for point in _points(item):
            point[axis] = center + (float(point[axis]) - center) * factor
    return geometries, None


def _resolve_edit_selector(
    geometries: list[dict[str, Any]], edit: dict[str, Any]
) -> str | None:
    selector = edit.get("selector")
    if not isinstance(selector, dict):
        return None
    groups = {
        item.get("template_instance") for item in geometries
        if isinstance(item.get("template_instance"), int)
    }
    if selector.get("kind") == "position_ordinal":
        resolution = resolve_cad_target({"selector": selector}, geometries)
        if resolution.get("status") != "resolved":
            return resolution.get("question") or "当前空间选择器无效。"
        ids = sorted(set(resolution.get("instance_ids") or []))
        if len(ids) == 1:
            edit["instance"] = ids[0]
            edit.pop("instances", None)
        else:
            edit["instance"] = None
            edit["instances"] = ids
        edit.pop("selector", None)
        return None
    if selector.get("kind") == "geometry_within_target":
        instances = edit.get("instances")
        if not isinstance(instances, list):
            instance = edit.get("instance")
            instances = [instance] if isinstance(instance, int) else []
        if not instances or any(value not in groups for value in instances):
            return "请先明确中心图元属于哪个完整图形。"
        geometry_type = str(selector.get("geometry_type") or "").lower()
        selected = [
            item for item in geometries
            if item.get("template_instance") in instances
            and str(item.get("type") or "").lower() == geometry_type
        ]
        if not selected:
            return "目标图形中没有找到中心圆，请在右侧画布点选。"
        if selector.get("spatial_role") == "center" and len(selected) > 1:
            target_items = [
                item for item in geometries
                if item.get("template_instance") in instances
            ]
            target_bounds = _bounds(target_items)
            if target_bounds is None:
                return "无法计算目标图形中心，请在右侧画布点选中心圆。"
            center_x = (target_bounds[0] + target_bounds[2]) / 2
            center_y = (target_bounds[1] + target_bounds[3]) / 2
            ranked: list[tuple[float, dict[str, Any]]] = []
            for item in selected:
                center = item.get("center")
                if not isinstance(center, dict):
                    continue
                ranked.append((
                    math.hypot(
                        float(center.get("x", 0.0)) - center_x,
                        float(center.get("y", 0.0)) - center_y,
                    ),
                    item,
                ))
            ranked.sort(key=lambda value: value[0])
            if not ranked:
                return "目标圆缺少中心坐标，请在右侧画布点选。"
            if len(ranked) > 1 and abs(ranked[0][0] - ranked[1][0]) < 1e-6:
                return "目标图形内有多个同样靠近中心的圆，请在右侧画布点选一个。"
            selected = [ranked[0][1]]
        ids: list[int] = []
        for item in selected:
            if not str(item.get("id", "")).isdigit():
                return "中心圆缺少稳定图元 ID，请重新生成候选方案。"
            ids.append(int(item["id"]))
        edit.pop("instance", None)
        edit.pop("instances", None)
        edit["geometry_ids"] = sorted(set(ids))
        return None
    if selector.get("kind") == "semantic_within_target":
        instances = edit.get("instances")
        if not isinstance(instances, list):
            instance = edit.get("instance")
            instances = [instance] if isinstance(instance, int) else []
        if not instances or any(value not in groups for value in instances):
            return "请先明确局部图元属于哪个完整图形。"
        semantic = str(selector.get("semantic") or "").strip()
        catalog = build_geometry_catalog(geometries)
        matches = [
            item for item in catalog.get("elements") or []
            if item.get("instance_id") in instances
            and str(item.get("semantic") or "") == semantic
        ]
        if not matches:
            return f"目标图形中没有找到{semantic}，请在右侧画布点选。"
        counts = {
            instance_id: sum(item.get("instance_id") == instance_id for item in matches)
            for instance_id in instances
        }
        missing_instances = sorted(
            instance_id for instance_id, count in counts.items() if count == 0
        )
        if missing_instances:
            return (
                f"实例 {missing_instances} 中没有找到{semantic}，"
                "请逐个在右侧画布点选。"
            )
        ambiguous_instances = sorted(
            instance_id for instance_id, count in counts.items() if count > 1
        )
        if ambiguous_instances:
            edit["_semantic_candidates"] = [
                {
                    "geometry_id": item.get("geometry_id"),
                    "instance_id": item.get("instance_id"),
                    "semantic": item.get("semantic"),
                    "center_m": item.get("center_m"),
                    "bounds_m": item.get("bounds_m"),
                }
                for item in matches
                if item.get("instance_id") in ambiguous_instances
            ]
            return (
                f"实例 {ambiguous_instances} 中存在多个同名{semantic}，"
                "请在右侧画布点选一个。"
            )
        ids = [item.get("geometry_id") for item in matches]
        if any(not isinstance(value, int) or value <= 0 for value in ids):
            return f"匹配到的{semantic}缺少稳定图元 ID，请重新生成候选方案。"
        edit.pop("instance", None)
        edit.pop("instances", None)
        edit["geometry_ids"] = sorted(set(ids))
        return None
    if selector.get("kind") == "attribute":
        attribute = selector.get("attribute")
        selected: list[dict[str, Any]] = []
        if attribute == "layer_id":
            selected = [
                item for item in geometries
                if item.get("layer_id") == selector.get("value")
            ]
        elif attribute == "same_layer_as_instance":
            reference = selector.get("reference_instance")
            if reference not in groups:
                return f"当前图纸没有第 {reference} 个图形，无法匹配同图层图元。"
            layers = {
                item.get("layer_id") for item in geometries
                if item.get("template_instance") == reference
                and item.get("layer_id") is not None
            }
            if not layers:
                return f"第 {reference} 个图形没有可识别的图层属性。"
            selected = [item for item in geometries if item.get("layer_id") in layers]
        elif attribute == "geometry_type":
            selected = [
                item for item in geometries
                if str(item.get("type") or "").lower() == selector.get("value")
            ]
        elif attribute == "semantic":
            value = selector.get("value")
            semantic = {
                "printing": "DRAW", "reference": "TRAVEL",
                "annotation": "ANNOTATION", "ignored": "IGNORE",
                "auxiliary": "AUXILIARY",
            }.get(value)
            selected = [
                item for item in geometries
                if str(item.get("role") or "").lower() == value
                or str(item.get("path_semantic") or "").upper() == semantic
            ]
        else:
            return "当前属性选择器无效。"
        if not selected:
            return "当前候选中没有符合该属性条件的图元。"
        ids: list[int] = []
        for item in selected:
            if not str(item.get("id", "")).isdigit():
                return "匹配到的图元缺少稳定 ID，不能执行批量修改。"
            ids.append(int(item["id"]))
        edit.pop("instance", None)
        edit.pop("instances", None)
        edit["geometry_ids"] = sorted(set(ids))
        return None
    if selector.get("kind") != "spatial":
        return "当前空间选择器无效。"
    reference = selector.get("reference_instance")
    if reference not in groups:
        return f"当前图纸没有第 {reference} 个图形，无法计算空间关系。"
    bounds_by_group = {
        group: _bounds([
            item for item in geometries if item.get("template_instance") == group
        ])
        for group in groups
    }
    reference_bounds = bounds_by_group.get(reference)
    if reference_bounds is None:
        return f"无法计算第 {reference} 个图形的边界。"
    relation = selector.get("relation")
    candidates = [group for group in groups if group != reference]
    if relation == "left_of":
        matched = [group for group in candidates if bounds_by_group[group]
                   and bounds_by_group[group][2] <= reference_bounds[0]]
    elif relation == "right_of":
        matched = [group for group in candidates if bounds_by_group[group]
                   and bounds_by_group[group][0] >= reference_bounds[2]]
    elif relation == "above":
        matched = [group for group in candidates if bounds_by_group[group]
                   and bounds_by_group[group][1] >= reference_bounds[3]]
    elif relation == "below":
        matched = [group for group in candidates if bounds_by_group[group]
                   and bounds_by_group[group][3] <= reference_bounds[1]]
    elif relation == "nearest":
        distances = []
        for group in candidates:
            bounds = bounds_by_group[group]
            if bounds is None:
                continue
            dx = max(0, reference_bounds[0] - bounds[2], bounds[0] - reference_bounds[2])
            dy = max(0, reference_bounds[1] - bounds[3], bounds[1] - reference_bounds[3])
            distances.append((math.hypot(dx, dy), group))
        distances.sort()
        if not distances:
            matched = []
        elif len(distances) > 1 and abs(distances[0][0] - distances[1][0]) < 1e-6:
            return "存在多个距离相同的最近图形，请点击目标或使用实例编号。"
        else:
            matched = [distances[0][1]]
    else:
        return "当前空间关系不受支持。"
    count = selector.get("count")
    if count is not None:
        if not isinstance(count, int) or count < 1 or len(matched) < count:
            return "符合该空间关系的图形数量不足，请明确目标。"
        boundary_index = {"left_of": (0, 2), "right_of": (2, 0),
                          "above": (3, 1), "below": (1, 3)}.get(relation)
        if boundary_index is None:
            return "此空间关系不支持指定图形数量。"
        reference_edge, candidate_edge = boundary_index
        ranked = sorted(
            (abs(bounds_by_group[group][candidate_edge]
                 - reference_bounds[reference_edge]), group)
            for group in matched
        )
        if count < len(ranked) and abs(ranked[count - 1][0] - ranked[count][0]) < 1e-6:
            return "多个图形距离相同，请点击目标或使用实例编号。"
        matched = [group for _, group in ranked[:count]]
    matched = sorted(matched)
    if not matched:
        return "当前候选中没有符合该空间关系的图形。"
    edit.pop("geometry_ids", None)
    if len(matched) == 1:
        edit["instance"] = matched[0]
        edit.pop("instances", None)
    else:
        edit["instance"] = None
        edit["instances"] = matched
    return None


def edit_candidate_geometries(
    source: list[dict[str, Any]], edit: dict[str, Any]
) -> tuple[list[dict[str, Any]] | None, str | None]:
    geometries = deepcopy(source)
    if edit.get("constraint_conflict"):
        return None, "本轮包含多个约束或否定要求，请明确本次执行哪一种约束。"
    if not geometries:
        return None, "当前候选没有可修改的图元。"
    has_unconfirmed_groups = any(
        not isinstance(item.get("template_instance"), int) or item["template_instance"] < 1
        for item in geometries
    )
    if has_unconfirmed_groups and not edit.get("geometry_ids"):
        return None, "此候选缺少已确认的实例分组，不能按整组修改。请先确认图纸实例分组。"
    groups = {
        item["template_instance"] for item in geometries
        if isinstance(item.get("template_instance"), int)
        and item["template_instance"] > 0
    }
    coordinate_frame = edit.get("coordinate_frame", "drawing")
    if coordinate_frame == "screen":
        return None, "屏幕方向只用于界面操作，不能直接作为图纸施工方向。请改用图纸上、下、左、右或东、西、南、北。"
    if coordinate_frame == "object_local" and not edit.get("local_direction_explicit"):
        return None, "沿长边或短边移动必须明确正方向或负方向，请补充方向。"
    if coordinate_frame == "object_local" and edit.get("local_axis_angle_degrees") is None:
        return None, "当前图形没有已确认的局部坐标轴，无法判断长边或短边方向。请在右侧画布点选目标并明确正负方向。"
    if edit.get("operation") == "rearrange_layout":
        if edit.get("layout_strategy") == "move_secondary":
            return space_two_instances(
                geometries,
                float(edit.get("gap_mm") or 0.0),
                str(edit.get("arrangement") or ""),
            )
        return rearrange_two_template_instances(
            geometries,
            spacing_mm=float(edit.get("gap_mm") or 0.0),
            arrangement=str(edit.get("arrangement") or ""),
            desired_quantity=int(edit.get("count") or 0),
            peer_placement=(
                str(edit["peer_placement"])
                if edit.get("peer_placement") in {"above", "below", "left", "right"}
                else None
            ),
        )
    if not (
        isinstance(edit.get("selector"), dict)
        and edit["selector"].get("kind") in {"attribute", "spatial"}
    ):
        resolution = resolve_cad_target(edit, geometries)
        if resolution.get("status") != "resolved":
            return None, str(resolution.get("question") or "不能确定本次修改目标。")
        edit["target_resolution"] = deepcopy(resolution)
        bind_resolved_target(edit, resolution)
    selector_error = _resolve_edit_selector(geometries, edit)
    if selector_error is not None:
        return None, selector_error
    geometry_ids = edit.get("geometry_ids")
    if geometry_ids is not None:
        if (
            not isinstance(geometry_ids, list)
            or not geometry_ids
            or len(geometry_ids) != len(set(geometry_ids))
            or any(not isinstance(value, int) for value in geometry_ids)
        ):
            return None, "选中的图元 ID 无效，请重新选择线段。"
        by_id = {
            int(item.get("id")): item for item in geometries
            if str(item.get("id", "")).isdigit()
        }
        if any(value not in by_id for value in geometry_ids):
            return None, "选中的图元已不在当前候选中，请重新载入图纸。"
        operation = edit.get("operation")
        selected_ids = set(geometry_ids)
        if edit.get("boundary_policy") == "split_shared":
            raw_shared = edit.get("shared_geometry_ids") or edit.get("_shared_boundary_ids") or []
            shared_ids = {value for value in raw_shared if isinstance(value, int)}
            geometries, selected, created_ids = _split_shared_boundaries_for_edit(
                geometries, selected_ids, shared_ids, operation=operation,
            )
            if geometries is None or selected is None:
                return None, "未找到可拆分的共享边界，请重新选择相邻对象。"
            edit["created_geometry_ids"] = created_ids
        else:
            selected = [by_id[value] for value in geometry_ids]
        if operation == "add_constrained":
            solved = add_symmetric_rectangles_on_circle(source)
            if solved.get("ok") is not True:
                return None, str(solved.get("message") or "约束图形求解失败。")
            created_ids = sorted(
                int(item["id"]) for item in solved.get("added_geometries") or []
                if str(item.get("id", "")).isdigit()
            )
            declared_ids = sorted(
                int(value) for value in edit.get("created_geometry_ids") or []
                if str(value).isdigit()
            )
            width_matches = math.isclose(
                float(solved.get("width_mm") or 0.0),
                float(edit.get("solved_width_mm") or 0.0),
                abs_tol=1e-3,
            )
            height_matches = math.isclose(
                float(solved.get("height_mm") or 0.0),
                float(edit.get("solved_height_mm") or 0.0),
                abs_tol=1e-3,
            )
            if (
                edit.get("constraint_kind") != "symmetric_rectangles_on_circle"
                or created_ids != declared_ids
                or int(solved.get("target_geometry_id") or 0) not in selected_ids
                or not width_matches
                or not height_matches
            ):
                return None, "约束求解结果与修改协议不一致，已停止保存。"
            return list(solved["geometries"]), None
        if operation == "add_template":
            from .agent_skills import drawing_template_geometries

            source_template = str(edit.get("source_template") or "")
            target_template = str(edit.get("target_template") or "")
            positions = list(edit.get("relative_positions") or [])
            dimensions = {
                "basketball": (28.0, 15.0),
                "badminton": (13.4, 6.1),
                "parking": (2.5, 5.0),
            }
            if source_template not in dimensions or target_template not in dimensions:
                return None, "相对新增协议包含不支持的模板类型。"
            if not positions or any(
                value not in {"above", "below", "left", "right"}
                for value in positions
            ):
                return None, "相对新增协议缺少有效位置。"
            source_items = [
                item for item in geometries
                if item.get("template_type") == source_template
            ] or selected
            bounds = _bounds(source_items)
            if bounds is None:
                return None, "无法确定相对新增的源图形边界。"
            min_x, min_y, max_x, max_y = bounds
            center_x, center_y = (min_x + max_x) / 2, (min_y + max_y) / 2
            source_width, source_height = max_x - min_x, max_y - min_y
            target_width_m, target_height_m = dimensions[target_template]
            target_width = target_width_m * 1000.0
            target_height = target_height_m * 1000.0
            gap = float(edit.get("gap_mm") or 0.0)
            next_instance = max(
                (
                    int(item.get("template_instance") or 0)
                    for item in geometries
                    if str(item.get("template_instance", "")).isdigit()
                ),
                default=0,
            )
            next_id = max(
                (
                    int(item.get("id") or 0) for item in geometries
                    if str(item.get("id", "")).isdigit()
                ),
                default=0,
            )
            additions: list[dict[str, Any]] = []
            offsets = {
                "above": (0.0, source_height / 2 + target_height / 2 + gap),
                "below": (0.0, -(source_height / 2 + target_height / 2 + gap)),
                "left": (-(source_width / 2 + target_width / 2 + gap), 0.0),
                "right": (source_width / 2 + target_width / 2 + gap, 0.0),
            }
            for position in positions:
                base = drawing_template_geometries({
                    "template": target_template,
                    "width_m": target_width_m,
                    "height_m": target_height_m,
                    "quantity": 1,
                })
                dx_offset, dy_offset = offsets[position]
                next_instance += 1
                for raw in base:
                    item = deepcopy(raw)
                    next_id += 1
                    item["id"] = next_id
                    item["template_instance"] = next_instance
                    item["template_type"] = target_template
                    for key in ("start", "end", "center", "position"):
                        point = item.get(key)
                        if isinstance(point, dict):
                            point["x"] = float(point.get("x", 0)) + center_x + dx_offset
                            point["y"] = float(point.get("y", 0)) + center_y + dy_offset
                    for key in ("vertices", "control_points"):
                        for point in item.get(key) or []:
                            if isinstance(point, dict):
                                point["x"] = float(point.get("x", 0)) + center_x + dx_offset
                                point["y"] = float(point.get("y", 0)) + center_y + dy_offset
                    additions.append(item)
            actual_ids = [int(item["id"]) for item in additions]
            declared_ids = [int(value) for value in edit.get("created_geometry_ids") or []]
            if actual_ids != declared_ids:
                return None, "相对新增结果与命令声明的图元 ID 不一致。"
            return geometries + additions, None
        if operation == "delete":
            selected_keys = {str(value) for value in geometry_ids}
            remaining = [
                item for item in geometries
                if str(item.get("id")) not in selected_keys
            ]
            if not remaining:
                return None, "图纸至少需要保留一个图元，不能删除全部内容。"
            return remaining, None
        if operation == "retain":
            return selected, None
        if operation in {'duplicate','mirror','offset','array'}:
            from .cad_selected_operations import apply_selected_operation
            return apply_selected_operation(geometries,selected,edit)
        if operation in {"align"}:
            return None, "对齐和复制需要选择整个图形，不能只选择单条线段。"
        if operation == "translate":
            try:
                dx, dy = float(edit["dx_mm"]), float(edit["dy_mm"])
            except (KeyError, TypeError, ValueError):
                return None, "请明确平移方向和距离。"
            if dx == 0 and dy == 0:
                return geometries, None  # Preserve exact numeric representation for no-op relation checks.
            _translate(selected, dx, dy)
            return geometries, None
        if operation == "rotate":
            try:
                degrees = float(edit["angle_degrees"])
            except (KeyError, TypeError, ValueError):
                return None, "请明确顺时针或逆时针旋转，以及旋转角度。"
            bounds = _bounds(selected)
            if bounds is None or not math.isfinite(degrees):
                return None, "无法计算选中线段的旋转中心或角度。"
            _rotate(selected, degrees, (bounds[0] + bounds[2]) / 2,
                    (bounds[1] + bounds[3]) / 2)
            return geometries, None
        if operation == "scale":
            try:
                factor = float(edit["factor"])
            except (KeyError, TypeError, ValueError):
                return None, "请明确等比例缩放的倍数。"
            bounds = _bounds(selected)
            if bounds is None or not math.isfinite(factor) or not 0.05 <= factor <= 20:
                return None, "无法计算选中线段的缩放中心，或缩放倍数不在 0.05 到 20 之间。"
            _scale(selected, factor, (bounds[0] + bounds[2]) / 2,
                   (bounds[1] + bounds[3]) / 2)
            return geometries, None
        if operation == "resize":
            return _resize_selected_geometry(geometries, selected, edit)
        return None, "暂不支持对当前选中的对象执行此修改。"
    instances = edit.get("instances")
    if instances is not None:
        if (
            not isinstance(instances, list)
            or len(instances) < 2
            or len(instances) != len(set(instances))
            or any(not isinstance(value, int) or value not in groups for value in instances)
        ):
            return None, "批量修改的所有目标实例必须真实存在且不能重复。"
        selected = [
            item for item in geometries if item["template_instance"] in instances
        ]
        operation = edit.get("operation")
        selected_groups = set(instances)
        if operation in {"delete", "retain"}:
            remaining_groups = groups - selected_groups if operation == "delete" else selected_groups
            if not remaining_groups:
                return None, "图纸至少需要保留一个实例，不能删除全部图形。"
            if remaining_groups == groups:
                return None, "所选实例没有改变图纸内容。"
            if operation == "delete":
                return [
                    item for item in geometries
                    if item["template_instance"] not in selected_groups
                ], None
            return selected, None
        if operation == "translate":
            _translate(selected, edit["dx_mm"], edit["dy_mm"])
            return geometries, None
        if operation == "rotate":
            try:
                degrees = float(edit["angle_degrees"])
            except (KeyError, TypeError, ValueError):
                return None, "请明确顺时针或逆时针旋转，以及旋转角度。"
            pivot = edit.get("pivot")
            if not math.isfinite(degrees) or pivot not in {
                "each_instance_center", "group_center",
            }:
                return None, "批量旋转必须明确选择各自中心或组合中心。"
            if pivot == "each_instance_center":
                for value in instances:
                    items = [
                        item for item in geometries
                        if item["template_instance"] == value
                    ]
                    bounds = _bounds(items)
                    if bounds is None:
                        return None, f"无法计算第 {value} 个图形的旋转中心。"
                    _rotate(
                        items, degrees,
                        (bounds[0] + bounds[2]) / 2,
                        (bounds[1] + bounds[3]) / 2,
                    )
            else:
                bounds = _bounds(selected)
                if bounds is None:
                    return None, "无法计算所选图形的组合中心。"
                _rotate(
                    selected, degrees,
                    (bounds[0] + bounds[2]) / 2,
                    (bounds[1] + bounds[3]) / 2,
                )
            return geometries, None
        if operation == "scale":
            try:
                factor = float(edit["factor"])
            except (KeyError, TypeError, ValueError):
                return None, "请明确等比例缩放的倍数。"
            pivot = edit.get("pivot")
            if not math.isfinite(factor) or not 0.05 <= factor <= 20:
                return None, "缩放倍数必须在 0.05 到 20 之间。"
            if pivot not in {"each_instance_center", "group_center"}:
                return None, "批量缩放必须明确选择各自中心或组合中心。"
            if pivot == "each_instance_center":
                for value in instances:
                    items = [
                        item for item in geometries
                        if item["template_instance"] == value
                    ]
                    bounds = _bounds(items)
                    if bounds is None:
                        return None, f"无法计算第 {value} 个图形的缩放中心。"
                    _scale(
                        items, factor,
                        (bounds[0] + bounds[2]) / 2,
                        (bounds[1] + bounds[3]) / 2,
                    )
            else:
                bounds = _bounds(selected)
                if bounds is None:
                    return None, "无法计算所选图形的组合中心。"
                _scale(
                    selected, factor,
                    (bounds[0] + bounds[2]) / 2,
                    (bounds[1] + bounds[3]) / 2,
                )
            return geometries, None
        return None, "批量修改目前仅支持平移、明确旋转中心的旋转和明确中心的等比例缩放。"
    instance = edit.get("instance")
    if instance is None:
        if len(groups) != 1:
            return None, "请明确要修改第几个图形；不会猜测目标实例。"
        instance = next(iter(groups))
    if instance not in groups:
        return None, f"当前图纸没有第 {instance} 个图形。"
    selected = [item for item in geometries if item["template_instance"] == instance]
    if edit["operation"] in {"delete", "retain"}:
        if len(groups) <= 1:
            return None, "图纸只剩一个实例，不能继续删除。"
        if edit["operation"] == "delete":
            return [item for item in geometries if item["template_instance"] != instance], None
        return selected, None
    if edit["operation"] == "rotate":
        bounds = _bounds(selected)
        try:
            degrees = float(edit["angle_degrees"])
        except (KeyError, TypeError, ValueError):
            return None, "请明确顺时针或逆时针旋转，以及旋转角度。"
        if bounds is None or not math.isfinite(degrees):
            return None, "无法计算图形旋转中心或角度。"
        _rotate(selected, degrees, (bounds[0] + bounds[2]) / 2,
                (bounds[1] + bounds[3]) / 2)
        return geometries, None
    if edit["operation"] == "scale":
        bounds = _bounds(selected)
        try:
            factor = float(edit["factor"])
        except (KeyError, TypeError, ValueError):
            return None, "请明确等比例缩放的倍数。"
        if bounds is None or not math.isfinite(factor) or not 0.05 <= factor <= 20:
            return None, "无法计算缩放中心，或缩放倍数不在 0.05 到 20 之间。"
        _scale(
            selected, factor,
            (bounds[0] + bounds[2]) / 2,
            (bounds[1] + bounds[3]) / 2,
        )
        return geometries, None
    if edit["operation"] == "duplicate":
        direction = edit.get("direction")
        distance = edit.get("distance_mm")
        if direction not in {"左", "右", "上", "下"} or not isinstance(distance, (int, float)) or distance <= 0:
            return None, "请指定复制到哪个方向，以及正的移动距离或实例间距。"
        bounds = _bounds(selected)
        if bounds is None or len(groups) >= 50:
            return None, "无法计算复制位置或已达到实例数量上限。"
        axis_size = (bounds[2] - bounds[0]) if direction in {"左", "右"} else (bounds[3] - bounds[1])
        offset = distance + (axis_size if edit.get("placement") == "gap" else 0)
        dx = offset * (-1 if direction == "左" else 1) if direction in {"左", "右"} else 0
        dy = offset * (-1 if direction == "下" else 1) if direction in {"上", "下"} else 0
        if offset < axis_size - 1e-6:
            return None, "复制位置与原图形重叠，请增大位移或指定间距。"
        new_instance = max(groups) + 1
        used_ids = {str(item.get("id")) for item in geometries}
        next_id = max((int(value) for value in used_ids if value.isdigit()), default=0) + 1
        for item in selected:
            copied = deepcopy(item)
            while str(next_id) in used_ids:
                next_id += 1
            copied["id"] = next_id
            used_ids.add(str(next_id))
            next_id += 1
            copied["template_instance"] = new_instance
            _translate([copied], dx, dy)
            geometries.append(copied)
        edit["new_instance"] = new_instance
        return geometries, None
    if edit["operation"] == "align":
        reference = edit.get("reference_instance")
        alignment = edit.get("alignment")
        if reference not in groups or reference == instance or alignment not in {
            "左", "右", "顶部", "底部", "上", "下", "水平居中", "垂直居中"
        }:
            return None, "请明确两个不同的图形实例及左、右、顶部、底部或轴向居中对齐方式。"
        source_bounds = _bounds(selected)
        target_bounds = _bounds([item for item in geometries if item["template_instance"] == reference])
        if source_bounds is None or target_bounds is None:
            return None, "无法计算图形边界，不能对齐。"
        index = {"左": 0, "右": 2, "顶部": 3, "上": 3, "底部": 1, "下": 1}
        if alignment in index:
            key = index[alignment]
            delta = target_bounds[key] - source_bounds[key]
            dx, dy = (delta, 0) if key in {0, 2} else (0, delta)
        elif alignment == "水平居中":
            dx, dy = (target_bounds[0] + target_bounds[2] - source_bounds[0] - source_bounds[2]) / 2, 0
        else:
            dx, dy = 0, (target_bounds[1] + target_bounds[3] - source_bounds[1] - source_bounds[3]) / 2
        _translate(selected, dx, dy)
        return geometries, None
    if edit["operation"] == "translate":
        _translate(selected, edit["dx_mm"], edit["dy_mm"])
        return geometries, None
    if edit["operation"] == "mirror":
        axis = edit.get("mirror_axis")
        if axis not in {"vertical", "horizontal"}:
            return None, "请明确镜像方向（左右镜像或上下镜像）。"
        keep_source = edit.get("keep_source", True)
        bounds = _bounds(selected)
        if bounds is None:
            return None, "无法计算镜像轴。"
        used_ids = {str(item.get("id")) for item in geometries}
        next_id = max((int(value) for value in used_ids if value.isdigit()), default=0) + 1
        if keep_source:
            if len(groups) >= 50:
                return None, "已达到实例数量上限。"
            new_instance = max(groups) + 1
        else:
            new_instance = instance
        mirrored: list[dict[str, Any]] = []
        for item in selected:
            copied = deepcopy(item)
            while str(next_id) in used_ids:
                next_id += 1
            copied["id"] = next_id
            used_ids.add(str(next_id))
            next_id += 1
            copied["template_instance"] = new_instance
            mirrored.append(copied)
        _mirror_transform(mirrored, axis, edit.get('mirror_coordinate_mm'))
        source_signatures = {_geometry_signature(item) for item in selected}
        mirrored = [
            item for item in mirrored
            if _geometry_signature(item) not in source_signatures
        ]
        if not mirrored:
            # A copy request needs a visible second instance even when the
            # selected shape is symmetric about its own bounding-box axis.
            # Place the mirrored copy one full width/height away along the
            # requested axis; an explicit mirror coordinate still wins.
            if keep_source and edit.get("mirror_coordinate_mm") is None:
                shift = (bounds[2] - bounds[0]) if axis == "vertical" else (bounds[3] - bounds[1])
                mirrored = [deepcopy(item) for item in selected]
                for item in mirrored:
                    for point in _points(item):
                        if axis == "vertical":
                            point["x"] = round(float(point["x"]) + shift, 8)
                        else:
                            point["y"] = round(float(point["y"]) + shift, 8)
            else:
                return None, (
                    "该图形在此方向上完全对称，镜像结果与原图重合，"
                    "请明确镜像轴位置。"
                )
        if keep_source:
            geometries.extend(mirrored)
            edit["new_instance"] = new_instance
        else:
            geometries = [
                item for item in geometries if item["template_instance"] != instance
            ]
            for copied in mirrored:
                copied["template_instance"] = instance
            geometries.extend(mirrored)
            edit.pop("new_instance", None)
        return geometries, None
    if edit["operation"] == "offset":
        side = edit.get("offset_side")
        distance = edit.get("distance_mm")
        if side not in {"inside", "outside"} or not isinstance(distance, (int, float)) or distance <= 0:
            return None, "请明确向内或向外偏移，以及正的偏移距离。"
        if len(groups) >= 50:
            return None, "已达到实例数量上限。"
        new_instance = max(groups) + 1
        used_ids = {str(item.get("id")) for item in geometries}
        next_id = max((int(value) for value in used_ids if value.isdigit()), default=0) + 1
        copies: list[dict[str, Any]] = []
        for item in selected:
            copied = deepcopy(item)
            while str(next_id) in used_ids:
                next_id += 1
            copied["id"] = next_id
            used_ids.add(str(next_id))
            next_id += 1
            copied["template_instance"] = new_instance
            geometry_type = str(copied.get("type") or "")
            if geometry_type in {"circle", "arc"}:
                radius = float(copied.get("radius", 0))
                new_radius = radius - distance if side == "inside" else radius + distance
                if new_radius <= 0:
                    return None, "向内偏移距离超过图形半径。"
                copied["radius"] = round(new_radius, 8)
            elif geometry_type == "line" and _is_closed_loop(selected):
                bounds = _bounds(selected)
                if bounds is None:
                    return None, "无法计算偏移基准。"
                width = bounds[2] - bounds[0]
                height = bounds[3] - bounds[1]
                size = min(width, height)
                if size <= 1e-9:
                    return None, "无法计算偏移比例。"
                factor = (size - 2 * distance) / size if side == "inside" else (size + 2 * distance) / size
                if factor <= 0:
                    return None, "向内偏移距离过大。"
                _scale(
                    [copied], factor,
                    (bounds[0] + bounds[2]) / 2,
                    (bounds[1] + bounds[3]) / 2,
                )
            elif geometry_type == "line":
                start, end = copied.get("start"), copied.get("end")
                if not isinstance(start, dict) or not isinstance(end, dict):
                    return None, "线段坐标无效。"
                lx = float(end["x"]) - float(start["x"])
                ly = float(end["y"]) - float(start["y"])
                length = math.hypot(lx, ly)
                if length < 1e-9:
                    return None, "线段长度无效。"
                nx, ny = -ly / length, lx / length
                sign = -1 if side == "inside" else 1
                _translate([copied], sign * distance * nx, sign * distance * ny)
            else:
                bounds = _bounds([copied])
                if bounds is None:
                    return None, "无法计算偏移基准。"
                width = bounds[2] - bounds[0]
                height = bounds[3] - bounds[1]
                size = min(width, height)
                if size <= 1e-9:
                    return None, "无法计算偏移比例。"
                factor = (size - 2 * distance) / size if side == "inside" else (size + 2 * distance) / size
                if factor <= 0:
                    return None, "向内偏移距离过大。"
                _scale(
                    [copied], factor,
                    (bounds[0] + bounds[2]) / 2,
                    (bounds[1] + bounds[3]) / 2,
                )
            copies.append(copied)
        geometries.extend(copies)
        edit["new_instance"] = new_instance
        return geometries, None
    if edit["operation"] == "array":
        mode = edit.get("array_mode")
        if mode == "rectangular":
            rows = edit.get("rows")
            columns = edit.get("columns")
            row_spacing = edit.get("row_spacing_mm")
            column_spacing = edit.get("column_spacing_mm")
            if (
                not isinstance(rows, int) or not isinstance(columns, int)
                or rows < 1 or columns < 1
                or not isinstance(row_spacing, (int, float)) or row_spacing <= 0
                or not isinstance(column_spacing, (int, float)) or column_spacing <= 0
            ):
                return None, "矩形阵列需要行数、列数以及正的行列间距。"
            total = rows * columns
            if total > 50 or len(groups) + total - 1 > 50:
                return None, "阵列后实例总数不能超过 50 个。"
            new_instance = max(groups) + 1
            used_ids = {str(item.get("id")) for item in geometries}
            next_id = max((int(value) for value in used_ids if value.isdigit()), default=0) + 1
            geometries.extend(_array_rectangular_copies(
                selected, used_ids, next_id, new_instance,
                rows, columns, row_spacing, column_spacing,
            ))
            edit["new_instance"] = new_instance
            return geometries, None
        if mode == "polar":
            count = edit.get("count")
            angle = edit.get("angle_degrees")
            if not isinstance(count, int) or count < 2 or count > 50:
                return None, "环形阵列需要 2 到 50 之间的份数。"
            if not isinstance(angle, (int, float)) or abs(angle) < 1e-9:
                return None, "环形阵列需要正的每份间隔角度。"
            if len(groups) + count - 1 > 50:
                return None, "阵列后实例总数不能超过 50 个。"
            bounds = _bounds(selected)
            if bounds is None:
                return None, "无法计算环形阵列中心。"
            new_instance = max(groups) + 1
            used_ids = {str(item.get("id")) for item in geometries}
            next_id = max((int(value) for value in used_ids if value.isdigit()), default=0) + 1
            geometries.extend(_array_polar_copies(
                selected, used_ids, next_id, new_instance,
                count, float(angle),
                (bounds[0] + bounds[2]) / 2,
                (bounds[1] + bounds[3]) / 2,
            ))
            edit["new_instance"] = new_instance
            return geometries, None
        return None, "请明确矩形阵列（N 行 M 列）或环形阵列。"
    if edit["operation"] == "constraint":
        return _apply_constraint_edit(geometries, edit)

    dimension, target = edit["dimension"], edit["value_mm"]
    if target <= 0:
        return None, "尺寸必须大于零。"
    if dimension == "半径":
        circles = [item for item in selected if item.get("type") in {"circle", "arc"}]
        if len(selected) != 1 or len(circles) != 1:
            return None, "半径修改需要明确选择单个圆形，不能自动修改复合图形中的圆。"
        circles[0]["radius"] = target
        return geometries, None
    axis = "x" if dimension == "宽度" else "y"
    coordinates: list[float] = []
    for item in selected:
        if item.get("type") in {"circle", "arc", "ellipse"}:
            return None, "该组包含圆弧或椭圆，单轴改尺寸会使其变形；请明确缩放整个图形或使用无圆弧的图纸。"
        coordinates.extend(float(point[axis]) for point in _points(item))
    if not coordinates or max(coordinates) <= min(coordinates):
        return None, "选中图形没有可修改的宽高。"
    center = (max(coordinates) + min(coordinates)) / 2
    factor = target / (max(coordinates) - min(coordinates))
    for item in selected:
        for point in _points(item):
            point[axis] = center + (float(point[axis]) - center) * factor
    return geometries, None


def space_two_instances(
    source: list[dict[str, Any]], spacing_mm: float, arrangement: str,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Move only instance 2; leave instance 1 and its dimensions untouched."""
    if spacing_mm < 0 or {item.get("template_instance") for item in source} != {1, 2}:
        return None, "增量间距调整目前仅支持两个已分组的图形。"
    rectangles = [item for item in source if item.get("type") == "polyline"
                  and item.get("template_instance") == 1 and item.get("closed")]
    if len(rectangles) != 1:
        return None, "无法确定图形外边界，请先确认实例分组。"
    vertices = rectangles[0].get("vertices") or []
    if not vertices:
        return None, "外边界没有有效顶点。"
    width = max(float(p["x"]) for p in vertices) - min(float(p["x"]) for p in vertices)
    height = max(float(p["y"]) for p in vertices) - min(float(p["y"]) for p in vertices)
    long_side_is_x = width >= height
    axis = ("y" if long_side_is_x else "x") if arrangement == "long_side_adjacent" else ("x" if long_side_is_x else "y")
    first = [float(p[axis]) for item in source if item.get("template_instance") == 1 for p in _points(item)]
    second = [float(p[axis]) for item in source if item.get("template_instance") == 2 for p in _points(item)]
    if not first or not second:
        return None, "实例没有可计算间距的坐标。"
    first_center = (max(first) + min(first)) / 2
    second_center = (max(second) + min(second)) / 2
    if abs(first_center - second_center) < 1e-6:
        return None, "两个实例在该排列轴上重合，无法确定移动方向。"
    positive = second_center > first_center
    current_gap = (min(second) - max(first)) if positive else (min(first) - max(second))
    delta = spacing_mm - current_gap
    return edit_candidate_geometries(source, {
        "operation": "translate", "instance": 2,
        "dx_mm": delta * (1 if positive else -1) if axis == "x" else 0,
        "dy_mm": delta * (1 if positive else -1) if axis == "y" else 0,
    })


def rearrange_two_template_instances(
    source: list[dict[str, Any]],
    *,
    spacing_mm: float,
    arrangement: str,
    desired_quantity: int,
    peer_placement: str | None = None,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Deterministically replay a two-template layout command.

    Repeated templates keep a symmetric layout around their existing shared
    centre. Composite templates keep the primary instance fixed and place the
    secondary instance on the declared side, matching the template composer.
    """
    if spacing_mm < 0 or arrangement not in {
        "long_side_adjacent", "short_side_adjacent",
    }:
        return None, "排列修改缺少有效的排列方向或间距。"
    working = deepcopy(source)
    instances = sorted({
        int(item["template_instance"])
        for item in source
        if isinstance(item.get("template_instance"), int)
        and int(item["template_instance"]) > 0
    })
    if len(instances) == 1 and desired_quantity == 2:
        next_id = max(
            (int(item.get("id") or 0) for item in working), default=0
        )
        source_instance = instances[0]
        clones: list[dict[str, Any]] = []
        for item in working:
            if item.get("template_instance") != source_instance:
                continue
            clone = deepcopy(item)
            next_id += 1
            clone["id"] = next_id
            clone["template_instance"] = source_instance + 1
            clones.append(clone)
        working.extend(clones)
        instances = [source_instance, source_instance + 1]
    if len(instances) != 2 or desired_quantity != 2:
        return None, "排列修改目前仅支持两个已分组的模板实例。"
    groups = {
        instance: [item for item in working if item.get("template_instance") == instance]
        for instance in instances
    }

    def bounds(items: list[dict[str, Any]]) -> tuple[float, float, float, float] | None:
        points = [point for item in items for point in _points(item)]
        if not points:
            return None
        xs = [float(point["x"]) for point in points]
        ys = [float(point["y"]) for point in points]
        return min(xs), min(ys), max(xs), max(ys)

    first_bounds, second_bounds = bounds(groups[instances[0]]), bounds(groups[instances[1]])
    if first_bounds is None or second_bounds is None:
        return None, "模板实例没有可计算的边界。"
    first_width = first_bounds[2] - first_bounds[0]
    first_height = first_bounds[3] - first_bounds[1]
    long_side_is_horizontal = first_width >= first_height
    use_x_axis = (
        not long_side_is_horizontal
        if arrangement == "long_side_adjacent"
        else long_side_is_horizontal
    )
    inferred = "right" if use_x_axis else "above"
    placement = peer_placement or inferred
    if placement in {"left", "right"} and not use_x_axis:
        return None, "指定的左右位置与当前长短边排列方向冲突。"
    if placement in {"above", "below"} and use_x_axis:
        return None, "指定的上下位置与当前长短边排列方向冲突。"

    same_template = {
        str(item.get("template_type") or "")
        for item in working if item.get("template_type")
    }
    same_template = len(same_template) == 1
    axis = "x" if use_x_axis else "y"
    cross = "y" if use_x_axis else "x"
    first_center = {
        "x": (first_bounds[0] + first_bounds[2]) / 2,
        "y": (first_bounds[1] + first_bounds[3]) / 2,
    }
    second_center = {
        "x": (second_bounds[0] + second_bounds[2]) / 2,
        "y": (second_bounds[1] + second_bounds[3]) / 2,
    }
    first_extent = first_width if use_x_axis else first_height
    second_extent = (
        second_bounds[2] - second_bounds[0]
        if use_x_axis else second_bounds[3] - second_bounds[1]
    )
    separation = first_extent / 2 + spacing_mm + second_extent / 2
    sign = -1.0 if placement in {"left", "below"} else 1.0
    desired = {
        instances[0]: dict(first_center),
        instances[1]: dict(second_center),
    }
    if same_template:
        midpoint = (first_center[axis] + second_center[axis]) / 2
        desired[instances[0]][axis] = midpoint - sign * separation / 2
        desired[instances[1]][axis] = midpoint + sign * separation / 2
        cross_midpoint = (first_center[cross] + second_center[cross]) / 2
        desired[instances[0]][cross] = cross_midpoint
        desired[instances[1]][cross] = cross_midpoint
    else:
        desired[instances[1]][axis] = first_center[axis] + sign * separation
        desired[instances[1]][cross] = first_center[cross]

    centers = {instances[0]: first_center, instances[1]: second_center}
    for instance, items in groups.items():
        dx = desired[instance]["x"] - centers[instance]["x"]
        dy = desired[instance]["y"] - centers[instance]["y"]
        for item in items:
            for point in _points(item):
                point["x"] = float(point["x"]) + dx
                point["y"] = float(point["y"]) + dy
    return working, None
