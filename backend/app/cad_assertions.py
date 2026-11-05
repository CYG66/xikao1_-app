"""Unified blocking assertions for deterministic CAD candidate persistence."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from .cad_edit_gate import build_cad_edit_preflight
from .cad_edit_plan import repair_cad_edit_plan_once
from .cad_edit_preview import build_cad_edit_preview
from .cad_edit_preview import validate_cad_edit_preview


def _fingerprint(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normalized_target(contract: dict[str, Any]) -> dict[str, Any]:
    target = deepcopy(
        contract.get("target") if isinstance(contract.get("target"), dict) else {}
    )
    scope = target.get("scope")
    if scope != "logical_object":
        target.pop("object_id", None)
        target.pop("object_ids", None)
    if scope != "instance":
        target.pop("instance_ids", None)
    if scope not in {"geometry", "logical_object"}:
        target.pop("geometry_ids", None)
    return target


def build_cad_machine_assertions(
    source: list[dict[str, Any]],
    target: list[dict[str, Any]],
    contract: dict[str, Any],
    edit_plan: dict[str, Any],
    edit_preview: dict[str, Any],
    *,
    preflight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Combine existing validators into one fail-closed persistence gate."""
    checked = preflight or build_cad_edit_preflight(source, target, contract)
    preview_validation = validate_cad_edit_preview(
        edit_preview, source, target, contract, preflight=checked,
    )
    declared_target = _normalized_target(contract)
    target_ids = list(declared_target.get("instance_ids") or []) + list(
        declared_target.get("geometry_ids") or []
    ) + list(declared_target.get("object_ids") or [])
    if declared_target.get("object_id"):
        target_ids.append(declared_target["object_id"])
    grounding = contract.get("intent_grounding")
    grounding_required = contract.get("intent_parser") == "model_structured_fallback"
    scope = checked.get("scope_validation") if isinstance(checked.get("scope_validation"), dict) else {}
    integrity = scope.get("non_target_integrity") if isinstance(scope.get("non_target_integrity"), dict) else {}
    effect = checked.get("effect_validation") if isinstance(checked.get("effect_validation"), dict) else {}
    assertions = [
        {
            "code": "version_binding",
            "ok": bool(contract.get("project_id") and contract.get("parent_variant_id")),
            "observed": {
                "project_id": contract.get("project_id"),
                "parent_variant_id": contract.get("parent_variant_id"),
            },
        },
        {
            "code": "target_resolved",
            "ok": bool(declared_target.get("scope") and target_ids),
            "observed": deepcopy(declared_target),
        },
        {
            "code": "required_parameters_present",
            "ok": not list(contract.get("missing_parameters") or []),
            "observed": list(contract.get("missing_parameters") or []),
        },
        {
            "code": "intent_grounding",
            "ok": (
                not grounding_required
                or isinstance(grounding, dict) and grounding.get("verified") is True
            ),
            "observed": deepcopy(grounding or {}),
        },
        {
            "code": "geometry_preflight",
            "ok": checked.get("ready") is True,
            "observed": [
                item.get("code") for item in checked.get("checks") or []
                if item.get("ok") is not True
            ],
        },
        {
            "code": "declared_operation_effect",
            "ok": effect.get("verified") is not False,
            "observed": deepcopy(effect),
        },
        {
            "code": "target_scope",
            "ok": scope.get("ok") is True,
            "observed": deepcopy(scope),
        },
        {
            "code": "non_target_integrity",
            "ok": integrity.get("verified") is True,
            "observed": deepcopy(integrity),
        },
        {
            "code": "edit_plan",
            "ok": (edit_plan.get("verification") or {}).get("verified") is True,
            "observed": deepcopy(edit_plan.get("verification") or {}),
        },
        {
            "code": "preview_exact",
            "ok": preview_validation.get("verified") is True,
            "observed": {
                key: value for key, value in preview_validation.items()
                if key != "preview"
            },
        },
    ]
    failures = [item["code"] for item in assertions if item["ok"] is not True]
    core = {
        "schema": "cad.machine-assertions.v1",
        "blocking": True,
        "verified": not failures,
        "assertions": assertions,
        "failure_codes": failures,
        "source_geometry_sha256": (edit_preview.get("source") or {}).get("geometry_sha256"),
        "candidate_geometry_sha256": (edit_preview.get("candidate") or {}).get("geometry_sha256"),
        "preview_sha256": edit_preview.get("preview_sha256"),
    }
    return {**core, "report_sha256": _fingerprint(core)}


