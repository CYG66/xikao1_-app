"""Validated, machine-readable contract for deterministic CAD edits."""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


CadEditOperation = Literal[
    "translate", "rotate", "scale", "resize", "duplicate", "align",
    "delete", "retain", "add_constrained", "chain",
    "mirror", "offset", "array", "constraint", "add_template",
    "rearrange_layout", "add_geometry",
]


class CadEditTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["instance", "geometry", "logical_object"]
    instance_ids: list[int] = Field(default_factory=list, max_length=50)
    geometry_ids: list[int] = Field(default_factory=list, max_length=500)
    object_id: str | None = Field(default=None, min_length=1, max_length=128)
    object_ids: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_target(self) -> "CadEditTarget":
        if self.scope == "instance":
            values, other = self.instance_ids, self.geometry_ids
        elif self.scope == "geometry":
            values, other = self.geometry_ids, self.instance_ids
        else:
            values, other = self.geometry_ids, self.instance_ids
        if not values or other:
            raise ValueError("target must contain IDs for exactly one scope")
        if any(value <= 0 for value in values) or len(values) != len(set(values)):
            raise ValueError("target IDs must be unique positive integers")
        if self.scope == "logical_object":
            ids = [value for value in [self.object_id, *self.object_ids] if value]
            if not ids or len(ids) != len(set(ids)):
                raise ValueError("logical_object target requires unique object_id values")
        if self.scope != "logical_object" and (self.object_id is not None or self.object_ids):
            raise ValueError("object_id is only valid for logical_object scope")
        return self


class CadEditParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dx_mm: float | None = None
    dy_mm: float | None = None
    angle_degrees: float | None = None
    pivot: Literal[
        "instance_center", "each_instance_center", "group_center"
    ] | None = None
    factor: float | None = Field(default=None, ge=0.05, le=20.0)
    dimension: Literal["宽度", "高度", "半径"] | None = None
    value_mm: float | None = Field(default=None, gt=0.0)
    direction: Literal["左", "右", "上", "下"] | None = None
    distance_mm: float | None = Field(default=None, gt=0.0)
    placement: Literal["offset", "gap"] | None = None
    alignment: Literal[
        "左", "右", "顶部", "底部", "上", "下", "水平居中", "垂直居中"
    ] | None = None
    boundary_policy: Literal["split_shared"] | None = None
    shared_geometry_ids: list[int] = Field(default_factory=list, max_length=100)
    created_geometry_ids: list[int] = Field(default_factory=list, max_length=100)
    created_object_ids: list[str] = Field(default_factory=list, max_length=50)
    constraint_kind: Literal["symmetric_rectangles_on_circle"] | None = None
    solved_width_mm: float | None = Field(default=None, gt=0.0)
    solved_height_mm: float | None = Field(default=None, gt=0.0)
    mirror_axis: Literal["vertical", "horizontal"] | None = None
    mirror_coordinate_mm: float | None = Field(default=None,allow_inf_nan=False)
    keep_source: bool | None = None
    offset_side: Literal["inside", "outside"] | None = None
    array_mode: Literal["rectangular", "polar"] | None = None
    rows: int | None = Field(default=None, ge=1, le=20)
    columns: int | None = Field(default=None, ge=1, le=20)
    row_spacing_mm: float | None = Field(default=None, gt=0.0)
    column_spacing_mm: float | None = Field(default=None, gt=0.0)
    count: int | None = Field(default=None, ge=2, le=50)
    constraint_type: Literal[
        "parallel", "concentric", "tangent", "equal", "perpendicular"
    ] | None = None
    source_template: Literal["basketball", "badminton", "parking"] | None = None
    target_template: Literal["basketball", "badminton", "parking"] | None = None
    relative_positions: list[Literal["above", "below", "left", "right"]] = Field(
        default_factory=list, min_length=0, max_length=4
    )
    gap_mm: float | None = Field(default=None, ge=0.0)
    arrangement: Literal["long_side_adjacent", "short_side_adjacent"] | None = None
    peer_placement: Literal["above", "below", "left", "right"] | None = None
    layout_strategy: Literal["move_secondary", "rebuild_templates"] | None = None
    selector: "CadEditSelector | None" = None

    @model_validator(mode="after")
    def validate_boundary_parameters(self) -> "CadEditParameters":
        for values in (self.shared_geometry_ids, self.created_geometry_ids):
            if any(value <= 0 for value in values) or len(values) != len(set(values)):
                raise ValueError("boundary geometry IDs must be unique positive integers")
        if self.boundary_policy == "split_shared":
            if not self.shared_geometry_ids or not self.created_geometry_ids:
                raise ValueError("split_shared requires source and created geometry IDs")
            if len(self.shared_geometry_ids) != len(self.created_geometry_ids):
                raise ValueError("split_shared source and created geometry counts must match")
            if set(self.shared_geometry_ids) & set(self.created_geometry_ids):
                raise ValueError("split_shared created IDs must be new")
        elif self.shared_geometry_ids:
            raise ValueError("boundary geometry IDs require split_shared policy")
        if any(not value.strip() for value in self.created_object_ids):
            raise ValueError("created object IDs must not be empty")
        if len(self.created_object_ids) != len(set(self.created_object_ids)):
            raise ValueError("created object IDs must be unique")
        return self


