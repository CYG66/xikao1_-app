"""Parse and atomically replay ordered CAD edits on stable targets."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from .cad_edit_contract import CadEditCommand, cad_edit_contract_to_edit
from .incremental_cad import edit_candidate_geometries, parse_incremental_edit


_ALLOWED_CHAIN_OPERATIONS = {"translate", "rotate", "scale", "resize", "align"}


def _target_prefix(edit: dict[str, Any]) -> str | None:
    instances = edit.get("instances")
    if isinstance(instances, list) and instances:
        return "第" + "个和第".join(str(value) for value in instances) + "个图形"
    if isinstance(edit.get("instance"), int):
        return f"第{edit['instance']}个图形"
    return None


def _target_signature(edit: dict[str, Any]) -> tuple[int, ...]:
    values = edit.get("instances")
    if isinstance(values, list) and values:
        return tuple(int(value) for value in values)
    return (int(edit["instance"]),) if isinstance(edit.get("instance"), int) else ()


def parse_incremental_edit_chain(message: str, *, selection_bound: bool=False) -> list[dict[str, Any]] | None:
    """Parse ordered clauses, inheriting the most recently stated target."""
    if not any(marker in message for marker in ("先", "再", "然后", "随后", "接着","并")):
        return None
    text = re.sub(r"^\s*(?:先|首先)\s*", "", message.strip())
    clauses = [
        value.strip(" ，,；;")
        for value in re.split(r"(?:，|,|；|;)?\s*(?:再|然后|随后|接着|并且?|并)\s*(?=(?:等比|把|将|向|往|逆时针|顺时针|旋转|缩小|放大|缩放|平移|移动|第))", text)
        if value.strip(" ，,；;")
    ]
    if not 2 <= len(clauses) <= 8:
        return None
    first = parse_incremental_edit(clauses[0]+(' 图形' if selection_bound else ''))
    if first is None or first.get("operation") not in _ALLOWED_CHAIN_OPERATIONS:
        return None
    prefix = _target_prefix(first) or ('选中的图形' if selection_bound else None)
    if not selection_bound and (not _target_signature(first) or prefix is None):
        return None
    edits = [first]
    for clause in clauses[1:]:
        edit = parse_incremental_edit(clause)
        if edit is None or not _target_signature(edit):
            edit = parse_incremental_edit(f"{prefix}{clause}")
        if (
            edit is None
            or edit.get("operation") not in _ALLOWED_CHAIN_OPERATIONS
            or (not selection_bound and not _target_signature(edit))
        ):
            return None
        edits.append(edit)
        prefix = _target_prefix(edit) or ('选中的图形' if selection_bound else None)
        if prefix is None:
            return None
    return edits


def replay_cad_edit_chain(
    source: list[dict[str, Any]], contract: dict[str, Any]
) -> tuple[list[dict[str, Any]] | None, str | None, list[dict[str, Any]]]:
    """Replay all steps on an isolated working copy; return nothing on failure."""
    try:
        command = CadEditCommand.model_validate(contract)
    except (TypeError, ValueError) as exc:
        return None, f"复合修改协议无效：{exc}", []
    if command.operation != "chain":
        return None, "当前协议不是复合修改链。", []
    working = deepcopy(source)
    evidence: list[dict[str, Any]] = []
    for index, step_contract in enumerate(command.chain_steps, 1):
        try:
            edit = cad_edit_contract_to_edit(step_contract)
        except (TypeError, ValueError) as exc:
            return None, f"第 {index} 步协议无效：{exc}", evidence
        updated, error = edit_candidate_geometries(working, edit)
        if updated is None:
            return None, f"第 {index} 步失败：{error or '无法执行'}", evidence
        from .cad_edit_gate import build_cad_edit_preflight

        preflight = build_cad_edit_preflight(working, updated, step_contract)
        difference = preflight.get("diff") or {}
        modified_ids = sorted(
            int(item["after"]["id"])
            for item in difference.get("modified") or []
            if str((item.get("after") or {}).get("id", "")).isdigit()
        )
        step_evidence = {
            "step": index,
            "operation": edit["operation"],
            "target": deepcopy(step_contract.get("target") or {}),
            "input_geometry_count": len(working),
            "output_geometry_count": len(updated),
            "input_fingerprint": preflight.get("source_fingerprint"),
            "output_fingerprint": preflight.get("target_fingerprint"),
            "modified_geometry_ids": modified_ids,
            "geometry_changed": preflight.get('source_fingerprint') != preflight.get('target_fingerprint'),
            "effect_validation": deepcopy(preflight.get('effect_validation') or {}),
            "verification": {
                "verified": preflight.get("ready") is True,
                "risk_level": preflight.get("risk_level"),
                "failed_check_codes": [
                    str(item.get("code") or "")
                    for item in preflight.get("checks") or []
                    if item.get("ok") is not True
                ],
            },
        }
        evidence.append(step_evidence)
        if preflight.get("ready") is not True:
            details = "；".join(
                str(item.get("detail") or item.get("label") or "复核失败")
                for item in preflight.get("checks") or []
                if item.get("ok") is not True
            )
            return None, f"第 {index} 步复核失败：{details}", evidence
        working = updated
    return working, None, evidence
