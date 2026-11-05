"""Preflight and risk classification for deterministic CAD candidate edits."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from .geometry_diff import build_geometry_diff


def geometry_fingerprint(geometries: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        geometries, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def geometry_entity_fingerprint(geometry: dict[str, Any]) -> str:
    payload = json.dumps(
        geometry, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_rejection_rollback_evidence(
    source: list[dict[str, Any]], reason: str,
) -> dict[str, Any]:
    source_hash = geometry_fingerprint(source)
    return {
        "schema": "cad.rollback.evidence.v1",
        "triggered": True,
        "candidate_discarded": True,
        "persisted": False,
        "source_before_sha256": source_hash,
        "source_after_sha256": source_hash,
        "verified": True,
        "reason": reason,
    }


def _semantic_geometry_fingerprint(geometries: list[dict[str, Any]]) -> str:
    """Hash exact geometry while treating equivalent int/float values equally."""
    def normalize(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): normalize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value

    payload = json.dumps(
        normalize(geometries),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_declared_edit_effect(
    source: list[dict[str, Any]],
    target: list[dict[str, Any]],
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Replay cad.edit.v2 and prove that the candidate has the declared effect."""
    if contract.get("schema") != "cad.edit.v2":
        return {
            "enforced": False,
            "verified": None,
            "reason": "legacy_contract",
            "message": "历史修改协议不执行参数重放校验。",
        }
    try:
        if contract.get("operation") == "add_geometry":
            from .cad_composition_addition import execute_relative_additions
            spec = contract.get("addition_contract")
            if not isinstance(spec, dict):
                raise ValueError("add_geometry requires a canonical addition contract")
            expected = execute_relative_additions(source, spec)["geometries"]
            error = None
        elif contract.get("operation") == "chain":
            from .cad_edit_chain import replay_cad_edit_chain
            expected, error, _ = replay_cad_edit_chain(source, contract)
        else:
            from .cad_edit_contract import cad_edit_contract_to_edit
            from .incremental_cad import edit_candidate_geometries
            edit = cad_edit_contract_to_edit(contract)
            expected, error = edit_candidate_geometries(source, edit)
    except (TypeError, ValueError) as exc:
        expected, error = None, f"修改协议无效：{exc}"
    if expected is None:
        return {
            "enforced": True,
            "verified": False,
            "reason": "replay_failed",
            "message": error or "无法根据修改协议重放期望结果。",
        }

    expected_hash = _semantic_geometry_fingerprint(expected)
    actual_hash = _semantic_geometry_fingerprint(target)
    expected_by_id = {
        _positive_id(item.get("id")): item for item in expected
        if isinstance(item, dict) and _positive_id(item.get("id")) is not None
    }
    actual_by_id = {
        _positive_id(item.get("id")): item for item in target
        if isinstance(item, dict) and _positive_id(item.get("id")) is not None
    }
    mismatched_ids = sorted(
        geometry_id for geometry_id in set(expected_by_id) & set(actual_by_id)
        if _semantic_geometry_fingerprint([expected_by_id[geometry_id]])
        != _semantic_geometry_fingerprint([actual_by_id[geometry_id]])
    )
    missing_ids = sorted(set(expected_by_id) - set(actual_by_id))
    unexpected_ids = sorted(set(actual_by_id) - set(expected_by_id))
    verified = expected_hash == actual_hash
    return {
        "enforced": True,
        "verified": verified,
        "reason": None if verified else "declared_effect_mismatch",
        "message": (
            "实际几何结果与声明的修改参数完全一致。"
            if verified else "实际几何结果与声明的距离、角度、倍数或尺寸不一致，已阻止保存。"
        ),
        "operation": contract.get("operation"),
        "expected_fingerprint": expected_hash,
        "actual_fingerprint": actual_hash,
        "mismatched_geometry_ids": mismatched_ids,
        "missing_geometry_ids": missing_ids,
        "unexpected_geometry_ids": unexpected_ids,
    }