def validate_cad_machine_assertions(
    report: dict[str, Any],
    source: list[dict[str, Any]],
    target: list[dict[str, Any]],
    contract: dict[str, Any],
    edit_plan: dict[str, Any],
    edit_preview: dict[str, Any],
) -> dict[str, Any]:
    if report.get("schema") != "cad.machine-assertions.v1":
        return {"verified": False, "reason": "invalid_assertion_schema"}
    expected_hash = str(report.get("report_sha256") or "")
    supplied_core = {
        key: deepcopy(value) for key, value in report.items()
        if key != "report_sha256"
    }
    supplied_hash = _fingerprint(supplied_core)
    rebuilt = build_cad_machine_assertions(
        source, target, contract, edit_plan, edit_preview,
    )
    rebuilt_hash = str(rebuilt["report_sha256"])
    verified = (
        report.get("verified") is True
        and bool(expected_hash)
        and expected_hash == supplied_hash == rebuilt_hash
        and rebuilt.get("verified") is True
    )
    return {
        "verified": verified,
        "reason": None if verified else "machine_assertion_mismatch",
        "expected_report_sha256": expected_hash,
        "supplied_report_sha256": supplied_hash,
        "actual_report_sha256": rebuilt_hash,
        "report": rebuilt,
    }


def repair_cad_machine_assertions_once(
    source: list[dict[str, Any]],
    target: list[dict[str, Any]],
    contract: dict[str, Any],
    edit_plan: dict[str, Any],
    edit_preview: dict[str, Any],
    report: dict[str, Any],
) -> tuple[
    list[dict[str, Any]], dict[str, Any], dict[str, Any],
    dict[str, Any], dict[str, Any],
]:
    """Repair one assertion-proven non-target drift and rerun every gate."""
    failure_codes = sorted({
        str(value) for value in report.get("failure_codes") or [] if value
    })
    base_evidence = {
        "schema": "cad.assertion-recovery.v1",
        "attempted": False,
        "attempt_count": int(
            ((edit_plan.get("repair") or {}).get("attempt_count") or 0)
        ),
        "trigger_failure_codes": failure_codes,
        "strategy": "restore_protected_geometries",
        "actions": [],
    }
    if report.get("verified") is True:
        return (
            deepcopy(target), deepcopy(edit_plan), deepcopy(edit_preview),
            deepcopy(report), {**base_evidence, "reason": "assertions_already_verified"},
        )

    # These are the only failures for which restoring bytes from the source is
    # deterministic. Never infer a missing target change or repair trust inputs.
    recoverable = {
        "geometry_preflight", "declared_operation_effect", "edit_plan",
        "target_scope", "non_target_integrity",
    }
    unsupported = sorted(set(failure_codes) - recoverable)
    has_scope_proof = bool(
        {"target_scope", "non_target_integrity"} & set(failure_codes)
    )
    if unsupported or "edit_plan" not in failure_codes or not has_scope_proof:
        return (
            deepcopy(target), deepcopy(edit_plan), deepcopy(edit_preview),
            deepcopy(report), {
                **base_evidence,
                "reason": "unsupported_machine_assertion_failure",
                "unsupported_failure_codes": unsupported,
            },
        )

    repaired, repaired_plan, plan_repair = repair_cad_edit_plan_once(
        source, target, contract, edit_plan,
    )
    if plan_repair.get("attempted") is not True:
        return (
            repaired, repaired_plan, deepcopy(edit_preview), deepcopy(report), {
                **base_evidence,
                "attempt_count": int(plan_repair.get("attempt_count") or 0),
                "reason": str(plan_repair.get("reason") or "repair_not_available"),
                "plan_repair": deepcopy(plan_repair),
            },
        )

    repaired_preview = build_cad_edit_preview(
        source,
        repaired,
        contract,
        target_resolution=deepcopy(edit_preview.get("target_resolution")),
    )
    repaired_report = build_cad_machine_assertions(
        source, repaired, contract, repaired_plan, repaired_preview,
    )
    recovered = repaired_report.get("verified") is True
    evidence = {
        **base_evidence,
        "attempted": True,
        "attempt_count": 1,
        "reason": "recovered" if recovered else "revalidation_failed",
        "actions": deepcopy(plan_repair.get("actions") or []),
        "plan_repair": deepcopy(plan_repair),
        "before_report_sha256": report.get("report_sha256"),
        "after_report_sha256": repaired_report.get("report_sha256"),
        "final_failure_codes": list(repaired_report.get("failure_codes") or []),
        "recovered": recovered,
        "repaired": recovered,
    }
    repaired_plan["assertion_recovery"] = deepcopy(evidence)
    # The plan changed when recovery evidence was attached, but its geometric
    # verification remains the authoritative input to the machine assertions.
    return repaired, repaired_plan, repaired_preview, repaired_report, evidence
