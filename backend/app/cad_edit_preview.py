"""Deterministic, read-only preview contracts for CAD candidate edits."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from .cad_edit_gate import build_cad_edit_preflight, geometry_fingerprint
from .geometry_diff import build_path_impact


def _fingerprint(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _geometry_ids(items: list[dict[str, Any]]) -> list[int]:
    return sorted({
        int(item["id"])
        for item in items
        if isinstance(item, dict) and str(item.get("id", "")).isdigit()
    })


def _normalized_contract(contract: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(contract)
    target = normalized.get("target")
    if isinstance(target, dict):
        scope = target.get("scope")
        if scope != "logical_object":
            target.pop("object_id", None)
            target.pop("object_ids", None)
        if scope != "instance":
            target.pop("instance_ids", None)
        if scope != "geometry" and scope != "logical_object":
            target.pop("geometry_ids", None)
    return normalized


def build_cad_edit_preview(
    source: list[dict[str, Any]],
    target: list[dict[str, Any]],
    contract: dict[str, Any],
    *,
    preflight: dict[str, Any] | None = None,
    target_resolution: dict[str, Any] | list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Describe the exact working-copy result before it may be persisted."""
    checked = preflight or build_cad_edit_preflight(source, target, contract)
    normalized_contract = _normalized_contract(contract)
    difference = checked.get("diff") if isinstance(checked.get("diff"), dict) else {}
    path_impact = build_path_impact(source, target)
    modified_ids = sorted({
        int(item["after"]["id"])
        for item in difference.get("modified") or []
        if isinstance(item, dict)
        and isinstance(item.get("after"), dict)
        and str(item["after"].get("id", "")).isdigit()
    })
    core = {
        "schema": "cad.edit-preview.v1",
        "review_only": True,
        "operation": str(normalized_contract.get("operation") or ""),
        "source": {
            "geometry_sha256": geometry_fingerprint(source),
            "geometry_count": len(source),
        },
        "candidate": {
            "geometry_sha256": geometry_fingerprint(target),
            "geometry_count": len(target),
        },
        "contract_sha256": _fingerprint(normalized_contract),
        "target": deepcopy(normalized_contract.get("target") or {}),
        "target_resolution": deepcopy(target_resolution),
        "changes": {
            "counts": deepcopy(difference.get("counts") or {}),
            "added_geometry_ids": _geometry_ids(difference.get("added") or []),
            "removed_geometry_ids": _geometry_ids(difference.get("removed") or []),
            "modified_geometry_ids": modified_ids,
        },
        "path_impact": path_impact,
        "validation": {
            "ready": checked.get("ready") is True,
            "checks": deepcopy(checked.get("checks") or []),
        },
        "risk": {
            "level": str(checked.get("risk_level") or "low"),
            "reasons": list(checked.get("risk_reasons") or []),
            "warnings": list(checked.get("warnings") or []),
        },
        "execution": {
            "requires_confirmation": checked.get("requires_confirmation") is True,
            "persisted": False,
            "execution_allowed": False,
        },
    }
    return {
        **core,
        "preview_sha256": _fingerprint(core),
    }


def validate_cad_edit_preview(
    preview: dict[str, Any],
    source: list[dict[str, Any]],
    target: list[dict[str, Any]],
    contract: dict[str, Any],
    *,
    preflight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Prove that persisted geometry is exactly the geometry shown in preview."""
    if preview.get("schema") != "cad.edit-preview.v1":
        return {"verified": False, "reason": "invalid_preview_schema"}
    rebuilt = build_cad_edit_preview(
        source,
        target,
        contract,
        preflight=preflight,
        target_resolution=preview.get("target_resolution"),
    )
    expected_hash = str(preview.get("preview_sha256") or "")
    provided_core = {
        key: deepcopy(value)
        for key, value in preview.items()
        if key != "preview_sha256"
    }
    provided_hash = _fingerprint(provided_core)
    actual_hash = str(rebuilt["preview_sha256"])
    payload_intact = bool(expected_hash) and expected_hash == provided_hash
    verified = payload_intact and expected_hash == actual_hash
    return {
        "verified": verified,
        "reason": (
            None if verified else
            "preview_payload_tampered" if not payload_intact else
            "preview_result_mismatch"
        ),
        "expected_preview_sha256": expected_hash,
        "provided_preview_sha256": provided_hash,
        "actual_preview_sha256": actual_hash,
        "source_geometry_sha256": rebuilt["source"]["geometry_sha256"],
        "candidate_geometry_sha256": rebuilt["candidate"]["geometry_sha256"],
        "preview": rebuilt,
    }
