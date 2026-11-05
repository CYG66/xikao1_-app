"""Strict contracts for goal-driven, verifiable agent execution plans."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


RiskLevel = Literal["read_only", "low", "medium", "high", "critical"]
GoalDomain = Literal["cad", "mission", "device", "diagnostic", "conversation"]
StepStatus = Literal[
    "pending",
    "awaiting_confirmation",
    "running",
    "verified",
    "failed",
    "rolled_back",
    "skipped",
]
PlanStatus = Literal[
    "draft",
    "ready",
    "running",
    "awaiting_confirmation",
    "repairing",
    "replanning",
    "completed",
    "failed",
    "rolled_back",
    "cancelled",
]
PlanEventType = Literal[
    "plan_created",
    "step_awaiting_confirmation",
    "step_started",
    "step_verified",
    "step_failed",
    "step_rolled_back",
    "step_skipped",
    "plan_repair_started",
    "plan_replan_requested",
    "plan_replanned",
    "plan_cancelled",
]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentTargetRef(BaseModel):
    """Stable reference to the object or scope affected by a goal."""

    model_config = ConfigDict(extra="forbid")

    scope: Literal[
        "project",
        "variant",
        "instance",
        "logical_object",
        "geometry",
        "path",
        "device",
    ]
    ids: list[str] = Field(min_length=1, max_length=500)
    label: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_ids(self) -> "AgentTargetRef":
        normalized = [value.strip() for value in self.ids]
        if any(not value for value in normalized):
            raise ValueError("target IDs must not be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("target IDs must be unique")
        self.ids = normalized
        return self


class SuccessCriterion(BaseModel):
    """One machine-checkable condition required for goal completion."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=500)
    metric: Literal[
        "geometry_count",
        "dimension",
        "position",
        "topology",
        "path_feasibility",
        "non_target_unchanged",
        "device_state",
        "user_confirmation",
        "custom",
    ]
    operator: Literal["eq", "ne", "gt", "gte", "lt", "lte", "valid", "unchanged"]
    expected: Any = None
    target: AgentTargetRef | None = None
    tolerance: float | None = Field(default=None, ge=0)
    required: bool = True

    @model_validator(mode="after")
    def validate_criterion(self) -> "SuccessCriterion":
        if self.operator not in {"valid", "unchanged"} and self.expected is None:
            raise ValueError("comparison criterion requires an expected value")
        if self.tolerance is not None and self.operator not in {"eq", "ne"}:
            raise ValueError("tolerance is only valid for equality comparisons")
        if self.operator == "unchanged" and self.target is None:
            raise ValueError("unchanged criterion requires a target")
        return self


class GoalSpec(BaseModel):
    """Normalized user goal with explicit targets, invariants, and source binding."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["agent.goal.v1"] = "agent.goal.v1"
    id: str = Field(min_length=1, max_length=128)
    user_request: str = Field(min_length=1, max_length=8000)
    summary: str = Field(min_length=1, max_length=500)
    domain: GoalDomain
    project_id: str | None = Field(default=None, min_length=1, max_length=128)
    source_variant_id: str | None = Field(default=None, min_length=1, max_length=128)
    source_version: int | None = Field(default=None, ge=1)
    source_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-fA-F]{64}$"
    )
    targets: list[AgentTargetRef] = Field(default_factory=list, max_length=100)
    success_criteria: list[SuccessCriterion] = Field(min_length=1, max_length=100)
    invariants: list[SuccessCriterion] = Field(default_factory=list, max_length=100)
    assumptions: list[str] = Field(default_factory=list, max_length=50)
    risk_level: RiskLevel = "low"

    @model_validator(mode="after")
    def validate_goal(self) -> "GoalSpec":
        criterion_ids = [item.id for item in [*self.success_criteria, *self.invariants]]
        if len(criterion_ids) != len(set(criterion_ids)):
            raise ValueError("criterion IDs must be unique within a goal")
        if self.domain == "cad" and self.project_id is None:
            raise ValueError("CAD goal requires project_id")
        if self.source_variant_id is not None and self.project_id is None:
            raise ValueError("source_variant_id requires project_id")
        if any(not item.strip() for item in self.assumptions):
            raise ValueError("assumptions must not be empty")
        return self


class PlanStep(BaseModel):
    """One deterministic, dependency-aware action in an execution plan."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=300)
    tool_name: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list, max_length=50)
    status: StepStatus = "pending"
    risk_level: RiskLevel = "low"
    requires_confirmation: bool = False
    verification_criteria_ids: list[str] = Field(default_factory=list, max_length=100)
    max_attempts: int = Field(default=1, ge=1, le=3)
    attempt_count: int = Field(default=0, ge=0, le=3)

    @model_validator(mode="after")
    def validate_step(self) -> "PlanStep":
        if self.id in self.depends_on:
            raise ValueError("step cannot depend on itself")
        if len(self.depends_on) != len(set(self.depends_on)):
            raise ValueError("step dependencies must be unique")
        if len(self.verification_criteria_ids) != len(
            set(self.verification_criteria_ids)
        ):
            raise ValueError("verification criterion IDs must be unique")
        if self.attempt_count > self.max_attempts:
            raise ValueError("attempt_count cannot exceed max_attempts")
        if self.status == "awaiting_confirmation" and not self.requires_confirmation:
            raise ValueError("awaiting confirmation step must require confirmation")
        return self


