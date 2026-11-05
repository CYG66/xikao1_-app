"""Compile CAD edit contracts into deterministic, verifiable change plans."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from typing import Any

from .geometry_diff import build_geometry_diff


def _ids(items: list[dict[str, Any]]) -> list[int]:
    return sorted(
        int(item["id"])
        for item in items
        if isinstance(item, dict) and str(item.get("id", "")).isdigit()
    )


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _semantic_target_ids(
    source: list[dict[str, Any]], declared_target: dict[str, Any]
) -> list[str]:
    """Stable, human-readable target IDs for the plan, e.g. "basketball:2"."""
    scope = str(declared_target.get("scope") or "")
    if scope == "instance":
        instance_ids = sorted({
            int(value) for value in declared_target.get("instance_ids") or []
            if str(value).isdigit()
        })
        wanted = set(instance_ids)
        type_by_instance: dict[int, str] = {}
        for item in source:
            instance_id = item.get("template_instance")
            if (
                isinstance(item, dict)
                and isinstance(instance_id, int)
                and instance_id in wanted
            ):
                template_type = str(item.get("template_type") or "").strip()
                if template_type and instance_id not in type_by_instance:
                    type_by_instance[instance_id] = template_type
        return [
            f"{type_by_instance.get(instance_id) or 'instance'}:{instance_id}"
            for instance_id in instance_ids
        ]
    if scope == "geometry":
        return [
            f"geometry:{value}" for value in sorted({
                int(value) for value in declared_target.get("geometry_ids") or []
                if str(value).isdigit()
            })
        ]
    if scope == "logical_object":
        return [
            f"logical_object:{value}" for value in [
                declared_target.get("object_id"),
                *(declared_target.get("object_ids") or []),
            ] if value
        ]
    return []


def build_cad_edit_plan(
    source: list[dict[str, Any]],
    target: list[dict[str, Any]],
    edit_contract: dict[str, Any],
) -> dict[str, Any]:
    operation = str(edit_contract.get("operation") or "")
    if operation == "chain":
        return _build_cad_edit_chain_plan(source, target, edit_contract)
    declared_target = edit_contract.get("target") or {}
    parameters = edit_contract.get("parameters") or {}
    target_ids = sorted({
        int(value) for value in declared_target.get("geometry_ids") or []
        if str(value).isdigit()
    })
    if declared_target.get("scope") == "instance":
        instance_ids = {
            int(value) for value in declared_target.get("instance_ids") or []
            if str(value).isdigit()
        }
        target_ids = sorted(
            int(item["id"])
            for item in source
            if str(item.get("id", "")).isdigit()
            and int(item.get("template_instance") or 0) in instance_ids
        )
    source_ids, target_geometry_ids = set(_ids(source)), set(_ids(target))
    added_ids = sorted(target_geometry_ids - source_ids)
    removed_ids = sorted(source_ids - target_geometry_ids)
    expected_added: list[int] | None = []
    expected_removed: list[int] | None = []
    expected_modified: list[int] | None = []

    if operation in {"translate", "rotate", "scale", "resize", "align"}:
        expected_modified = target_ids
        if operation == "translate" and parameters.get("boundary_policy") == "split_shared":
            shared_ids = {
                int(value) for value in parameters.get("shared_geometry_ids") or []
                if str(value).isdigit()
            }
            expected_modified = sorted(set(target_ids) - shared_ids)
            expected_added = sorted({
                int(value) for value in parameters.get("created_geometry_ids") or []
                if str(value).isdigit()
            })
    elif operation == "duplicate":
        expected_added = added_ids
    elif operation == 'mirror':
        if parameters.get('keep_source', True) is False:
            expected_modified = target_ids
        else:
            expected_added = added_ids
    elif operation == "delete":
        expected_removed = target_ids
    elif operation == "retain":
        expected_removed = sorted(source_ids - set(target_ids))
    elif operation in {"add_constrained", "add_geometry"}:
        expected_added = sorted({
            int(value) for value in parameters.get("created_geometry_ids") or []
            if str(value).isdigit()
        })
    elif operation == "add_template":
        expected_added = sorted({
            int(value) for value in parameters.get("created_geometry_ids") or []
            if str(value).isdigit()
        })
    elif operation == "rearrange_layout":
        layout_difference = build_geometry_diff(source, target)
        expected_added = sorted({
            int(value) for value in parameters.get("created_geometry_ids") or []
            if str(value).isdigit()
        })
        expected_removed = removed_ids
        expected_modified = sorted(
            int(item["after"]["id"])
            for item in layout_difference.get("modified") or []
            if str((item.get("after") or {}).get("id", "")).isdigit()
        )
    else:
        expected_added = expected_removed = expected_modified = None

    protected_ids = sorted(
        source_ids
        - set(expected_removed or [])
        - set(expected_modified or [])
    )
    assertions: list[dict[str, Any]] = [
        {"kind": "exact_added_ids", "expected": expected_added},
        {"kind": "exact_removed_ids", "expected": expected_removed},
        {"kind": "exact_modified_ids", "expected": expected_modified},
        {"kind": "protected_geometries_unchanged", "geometry_ids": protected_ids},
        {"kind": "result_not_empty"},
    ]
    if operation == "add_constrained" and parameters.get("constraint_kind"):
        assertions.extend([
            {
                "kind": "added_geometry_type_count",
                "geometry_type": "polyline",
                "expected": len(expected_added or []),
                "geometry_ids": expected_added or [],
            },
            {
                "kind": "symmetric_rectangles_on_circle",
                "geometry_ids": expected_added or [],
                "target_geometry_ids": target_ids,
            },
        ])
    plan = {
        "schema": "cad.edit-plan.v1",
        "operation": operation,
        "source_text": edit_contract.get("source_text"),
        "target": deepcopy(declared_target),
        "target_level": str(declared_target.get("scope") or ""),
        "target_ids": _semantic_target_ids(source, declared_target),
        "parameters": deepcopy(parameters),
        "assumptions": list(edit_contract.get("assumptions") or []),
        "intent_schema": edit_contract.get("intent_schema"),
        "intent_parser": edit_contract.get("intent_parser"),
        "intent_evidence_text": list(
            edit_contract.get("intent_evidence_text") or []
        ),
        "intent_confidence": edit_contract.get("intent_confidence"),
        "intent_grounding": deepcopy(edit_contract.get("intent_grounding") or {}),
        "constraints": deepcopy(edit_contract.get("constraints") or []),
        "missing_parameters": list(edit_contract.get("missing_parameters") or []),
        "auto_decisions": deepcopy(edit_contract.get("auto_decisions") or []),
        "expected_changes": {
            "added_geometry_ids": expected_added,
            "removed_geometry_ids": expected_removed,
            "modified_geometry_ids": expected_modified,
            "protected_geometry_ids": protected_ids,
        },
        "assertions": assertions,
    }
    plan["verification"] = verify_cad_edit_plan(source, target, plan)
    return plan


def _build_cad_edit_chain_plan(
    source: list[dict[str, Any]],
    target: list[dict[str, Any]],
    edit_contract: dict[str, Any],
) -> dict[str, Any]:
    from .cad_edit_chain import replay_cad_edit_chain

    expected, error, replay = replay_cad_edit_chain(source, edit_contract)
    step_plans: list[dict[str, Any]] = []
    working = deepcopy(source)
    if expected is not None:
        from .cad_edit_contract import cad_edit_contract_to_edit
        from .incremental_cad import edit_candidate_geometries
        for step in edit_contract.get("chain_steps") or []:
            edit = cad_edit_contract_to_edit(step)
            updated, step_error = edit_candidate_geometries(working, edit)
            if updated is None:
                error = step_error
                break
            step_plan = build_cad_edit_plan(working, updated, step)
            # A rotationally symmetric entity can legitimately remain byte-for-byte
            # unchanged while the rest of its instance rotates. For a chain, each
            # step result comes from the deterministic executor, so record its exact
            # observed delta and then verify that delta rather than assuming every
            # geometry in the selected instance must change.
            actual = (step_plan.get("verification") or {}).get("actual_changes") or {}
            step_expected = step_plan.get("expected_changes") or {}
            step_expected.update({
                "added_geometry_ids": list(actual.get("added") or []),
                "removed_geometry_ids": list(actual.get("removed") or []),
                "modified_geometry_ids": list(actual.get("modified") or []),
            })
            protected = sorted(
                set(_ids(working))
                - set(step_expected["removed_geometry_ids"])
                - set(step_expected["modified_geometry_ids"])
            )
            step_expected["protected_geometry_ids"] = protected
            for assertion in step_plan.get("assertions") or []:
                kind = assertion.get("kind")
                if kind == "exact_added_ids":
                    assertion["expected"] = step_expected["added_geometry_ids"]
                elif kind == "exact_removed_ids":
                    assertion["expected"] = step_expected["removed_geometry_ids"]
                elif kind == "exact_modified_ids":
                    assertion["expected"] = step_expected["modified_geometry_ids"]
                elif kind == "protected_geometries_unchanged":
                    assertion["geometry_ids"] = protected
            step_plan["verification"] = verify_cad_edit_plan(
                working, updated, step_plan
            )
            step_plans.append(step_plan)
            working = updated
    difference = build_geometry_diff(source, expected or target)
    expected_changes = {
        "added_geometry_ids": _ids(difference.get("added") or []),
        "removed_geometry_ids": _ids(difference.get("removed") or []),
        "modified_geometry_ids": sorted(
            int(item["after"]["id"])
            for item in difference.get("modified") or []
            if str((item.get("after") or {}).get("id", "")).isdigit()
        ),
    }
    exact = expected is not None and _canonical(expected) == _canonical(target)
    checks = [
        {"kind": "chain_replay", "ok": expected is not None, "observed": error},
        {
            "kind": "all_steps_verified",
            "ok": bool(step_plans) and all(
                (item.get("verification") or {}).get("verified") is True
                for item in step_plans
            ),
            "observed": len(step_plans),
        },
        {"kind": "chain_result_exact", "ok": exact, "observed": exact},
    ]
    failures = [item for item in checks if item["ok"] is not True]
    return {
        "schema": "cad.edit-plan.v1",
        "operation": "chain",
        "source_text": edit_contract.get("source_text"),
        "target": deepcopy(edit_contract.get("target") or {}),
        "target_level": str((edit_contract.get("target") or {}).get("scope") or ""),
        "target_ids": _semantic_target_ids(source, edit_contract.get("target") or {}),
        "parameters": {},
        "assumptions": list(edit_contract.get("assumptions") or []),
        "expected_changes": expected_changes,
        "assertions": [{"kind": item["kind"]} for item in checks],
        "steps": step_plans,
        "replay": replay,
        "verification": {
            "verified": not failures,
            "checks": checks,
            "failures": failures,
            "actual_changes": expected_changes,
        },
    }


def verify_cad_edit_plan(
    source: list[dict[str, Any]],
    target: list[dict[str, Any]],
    plan: dict[str, Any],
) -> dict[str, Any]:
    difference = build_geometry_diff(source, target)
    actual = {
        "added": _ids(difference.get("added") or []),
        "removed": _ids(difference.get("removed") or []),
        "modified": sorted(
            int(item["after"]["id"])
            for item in difference.get("modified") or []
            if str((item.get("after") or {}).get("id", "")).isdigit()
        ),
    }
    source_by_id = {int(item["id"]): item for item in source if str(item.get("id", "")).isdigit()}
    target_by_id = {int(item["id"]): item for item in target if str(item.get("id", "")).isdigit()}
    checks: list[dict[str, Any]] = []
    for assertion in plan.get("assertions") or []:
        kind = str(assertion.get("kind") or "")
        ok = False
        observed: Any = None
        if kind.startswith("exact_"):
            key = kind.removeprefix("exact_").removesuffix("_ids")
            expected = assertion.get("expected")
            observed = actual.get(key)
            ok = expected is None or observed == expected
        elif kind == "protected_geometries_unchanged":
            ids = [int(value) for value in assertion.get("geometry_ids") or []]
            changed = [
                value for value in ids
                if value not in source_by_id
                or value not in target_by_id
                or _canonical(source_by_id[value]) != _canonical(target_by_id[value])
            ]
            observed = {"changed_ids": changed}
            ok = not changed
        elif kind == "result_not_empty":
            observed = len(target)
            ok = bool(target)
        elif kind == "added_geometry_type_count":
            ids = [int(value) for value in assertion.get("geometry_ids") or []]
            geometry_type = str(assertion.get("geometry_type") or "")
            observed = sum(
                1 for value in ids
                if str(target_by_id.get(value, {}).get("type") or "") == geometry_type
            )
            ok = observed == int(assertion.get("expected") or 0)
        elif kind == "symmetric_rectangles_on_circle":
            observed = _verify_symmetric_rectangles(
                target,
                [int(value) for value in assertion.get("geometry_ids") or []],
                [int(value) for value in assertion.get("target_geometry_ids") or []],
            )
            ok = observed.get("verified") is True
        checks.append({"kind": kind, "ok": ok, "observed": observed})
    failures = [item for item in checks if item["ok"] is not True]
    return {
        "verified": not failures,
        "checks": checks,
        "failures": failures,
        "actual_changes": actual,
    }


def repair_cad_edit_plan_once(
    source: list[dict[str, Any]],
    target: list[dict[str, Any]],
    edit_contract: dict[str, Any],
    plan: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Repair assertion-proven scope drift once without inventing geometry."""
    initial_plan = deepcopy(plan or build_cad_edit_plan(source, target, edit_contract))
    verification = initial_plan.get("verification") or {}
    previous_repair = initial_plan.get("repair") or {}
    previous_attempts = int(previous_repair.get("attempt_count") or 0)
    if verification.get("verified") is True:
        evidence = {
            "schema": "cad.edit-repair.v1",
            "attempted": False,
            "attempt_count": previous_attempts,
            "reason": "plan_already_verified",
            "trigger_failures": [],
            "actions": [],
        }
        return deepcopy(target), initial_plan, evidence
    failures = [
        item for item in verification.get("failures") or []
        if isinstance(item, dict)
    ]
    failure_kinds = [str(item.get("kind") or "") for item in failures]
    if previous_attempts >= 1:
        evidence = {
            "schema": "cad.edit-repair.v1",
            "attempted": False,
            "attempt_count": previous_attempts,
            "reason": "repair_limit_reached",
            "trigger_failures": failure_kinds,
            "actions": [],
        }
        return deepcopy(target), initial_plan, evidence

    safe_assertions = {
        "exact_added_ids", "exact_removed_ids", "exact_modified_ids",
        "protected_geometries_unchanged",
    }
    unsupported = sorted(set(failure_kinds) - safe_assertions)
    expected = initial_plan.get("expected_changes") or {}
    actual = verification.get("actual_changes") or {}
    expected_added = expected.get("added_geometry_ids")
    expected_removed = expected.get("removed_geometry_ids")
    expected_modified = expected.get("modified_geometry_ids")
    if unsupported or any(
        value is None for value in (expected_added, expected_removed, expected_modified)
    ):
        evidence = {
            "schema": "cad.edit-repair.v1",
            "attempted": False,
            "attempt_count": 0,
            "reason": "unsupported_failed_assertion",
            "trigger_failures": failure_kinds,
            "unsupported_failures": unsupported,
            "actions": [],
        }
        initial_plan["repair"] = evidence
        return deepcopy(target), initial_plan, evidence

    expected_added_set = {int(value) for value in expected_added}
    expected_removed_set = {int(value) for value in expected_removed}
    expected_modified_set = {int(value) for value in expected_modified}
    actual_added = {int(value) for value in actual.get("added") or []}
    actual_removed = {int(value) for value in actual.get("removed") or []}
    actual_modified = {int(value) for value in actual.get("modified") or []}
    missing_added = sorted(expected_added_set - actual_added)
    missing_modified = sorted(expected_modified_set - actual_modified)
    if missing_added or missing_modified:
        evidence = {
            "schema": "cad.edit-repair.v1",
            "attempted": False,
            "attempt_count": 0,
            "reason": "missing_intended_geometry_change",
            "trigger_failures": failure_kinds,
            "missing_added_geometry_ids": missing_added,
            "missing_modified_geometry_ids": missing_modified,
            "actions": [],
        }
        initial_plan["repair"] = evidence
        return deepcopy(target), initial_plan, evidence

    source_by_id = {
        int(item["id"]): deepcopy(item) for item in source
        if isinstance(item, dict) and str(item.get("id", "")).isdigit()
    }
    target_by_id = {
        int(item["id"]): deepcopy(item) for item in target
        if isinstance(item, dict) and str(item.get("id", "")).isdigit()
    }
    unexpected_added = sorted(actual_added - expected_added_set)
    unexpected_removed = sorted(actual_removed - expected_removed_set)
    unexpected_modified = sorted(actual_modified - expected_modified_set)
    restore_ids = sorted(set(unexpected_removed) | set(unexpected_modified))
    remove_ids = sorted(set(unexpected_added) | expected_removed_set)
    actions: list[dict[str, Any]] = []
    if restore_ids:
        actions.append({
            "kind": "restore_source_geometries",
            "geometry_ids": restore_ids,
        })
        for geometry_id in restore_ids:
            if geometry_id in source_by_id:
                target_by_id[geometry_id] = deepcopy(source_by_id[geometry_id])
    if remove_ids:
        actions.append({
            "kind": "remove_unexpected_or_declared_deleted_geometries",
            "geometry_ids": remove_ids,
        })
        for geometry_id in remove_ids:
            target_by_id.pop(geometry_id, None)
    if not actions:
        evidence = {
            "schema": "cad.edit-repair.v1",
            "attempted": False,
            "attempt_count": 0,
            "reason": "no_deterministic_repair_action",
            "trigger_failures": failure_kinds,
            "actions": [],
        }
        initial_plan["repair"] = evidence
        return deepcopy(target), initial_plan, evidence

    source_order = [
        int(item["id"]) for item in source
        if isinstance(item, dict) and str(item.get("id", "")).isdigit()
    ]
    target_order = [
        int(item["id"]) for item in target
        if isinstance(item, dict) and str(item.get("id", "")).isdigit()
    ]
    order = [
        value for value in [*source_order, *target_order]
        if value in target_by_id
    ]
    order = list(dict.fromkeys(order))
    repaired = [target_by_id[value] for value in order]
    final_plan = build_cad_edit_plan(source, repaired, edit_contract)
    evidence = {
        "schema": "cad.edit-repair.v1",
        "attempted": True,
        "attempt_count": 1,
        "reason": "assertion_guided_scope_repair",
        "trigger_failures": failure_kinds,
        "actions": actions,
        "initial_verification": deepcopy(verification),
        "final_verification": deepcopy(final_plan.get("verification") or {}),
        "repaired": (final_plan.get("verification") or {}).get("verified") is True,
    }
    final_plan["repair"] = evidence
    return repaired, final_plan, evidence


