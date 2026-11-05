"""Adapt the existing CAD validation chain to agent plan step results."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict

from .agent_plan_models import PlanStep, StepResult
from .cad_assertions import build_cad_machine_assertions
from .cad_edit_gate import (
    build_cad_edit_preflight,
    build_rejection_rollback_evidence,
)
from .geometry_diff import build_geometry_diff


class CadPlanVerification(BaseModel):
    """Complete, immutable-style evidence for one CAD plan step attempt."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "agent.cad-plan-verification.v1"
    step_result: StepResult
    geometry_diff: dict[str, Any]
    preflight: dict[str, Any]
    machine_assertions: dict[str, Any]
    rollback_evidence: dict[str, Any] | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _failure_message(
    failure_codes: list[str], preflight: dict[str, Any]
) -> str:
    failed_checks = [
        str(item.get("detail") or item.get("label") or item.get("code"))
        for item in preflight.get("checks") or []
        if isinstance(item, dict) and item.get("ok") is not True
    ]
    if failed_checks:
        return "CAD 修改验证未通过：" + "；".join(failed_checks)
    if failure_codes:
        return "CAD 修改验证未通过：" + "、".join(failure_codes)
    return "CAD 修改验证未通过，候选结果已丢弃。"


def verify_cad_plan_step(
    *,
    step: PlanStep,
    source: list[dict[str, Any]],
    candidate: list[dict[str, Any]],
    contract: dict[str, Any],
    edit_plan: dict[str, Any],
    edit_preview: dict[str, Any],
    started_at: datetime,
    finished_at: datetime | None = None,
) -> CadPlanVerification:
    """Run the established CAD gates and express them as a plan step result.

    This adapter never edits geometry, persists a candidate, retries a model,
    or repairs a failed result. Those responsibilities remain in their existing
    execution, storage, and orchestration modules.
    """
    if step.status != "running":
        raise ValueError("CAD plan verification requires a running step")
    if step.attempt_count < 1:
        raise ValueError("running CAD step must have an active attempt")

    geometry_diff = build_geometry_diff(source, candidate)
    preflight = build_cad_edit_preflight(source, candidate, contract)
    assertions = build_cad_machine_assertions(
        source,
        candidate,
        contract,
        edit_plan,
        edit_preview,
        preflight=preflight,
    )
    verified = assertions.get("verified") is True
    criterion_results = {
        criterion_id: verified
        for criterion_id in step.verification_criteria_ids
    }
    technical_checks = {
        "cad_preflight": preflight.get("ready") is True,
        "cad_machine_assertions": verified,
    }
    verification = {**criterion_results, **technical_checks}
    failure_codes = [
        str(value) for value in assertions.get("failure_codes") or []
    ]
    rollback = None
    if not verified:
        reason = failure_codes[0] if failure_codes else "cad_verification_failed"
        rollback = build_rejection_rollback_evidence(source, reason)

    output = {
        "geometry_diff": geometry_diff,
        "preflight": preflight,
        "machine_assertions": assertions,
    }
    if rollback is not None:
        output["rollback_evidence"] = rollback

    result = StepResult(
        step_id=step.id,
        attempt=step.attempt_count,
        status="verified" if verified else "failed",
        started_at=started_at,
        finished_at=finished_at or _utc_now(),
        output=output,
        observations=[
            {
                "schema": "cad.plan-step-observation.v1",
                "changed_geometry_count": sum(
                    int((geometry_diff.get("counts") or {}).get(key) or 0)
                    for key in ("added", "removed", "modified")
                ),
                "risk_level": preflight.get("risk_level"),
                "requires_confirmation": preflight.get("requires_confirmation")
                is True,
                "failure_codes": failure_codes,
            }
        ],
        verification=verification,
        failure_code=(
            failure_codes[0]
            if failure_codes
            else "cad_verification_failed" if not verified else None
        ),
        failure_message=(
            _failure_message(failure_codes, preflight) if not verified else None
        ),
        retryable=False,
    )
    return CadPlanVerification(
        step_result=result,
        geometry_diff=geometry_diff,
        preflight=preflight,
        machine_assertions=assertions,
        rollback_evidence=rollback,
    )