class CadEditSelector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["semantic_within_target", "geometry_within_target"]
    semantic: Literal["中心圆", "外框", "中线"] | None = None
    geometry_type: Literal[
        "line", "circle", "arc", "polyline", "ellipse"
    ] | None = None
    spatial_role: Literal["center"] | None = None

    @model_validator(mode="after")
    def validate_selector(self) -> "CadEditSelector":
        if self.kind == "semantic_within_target":
            if self.semantic is None or self.geometry_type is not None or self.spatial_role is not None:
                raise ValueError("semantic selector requires only semantic")
        elif self.geometry_type is None:
            raise ValueError("geometry selector requires geometry_type")
        return self


class CadEditCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_schema: Literal["cad.edit.v2"] = Field(
        default="cad.edit.v2", alias="schema"
    )
    operation: CadEditOperation
    addition_contract: dict[str, Any] | None = None
    target: CadEditTarget
    coordinate_frame: Literal["drawing", "vehicle", "object_local"] = "drawing"
    parameters: CadEditParameters = Field(default_factory=CadEditParameters)
    reference_instance_id: int | None = Field(default=None, ge=1)
    created_instance_id: int | None = Field(default=None, ge=1)
    source_text: str | None = Field(default=None, max_length=2000)
    assumptions: list[str] = Field(default_factory=list, max_length=20)
    intent_schema: Literal["cad.edit-intent.v1"] | None = None
    intent_parser: Literal["model_structured_fallback"] | None = None
    intent_evidence_text: list[str] = Field(default_factory=list, max_length=6)
    intent_confidence: float | None = Field(default=None, ge=0, le=1)
    intent_grounding: dict[str, Any] = Field(default_factory=dict)
    constraints: list[dict[str, Any]] = Field(default_factory=list, max_length=50)
    missing_parameters: list[str] = Field(default_factory=list, max_length=50)
    auto_decisions: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    chain_steps: list[dict[str, Any]] = Field(default_factory=list, max_length=8)
    project_id: str | None = Field(default=None, min_length=1, max_length=64)
    parent_variant_id: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_operation_parameters(self) -> "CadEditCommand":
        p = self.parameters
        if p.selector is not None and self.target.scope != "instance":
            raise ValueError("local semantic selector requires an instance target")
        if self.operation == "chain":
            if not 2 <= len(self.chain_steps) <= 8:
                raise ValueError("chain requires 2 to 8 steps")
            allowed = {"translate", "rotate", "scale", "resize", "align"}
            for raw in self.chain_steps:
                step = CadEditCommand.model_validate(raw)
                if step.operation not in allowed:
                    raise ValueError("chain steps must use safe operations")
                if step.target.scope != self.target.scope:
                    raise ValueError("chain steps must use one target scope")
                container_ids = (
                    set(self.target.instance_ids)
                    if self.target.scope == "instance"
                    else set(self.target.geometry_ids)
                )
                step_ids = (
                    set(step.target.instance_ids)
                    if step.target.scope == "instance"
                    else set(step.target.geometry_ids)
                )
                if not step_ids or not step_ids.issubset(container_ids):
                    raise ValueError("chain step target must belong to chain target union")
                if self.target.scope == "logical_object":
                    container_objects = {
                        value for value in [
                            self.target.object_id, *self.target.object_ids,
                        ] if value
                    }
                    step_objects = {
                        value for value in [
                            step.target.object_id, *step.target.object_ids,
                        ] if value
                    }
                    if not step_objects.issubset(container_objects):
                        raise ValueError(
                            "chain logical target must belong to chain target union"
                        )
        elif self.operation == "translate":
            if p.dx_mm is None or p.dy_mm is None:
                raise ValueError("translate requires dx_mm and dy_mm")
            if not all(math.isfinite(value) for value in (p.dx_mm, p.dy_mm)):
                raise ValueError("translation values must be finite")
            if abs(p.dx_mm) < 1e-9 and abs(p.dy_mm) < 1e-9:
                relation_check = self.target.scope == "logical_object" and any(
                    c.get("kind") == "concentric" and c.get("moving_object_id")
                    and c.get("reference_object_id") and c.get("reference_geometry_ids")
                    for c in self.constraints
                )
                if not relation_check:
                    raise ValueError("translation must change the geometry")
            if p.boundary_policy == "split_shared":
                if self.target.scope != "logical_object":
                    raise ValueError("split_shared requires a logical_object target")
                if not set(p.shared_geometry_ids).issubset(self.target.geometry_ids):
                    raise ValueError("split_shared source IDs must belong to the target")
        elif self.operation == "rotate":
            if p.angle_degrees is None or not math.isfinite(p.angle_degrees):
                raise ValueError("rotate requires a finite angle")
            if abs(p.angle_degrees) < 1e-9 or p.pivot is None:
                raise ValueError("rotate requires a non-zero angle and pivot")
        elif self.operation == "scale":
            if p.factor is None or abs(p.factor - 1.0) < 1e-9 or p.pivot is None:
                raise ValueError("scale requires a changing factor and pivot")
        elif self.operation == "resize":
            if p.dimension is None or p.value_mm is None:
                raise ValueError("resize requires dimension and value_mm")
        elif self.operation == "duplicate":
            if p.direction is None or p.distance_mm is None or p.placement is None:
                raise ValueError("duplicate requires direction, distance and placement")
            if self.created_instance_id is None and not (self.target.scope in {'geometry','logical_object'} and p.created_geometry_ids):
                raise ValueError("duplicate requires created_instance_id")
        elif self.operation == "align":
            if p.alignment is None or self.reference_instance_id is None:
                raise ValueError("align requires alignment and reference_instance_id")
        elif self.operation == "add_constrained":
            if self.target.scope != "logical_object":
                raise ValueError("add_constrained requires a logical object target")
            if (
                p.constraint_kind is None
                or not p.created_geometry_ids
                or not p.created_object_ids
                or p.solved_width_mm is None
                or p.solved_height_mm is None
            ):
                raise ValueError("add_constrained requires solved geometry evidence")
        elif self.operation == "mirror":
            if p.mirror_axis is None:
                raise ValueError("mirror requires mirror_axis")
            if p.keep_source is not False and self.created_instance_id is None and not (self.target.scope in {'geometry','logical_object'} and p.created_geometry_ids):
                raise ValueError("mirror with keep_source requires created_instance_id")
        elif self.operation == "offset":
            if p.offset_side is None or p.distance_mm is None or (self.created_instance_id is None and not (self.target.scope in {'geometry','logical_object'} and p.created_geometry_ids)):
                raise ValueError("offset requires offset_side, distance_mm and created_instance_id")
        elif self.operation == "array":
            if p.array_mode is None or (self.created_instance_id is None and not (self.target.scope in {'geometry','logical_object'} and p.created_geometry_ids)):
                raise ValueError("array requires array_mode and created_instance_id")
            if p.array_mode == "rectangular" and (
                p.rows is None or p.columns is None
                or p.row_spacing_mm is None or p.column_spacing_mm is None
            ):
                raise ValueError("rectangular array requires rows, columns and both spacings")
            if p.array_mode == "polar" and (
                p.count is None or p.angle_degrees is None
            ):
                raise ValueError("polar array requires count and angle_degrees")
        elif self.operation == "constraint":
            if p.constraint_type is None or self.reference_instance_id is None:
                raise ValueError("constraint requires constraint_type and reference_instance_id")
            if p.constraint_type == "equal" and (
                p.dimension is None or p.value_mm is not None
            ):
                raise ValueError("equal constraint requires dimension and no value_mm")
        elif self.operation == "add_template":
            if self.target.scope != "geometry":
                raise ValueError("add_template requires a geometry target")
            if (
                p.source_template is None
                or p.target_template is None
                or not p.relative_positions
                or len(p.relative_positions) != len(set(p.relative_positions))
                or not p.created_geometry_ids
            ):
                raise ValueError(
                    "add_template requires source/target templates, unique positions and created IDs"
                )
        elif self.operation == "add_geometry":
            if self.target.scope != "geometry" or not p.created_geometry_ids or not isinstance(self.addition_contract, dict):
                raise ValueError("add_geometry requires a geometry baseline, created IDs and addition contract")
        elif self.operation == "rearrange_layout":
            if self.target.scope != "geometry":
                raise ValueError("rearrange_layout requires the source geometry set")
            if (
                p.arrangement is None or p.gap_mm is None
                or p.layout_strategy is None or p.count is None
            ):
                raise ValueError(
                    "rearrange_layout requires arrangement, gap_mm, layout_strategy and count"
                )
        if self.operation != "translate" and p.boundary_policy is not None:
            raise ValueError("split_shared is only supported for translation")
        if self.operation in {'duplicate','mirror','offset','array'} and self.target.scope in {'geometry','logical_object'} and p.created_geometry_ids:
            if set(p.created_geometry_ids)&set(self.target.geometry_ids):
                raise ValueError('created geometry IDs must not replace target IDs')
            copies=(p.rows*p.columns-1 if p.array_mode=='rectangular' else p.count-1) if self.operation=='array' else 1
            if len(p.created_geometry_ids)!=len(self.target.geometry_ids)*copies:
                raise ValueError('created geometry count must match the declared operation')
        return self


