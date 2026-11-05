from copy import deepcopy
from datetime import datetime, timezone

from app.agent_plan_models import PlanStep
from app.agent_plan_models import ExecutionPlan, GoalSpec, SuccessCriterion
from app.agent_plan_orchestrator import finish_plan_step, start_plan_step
from app.agent_plan_recovery import start_deterministic_repair
from app.cad_edit_contract import build_cad_edit_contract
from app.cad_edit_plan import build_cad_edit_plan
from app.cad_edit_preview import build_cad_edit_preview
from app.cad_plan_recovery import verify_and_repair_cad_plan_step_once
from app.incremental_cad import edit_candidate_geometries


def _source() -> list[dict]:
    return [
        {
            "id": 1,
            "type": "line",
            "template_instance": 1,
            "start": {"x": 0, "y": 0},
            "end": {"x": 1000, "y": 0},
        },
        {
            "id": 2,
            "type": "line",
            "template_instance": 2,
            "start": {"x": 3000, "y": 0},
            "end": {"x": 4000, "y": 0},
        },
    ]


def _artifacts(source: list[dict], candidate: list[dict]) -> tuple[dict, dict, dict]:
    edit = {
        "operation": "translate",
        "instance": 2,
        "dx_mm": 1000.0,
        "dy_mm": 0.0,
        "project_id": "project-1",
        "parent_variant_id": "variant-1",
    }
    contract = build_cad_edit_contract(edit, source_text="第二条线向右移动一米")
    return (
        contract,
        build_cad_edit_plan(source, candidate, contract),
        build_cad_edit_preview(source, candidate, contract),
    )


def _step() -> PlanStep:
    return PlanStep(
        id="edit",
        title="修改图纸",
        tool_name="modify_drawing",
        status="running",
        attempt_count=1,
        verification_criteria_ids=["valid"],
    )


def test_non_target_drift_is_repaired_once_and_fully_reverified() -> None:
    source = _source()
    target, error = edit_candidate_geometries(
        source,
        {"operation": "translate", "instance": 2, "dx_mm": 1000, "dy_mm": 0},
    )
    assert error is None
    drifted = deepcopy(target or [])
    drifted[0]["end"]["x"] += 125
    contract, edit_plan, preview = _artifacts(source, drifted)

    recovery = verify_and_repair_cad_plan_step_once(
        step=_step(),
        source=source,
        candidate=drifted,
        contract=contract,
        edit_plan=edit_plan,
        edit_preview=preview,
        started_at=datetime.now(timezone.utc),
    )

    assert recovery.attempted is True
    assert recovery.recovered is True
    assert recovery.candidate == target
    assert recovery.verification.step_result.status == "verified"
    assert recovery.evidence["attempt_count"] == 1


def test_missing_version_binding_is_not_auto_repaired() -> None:
    source = _source()
    target, error = edit_candidate_geometries(
        source,
        {"operation": "translate", "instance": 2, "dx_mm": 1000, "dy_mm": 0},
    )
    assert error is None
    contract, edit_plan, preview = _artifacts(source, target or [])
    contract.pop("parent_variant_id", None)
    edit_plan = build_cad_edit_plan(source, target or [], contract)
    preview = build_cad_edit_preview(source, target or [], contract)

    recovery = verify_and_repair_cad_plan_step_once(
        step=_step(),
        source=source,
        candidate=target or [],
        contract=contract,
        edit_plan=edit_plan,
        edit_preview=preview,
        started_at=datetime.now(timezone.utc),
    )

    assert recovery.attempted is False
    assert recovery.recovered is False
    assert recovery.verification.step_result.status == "failed"
    assert "version_binding" in recovery.evidence["unsupported_failure_codes"]


def test_repaired_result_completes_plan_after_repair_transition() -> None:
    source = _source()
    target, error = edit_candidate_geometries(
        source,
        {"operation": "translate", "instance": 2, "dx_mm": 1000, "dy_mm": 0},
    )
    assert error is None
    drifted = deepcopy(target or [])
    drifted[0]["end"]["x"] += 125
    contract, edit_plan, preview = _artifacts(source, drifted)
    plan = ExecutionPlan(
        id="plan-repair-integration",
        status="ready",
        goal=GoalSpec(
            id="goal-repair-integration",
            user_request="移动第二条线",
            summary="修改并验证",
            domain="cad",
            project_id="project-1",
            success_criteria=[
                SuccessCriterion(
                    id="valid",
                    description="结果有效",
                    metric="topology",
                    operator="valid",
                )
            ],
        ),
        steps=[_step().model_copy(update={"status": "pending", "attempt_count": 0})],
    )
    running = start_plan_step(plan, "edit", sequence=1).plan
    recovery = verify_and_repair_cad_plan_step_once(
        step=running.steps[0],
        source=source,
        candidate=drifted,
        contract=contract,
        edit_plan=edit_plan,
        edit_preview=preview,
        started_at=datetime.now(timezone.utc),
    )
    initial_failure = recovery.verification.step_result.model_copy(
        update={
            "status": "failed",
            "failure_code": "target_scope",
            "failure_message": "需要确定性修复",
            "verification": {"valid": False},
        }
    )
    repairing = start_deterministic_repair(
        running, initial_failure, sequence=2, evidence=recovery.evidence
    )

    completed = finish_plan_step(
        repairing.plan, recovery.verification.step_result, sequence=3
    )

    assert completed.plan.status == "completed"
    assert completed.plan.deterministic_repair_count == 1
