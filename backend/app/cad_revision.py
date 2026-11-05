"""Unified diff, validation, snapshot and rollback contract for CAD revisions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

from .agent_skills import diff_drawings, snapshot_drawing, validate_drawing
from .logical_topology import (
    logical_object_ids_for_edit,
    logical_graph_fingerprint,
    validate_logical_object_continuity,
    validate_logical_object_graph,
)


def build_cad_revision_contract(
    source: list[dict[str, Any]],
    target: list[dict[str, Any]],
    *,
    parent_variant_id: str,
    variant_id: str,
    edit_contract: dict[str, Any] | None = None,
    source_logical_objects: list[dict[str, Any]] | None = None,
    target_logical_objects: list[dict[str, Any]] | None = None,
    source_topology: dict[str, Any] | None = None,
    target_topology: dict[str, Any] | None = None,
) -> dict[str, Any]:
    before = snapshot_drawing(source, "修改前")
    after = snapshot_drawing(target, "修改后")
    difference = diff_drawings(source, target)
    before_validation = validate_drawing(source)
    after_validation = validate_drawing(target)
    logical_validation = validate_logical_object_continuity(
        source,
        target,
        source_logical_objects,
        target_logical_objects,
        source_topology,
        target_topology,
        target_object_ids=logical_object_ids_for_edit(
            source, source_logical_objects, edit_contract
        ),
        edit_contract=edit_contract,
    )
    counts = difference.get("geometry_diff", {}).get("counts", {})
    changed = sum(
        int(counts.get(key) or 0) for key in ("added", "removed", "modified")
    )
    verified = (
        before.get("ok") is True
        and after.get("ok") is True
        and before.get("sha256") != after.get("sha256")
        and changed > 0
        and after_validation.get("ok") is True
        and logical_validation.get("verified") is True
    )
    return {
        "schema": "cad.revision.v1",
        "status": "verified" if verified else "invalid",
        "parent_variant_id": parent_variant_id,
        "variant_id": variant_id,
        "before_snapshot": before,
        "after_snapshot": after,
        "diff": difference,
        "validation": {
            "before": before_validation,
            "after": after_validation,
        },
        "logical_object_validation": logical_validation,
        "logical_object_diff": logical_validation["diff"],
        "logical_graph_fingerprint": logical_graph_fingerprint(
            target_logical_objects, target_topology
        ),
        "edit_contract": deepcopy(edit_contract) if isinstance(edit_contract, dict) else None,
        "rollback": {
            "available": verified,
            "target_variant_id": parent_variant_id,
            "expected_snapshot_id": before.get("snapshot_id"),
            "expected_sha256": before.get("sha256"),
        },
        "execution_allowed": False,
    }


def verify_cad_revision_state(
    revision: dict[str, Any] | None,
    geometries: list[dict[str, Any]],
    expected: Literal["before", "after"],
) -> dict[str, Any]:
    current = snapshot_drawing(geometries, "回滚复核" if expected == "before" else "重做复核")
    key = "before_snapshot" if expected == "before" else "after_snapshot"
    recorded = revision.get(key) if isinstance(revision, dict) else None
    expected_sha = recorded.get("sha256") if isinstance(recorded, dict) else None
    verified = bool(expected_sha and current.get("sha256") == expected_sha)
    return {
        "schema": "cad.rollback.verification.v1",
        "status": "success" if verified else "failed",
        "verified": verified,
        "expected": expected,
        "expected_sha256": expected_sha,
        "actual_sha256": current.get("sha256"),
        "snapshot": current,
    }


def verify_variant_revision_for_planning(
    variant: dict[str, Any] | None,
) -> dict[str, Any]:
    """Bind planning to the exact, previously verified candidate geometry."""
    if not isinstance(variant, dict):
        return _planning_source_result(False, "missing_variant", "候选方案不存在")
    from .cad_candidate_state import candidate_is_accepted
    if not candidate_is_accepted(variant):
        return _planning_source_result(False, "acceptance_not_passed", "候选尚未通过需求验收")
    geometries = variant.get("geometries")
    if not isinstance(geometries, list) or not geometries:
        return _planning_source_result(False, "missing_geometry", "候选方案没有有效图形")
    current = snapshot_drawing(geometries, "规划源")
    logical_objects = variant.get("logical_objects")
    topology = variant.get("topology")
    logical_validation = validate_logical_object_graph(
        geometries,
        logical_objects if isinstance(logical_objects, list) else [],
        topology if isinstance(topology, dict) else {},
    )
    if logical_validation.get("verified") is not True:
        return _planning_source_result(
            False, "invalid_logical_graph", "候选方案的对象关系已损坏，请重新生成候选方案",
            variant=variant, snapshot=current,
        )
    parent_variant_id = variant.get("parent_variant_id")
    if not parent_variant_id:
        return _planning_source_result(
            current.get("ok") is True,
            "verified" if current.get("ok") is True else "snapshot_failed",
            "候选方案已绑定规划快照" if current.get("ok") is True else "无法生成候选方案快照",
            variant=variant,
            snapshot=current,
        )

    revision = variant.get("revision_contract")
    if not isinstance(revision, dict):
        return _planning_source_result(
            False, "missing_revision", "修改后的候选缺少版本验证，请重新生成候选方案",
            variant=variant, snapshot=current,
        )
    after = revision.get("after_snapshot")
    validation = revision.get("validation")
    after_validation = validation.get("after") if isinstance(validation, dict) else None
    expected_sha = after.get("sha256") if isinstance(after, dict) else None
    checks = {
        "schema": revision.get("schema") == "cad.revision.v1",
        "status": revision.get("status") == "verified",
        "variant_id": revision.get("variant_id") == variant.get("id"),
        "parent_variant_id": revision.get("parent_variant_id") == parent_variant_id,
        "snapshot": bool(expected_sha and current.get("sha256") == expected_sha),
        "validation": isinstance(after_validation, dict)
        and after_validation.get("ok") is True,
    }
    if logical_objects:
        recorded_logical = revision.get("logical_object_validation")
        checks["logical_objects"] = (
            isinstance(recorded_logical, dict)
            and recorded_logical.get("verified") is True
            and revision.get("logical_graph_fingerprint")
            == logical_graph_fingerprint(logical_objects, topology)
        )
    verified = all(checks.values())
    return _planning_source_result(
        verified,
        "verified" if verified else "revision_mismatch",
        "候选修改及规划源已验证" if verified else "候选内容与已验证版本不一致，请重新生成候选方案",
        variant=variant,
        snapshot=current,
        checks=checks,
    )


def _planning_source_result(
    ok: bool,
    reason: str,
    message: str,
    *,
    variant: dict[str, Any] | None = None,
    snapshot: dict[str, Any] | None = None,
    checks: dict[str, bool] | None = None,
) -> dict[str, Any]:
    return {
        "schema": "cad.planning-source.v1",
        "ok": ok,
        "reason": reason,
        "message": message,
        "variant_id": variant.get("id") if isinstance(variant, dict) else None,
        "parent_variant_id": (
            variant.get("parent_variant_id") if isinstance(variant, dict) else None
        ),
        "snapshot_id": snapshot.get("snapshot_id") if isinstance(snapshot, dict) else None,
        "sha256": snapshot.get("sha256") if isinstance(snapshot, dict) else None,
        "checks": checks or {},
    }