_PARAMETER_KEYS = {
    "dx_mm", "dy_mm", "angle_degrees", "pivot", "factor", "dimension",
    "value_mm", "direction", "distance_mm", "placement", "alignment",
    "boundary_policy", "shared_geometry_ids", "created_geometry_ids",
    "created_object_ids", "constraint_kind", "solved_width_mm",
    "solved_height_mm", "mirror_axis", "mirror_coordinate_mm", "keep_source", "offset_side",
    "array_mode", "rows", "columns", "row_spacing_mm",
    "column_spacing_mm", "count", "constraint_type", "selector",
    "source_template", "target_template", "relative_positions", "gap_mm",
    "arrangement", "peer_placement", "layout_strategy",
}


def build_cad_edit_contract(
    edit: dict[str, Any], *, source_text: str | None = None
) -> dict[str, Any]:
    """Build and validate the public v2 contract from a resolved legacy edit."""
    geometry_ids = edit.get("geometry_ids")
    logical_object_id = edit.get("logical_object_id")
    logical_object_ids = edit.get("logical_object_ids")
    instances = edit.get("instances")
    instance = edit.get("instance")
    if (logical_object_id or logical_object_ids) and isinstance(geometry_ids, list) and geometry_ids:
        target = CadEditTarget(
            scope="logical_object",
            object_id=str(logical_object_id) if logical_object_id else None,
            object_ids=[str(value) for value in logical_object_ids or []],
            geometry_ids=geometry_ids,
        )
    elif (isinstance(instance, int)) or (isinstance(instances, list) and instances):
        # A resolved instance target wins over stray geometry IDs. Treating a
        # whole-instance intent as geometry-level can silently edit only part
        # of the drawing — the classic "changed the wrong granularity" failure.
        instance_ids = (
            instances if isinstance(instances, list) and instances
            else [instance] if isinstance(instance, int)
            else []
        )
        target = CadEditTarget(scope="instance", instance_ids=instance_ids)
    elif isinstance(geometry_ids, list) and geometry_ids:
        target = CadEditTarget(scope="geometry", geometry_ids=geometry_ids)
    else:
        instance_ids = (
            instances if isinstance(instances, list) and instances
            else [instance] if isinstance(instance, int)
            else []
        )
        target = CadEditTarget(scope="instance", instance_ids=instance_ids)
    parameters = {
        key: edit[key]
        for key in _PARAMETER_KEYS - {"selector"}
        if edit.get(key) is not None
    }
    selector = edit.get("selector")
    if (
        target.scope == "instance"
        and isinstance(selector, dict)
        and selector.get("kind") in {
            "semantic_within_target", "geometry_within_target",
        }
    ):
        parameters["selector"] = selector
    command = CadEditCommand(
        operation=edit.get("operation"),
        addition_contract=edit.get("addition_contract"),
        target=target,
        coordinate_frame=edit.get("coordinate_frame", "drawing"),
        parameters=CadEditParameters(**parameters),
        reference_instance_id=edit.get("reference_instance"),
        created_instance_id=edit.get("new_instance"),
        source_text=source_text,
        assumptions=list(edit.get("assumptions") or []),
        intent_schema=edit.get("intent_schema"),
        intent_parser=edit.get("intent_parser"),
        intent_evidence_text=list(edit.get("intent_evidence_text") or []),
        intent_confidence=edit.get("intent_confidence"),
        intent_grounding=dict(edit.get("intent_grounding") or {}),
        constraints=list(edit.get("constraints") or []),
        missing_parameters=list(edit.get("missing_parameters") or []),
        auto_decisions=list(edit.get("auto_decisions") or []),
        project_id=edit.get("project_id"),
        parent_variant_id=edit.get("parent_variant_id"),
    )
    payload = command.model_dump(mode="json", by_alias=True, exclude_none=True)
    target_payload = payload.get("target")
    if isinstance(target_payload, dict) and target_payload.get("scope") != "logical_object":
        target_payload.pop("object_id", None)
        target_payload.pop("object_ids", None)
    elif isinstance(target_payload, dict):
        if not target_payload.get("object_id"):
            target_payload.pop("object_id", None)
        if not target_payload.get("object_ids"):
            target_payload.pop("object_ids", None)
    return payload