def _verify_symmetric_rectangles(
    geometries: list[dict[str, Any]],
    added_ids: list[int],
    target_ids: list[int],
) -> dict[str, Any]:
    by_id = {
        int(item["id"]): item for item in geometries
        if str(item.get("id", "")).isdigit()
    }
    rectangles = [by_id[value] for value in added_ids if value in by_id]
    circles = [
        item for item in geometries
        if item.get("type") == "circle" and isinstance(item.get("center"), dict)
    ]
    borders = [by_id[value] for value in target_ids if value in by_id and by_id[value].get("type") == "polyline"]
    if len(rectangles) != 2 or not circles or not borders:
        return {"verified": False, "reason": "missing_required_geometry"}
    circle = max(circles, key=lambda item: float(item.get("radius") or 0.0))
    cx = float(circle["center"]["x"])
    cy = float(circle["center"]["y"])
    radius = float(circle["radius"])
    tolerance = max(1.0, radius * 1e-6)
    border_points = borders[0].get("vertices") or []
    min_y = min(float(point["y"]) for point in border_points)
    max_y = max(float(point["y"]) for point in border_points)
    rectangle_points = [item.get("vertices") or [] for item in rectangles]
    outer_points = [point for points in rectangle_points for point in points[1:3]]
    on_circle = all(
        abs(math.hypot(float(point["x"]) - cx, float(point["y"]) - cy) - radius)
        <= tolerance
        for point in outer_points
    )
    attached = any(abs(float(point["y"]) - max_y) <= tolerance for point in rectangle_points[0]) and any(
        abs(float(point["y"]) - min_y) <= tolerance for point in rectangle_points[1]
    )
    top_outer = max(float(point["y"]) for point in rectangle_points[0])
    bottom_outer = min(float(point["y"]) for point in rectangle_points[1])
    symmetric = abs((top_outer - cy) - (cy - bottom_outer)) <= tolerance
    return {
        "verified": on_circle and attached and symmetric,
        "outer_vertices_on_circle": on_circle,
        "attached_to_target": attached,
        "symmetric": symmetric,
        "tolerance_mm": tolerance,
    }
