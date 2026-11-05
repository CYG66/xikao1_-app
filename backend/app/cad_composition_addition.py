"""Compile explicit relative additions into the shared CAD construction IR.

The parser accepts only fully specified dimensions and offsets.  It returns
None on ambiguity so the ordinary clarification/model path remains in charge.
"""

from __future__ import annotations

import math
import re
from copy import deepcopy
from typing import Any

from .cad_construction import execute_construction_plan, construction_geometry_bounds


_NUMBER = r"(\d+(?:\.\d+)?)"
_UNIT = r"(毫米|厘米|米|mm|cm|m)"
_SCALE = {"毫米": 1.0, "厘米": 10.0, "米": 1000.0, "mm": 1.0, "cm": 10.0, "m": 1000.0}


def _millimetres(match: re.Match[str]) -> float:
    return float(match.group(1)) * _SCALE[match.group(2).lower()]


def parse_relative_additions(text: str) -> dict[str, Any] | None:
    """Read a measured mirrored pair relative to the selected drawing center.

    This is a generic relationship, independent of the name or template of
    the existing drawing. Unsupported/ambiguous wording is left to the model.
    """
    source = str(text or "")
    if not (re.search(r"(?:两个|2个|上下各(?:一|1)个)\s*矩形", source)
            and "上" in source and "下" in source and "中心线" in source):
        return None
    width = re.search(rf"(?:宽|宽度)\s*{_NUMBER}\s*{_UNIT}", source, re.I)
    height = re.search(rf"(?:高|高度)\s*{_NUMBER}\s*{_UNIT}", source, re.I)
    above = re.search(rf"上方\s*{_NUMBER}\s*{_UNIT}", source, re.I)
    below = re.search(rf"下方\s*{_NUMBER}\s*{_UNIT}", source, re.I)
    if not all((width, height, above, below)):
        return None
    values = [_millimetres(item) for item in (width, height, above, below)]
    if not all(math.isfinite(value) and 0 < value <= 100000 for value in values):
        return None
    if "对称" in source and abs(values[2] - values[3]) > 1e-6:
        return None
    return {"schema": "cad.relative-additions.v1", "shape": "rectangle", "count": 2,
            "width_mm": values[0], "height_mm": values[1],
            "offsets_mm": [values[2], -values[3]], "reference": "selected_drawing_center",
            "source_text": source}


def execute_relative_additions(
    parent_geometries: list[dict[str, Any]], contract: dict[str, Any]
) -> dict[str, Any]:
    """Run generic rectangle primitives in CadConstructionPlan, then measure.

    The original geometry is never passed into the executor or changed.
    IDs are remapped only after the isolated plan has passed its assertions.
    """
    if (not parent_geometries or contract.get("shape") != "rectangle"
            or contract.get("reference") != "selected_drawing_center"):
        raise ValueError("relative addition has no supported source or shape")
    bounds = construction_geometry_bounds(parent_geometries)
    cx = (bounds["min_x"] + bounds["max_x"]) / 2
    cy = (bounds["min_y"] + bounds["max_y"]) / 2
    width = float(contract["width_mm"])
    height = float(contract["height_mm"])
    offsets = list(contract["offsets_mm"])
    if (not math.isfinite(width) or not math.isfinite(height)
            or not 0 < width <= 100000 or not 0 < height <= 100000
            or len(offsets) != int(contract.get("count") or 0)
            or not 1 <= len(offsets) <= 50
            or any(not isinstance(value, (int, float)) or not math.isfinite(value)
                   or abs(value) > 100000 for value in offsets)):
        raise ValueError("relative addition contract has invalid dimensions or placements")
    steps = []
    assertions = [{"kind": "entity_count", "assertion_id": "addition-count", "equals": len(offsets)}]
    for index, offset in enumerate(offsets, 1):
        ref = f"addition-{index}"
        steps.append({"step_id": ref, "output_ref": ref, "layer_id": 1,
                      "semantic": {"assembly_id": ref, "assembly_label": f"新增图形 {index}",
                                   "object_id": ref, "object_type": "rectangle", "label": f"矩形 {index}"},
                      "op": "add_centered_rectangle", "center": {"x": cx, "y": cy + offset},
                      "width": width, "height": height})
        assertions.extend([
            {"kind": "closed", "assertion_id": f"closed-{index}", "target_ref": ref},
            {"kind": "bounds_size", "assertion_id": f"size-{index}", "target_ref": ref,
             "width": width, "height": height, "tolerance": 0.001},
        ])
    plan = {"schema_version": "cad.construction-plan.v1", "units": "mm", "steps": steps,
            "assertions": assertions, "budgets": {"max_steps": 100, "max_entities": 500}}
    result = execute_construction_plan(plan)
    added = deepcopy(result["geometries"])
    next_id = max(int(item["id"]) for item in parent_geometries) + 1
    id_map = {}
    for item in added:
        old_id = int(item["id"])
        id_map[old_id] = next_id
        item["id"] = next_id
        next_id += 1
    measured = []
    for item, offset in zip(added, offsets):
        box = construction_geometry_bounds([item])
        observed = ((box["min_x"] + box["max_x"]) / 2,
                    (box["min_y"] + box["max_y"]) / 2)
        passed = (abs(box["max_x"] - box["min_x"] - width) <= 1
                  and abs(box["max_y"] - box["min_y"] - height) <= 1
                  and abs(observed[0] - cx) <= 1
                  and abs(observed[1] - cy - offset) <= 1)
        measured.append({"geometry_id": item["id"], "center_mm": observed,
                         "width_mm": box["max_x"] - box["min_x"],
                         "height_mm": box["max_y"] - box["min_y"], "passed": passed})
    if len(added) != len(offsets) or not all(item["passed"] for item in measured):
        raise ValueError("relative addition failed independent geometry acceptance")
    objects = deepcopy(result["logical_objects"])
    for obj in objects:
        obj["geometry_refs"] = [id_map[int(value)] for value in obj.get("geometry_refs") or []]
    return {"geometries": deepcopy(parent_geometries) + added, "added": added,
            "logical_objects": objects, "plan": result["plan"],
            "acceptance": {"status": "passed", "authority": "backend_measured_geometry",
                           "checks": measured, "parent_preserved": True}}
