"""Measure compiled object relations independently of transform parameters."""
import json
import math


def _primitive(items):
    if len(items) != 1:
        raise ValueError("暂不能独立验收该复合对象的中心或尺寸")
    g = items[0]
    if g.get("type") == "circle":
        x, y = float(g["center"]["x"]), float(g["center"]["y"])
        r = float(g["radius"])
        if not all(math.isfinite(v) for v in (x, y, r)) or r <= 0:
            raise ValueError("圆形参数无效")
        return {"center": (x, y), "宽度": 2*r, "高度": 2*r, "半径": r}
    points = [(float(p["x"]), float(p["y"])) for p in g.get("vertices") or []]
    if len(points) == 5 and points[0] == points[-1]:
        points = points[:-1]
    if g.get("type") != "polyline" or not g.get("closed") or len(points) != 4:
        raise ValueError("暂不能独立确认对象几何中心")
    if not all(math.isfinite(v) for p in points for v in p):
        raise ValueError("矩形坐标无效")
    xs, ys = zip(*points)
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    if x1 <= x0 or y1 <= y0 or set(points) != {(x,y) for x in (x0,x1) for y in (y0,y1)}:
        raise ValueError("实际轮廓不是轴对齐矩形")
    if any(points[i][0] != points[(i+1)%4][0] and points[i][1] != points[(i+1)%4][1] for i in range(4)):
        raise ValueError("实际轮廓含对角连接")
    return {"center": ((x0+x1)/2, (y0+y1)/2), "宽度": x1-x0, "高度": y1-y0}


def validate_edit_relations(source, target, contract):
    relations = [c for c in contract.get("constraints") or [] if isinstance(c, dict)
                 and c.get("kind") in {"concentric", "equal"} and c.get("moving_object_id")]
    if not relations:
        return {"enforced": False, "verified": True, "checks": [], "message": "本次无已编译对象关系需要复核。"}
    checks = []
    before = {g.get("id"): g for g in source}
    after = {g.get("id"): g for g in target}
    moving = list((contract.get("target") or {}).get("geometry_ids") or [])
    for relation in relations:
        record = {"kind": relation["kind"], "moving_object_id": relation["moving_object_id"],
                  "reference_object_id": relation.get("reference_object_id"), "verified": False}
        try:
            reference = relation.get("reference_geometry_ids") or []
            if (not moving or not reference or len(set(reference)) != len(reference)
                    or set(moving) & set(reference) or len(before) != len(source) or len(after) != len(target)):
                raise ValueError("关系验收的对象归属无效")
            if any(json.dumps(before[i], sort_keys=True) != json.dumps(after[i], sort_keys=True) for i in reference):
                raise ValueError("固定参考对象发生变化")
            if set(before) != set(after):
                raise ValueError("关系修改不能新增或删除图元")
            protected = set(before) - set(moving)
            if any(json.dumps(before[i], sort_keys=True) != json.dumps(after[i], sort_keys=True) for i in protected):
                raise ValueError("非目标对象发生变化")
            if any(before[i].get("type") != after[i].get("type") for i in moving):
                raise ValueError("目标对象的几何类型发生变化")
            original = _primitive([before[i] for i in moving])
            actual = _primitive([after[i] for i in moving])
            expected = _primitive([before[i] for i in reference])
            preserved = []
            def preserve(field):
                drift = (math.dist(actual[field], original[field]) if field == "center"
                         else abs(actual[field] - original[field]))
                preserved.append({"field": field, "error_mm": drift, "verified": drift <= 0.001})
            if relation["kind"] == "concentric":
                error = math.dist(actual["center"], expected["center"])
                record.update(actual_center=actual["center"], reference_center=expected["center"])
                for field in ("宽度", "高度"):
                    preserve(field)
            else:
                metric = relation.get("dimension")
                if metric not in {"宽度", "高度", "半径"}:
                    raise ValueError("关系验收不支持该比较尺度")
                error = abs(actual[metric] - expected[metric])
                record.update(dimension=metric, actual_mm=actual[metric], required_mm=expected[metric])
                preserve("center")
                if metric in {"宽度", "高度"}:
                    preserve("高度" if metric == "宽度" else "宽度")
            record.update(error_mm=error, tolerance_mm=0.001, preservation_checks=preserved,
                          verified=error <= 0.001 and all(p["verified"] for p in preserved))
            record["message"] = ("实际对象关系通过独立测量" if record["verified"] else
                                 "实际对象关系或应保留的位置、尺寸未满足要求")
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            record["message"] = str(exc)
        checks.append(record)
    verified = all(c["verified"] for c in checks)
    return {"enforced": True, "verified": verified, "checks": checks,
            "message": "对象关系独立验收通过。" if verified else "对象关系独立验收失败：" + "；".join(c["message"] for c in checks if not c["verified"])}