def _finite_coordinates(value: Any) -> bool:
    if isinstance(value, dict):
        return all(_finite_coordinates(item) for item in value.values())
    if isinstance(value, list):
        return all(_finite_coordinates(item) for item in value)
    if isinstance(value, float):
        return math.isfinite(value)
    return True


def _positive_id(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def validate_split_shared_boundary_provenance(
    source: list[dict[str, Any]],
    target: list[dict[str, Any]],
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Prove every new boundary is a translated clone of a declared shared edge."""
    parameters = contract.get("parameters") if isinstance(contract.get("parameters"), dict) else {}
    if parameters.get("boundary_policy") != "split_shared":
        return {
            "enforced": False, "verified": True, "reason": None,
            "message": "本次修改不涉及共享边界拆分。",
        }
    target_spec = contract.get("target") if isinstance(contract.get("target"), dict) else {}
    shared_ids = [
        value for raw in parameters.get("shared_geometry_ids") or []
        if (value := _positive_id(raw)) is not None
    ]
    created_ids = [
        value for raw in parameters.get("created_geometry_ids") or []
        if (value := _positive_id(raw)) is not None
    ]
    declared_target_ids = {
        value for raw in target_spec.get("geometry_ids") or []
        if (value := _positive_id(raw)) is not None
    }
    source_by_id = {
        value: item for item in source
        if isinstance(item, dict)
        and (value := _positive_id(item.get("id"))) is not None
    }
    target_by_id = {
        value: item for item in target
        if isinstance(item, dict)
        and (value := _positive_id(item.get("id"))) is not None
    }
    actual_added = set(target_by_id) - set(source_by_id)
    errors: list[str] = []
    if target_spec.get("scope") != "logical_object":
        errors.append("拆分操作没有绑定逻辑对象")
    if len(shared_ids) != len(set(shared_ids)) or len(created_ids) != len(set(created_ids)):
        errors.append("边界 ID 存在重复")
    if not shared_ids or len(shared_ids) != len(created_ids):
        errors.append("共享边界与新边界数量不一致")
    if not set(shared_ids).issubset(declared_target_ids):
        errors.append("共享边界不属于声明目标")
    if any(value not in source_by_id for value in shared_ids):
        errors.append("共享边界已不存在")
    if set(created_ids) != actual_added:
        errors.append("新增边界与协议声明不一致")
    try:
        dx = float(parameters["dx_mm"])
        dy = float(parameters["dy_mm"])
    except (KeyError, TypeError, ValueError):
        dx = dy = math.nan
        errors.append("拆分平移参数无效")

    mismatched_pairs: list[dict[str, int]] = []
    for shared_id, created_id in zip(sorted(shared_ids), sorted(created_ids)):
        source_item = source_by_id.get(shared_id)
        created_item = target_by_id.get(created_id)
        original_item = target_by_id.get(shared_id)
        if source_item is None or created_item is None:
            mismatched_pairs.append({"shared_geometry_id": shared_id,
                                     "created_geometry_id": created_id})
            continue
        expected = json.loads(json.dumps(source_item, ensure_ascii=False))
        expected["id"] = created_id
        for key in ("start", "end", "center", "position"):
            point = expected.get(key)
            if isinstance(point, dict):
                point["x"] = float(point["x"]) + dx
                point["y"] = float(point["y"]) + dy
        for key in ("vertices", "control_points"):
            for point in expected.get(key) or []:
                if isinstance(point, dict):
                    point["x"] = float(point["x"]) + dx
                    point["y"] = float(point["y"]) + dy
        if (
            _semantic_geometry_fingerprint([expected])
            != _semantic_geometry_fingerprint([created_item])
            or original_item is None
            or _semantic_geometry_fingerprint([source_item])
            != _semantic_geometry_fingerprint([original_item])
        ):
            mismatched_pairs.append({"shared_geometry_id": shared_id,
                                     "created_geometry_id": created_id})
    if mismatched_pairs:
        errors.append("新边界不是原共享边界的精确平移副本")
    return {
        "enforced": True,
        "verified": not errors,
        "reason": None if not errors else "split_boundary_provenance_mismatch",
        "message": (
            "新增边界均来自声明共享边界的确定性复制。"
            if not errors else "共享边界拆分来源校验失败，已阻止保存：" + "；".join(errors)
        ),
        "shared_geometry_ids": sorted(shared_ids),
        "created_geometry_ids": sorted(created_ids),
        "mismatched_pairs": mismatched_pairs,
    }


def validate_target_change_scope(
    source: list[dict[str, Any]],
    target: list[dict[str, Any]],
    target_spec: dict[str, Any],
    *,
    operation: str = "",
    created_instance_id: int | None = None,
    expected_modified_ids: set[int] | None = None,
    expected_removed_ids: set[int] | None = None,
    expected_added_ids: set[int] | None = None,
    allowed_added_ids: set[int] | None = None,
    preserve_source: bool = True,
) -> dict[str, Any]:
    """Verify that actual geometry changes cannot escape the declared target."""
    difference = build_geometry_diff(source, target)
    modified_ids = {
        value for change in difference.get("modified") or []
        if isinstance(change, dict)
        and isinstance(change.get("before"), dict)
        and (value := _positive_id(change["before"].get("id"))) is not None
    }
    removed_ids = {
        value for item in difference.get("removed") or []
        if isinstance(item, dict)
        and (value := _positive_id(item.get("id"))) is not None
    }
    added_ids = {
        value for item in difference.get("added") or []
        if isinstance(item, dict)
        and (value := _positive_id(item.get("id"))) is not None
    }
    scope = str(target_spec.get("scope") or "")
    geometry_ids = {
        value for raw in target_spec.get("geometry_ids") or []
        if (value := _positive_id(raw)) is not None
    }
    instance_ids = {
        value for raw in target_spec.get("instance_ids") or []
        if (value := _positive_id(raw)) is not None
    }
    source_ids = {
        value for item in source if isinstance(item, dict)
        if (value := _positive_id(item.get("id"))) is not None
    }
    if scope in {"geometry", "logical_object"} and geometry_ids and not instance_ids:
        allowed_existing_ids = geometry_ids
    elif scope == "instance" and instance_ids and not geometry_ids:
        allowed_existing_ids = {
            value for item in source if isinstance(item, dict)
            and _positive_id(item.get("template_instance")) in instance_ids
            if (value := _positive_id(item.get("id"))) is not None
        }
    else:
        return {
            "ok": False,
            "reason": "invalid_target",
            "message": "修改目标必须明确为图元或实例，且只能使用一种目标范围。",
            "actual": {},
        }
    if not allowed_existing_ids or not allowed_existing_ids.issubset(source_ids):
        return {
            "ok": False,
            "reason": "stale_target",
            "message": "目标图元或实例已不存在，请重新载入图纸。",
            "actual": {},
        }

    changed_existing_ids = modified_ids | removed_ids
    unexpected_existing: set[int]
    unexpected_added: set[int] = set()
    if operation == "retain":
        unexpected_existing = modified_ids | (removed_ids & allowed_existing_ids)
    elif operation in {'duplicate','mirror','offset','array'} and allowed_added_ids is not None:
        declared=set(allowed_added_ids)
        unexpected_existing=changed_existing_ids if operation=='duplicate' else changed_existing_ids-allowed_existing_ids
        unexpected_added=added_ids-declared
        if declared!=added_ids:
            unexpected_added|=declared-added_ids
    elif operation == "duplicate":
        unexpected_existing = changed_existing_ids
        if created_instance_id is None:
            unexpected_added = added_ids
        else:
            unexpected_added = {
                value for item in difference.get("added") or []
                if isinstance(item, dict)
                and _positive_id(item.get("template_instance")) != created_instance_id
                if (value := _positive_id(item.get("id"))) is not None
            }
    elif operation in {"mirror", "offset", "array"}:
        unexpected_existing = changed_existing_ids - allowed_existing_ids
        source_instances = {
            value for item in source if isinstance(item, dict)
            if (value := _positive_id(item.get("template_instance"))) is not None
        }

        def _allowed_added_instance(instance_value: int | None) -> bool:
            if instance_value is None:
                return False
            if instance_value in instance_ids:
                # replacement inside a declared target instance
                return True
            if (
                created_instance_id is not None
                and instance_value >= created_instance_id
                and instance_value not in source_instances
            ):
                # fresh instances generated by mirror / offset / array
                return True
            return False

        unexpected_added = {
            value for item in difference.get("added") or []
            if isinstance(item, dict)
            and not _allowed_added_instance(_positive_id(item.get("template_instance")))
            if (value := _positive_id(item.get("id"))) is not None
        }
    else:
        unexpected_existing = changed_existing_ids - allowed_existing_ids
        if added_ids:
            if allowed_added_ids is not None:
                unexpected_added = added_ids - allowed_added_ids
            elif scope not in {"instance", "logical_object"}:
                unexpected_added = set(added_ids)
            else:
                unexpected_added = {
                    value for item in difference.get("added") or []
                    if isinstance(item, dict)
                    and _positive_id(item.get("template_instance")) not in instance_ids
                    if (value := _positive_id(item.get("id"))) is not None
                }

    protected_ids = (
        allowed_existing_ids
        if operation == "retain"
        else source_ids - allowed_existing_ids
        if operation == "mirror" and (not preserve_source or removed_ids & allowed_existing_ids)
        else source_ids
        if operation in {"duplicate", "mirror", "offset", "array"}
        else source_ids - allowed_existing_ids
    )
    source_by_id = {
        value: item for item in source if isinstance(item, dict)
        if (value := _positive_id(item.get("id"))) is not None
    }
    target_by_id = {
        value: item for item in target if isinstance(item, dict)
        if (value := _positive_id(item.get("id"))) is not None
    }
    source_protected_hashes = {
        value: geometry_entity_fingerprint(source_by_id[value])
        for value in sorted(protected_ids) if value in source_by_id
    }
    target_protected_hashes = {
        value: geometry_entity_fingerprint(target_by_id[value])
        for value in sorted(protected_ids) if value in target_by_id
    }
    hash_mismatch_ids = sorted(
        value for value in protected_ids
        if source_protected_hashes.get(value) != target_protected_hashes.get(value)
    )

    def hash_root(values: dict[int, str]) -> str:
        payload = json.dumps(values, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    non_target_integrity = {
        "verified": not hash_mismatch_ids,
        "protected_geometry_count": len(protected_ids),
        "protected_geometry_ids": sorted(protected_ids),
        "mismatched_geometry_ids": hash_mismatch_ids,
        "source_hash_root": hash_root(source_protected_hashes),
        "target_hash_root": hash_root(target_protected_hashes),
    }

    mismatch: dict[str, list[int]] = {}
    for label, actual, expected in (
        ("modified", modified_ids, expected_modified_ids),
        ("removed", removed_ids, expected_removed_ids),
        ("added", added_ids, expected_added_ids),
    ):
        if expected is not None and actual != expected:
            mismatch[label] = sorted(actual ^ expected)

    ok = (
        not unexpected_existing
        and not unexpected_added
        and not mismatch
        and non_target_integrity["verified"]
    )
    return {
        "ok": ok,
        "reason": None if ok else "change_scope_mismatch",
        "message": (
            "实际变化与声明目标范围一致。"
            if ok else "实际变化超出声明目标或与操作清单不一致，已阻止保存。"
        ),
        "target": {
            "scope": scope,
            "allowed_existing_ids": sorted(allowed_existing_ids),
            "instance_ids": sorted(instance_ids),
        },
        "actual": {
            "modified_ids": sorted(modified_ids),
            "removed_ids": sorted(removed_ids),
            "added_ids": sorted(added_ids),
        },
        "unexpected_existing_ids": sorted(unexpected_existing),
        "unexpected_added_ids": sorted(unexpected_added),
        "operation_mismatch": mismatch,
        "non_target_integrity": non_target_integrity,
    }


def build_cad_edit_preflight(
    source: list[dict[str, Any]],
    target: list[dict[str, Any]],
    contract: dict[str, Any],
) -> dict[str, Any]:
    """Reject invalid edits and require confirmation for high-impact changes."""
    checks: list[dict[str, Any]] = []

    def check(code: str, label: str, ok: bool, detail: str) -> None:
        checks.append({"code": code, "label": label, "ok": ok, "detail": detail})

    difference = build_geometry_diff(source, target)
    counts = difference.get("counts") or {}
    changed = sum(int(counts.get(key) or 0) for key in ("added", "removed", "modified"))
    operation = str(contract.get("operation") or "").lower()
    rotational_invariant = (
        operation in {"rotate", "rotation"}
        and bool(source)
        and bool(target)
        and all(str(item.get("type") or "").lower() == "circle" for item in source + target)
    )
    check(
        "geometry_change", "几何变化", changed > 0 or rotational_invariant,
        ("检测到旋转操作；圆形绕自身中心旋转后几何保持不变，按操作验收通过"
         if rotational_invariant and not changed
         else f"检测到 {changed} 项几何变化" if changed else "修改前后没有几何变化"),
    )
    check(
        "target_not_empty", "结果图纸", bool(target),
        "结果仍包含有效图元" if target else "修改会清空整张图纸",
    )
    finite = _finite_coordinates(target)
    check(
        "finite_coordinates", "坐标有效性", finite,
        "全部坐标均为有限数值" if finite else "结果包含无穷大或非数值坐标",
    )
    target_ids = [item.get("id") for item in target if isinstance(item, dict)]
    stable_ids = (
        len(target_ids) == len(target)
        and all(isinstance(value, int) and value > 0 for value in target_ids)
        and len(target_ids) == len(set(target_ids))
    )
    check(
        "stable_geometry_ids", "稳定图元 ID", stable_ids,
        "图元 ID 完整且无重复" if stable_ids else "结果包含缺失、无效或重复的图元 ID",
    )

    effect_validation = validate_declared_edit_effect(source, target, contract)
    from .cad_edit_relation_acceptance import validate_edit_relations
    relation_validation = validate_edit_relations(source, target, contract)
    check("object_relation_acceptance", "对象关系独立验收", relation_validation["verified"], relation_validation["message"])
    already_satisfied = (
        changed == 0 and relation_validation["enforced"] and relation_validation["verified"]
        and geometry_fingerprint(source) == geometry_fingerprint(target)
    )
    if already_satisfied:
        checks[0].update(ok=True, detail="独立几何验收确认关系已满足，无需修改图元")
    check(
        "declared_edit_effect",
        "修改参数一致性",
        effect_validation.get("verified") is not False,
        str(effect_validation.get("message") or "修改参数复核完成。"),
    )

    split_validation = validate_split_shared_boundary_provenance(
        source, target, contract
    )
    check(
        "split_boundary_provenance",
        "共享边界来源",
        split_validation.get("verified") is True,
        str(split_validation.get("message") or "共享边界来源复核完成。"),
    )

    operation = str(contract.get("operation") or "")
    parameters = contract.get("parameters") if isinstance(contract.get("parameters"), dict) else {}
    risk_reasons: list[str] = []
    warning_reasons: list[str] = []
    removed = int(counts.get("removed") or 0)
    removal_ratio = removed / max(1, len(source))
    if operation in {"delete", "retain"}:
        warning_reasons.append(f"将删除 {removed} 个图元（{removal_ratio:.0%}）")
        if removal_ratio > 0.5:
            risk_reasons.append("删除范围超过原图一半")
    if operation == "translate":
        distance = math.hypot(
            float(parameters.get("dx_mm") or 0),
            float(parameters.get("dy_mm") or 0),
        )
        if distance > 10000:
            risk_reasons.append(f"平移距离为 {distance / 1000:g} 米")
        elif distance > 5000:
            warning_reasons.append(f"平移距离较大：{distance / 1000:g} 米")
        if parameters.get("boundary_policy") == "split_shared":
            risk_reasons.append("将拆分共享边界并重建目标侧边界")
    if operation == "scale":
        factor = float(parameters.get("factor") or 0)
        if factor < 0.5 or factor > 2:
            risk_reasons.append(f"缩放倍数为 {factor:g}")
        elif factor < 0.75 or factor > 1.5:
            warning_reasons.append(f"缩放幅度较大：{factor:g} 倍")
    if operation == "rotate":
        angle = abs(float(parameters.get("angle_degrees") or 0))
        if angle > 180:
            risk_reasons.append(f"旋转角度为 {angle:g} 度")
    if operation in {"mirror", "offset", "array"}:
        added_count = int(counts.get("added") or 0)
        if added_count > 0:
            warning_reasons.append(f"将新增 {added_count} 个图元")
        if operation == "array":
            risk_reasons.append("阵列生成多个副本，确认后再应用")
        elif operation == "mirror" and parameters.get("keep_source", True) is not False:
            warning_reasons.append("镜像将保留原图并生成镜像副本")
        elif operation == "offset":
            warning_reasons.append("偏移将生成等距副本")
    if operation == "constraint":
        warning_reasons.append("将调整图形位置或尺寸以满足几何约束")
    if operation == "chain":
        warning_reasons.append(
            f"将按顺序执行 {len(contract.get('chain_steps') or [])} 个修改步骤"
        )
        for step in contract.get("chain_steps") or []:
            step_operation = str(step.get("operation") or "")
            step_parameters = step.get("parameters") or {}
            if step_operation == "translate" and math.hypot(
                float(step_parameters.get("dx_mm") or 0),
                float(step_parameters.get("dy_mm") or 0),
            ) > 10000:
                risk_reasons.append("复合修改包含超过 10 米的平移")
            if step_operation == "scale" and (
                float(step_parameters.get("factor") or 0) < 0.5
                or float(step_parameters.get("factor") or 0) > 2
            ):
                risk_reasons.append("复合修改包含高幅度缩放")
    target_info = contract.get("target") if isinstance(contract.get("target"), dict) else {}
    if target_info:
        scope_validation = validate_target_change_scope(
            source,
            target,
            target_info,
            operation=operation,
            created_instance_id=_positive_id(contract.get("created_instance_id")),
            preserve_source=parameters.get('keep_source', True) is not False,
            allowed_added_ids={
                value for raw in parameters.get("created_geometry_ids") or []
                if (value := _positive_id(raw)) is not None
            } if (
                parameters.get("boundary_policy") == "split_shared"
                or operation in {"add_constrained", "add_template", "add_geometry", "rearrange_layout"}
                or (operation in {"duplicate","mirror","offset","array"} and bool(parameters.get('created_geometry_ids')))
            ) else None,
        )
        check(
            "target_change_scope",
            "目标范围一致性",
            scope_validation["ok"],
            scope_validation["message"],
        )
        integrity = scope_validation.get("non_target_integrity") or {}
        check(
            "non_target_integrity",
            "非目标哈希不变",
            integrity.get("verified") is True,
            (
                f"{integrity.get('protected_geometry_count', 0)} 个受保护图元哈希保持不变"
                if integrity.get("verified") is True
                else "非目标图元哈希发生变化："
                + ", ".join(str(value) for value in integrity.get("mismatched_geometry_ids") or [])
            ),
        )
    else:
        scope_validation = None
    selected_count = len(
        target_info.get("instance_ids") or target_info.get("geometry_ids") or []
    )
    if selected_count >= 10:
        risk_reasons.append(f"一次修改 {selected_count} 个目标")
    elif selected_count >= 5:
        warning_reasons.append(f"一次修改 {selected_count} 个目标")

    risk_level = "high" if risk_reasons else "medium" if warning_reasons else "low"
    ready = all(item["ok"] for item in checks)
    return {
        "schema": "cad.preflight.v1",
        "ready": ready,
        "already_satisfied": ready and already_satisfied,
        "risk_level": risk_level,
        "requires_confirmation": ready and risk_level == "high",
        "risk_reasons": risk_reasons,
        "warnings": warning_reasons,
        "checks": checks,
        "split_boundary_validation": split_validation,
        "diff": difference,
        "source_fingerprint": geometry_fingerprint(source),
        "target_fingerprint": geometry_fingerprint(target),
        "scope_validation": scope_validation,
        "effect_validation": effect_validation,
        "relation_validation": relation_validation,
    }