def build_cad_edit_chain_contract(
    edits: list[dict[str, Any]], *, source_text: str
) -> dict[str, Any]:
    """Build an ordered CAD edit chain with a validated target union."""
    if not 2 <= len(edits) <= 8:
        raise ValueError("CAD edit chain requires 2 to 8 steps")
    steps = [build_cad_edit_contract(edit, source_text=source_text) for edit in edits]
    scopes = {str(step["target"]["scope"]) for step in steps}
    if len(scopes) != 1:
        raise ValueError("CAD edit chain steps must share one target scope")
    scope = scopes.pop()
    if scope == "instance":
        target = CadEditTarget(
            scope="instance",
            instance_ids=sorted({
                int(value)
                for step in steps
                for value in step["target"].get("instance_ids") or []
            }),
        )
    elif scope == "geometry":
        target = CadEditTarget(
            scope="geometry",
            geometry_ids=sorted({
                int(value)
                for step in steps
                for value in step["target"].get("geometry_ids") or []
            }),
        )
    else:
        target = CadEditTarget(
            scope="logical_object",
            geometry_ids=sorted({
                int(value)
                for step in steps
                for value in step["target"].get("geometry_ids") or []
            }),
            object_ids=sorted({
                str(value)
                for step in steps
                for value in [
                    step["target"].get("object_id"),
                    *(step["target"].get("object_ids") or []),
                ]
                if value
            }),
        )
    command = CadEditCommand(
        operation="chain",
        target=target,
        source_text=source_text,
        intent_schema="cad.edit-intent.v1",
        assumptions=[
            "复合修改按用户给出的先后顺序执行",
            "任一步失败时整批回滚",
            "每一步只能修改复合目标并集中的已声明对象",
        ],
        chain_steps=steps,
        project_id=edits[0].get("project_id"),
        parent_variant_id=edits[0].get("parent_variant_id"),
    )
    return command.model_dump(mode="json", by_alias=True, exclude_none=True)


