"""Compile source-bound object constraints to the existing transform pipeline."""
from copy import deepcopy
import math
import re

from .incremental_cad import _bounds


def compile_object_constraint(edit, objects, geometries, text):
    if edit.get('operation') == 'align' and edit.get('alignment') == '水平居中':
        selected = set(edit.get('geometry_ids') or [])
        candidates = [o for o in objects if set(o.get('geometry_refs') or []).issubset(selected)
                      and o.get('geometry_refs')]
        by_id = {g['id']: g for g in geometries}
        if len(candidates) == 2 and re.search(r'以左侧.{0,12}为(?:固定)?基准', text):
            groups = sorted(candidates, key=lambda o: _bounds([by_id[i] for i in o['geometry_refs']])[0])
            a, b = [_bounds([by_id[i] for i in o['geometry_refs']]) for o in groups]
            if a[0] < b[0]:
                dy = (a[1]+a[3]-b[1]-b[3])/2
                result = deepcopy(edit)
                for key in ('alignment', 'reference_instance', 'logical_object_ids', 'instance', 'instances'):
                    result.pop(key, None)
                result.update(operation='translate', geometry_ids=groups[1]['geometry_refs'],
                              logical_object_id=groups[1]['object_id'], dx_mm=0, dy_mm=dy)
                if abs(dy) <= 1e-9:
                    result['_measured_relation_satisfied'] = '两个对象的中心Y坐标已相同，固定对象和尺寸均保持不变。'
                return result, None
    if edit.get("constraint_conflict"):
        return None, "本轮包含多个约束或否定要求，请明确本次只执行哪一种约束；若是改口，请说明改为哪一种。"
    kind = edit.get("constraint_type")
    if edit.get("operation") != "constraint" or kind not in {"concentric", "equal"}:
        return edit, None
    ids = [v for v in [edit.get("logical_object_id"), *(edit.get("logical_object_ids") or [])] if v]
    if not ids:
        return edit, None  # Existing instance constraints retain their contract.
    metric = edit.get("dimension")
    if kind == "equal" and not metric:
        return None, "请明确一样大是指宽度、高度、半径还是面积相等。"
    if kind == "equal" and metric not in {"宽度", "高度", "半径"}:
        return None, "当前尚不支持面积或周长相等约束；不会替换为宽度、高度或半径相等。"
    by_object = {o.get("object_id"): o for o in objects}
    if len(ids) != 2 or len(set(ids)) != 2 or any(v not in by_object for v in ids):
        return None, "请明确约束涉及的两个完整对象。"
    by_id = {g.get("id"): g for g in geometries}
    groups = [list(by_object[v].get("geometry_refs") or []) for v in ids]
    if any(not refs or len(refs) != len(set(refs)) or any(v not in by_id for v in refs) for refs in groups):
        return None, "约束对象的图元归属已变化，请重新选择。"
    if set(groups[0]) & set(groups[1]) or set(edit.get("geometry_ids") or []) != set(groups[0] + groups[1]):
        return None, "约束修改需要两个不共享图元的完整对象。"
    references = []
    exact_references = []
    # Durable edit sessions join raw turns with newlines. A later explicit
    # reference replaces an earlier one; conflicts within one turn still clarify.
    reference_text = next((line for line in reversed(text.splitlines())
                           if re.search(r"以.{1,60}为(?:(?:固定)?基准|参考)|固定|保持", line)), text)
    if re.search(r"(?:不要|不用|别|不)(?:以|固定|保持)", reference_text):
        return None, "请正面明确约束时固定哪个对象，不会从否定指令推断基准。"
    for i, object_id in enumerate(ids):
        label = str(by_object[object_id].get("label") or "").strip()
        def names_reference(name):
            return re.search(r"(?:以\s*" + re.escape(name) + r"\s*为(?:(?:固定)?基准|参考)|(?:固定|保持)\s*" + re.escape(name) + r"\s*(?:不动|位置不变|(?=[，。；\s]|$)))", reference_text)
        if label and names_reference(label):
            exact_references.append(i)
        labels = {label} if label else set()
        # Basic geometric names are grounded in the measured primitive, not
        # model-authored labels such as 'circle body' versus 'circle outline'.
        from .cad_edit_relation_acceptance import _primitive
        try:
            measured = _primitive([by_id[v] for v in groups[i]])
            labels.update({"圆形", "圆"} if "半径" in measured else {"矩形", "长方形"})
        except (KeyError, TypeError, ValueError, OverflowError):
            pass
        if any(names_reference(name) for name in labels):
            references.append(i)
    references = exact_references or references
    if len(references) != 1:
        return None, "请说明固定哪个对象，例如“以圆形为基准，修改矩形”。"
    reference = references[0]
    moving = 1 - reference
    bounds = [_bounds([by_id[v] for v in refs]) for refs in groups]
    if any(b is None or not all(math.isfinite(v) for v in b) for b in bounds):
        return None, "无法确定对象中心，请明确中心坐标。"
    # Bounds centers are geometric centers only for the supported symmetric
    # primitives. Do not silently substitute a bounding-box center for a centroid.
    for refs in groups:
        if len(refs) != 1:
            return None, "当前对象的几何中心尚不能独立确认，请明确中心坐标。"
        g = by_id[refs[0]]
        if g.get("type") == "circle":
            if not isinstance(g.get("radius"), (int, float)) or not math.isfinite(g["radius"]) or g["radius"] <= 0:
                return None, "圆形半径无效，已停止同心修改。"
            continue
        vertices = g.get("vertices") or []
        if len(vertices) == 5 and vertices[0] == vertices[-1]:
            vertices = vertices[:-1]
        corners = {(p.get("x"), p.get("y")) for p in vertices}
        b = _bounds([g])
        if not (g.get("type") == "polyline" and g.get("closed") and len(vertices) == 4
                and len(corners) == 4 and b and b[2] > b[0] and b[3] > b[1]
                and corners == {(x, y) for x in (b[0], b[2]) for y in (b[1], b[3])}):
            return None, "当前对象的几何中心尚不能独立确认，请明确中心坐标。"
        if any(vertices[i].get("x") != vertices[(i+1)%4].get("x") and vertices[i].get("y") != vertices[(i+1)%4].get("y") for i in range(4)):
            return None, "对象轮廓不能确认是矩形，已停止同心修改。"
    source, target = bounds[moving], bounds[reference]
    result = deepcopy(edit)
    for key in ("constraint_type", "logical_object_ids", "instance", "instances", "reference_instance"):
        result.pop(key, None)
    result.update(logical_object_id=ids[moving], geometry_ids=groups[moving])
    if kind == "concentric":
        result.pop("dimension", None)
        result.update(operation="translate", dx_mm=(target[0]+target[2]-source[0]-source[2])/2,
                      dy_mm=(target[1]+target[3]-source[1]-source[3])/2)
    else:
        moving_geometry = by_id[groups[moving][0]]
        reference_geometry = by_id[groups[reference][0]]
        if metric == "半径":
            if moving_geometry.get("type") != "circle" or reference_geometry.get("type") != "circle":
                return None, "半径相等需要两个完整圆形，不能把矩形尺寸解释成半径。"
            value = reference_geometry["radius"]
        else:
            if moving_geometry.get("type") == "circle":
                return None, "圆形不能只改宽度或高度而保持另一尺寸；请明确是否改为半径相等。"
            axis = 0 if metric == "宽度" else 1
            value = target[axis+2] - target[axis]
        result.update(operation="resize", dimension=metric, value_mm=value)
        actual = (source[2]-source[0] if metric == '宽度' else source[3]-source[1] if metric == '高度'
                  else by_id[groups[moving][0]].get('radius'))
        if actual is not None and abs(actual-value) <= 1e-9:
            result['_measured_relation_satisfied'] = '指定尺寸关系已经满足，基准对象和其他尺寸保持不变。'
    result.setdefault("constraints", []).append({"kind": kind, "dimension": metric if kind == "equal" else None, "moving_object_id": ids[moving],
        "reference_object_id": ids[reference], "reference_geometry_ids": groups[reference],
        "center_definition": "verified_primitive_center"})
    return result, None


def compile_concentric_edit(edit, objects, geometries, text):
    """Compatibility entry for existing concentric callers."""
    if edit.get("constraint_type") != "concentric":
        return edit, None
    return compile_object_constraint(edit, objects, geometries, text)