class StepResult(BaseModel):
    """Immutable-style observation and verification outcome for one attempt."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["agent.step-result.v1"] = "agent.step-result.v1"
    step_id: str = Field(min_length=1, max_length=128)
    attempt: int = Field(ge=1, le=3)
    status: Literal["verified", "failed", "rolled_back", "skipped"]
    started_at: datetime
    finished_at: datetime = Field(default_factory=_utc_now)
    output: dict[str, Any] = Field(default_factory=dict)
    observations: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    verification: dict[str, bool] = Field(default_factory=dict)
    failure_code: str | None = Field(default=None, min_length=1, max_length=128)
    failure_message: str | None = Field(default=None, min_length=1, max_length=1000)
    retryable: bool = False

    @model_validator(mode="after")
    def validate_result(self) -> "StepResult":
        if self.finished_at < self.started_at:
            raise ValueError("finished_at cannot precede started_at")
        failed = self.status == "failed"
        has_failure_details = self.failure_code is not None or self.failure_message is not None
        complete_failure_details = bool(self.failure_code and self.failure_message)
        if failed and not complete_failure_details:
            raise ValueError("failed result requires failure_code and failure_message")
        if not failed and has_failure_details:
            raise ValueError("only failed result may contain failure details")
        if self.status == "verified" and any(
            value is not True for value in self.verification.values()
        ):
            raise ValueError("verified result cannot contain failed checks")
        if self.retryable and not failed:
            raise ValueError("only failed results can be retryable")
        return self


class ExecutionPlan(BaseModel):
    """Ordered plan whose dependency and verification references are validated."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["agent.plan.v1"] = "agent.plan.v1"
    id: str = Field(min_length=1, max_length=128)
    revision: int = Field(default=1, ge=1)
    goal: GoalSpec
    status: PlanStatus = "draft"
    steps: list[PlanStep] = Field(min_length=1, max_length=100)
    deterministic_repair_limit: int = Field(default=1, ge=0, le=1)
    replan_limit: int = Field(default=1, ge=0, le=1)
    deterministic_repair_count: int = Field(default=0, ge=0, le=1)
    replan_count: int = Field(default=0, ge=0, le=1)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def validate_plan(self) -> "ExecutionPlan":
        step_ids = [step.id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("plan step IDs must be unique")
        known: set[str] = set()
        criteria = {
            item.id for item in [*self.goal.success_criteria, *self.goal.invariants]
        }
        for step in self.steps:
            if any(dependency not in known for dependency in step.depends_on):
                raise ValueError("step dependencies must reference earlier steps")
            if any(
                criterion not in criteria
                for criterion in step.verification_criteria_ids
            ):
                raise ValueError("step references an unknown verification criterion")
            known.add(step.id)
        if self.deterministic_repair_count > self.deterministic_repair_limit:
            raise ValueError("deterministic repair limit exceeded")
        if self.replan_count > self.replan_limit:
            raise ValueError("replan limit exceeded")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if self.status == "completed" and any(
            step.status not in {"verified", "skipped"} for step in self.steps
        ):
            raise ValueError("completed plan requires all steps verified or skipped")
        return self


class PlanEvent(BaseModel):
    """Append-only audit event emitted by one accepted state transition."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["agent.plan-event.v1"] = "agent.plan-event.v1"
    id: str = Field(min_length=1, max_length=128)
    plan_id: str = Field(min_length=1, max_length=128)
    sequence: int = Field(ge=1)
    plan_revision: int = Field(ge=1)
    event_type: PlanEventType
    step_id: str | None = Field(default=None, min_length=1, max_length=128)
    from_status: str | None = Field(default=None, max_length=64)
    to_status: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=1000)
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def validate_event(self) -> "PlanEvent":
        if self.event_type != "plan_created" and self.step_id is None:
            raise ValueError("step transition event requires step_id")
        if self.event_type == "plan_created" and self.step_id is not None:
            raise ValueError("plan_created event cannot reference a step")
        return self


class PlanTransition(BaseModel):
    """Atomic output of the pure state machine for persistence by a store."""

    model_config = ConfigDict(extra="forbid")

    plan: ExecutionPlan
    event: PlanEvent

    @model_validator(mode="after")
    def validate_transition(self) -> "PlanTransition":
        if self.event.plan_id != self.plan.id:
            raise ValueError("event plan_id must match plan")
        if self.event.plan_revision != self.plan.revision:
            raise ValueError("event revision must match plan revision")
        return self