def cad_edit_contract_to_edit(contract: dict[str, Any]) -> dict[str, Any]:
    """Validate a public v2 contract and restore the internal executor shape."""
    command = CadEditCommand.model_validate(contract)
    if command.operation == "chain":
        raise ValueError("chain contract must be replayed with replay_cad_edit_chain")
    payload = command.model_dump(mode="python", by_alias=True, exclude_none=True)
    target = payload["target"]
    ids = (
        list(target["instance_ids"])
        if target["scope"] == "instance"
        else list(target["geometry_ids"])
    )
    edit: dict[str, Any] = {
        "operation": payload["operation"],
        "coordinate_frame": payload.get("coordinate_frame", "drawing"),
        **dict(payload.get("parameters") or {}),
    }
    if target["scope"] == "logical_object":
        edit["geometry_ids"] = ids
        if target.get("object_id"):
            edit["logical_object_id"] = target["object_id"]
        if target.get("object_ids"):
            edit["logical_object_ids"] = target["object_ids"]
    elif target["scope"] == "geometry":
        edit["geometry_ids"] = ids
    elif len(ids) == 1:
        edit["instance"] = ids[0]
    else:
        edit["instance"] = None
        edit["instances"] = ids
    if payload.get("reference_instance_id") is not None:
        edit["reference_instance"] = payload["reference_instance_id"]
    if payload.get("created_instance_id") is not None:
        edit["new_instance"] = payload["created_instance_id"]
    for key in ("project_id", "parent_variant_id"):
        if payload.get(key) is not None:
            edit[key] = payload[key]
    for key in (
        "assumptions", "constraints", "missing_parameters", "auto_decisions",
        "intent_schema", "intent_parser", "intent_evidence_text",
        "intent_confidence", "intent_grounding",
    ):
        if payload.get(key) is not None:
            edit[key] = payload[key]
    return edit
