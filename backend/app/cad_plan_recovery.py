"""One-shot deterministic CAD recovery for a verified plan step candidate."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from .agent_plan_models import PlanStep
from .cad_assertions import repair_cad_machine_assertions_once
from .cad_plan_verifier import CadPlanVerification, verify_cad_plan_step


class CadPlanRecovery(BaseModel):
    """Artifacts produced by at most one deterministic CAD repair."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "agent.cad-plan-recovery.v1"
    attempted: bool
    recovered: bool
    candidate: list[dict[str, Any]]
    edit_plan: dict[str, Any]
    edit_preview: dict[str, Any]
    verification: CadPlanVerification
    evidence: dict[str, Any]


def verify_and_repair_cad_plan_step_once(
    *,
    step: PlanStep,
    source: list[dict[str, Any]],
    candidate: list[dict[str, Any]],
    contract: dict[str, Any],
    edit_plan: dict[str, Any],
    edit_preview: dict[str, Any],
    started_at: datetime,
) -> CadPlanRecovery:
    """Verify a candidate and apply the existing deterministic repair once."""
    initial = verify_cad_plan_step(
        step=step,
        source=source,
        candidate=candidate,
        contract=contract,
        edit_plan=edit_plan,
        edit_preview=edit_preview,
        started_at=started_at,
    )
    if initial.step_result.status == "verified":
        return CadPlanRecovery(
            attempted=False,
            recovered=False,
            candidate=deepcopy(candidate),
            edit_plan=deepcopy(edit_plan),
            edit_preview=deepcopy(edit_preview),
            verification=initial,
            evidence={"reason": "verification_already_passed"},
        )

    repaired, repaired_plan, repaired_preview, _, evidence = (
        repair_cad_machine_assertions_once(
            source,
            candidate,
            contract,
            edit_plan,
            edit_preview,
            initial.machine_assertions,
        )
    )
    attempted = evidence.get("attempted") is True
    if not attempted:
        return CadPlanRecovery(
            attempted=False,
            recovered=False,
            candidate=deepcopy(candidate),
            edit_plan=deepcopy(edit_plan),
            edit_preview=deepcopy(edit_preview),
            verification=initial,
            evidence=deepcopy(evidence),
        )

    final = verify_cad_plan_step(
        step=step,
        source=source,
        candidate=repaired,
        contract=contract,
        edit_plan=repaired_plan,
        edit_preview=repaired_preview,
        started_at=started_at,
    )
    return CadPlanRecovery(
        attempted=True,
        recovered=final.step_result.status == "verified",
        candidate=repaired,
        edit_plan=repaired_plan,
        edit_preview=repaired_preview,
        verification=final,
        evidence=deepcopy(evidence),
    )
