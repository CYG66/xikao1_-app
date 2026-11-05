"""Reject CAD follow-up contracts whose changed fields lack user evidence."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import re
from typing import Any


_FOLLOWUP_MARKERS = (
    "它", "这个", "那个", "刚才", "上次", "再来", "重复", "同样", "相同",
    "另一个", "其余", "剩下", "不是", "说错了", "改成", "改为", "应该是", "应为",
)
_OPERATION_MARKERS = {
    "translate": ("移动", "平移", "挪", "偏移", "移到", "移至"),
    "rotate": ("旋转", "转动"),
    "scale": ("缩放", "放大", "缩小", "扩大", "收缩"),
    "resize": ("宽度", "高度", "半径", "尺寸", "改宽", "改高"),
    "duplicate": ("复制", "拷贝", "再生成一个", "再来一个"),
    "align": ("对齐", "齐平", "排齐"),
    "delete": ("删除", "删掉", "移除", "去掉"),
    "retain": ("只保留", "仅保留"),
}


def _same(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(float(left), float(right), abs_tol=1e-6)
    return left == right


def _contract_sha256(contract: dict[str, Any]) -> str:
    payload = deepcopy(contract)
    grounding = payload.get("intent_grounding")
    if isinstance(grounding, dict):
        grounding.pop("counterfactual_guard", None)
        if not grounding:
            payload.pop("intent_grounding", None)
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _report_sha256(report: dict[str, Any]) -> str:
    payload = {key: value for key, value in report.items() if key != "report_sha256"}
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _target(contract: dict[str, Any]) -> dict[str, Any]:
    raw = contract.get("target") if isinstance(contract.get("target"), dict) else {}
    return {
        "scope": raw.get("scope"),
        "instance_ids": sorted(raw.get("instance_ids") or []),
        "geometry_ids": sorted(raw.get("geometry_ids") or []),
        "object_ids": sorted([
            value for value in [raw.get("object_id"), *(raw.get("object_ids") or [])]
            if value
        ]),
    }


def _parameter_changes(
    previous: dict[str, Any], current: dict[str, Any], operation: str,
) -> list[str]:
    fields = {
        "translate": ("dx_mm", "dy_mm", "coordinate_frame"),
        "rotate": ("angle_degrees", "pivot"),
        "scale": ("factor", "pivot"),
        "resize": ("dimension", "value_mm"),
        "duplicate": ("direction", "distance_mm", "placement"),
        "align": ("alignment",),
    }.get(operation, ())
    before = previous.get("parameters") if isinstance(previous.get("parameters"), dict) else {}
    after = current.get("parameters") if isinstance(current.get("parameters"), dict) else {}
    result = []
    for field in fields:
        left = previous.get("coordinate_frame") if field == "coordinate_frame" else before.get(field)
        right = current.get("coordinate_frame") if field == "coordinate_frame" else after.get(field)
        if not _same(left, right):
            result.append(field)
    return result


def _parameter_evidence(
    field: str, text: str, previous_value: Any, current_value: Any,
) -> bool:
    compact = "".join(text.lower().split())
    rules = {
        "dx_mm": bool(re.search(r"\d+(?:\.\d+)?\s*(?:米|m|厘米|cm|毫米|mm)", text))
        or any(word in compact for word in ("同样距离", "相同距离")),
        "dy_mm": bool(re.search(r"\d+(?:\.\d+)?\s*(?:米|m|厘米|cm|毫米|mm)", text))
        or any(word in compact for word in ("同样距离", "相同距离")),
        "coordinate_frame": any(word in compact for word in ("小车前", "小车后", "车头", "图纸", "局部坐标")),
        "angle_degrees": bool(re.search(r"\d+(?:\.\d+)?\s*度", text))
        or any(word in compact for word in ("同样角度", "相同角度")),
        "pivot": any(word in compact for word in ("各自中心", "自身中心", "组合中心", "整体中心", "整组中心")),
        "factor": bool(re.search(r"\d+(?:\.\d+)?\s*倍", text)),
        "dimension": any(word in compact for word in ("宽度", "高度", "半径")),
        "value_mm": bool(re.search(r"\d+(?:\.\d+)?\s*(?:米|m|厘米|cm|毫米|mm)", text)),
        "direction": any(word in compact for word in ("左", "右", "上", "下", "前", "后", "东", "西", "南", "北")),
        "distance_mm": bool(re.search(r"\d+(?:\.\d+)?\s*(?:米|m|厘米|cm|毫米|mm)", text)),
        "placement": any(word in compact for word in ("间距", "间隔", "净距", "偏移", "移动距离")),
        "alignment": any(word in compact for word in ("左对齐", "右对齐", "顶部对齐", "底部对齐", "居中", "齐平", "排齐")),
    }
    if field in {"dx_mm", "dy_mm"}:
        direction = any(word in compact for word in (
            "向左", "向右", "向上", "向下", "向前", "向后", "往左", "往右",
            "往上", "往下", "往前", "往后", "左移", "右移", "上移", "下移",
        ))
        try:
            before = float(previous_value or 0.0)
            after = float(current_value or 0.0)
        except (TypeError, ValueError):
            return False
        direction_changed = (
            (before == 0.0) != (after == 0.0)
            or (before < 0.0) != (after < 0.0)
        )
        return bool(rules[field]) and (direction or not direction_changed)
    return bool(rules.get(field, False))


def _parameter_value(contract: dict[str, Any], field: str) -> Any:
    if field == "coordinate_frame":
        return contract.get(field)
    parameters = contract.get("parameters")
    return parameters.get(field) if isinstance(parameters, dict) else None


def _finish_report(
    report: dict[str, Any],
    previous_contract: dict[str, Any] | None,
    current_contract: dict[str, Any],
) -> dict[str, Any]:
    report["previous_contract_sha256"] = (
        _contract_sha256(previous_contract)
        if isinstance(previous_contract, dict) else None
    )
    report["current_contract_sha256"] = _contract_sha256(current_contract)
    report["report_sha256"] = _report_sha256(report)
    return report


def validate_counterfactual_followup(
    previous_contract: dict[str, Any] | None,
    current_contract: dict[str, Any],
    user_text: str,
) -> dict[str, Any]:
    """Prove that every changed inherited field is explicit in this turn."""
    if (
        not isinstance(previous_contract, dict)
        or previous_contract.get("schema") != "cad.edit.v2"
        or current_contract.get("schema") != "cad.edit.v2"
        or not any(marker in user_text for marker in _FOLLOWUP_MARKERS)
    ):
        return _finish_report({
            "schema": "cad.counterfactual-guard.v1",
            "enforced": False,
            "verified": True,
            "reason": "independent_instruction",
            "changed_fields": [],
            "unsupported_changes": [],
        }, previous_contract, current_contract)

    changed: list[str] = []
    unsupported: list[str] = []
    previous_operation = str(previous_contract.get("operation") or "")
    current_operation = str(current_contract.get("operation") or "")
    if previous_operation != current_operation:
        changed.append("operation")
        if not any(
            marker in user_text
            for marker in _OPERATION_MARKERS.get(current_operation, ())
        ):
            unsupported.append("operation")

    if _target(previous_contract) != _target(current_contract):
        changed.append("target")
        target_evidence = bool(re.search(
            r"第\s*(?:\d+|[一二两三四五六七八九十]+)\s*(?:个|组|座|块|片|条)?",
            user_text,
        )) or any(word in user_text for word in (
            "上方", "下方", "左侧", "右侧", "中间", "另一个", "其余", "剩下",
            "中心圆", "外框", "中线", "选中", "图层", "喷墨路径", "参考线",
        ))
        if not target_evidence:
            unsupported.append("target")

    if previous_operation == current_operation:
        for field in _parameter_changes(
            previous_contract, current_contract, current_operation,
        ):
            path = f"parameters.{field}"
            changed.append(path)
            if not _parameter_evidence(
                field,
                user_text,
                _parameter_value(previous_contract, field),
                _parameter_value(current_contract, field),
            ):
                unsupported.append(path)

    if str(previous_contract.get("project_id") or "") != str(
        current_contract.get("project_id") or ""
    ):
        changed.append("project_id")
        unsupported.append("project_id")

    verified = not unsupported
    return _finish_report({
        "schema": "cad.counterfactual-guard.v1",
        "enforced": True,
        "verified": verified,
        "reason": None if verified else "unproven_followup_change",
        "changed_fields": changed,
        "unsupported_changes": unsupported,
        "previous": {
            "operation": previous_operation,
            "target": _target(previous_contract),
        },
        "current": {
            "operation": current_operation,
            "target": _target(current_contract),
        },
    }, previous_contract, current_contract)


def validate_counterfactual_guard_report(
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Verify that a persisted guard report still binds this exact contract."""
    grounding = contract.get("intent_grounding")
    report = (
        grounding.get("counterfactual_guard")
        if isinstance(grounding, dict) else None
    )
    if not isinstance(report, dict):
        return {
            "schema": "cad.counterfactual-guard-validation.v1",
            "verified": False,
            "reason": "missing_guard_report",
        }
    expected_report_sha256 = _report_sha256(report)
    checks = {
        "schema_valid": report.get("schema") == "cad.counterfactual-guard.v1",
        "decision_verified": report.get("verified") is True,
        "contract_unchanged": (
            report.get("current_contract_sha256") == _contract_sha256(contract)
        ),
        "report_unchanged": report.get("report_sha256") == expected_report_sha256,
    }
    return {
        "schema": "cad.counterfactual-guard-validation.v1",
        "verified": all(checks.values()),
        "checks": checks,
        "current_contract_sha256": _contract_sha256(contract),
        "report_sha256": expected_report_sha256,
    }
