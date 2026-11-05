"""Strict, deterministic construction plans for the generic 2D CAD PoC.

The module deliberately does not call an LLM and does not persist projects.
It turns a validated symbolic plan into the application's existing CAD IR so
the normal preview, candidate, version and feasibility layers can consume it.
"""

from __future__ import annotations

import math
import re
from copy import deepcopy
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator, field_validator

from .agent_skills import (
    check_drawing_feasibility, DRAWING_TEMPLATE_SKILLS,
    drawing_template_geometries, compose_template_geometries,
    build_template_logical_object_graph,
)
from .cad_constraint_solver import (
    ConstructionConstraint,
    ConstraintSolveError,
    solve_geometric_constraints,
)
from .logical_topology import validate_logical_object_graph
from .tooling import CadGeometry
from .cad_parametric import ParametricError, expression, sample_curve


MAX_CONSTRUCTION_STEPS = 100
MAX_CONSTRUCTION_ENTITIES = 5000
_GEOMETRY_ADAPTER = TypeAdapter(CadGeometry)


class ConstructionPlanError(ValueError):
    """A stable error that can be returned to an LLM for one repair attempt."""

    def __init__(
        self, code: str, message: str, *, step_id: str | None = None,
        assertion_id: str | None = None, constraint_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.step_id = step_id
        self.assertion_id = assertion_id
        self.constraint_id = constraint_id
        self.details = details

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "cad.construction-error.v1",
            "code": self.code,
            "message": self.message,
            **({"step_id": self.step_id} if self.step_id else {}),
            **({"assertion_id": self.assertion_id} if self.assertion_id else {}),
            **({"constraint_id": self.constraint_id} if self.constraint_id else {}),
            **({"details": self.details} if self.details else {}),
        }


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def evaluate_constant_float_fields(cls, value):
        """Accept the same safe constant expressions in every float field.

        Coordinates already support expressions such as ``2*sin(pi/5)``.
        Applying that rule to the other scalar fields keeps the plan protocol
        internally consistent without evaluating names, parameter ``t`` or
        arbitrary Python.
        """
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        for name, field in cls.model_fields.items():
            raw = normalized.get(name)
            annotation = field.annotation
            accepts_float = annotation is float or float in getattr(annotation, "__args__", ())
            if not accepts_float or not isinstance(raw, str):
                continue
            if re.search(r"\bt\b", raw):
                raise ValueError(f"固定数值字段 {name} 不能依赖参数t")
            number = expression(raw)(0)
            if not math.isfinite(number):
                raise ValueError(f"固定数值字段 {name} 必须为有限值")
            normalized[name] = number
        return normalized


class ConstructionPoint(_StrictModel):
    x: float = Field(ge=-100000.0, le=100000.0)
    y: float = Field(ge=-100000.0, le=100000.0)

    @field_validator("x", "y", mode="before", json_schema_input_type=Union[float, str])
    @classmethod
    def evaluate_coordinate(cls, value):
        if isinstance(value, str):
            if re.search(r"\bt\b", value):
                raise ValueError("固定坐标表达式不能依赖参数t")
            return expression(value)(0)
        return value


class ConstructionSemantic(_StrictModel):
    assembly_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    assembly_label: str | None = Field(default=None, min_length=1, max_length=100)
    object_id: str | None = Field(
        default=None, min_length=1, max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    object_type: str = Field(default="drawing_part", min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=100)
    role: str | None = Field(default=None, min_length=1, max_length=64)


class ConstructionStepBase(_StrictModel):
    step_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")
    output_ref: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    layer_id: int = Field(default=1, ge=1, le=1000)
    semantic: ConstructionSemantic


class AddLineStep(ConstructionStepBase):
    op: Literal["add_line"]
    start: ConstructionPoint
    end: ConstructionPoint


class AddPolylineStep(ConstructionStepBase):
    op: Literal["add_polyline"]
    vertices: list[ConstructionPoint] = Field(min_length=2, max_length=500)
    closed: bool = False


class AddRectangleStep(ConstructionStepBase):
    op: Literal["add_rectangle"]
    origin: ConstructionPoint
    width: float = Field(gt=0.0, le=100000.0)
    height: float = Field(gt=0.0, le=100000.0)
    rotation_deg: float = Field(default=0.0, ge=-3600.0, le=3600.0)


class AddCenteredRectangleStep(ConstructionStepBase):
    op: Literal["add_centered_rectangle"]
    center: ConstructionPoint
    width: float = Field(gt=0.0, le=100000.0)
    height: float = Field(gt=0.0, le=100000.0)
    rotation_deg: float = Field(default=0.0, ge=-3600.0, le=3600.0)


class AddCircleStep(ConstructionStepBase):
    op: Literal["add_circle"]
    center: ConstructionPoint
    radius: float = Field(gt=0.0, le=50000.0)


class AddArcStep(ConstructionStepBase):
    op: Literal["add_arc"]
    center: ConstructionPoint
    radius: float = Field(gt=0.0, le=50000.0)
    start_angle: float = Field(ge=-3600.0, le=3600.0, description="Degrees, not radians; half-turn is 180.")
    end_angle: float = Field(ge=-3600.0, le=3600.0, description="Degrees, not radians; half-turn is 180.")


class AddEllipseStep(ConstructionStepBase):
    op: Literal["add_ellipse"]
    center: ConstructionPoint
    major_radius: float = Field(gt=0.0, le=50000.0)
    minor_radius: float = Field(gt=0.0, le=50000.0)
    rotation_deg: float = Field(default=0.0, ge=-3600.0, le=3600.0)
    start_angle: float = Field(default=0.0, ge=-3600.0, le=3600.0)
    end_angle: float = Field(default=360.0, ge=-3600.0, le=3600.0)

    @model_validator(mode="after")
    def validate_axes(self) -> "AddEllipseStep":
        if self.minor_radius > self.major_radius:
            raise ValueError("minor_radius must not exceed major_radius")
        return self


class AddBezierStep(ConstructionStepBase):
    op: Literal["add_bezier"]
    control_points: list[ConstructionPoint] = Field(min_length=3, max_length=4)

    @model_validator(mode="after")
    def validate_degree(self) -> "AddBezierStep":
        if len(self.control_points) not in {3, 4}:
            raise ValueError("bezier requires exactly 3 or 4 control points")
        return self


class AddSplineStep(ConstructionStepBase):
    op: Literal["add_spline"]
    degree: int = Field(default=3, ge=1, le=5)
    control_points: list[ConstructionPoint] = Field(min_length=2, max_length=100)
    closed: bool = False

    @model_validator(mode="after")
    def validate_control_points(self) -> "AddSplineStep":
        if len(self.control_points) <= self.degree:
            raise ValueError("spline requires more control points than its degree")
        return self


class CompositeLineSegment(_StrictModel):
    kind: Literal["line"]
    start: ConstructionPoint
    end: ConstructionPoint


class CompositeBezierSegment(_StrictModel):
    kind: Literal["bezier"]
    control_points: list[ConstructionPoint] = Field(min_length=3, max_length=4)

    @model_validator(mode="after")
    def validate_degree(self) -> "CompositeBezierSegment":
        if len(self.control_points) not in {3, 4}:
            raise ValueError("bezier segment requires exactly 3 or 4 control points")
        return self


class CompositeSplineSegment(_StrictModel):
    kind: Literal["spline"]
    degree: int = Field(default=3, ge=1, le=5)
    control_points: list[ConstructionPoint] = Field(min_length=2, max_length=100)

    @model_validator(mode="after")
    def validate_control_points(self) -> "CompositeSplineSegment":
        if len(self.control_points) <= self.degree:
            raise ValueError("spline segment requires more control points than its degree")
        return self


class CompositeArcSegment(_StrictModel):
    """Exact circular segment inside one logical composite boundary."""
    kind: Literal["arc"]
    center: ConstructionPoint
    radius: float = Field(gt=0.0, le=50000.0)
    start_angle: float = Field(ge=-3600.0, le=3600.0, description="Degrees, not radians; half-turn is 180.")
    end_angle: float = Field(ge=-3600.0, le=3600.0, description="Degrees, not radians; half-turn is 180.")
    clockwise: bool = False


CompositePathSegment = Annotated[
    Union[
        CompositeLineSegment, CompositeBezierSegment,
        CompositeSplineSegment, CompositeArcSegment,
    ],
    Field(discriminator="kind"),
]


class AddCompositePathStep(ConstructionStepBase):
    op: Literal["add_composite_path"]
    segments: list[CompositePathSegment] = Field(min_length=1, max_length=100)
    closed: bool = False
    samples_per_curve: int = Field(default=32, ge=8, le=128)
    connection_tolerance: float = Field(default=0.000001, ge=0.0, le=1.0)
    continuity: Literal["C0", "C1"] = "C0"
    tangent_tolerance_deg: float = Field(default=1.0, ge=0.0, le=45.0)
    allow_self_intersection: bool = False
    allow_duplicate_segments: bool = False
    max_curvature: float | None = Field(default=None, gt=0.0, le=1000000.0)
    max_sampling_error: float | None = Field(default=None, gt=0.0, le=100000.0)


class AddRotationalPathStep(AddCompositePathStep):
    """Repeat a model-designed curve sector into one continuous boundary."""
    op: Literal["add_rotational_path"]
    center: ConstructionPoint = Field(default_factory=lambda: ConstructionPoint(x=0, y=0))
    count: int = Field(ge=2, le=50)
    closed: Literal[True] = True
    fit_width: float | None = Field(default=None, gt=0, le=100000)
    fit_height: float | None = Field(default=None, gt=0, le=100000)
    constrain_sector_end: bool = False
    direction: Literal["auto", "clockwise", "counterclockwise"] = "auto"

    @model_validator(mode="after")
    def validate_fit(self):
        if (self.fit_width is None) != (self.fit_height is None):
            raise ValueError("fit_width and fit_height must be specified together")
        return self


def _expand_rotational_path(step: AddRotationalPathStep) -> AddCompositePathStep:
    payload = step.model_dump(mode="json")
    payload["op"] = "add_composite_path"
    payload.pop("count")
    payload.pop("center")
    payload.pop("fit_width")
    payload.pop("fit_height")
    payload.pop("constrain_sector_end")
    payload.pop("direction")
    seed_segments = deepcopy(step.segments)
    sign = -1 if step.direction == "clockwise" else 1
    if step.direction == "auto":
        start = _segment_start(seed_segments[0])
        tx, ty = _segment_tangent(seed_segments[0], at_end=False)
        cross = (start.x-step.center.x)*ty - (start.y-step.center.y)*tx
        if abs(cross) <= 1e-12:
            end = _segment_end(seed_segments[-1])
            cross = (start.x-step.center.x)*(end.y-step.center.y) - (start.y-step.center.y)*(end.x-step.center.x)
        if abs(cross) <= 1e-12:
            raise ConstructionPlanError("ambiguous_rotation_direction", "无法从曲线单元确定旋转方向，请明确direction。", step_id=step.step_id)
        sign = 1 if cross > 0 else -1
    if step.constrain_sector_end:
        # This is an explicit endpoint relation in the IR, not an inferred
        # geometry repair. Preserve the terminal handle relative to its end.
        start = _segment_start(seed_segments[0])
        angle = sign * math.tau / step.count
        x, y = start.x-step.center.x, start.y-step.center.y
        target = ConstructionPoint(x=step.center.x+math.cos(angle)*x-math.sin(angle)*y,
                                   y=step.center.y+math.sin(angle)*x+math.cos(angle)*y)
        last = seed_segments[-1]
        end = _segment_end(last)
        # constrain_sector_end is an explicit IR relation: derive the end
        # from center/direction/count instead of trusting a model-computed
        # angle. The expanded geometry still passes all independent gates.
        dx, dy = target.x-end.x, target.y-end.y
        if isinstance(last, CompositeLineSegment):
            last.end = target
        elif isinstance(last, CompositeArcSegment):
            actual=math.hypot(target.x-last.center.x,target.y-last.center.y)
            if abs(actual-last.radius)>step.connection_tolerance:
                raise ConstructionPlanError('sector_arc_endpoint_conflict',
                    '旋转周期终点不在末段圆弧的圆上，无法同时保持圆心、半径和端点约束。',
                    step_id=step.step_id,details={'target':target.model_dump(),
                        'arc_center':last.center.model_dump(),'radius':last.radius,'target_radius':actual,
                        'repair_instruction':'修正该周期的圆弧圆心或其连接方案，使目标终点落在既定圆弧上；不能将圆弧当成贝塞尔控制点修改。'})
            last.end_angle=math.degrees(math.atan2(target.y-last.center.y,target.x-last.center.x))
        else:
            last.control_points[-1] = target
            last.control_points[-2].x += dx
            last.control_points[-2].y += dy
            if step.continuity == "C1":
                tx, ty = _segment_tangent(seed_segments[0], at_end=False)
                rx, ry = math.cos(angle)*tx-math.sin(angle)*ty, math.sin(angle)*tx+math.cos(angle)*ty
                length = math.hypot(rx, ry)
                handle = _point_distance(target, last.control_points[-2])
                if length > 1e-12:
                    last.control_points[-2] = ConstructionPoint(
                        x=target.x-rx*handle/length, y=target.y-ry*handle/length)
    if not step.allow_duplicate_segments:
        for index,segment in enumerate(seed_segments):
            if not isinstance(segment,CompositeArcSegment) or _point_distance(segment.center,step.center)>step.connection_tolerance:
                continue
            sweep=((segment.start_angle-segment.end_angle) if segment.clockwise
                   else (segment.end_angle-segment.start_angle))%360
            if math.isclose(sweep,0,abs_tol=1e-12) and not math.isclose(segment.start_angle,segment.end_angle,abs_tol=1e-12):sweep=360
            period=360/step.count
            if sweep>period+math.degrees(step.connection_tolerance/segment.radius):
                alternative=360-sweep
                raise ConstructionPlanError('rotational_arc_overlaps_period',
                    '种子圆弧与旋转中心同心，但角度跨度大于一个周期，展开后必然重复。',
                    step_id=step.step_id,details={'seed_segment_index':index,
                        'start_angle_degrees':segment.start_angle,'end_angle_degrees':segment.end_angle,
                        'clockwise':segment.clockwise,'arc_sweep_degrees':sweep,
                        'period_degrees':period,'rotation_count':step.count,
                        'opposite_direction_sweep_degrees':alternative,
                        'repair_instruction':'修正该圆弧角度或clockwise方向，使它只覆盖单个周期内的弧段，并与前后端点连接。注意跨越0度时可能错误地选成接近360度的长弧；若保持端点反向遍历可满足周期，请仅改正方向，不要修改用户半径或生成整图坐标。'})
    segments = []
    for index in range(step.count):
        angle = sign * math.tau * index / step.count
        cosine, sine = math.cos(angle), math.sin(angle)
        for original in seed_segments:
            segment = original.model_dump(mode="json")
            points = ([segment["start"], segment["end"]] if segment["kind"] == "line"
                      else [segment['center']] if segment['kind']=='arc' else segment["control_points"])
            for point in points:
                x, y = point["x"] - step.center.x, point["y"] - step.center.y
                point["x"] = step.center.x + cosine*x - sine*y
                point["y"] = step.center.y + sine*x + cosine*y
            if segment['kind']=='arc':
                segment['start_angle']+=math.degrees(angle)
                segment['end_angle']+=math.degrees(angle)
            segments.append(segment)
    payload["segments"] = segments
    expanded = AddCompositePathStep.model_validate(payload)
    if step.fit_width is not None:
        sampled = _sample_composite_path(expanded)
        xs, ys = [p.x for p in sampled], [p.y for p in sampled]
        width, height = max(xs)-min(xs), max(ys)-min(ys)
        if min(width, height) <= 1e-12:
            raise ConstructionPlanError("degenerate_rotational_path", "重复路径尺寸退化", step_id=step.step_id)
        for segment in payload["segments"]:
            points = ([segment["start"], segment["end"]] if segment["kind"] == "line"
                      else [segment['center']] if segment['kind']=='arc' else segment["control_points"])
            if segment['kind']=='arc':
                fx,fy=step.fit_width/width,step.fit_height/height
                if not math.isclose(fx,fy,rel_tol=1e-8,abs_tol=1e-10):
                    raise ConstructionPlanError('nonuniform_arc_fit',
                        '圆弧不能按不同横纵比例缩放后仍保留为圆弧。',step_id=step.step_id,
                        details={'scale_x':fx,'scale_y':fy})
                segment['radius']*=fx
            for point in points:
                point["x"] = step.center.x + (point["x"]-step.center.x)*step.fit_width/width
                point["y"] = step.center.y + (point["y"]-step.center.y)*step.fit_height/height
        expanded = AddCompositePathStep.model_validate(payload)
    return expanded


class AddParametricCurveStep(ConstructionStepBase):
    op: Literal["add_parametric_curve"]
    x_expression: str = Field(min_length=1, max_length=512)
    y_expression: str = Field(min_length=1, max_length=512)
    t_start: str = Field(default="0", min_length=1, max_length=512)
    t_end: str = Field(min_length=1, max_length=512)
    max_sampling_error: float = Field(default=0.001, gt=0, le=1)
    closed: bool = False


class RectangularArrayStep(ConstructionStepBase):
    op: Literal["rectangular_array"]
    source_ref: str = Field(min_length=1, max_length=128)
    rows: int = Field(default=1, ge=1, le=50)
    columns: int = Field(default=1, ge=1, le=50)
    row_spacing: float = Field(default=0.0, ge=-100000.0, le=100000.0)
    column_spacing: float = Field(default=0.0, ge=-100000.0, le=100000.0)
    include_source: bool = False


class TemplateInstanceSpec(_StrictModel):
    template: str = Field(min_length=1, max_length=64)
    width_m: float | None = Field(default=None, gt=0, le=100)
    height_m: float | None = Field(default=None, gt=0, le=100)
    radius_m: float | None = Field(default=None, gt=0, le=100)
    quantity: int = Field(default=1, ge=1, le=50)
    spacing_m: float = Field(default=0, ge=0, le=100)
    arrangement: Literal["long_side_adjacent", "short_side_adjacent"] | None = None
    spacing_reference: Literal["edge", "center", "standard_parking_space_width"] | None = None
    peer_placement: Literal["right", "above", "left", "below"] | None = None
    placement: list[Literal["right", "left", "above", "below", "between"]] = Field(default_factory=list, max_length=4)
    placement_inferred: bool = False
    layout_override: bool = False
    grid_columns: int = Field(default=4, ge=1, le=50)
    grid_rows: int = Field(default=4, ge=1, le=50)

    @field_validator("template")
    @classmethod
    def registered_template(cls, value):
        if value not in DRAWING_TEMPLATE_SKILLS:
            raise ValueError("unknown CAD template")
        return value


class AddTemplateStep(ConstructionStepBase):
    """Backend-owned parameterized templates; dimensions always use metres."""
    op: Literal["add_template"]
    matches: list[TemplateInstanceSpec] = Field(min_length=1, max_length=10)
    circumscribed_circle: bool = False
    origin: ConstructionPoint = Field(default_factory=lambda: ConstructionPoint(x=0, y=0))
    rotation_deg: float = Field(default=0, ge=-3600, le=3600)


ConstructionStep = Annotated[
    Union[
        AddLineStep, AddPolylineStep, AddRectangleStep,
        AddCenteredRectangleStep, AddCircleStep, AddArcStep, AddEllipseStep,
        AddBezierStep, AddSplineStep, AddCompositePathStep, AddRotationalPathStep,
        RectangularArrayStep, AddParametricCurveStep, AddTemplateStep,
    ],
    Field(discriminator="op"),
]


class EntityCountAssertion(_StrictModel):
    kind: Literal["entity_count"]
    assertion_id: str = Field(min_length=1, max_length=64)
    target_ref: str | None = Field(default=None, min_length=1, max_length=128)
    equals: int = Field(ge=0, le=MAX_CONSTRUCTION_ENTITIES)


class BoundsSizeAssertion(_StrictModel):
    kind: Literal["bounds_size"]
    assertion_id: str = Field(min_length=1, max_length=64)
    target_ref: str | None = Field(default=None, min_length=1, max_length=128)
    width: float = Field(ge=0.0, le=100000.0)
    height: float = Field(ge=0.0, le=100000.0)
    tolerance: float = Field(default=0.001, ge=0.0, le=1000.0)


class ClosedAssertion(_StrictModel):
    kind: Literal["closed"]
    assertion_id: str = Field(min_length=1, max_length=64)
    target_ref: str = Field(min_length=1, max_length=128)


class RadialPatternAssertion(_StrictModel):
    kind: Literal["radial_pattern"]
    assertion_id: str = Field(min_length=1, max_length=64)
    target_ref: str = Field(min_length=1, max_length=128)
    lobes: int = Field(ge=2, le=100)
    profile: Literal["smooth", "polygonal"] = "smooth"


class CenterDistanceAssertion(_StrictModel):
    kind: Literal["center_distance"]
    assertion_id: str = Field(min_length=1, max_length=64)
    target_ref: str = Field(min_length=1, max_length=128)
    reference_ref: str = Field(min_length=1, max_length=128)
    distance: float = Field(ge=0.0, le=100000.0)
    tolerance: float = Field(default=0.001, ge=0.0, le=1000.0)


class AreaAssertion(_StrictModel):
    kind: Literal["area"]
    assertion_id: str = Field(min_length=1, max_length=64)
    target_ref: str = Field(min_length=1, max_length=128)
    area: float = Field(gt=0.0, le=10_000_000_000.0)
    tolerance: float = Field(default=0.01, ge=0.0, le=1_000_000.0)


ConstructionAssertion = Annotated[
    Union[
        EntityCountAssertion, BoundsSizeAssertion, ClosedAssertion, AreaAssertion,
        RadialPatternAssertion, CenterDistanceAssertion,
    ],
    Field(discriminator="kind"),
]


class ConstructionBudgets(_StrictModel):
    max_steps: int = Field(default=MAX_CONSTRUCTION_STEPS, ge=1, le=MAX_CONSTRUCTION_STEPS)
    max_entities: int = Field(default=500, ge=1, le=MAX_CONSTRUCTION_ENTITIES)


class FreeOutlineLayout(_StrictModel):
    """Fit an existing free outline, then place it relative to another one."""
    target_ref: str = Field(min_length=1, max_length=128)
    width: float | None = Field(default=None,gt=0, le=100000)
    height: float | None = Field(default=None,gt=0, le=100000)
    right_of_ref: str | None = None
    gap: float = Field(default=0, ge=0, le=100000)
    gap_reference: Literal["edge", "center"] = "edge"
    center: ConstructionPoint | None = None

    @model_validator(mode='after')
    def complete_fit_or_translation(self):
        if (self.width is None)!=(self.height is None):
            raise ValueError('布局缩放必须同时指定宽高')
        if self.width is None and self.center is None and self.right_of_ref is None:
            raise ValueError('无缩放尺寸时必须指定中心位置或相对定位')
        if self.center is not None and self.right_of_ref is not None:
            raise ValueError('中心定位不能同时指定相对排列')
        return self


class CadConstructionPlan(_StrictModel):
    schema_version: Literal["cad.construction-plan.v1"] = "cad.construction-plan.v1"
    units: Literal["m", "mm"] = "m"
    project_id: str | None = Field(default=None, min_length=1, max_length=128)
    source_version: int | None = Field(default=None, ge=1)
    steps: list[ConstructionStep] = Field(min_length=1, max_length=MAX_CONSTRUCTION_STEPS)
    constraints: list[ConstructionConstraint] = Field(default_factory=list, max_length=100)
    constraint_backend: Literal["auto", "builtin", "solvespace", "planegcs"] = "auto"
    assertions: list[ConstructionAssertion] = Field(default_factory=list, max_length=100)
    budgets: ConstructionBudgets = Field(default_factory=ConstructionBudgets)
    free_outline_layout: list[FreeOutlineLayout] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_plan_graph(self) -> "CadConstructionPlan":
        if len(self.steps) > self.budgets.max_steps:
            raise ValueError("steps exceed budgets.max_steps")
        from .cad_plan_references import plan_reference_errors
        import json
        errors = plan_reference_errors(self)
        if errors:
            raise ValueError("plan_reference_validation_failed: " + json.dumps(
                errors, ensure_ascii=False))
        return self


def execute_construction_plan(
    plan: CadConstructionPlan | dict[str, Any],
) -> dict[str, Any]:
    """Execute a plan in an isolated working state and return existing CAD IR.

    No caller-owned geometry is mutated. Any failed step, assertion or graph
    validation raises ``ConstructionPlanError`` and returns no partial result.
    """
    validated = plan if isinstance(plan, CadConstructionPlan) else CadConstructionPlan.model_validate(plan)
    scale = 1000.0 if validated.units == "m" else 1.0
    geometries: list[dict[str, Any]] = []
    refs: dict[str, list[int]] = {}
    objects: list[dict[str, Any]] = []
    topology = {"schema_version": "cad.topology.v1", "shared_geometries": [], "relations": []}
    curve_quality: list[dict[str, Any]] = []
    next_id = 1

    for step in validated.steps:
        if isinstance(step, AddParametricCurveStep):
            try:
                if re.search(r"\bt\b", step.t_start + " " + step.t_end):
                    raise ParametricError("参数区间端点不能依赖t")
                start, end = expression(step.t_start)(0), expression(step.t_end)(0)
                if not start < end or end-start > 100000:
                    raise ParametricError("参数区间必须有限递增且跨度不超过100000")
                points, error = sample_curve(step.x_expression, step.y_expression,
                                             start, end, step.max_sampling_error)
                sampling_tolerance=step.max_sampling_error
                layout=next((item for item in validated.free_outline_layout if item.target_ref==step.output_ref),None)
                if layout is not None and layout.width is not None:
                    width=max(p[0] for p in points)-min(p[0] for p in points)
                    height=max(p[1] for p in points)-min(p[1] for p in points)
                    if min(width,height)>1e-12:
                        amplification=max(layout.width/width,layout.height/height)
                        if error*amplification>step.max_sampling_error:
                            sampling_tolerance=step.max_sampling_error/amplification*.95
                            points,error=sample_curve(step.x_expression,step.y_expression,start,end,sampling_tolerance)
                if step.closed:
                    if math.dist(points[0], points[-1]) > step.max_sampling_error:
                        raise ParametricError("闭合曲线的公式端点不重合")
                    points[-1] = points[0]
                curve_quality.append({"step_id": step.step_id, "kind": "parametric",
                                      "output_ref": step.output_ref,
                                      "max_sampling_error": step.max_sampling_error,
                                      "observed_sampling_error": error,
                                      "pre_layout_sampling_tolerance":sampling_tolerance,
                                      "point_count": len(points)})
                payload = step.model_dump(include={"step_id", "output_ref", "layer_id", "semantic", "closed"})
                step = AddPolylineStep(**payload, op="add_polyline",
                                       vertices=[ConstructionPoint(x=x, y=y) for x, y in points])
            except ParametricError as exc:
                from .cad_parametric import construction_expression_errors
                diagnostics=construction_expression_errors(validated.model_dump(mode='json'))
                details={'expression_errors':diagnostics} if diagnostics else {}
                if diagnostics:
                    details['affected_output_refs']=sorted({d['output_ref'] for d in diagnostics if d['output_ref']})
                    details['repair_instruction']='一次修正expression_errors列出的全部表达式；仅允许t、pi、e，其他参数按需求展开为数值，保留全部未失败部件。'
                raise ConstructionPlanError("invalid_parametric_curve", str(exc), step_id=step.step_id,details=details) from exc
        rotational_source=step if isinstance(step,AddRotationalPathStep) else None
        if isinstance(step, AddRotationalPathStep):
            step = _expand_rotational_path(step)
        if isinstance(step, AddCompositePathStep):
            try:
                curve_quality.append(_validate_composite_path_quality(step))
            except ConstructionPlanError as exc:
                if rotational_source and (exc.details or {}).get('conflicts'):
                    size=len(rotational_source.segments)
                    exc.details['seed_segment_count']=size
                    exc.details['rotation_count']=rotational_source.count
                    for pair in exc.details['conflicts']:
                        pair['seed_segment_indices']=[i%size for i in pair['expanded_segment_indices']]
                        pair['rotation_instances']=[i//size for i in pair['expanded_segment_indices']]
                raise
        predicted_count = _predicted_entity_count(step, refs)
        if len(geometries) + predicted_count > validated.budgets.max_entities:
            raise ConstructionPlanError(
                "entity_budget_exceeded",
                f"图元数量超过计划上限 {validated.budgets.max_entities}",
                step_id=step.step_id,
            )
        try:
            created = _execute_step(step, refs, geometries, next_id, scale)
        except ConstructionPlanError:
            raise
        except Exception as exc:  # stable boundary for deterministic repair
            raise ConstructionPlanError(
                "step_execution_failed", str(exc), step_id=step.step_id,
            ) from exc
        if not created and not (
            isinstance(step, RectangularArrayStep) and step.include_source
        ):
            raise ConstructionPlanError(
                "empty_step_result", "构造步骤没有生成任何图元", step_id=step.step_id,
            )
        try:
            checked = []
            for item in created:
                # These tags come exclusively from the local template engine.
                tags = {key: value for key, value in item.items()
                        if isinstance(step, AddTemplateStep) and key in {
                            "template_instance", "template_type", "label", "role", "path_semantic"}}
                geometry = _GEOMETRY_ADAPTER.validate_python(
                    {key: value for key, value in item.items() if key not in tags}).model_dump()
                checked.append({**geometry, **tags})
        except Exception as exc:
            raise ConstructionPlanError(
                "invalid_geometry_result", str(exc), step_id=step.step_id,
            ) from exc
        if len(geometries) + len(checked) > validated.budgets.max_entities:
            raise ConstructionPlanError("entity_budget_exceeded", "模板展开后图元数量超过计划上限", step_id=step.step_id)
        geometries.extend(checked)
        created_ids = [int(item["id"]) for item in checked]
        if isinstance(step, RectangularArrayStep):
            source_ids = list(refs[step.source_ref])
            refs[step.output_ref] = (
                source_ids + created_ids if step.include_source else created_ids
            )
            objects.extend(
                _array_logical_objects(step, checked, len(source_ids))
            )
        else:
            refs[step.output_ref] = created_ids
            if isinstance(step, AddTemplateStep):
                match = step.matches[0].model_dump(exclude_none=True)
                graph = build_template_logical_object_graph(match, checked)
                existing_ids = {item["object_id"] for item in objects}
                if any(item["object_id"] in existing_ids for item in graph["logical_objects"]):
                    names = {item["object_id"]: f"{step.output_ref}:{item['object_id']}"
                             for item in graph["logical_objects"]}
                    for item in graph["logical_objects"]:
                        item["object_id"] = names[item["object_id"]]
                        item["identity_key"] = item["object_id"]
                    for item in graph["topology"].get("shared_geometries") or []:
                        item["object_ids"] = [names[value] for value in item["object_ids"]]
                    for item in graph["topology"].get("relations") or []:
                        for key in ("source_object_id", "target_object_id"):
                            item[key] = names[item[key]]
                # Preserve per-instance identities, including shared parking edges.
                objects.extend(graph["logical_objects"])
                for key in ("shared_geometries", "relations"):
                    topology[key].extend(graph["topology"].get(key) or [])
            else:
                objects.append(_logical_object(step, checked))
        if created_ids:
            next_id = max(created_ids) + 1

    _apply_free_outline_layout(validated.free_outline_layout, geometries, refs, scale, curve_quality)
    try:
        geometries, constraint_solve = solve_geometric_constraints(
            geometries,
            refs,
            validated.constraints,
            unit_scale=scale,
            backend=validated.constraint_backend,
        )
    except ConstraintSolveError as exc:
        raise ConstructionPlanError(
            exc.code,
            exc.message,
            constraint_id=exc.constraint_id,
        ) from exc
    _refresh_logical_object_bounds(objects, geometries)
    if len(objects)==1 and not objects[0].get('assembly_id') and set(objects[0].get('geometry_refs') or [])=={g['id'] for g in geometries}:
        objects[0]['assembly_id']='assembly:'+objects[0]['object_id']
        objects[0]['assembly_label']=objects[0].get('label') or '完整图形'
    graph_validation = validate_logical_object_graph(geometries, objects, topology)
    graph_details={}
    if not graph_validation['verified']:
        identity_members={}
        for item in objects:
            identity_members.setdefault(item.get('object_id'),[]).append({
                'label':item.get('label'),'assembly_id':item.get('assembly_id'),
                'geometry_refs':deepcopy(item.get('geometry_refs') or []),
                'source_steps':[{'step_id':step.step_id,'output_ref':step.output_ref}
                    for step in validated.steps if set(refs.get(step.output_ref) or []) & set(item.get('geometry_refs') or [])]})
        identity_conflicts=[{'object_id':key,'members':members} for key,members in identity_members.items() if len(members)>1]
        graph_details={'validation_errors':graph_validation['errors'],'identity_conflicts':identity_conflicts,
            'identity_contract':'不同部件使用不同object_id；同一整体的部件共享assembly_id。不能合并或丢弃几何以消除ID冲突。'}
        if identity_conflicts and all(e.get('code')=='invalid_object_ids' for e in graph_validation['errors']):
            graph_details['identity_only_repair']=True
            graph_details['affected_output_refs']=sorted({s['output_ref'] for conflict in identity_conflicts
                for member in conflict['members'] for s in member['source_steps']})
    try:
        _run_assertions(validated.assertions, geometries, refs, scale)
    except ConstructionPlanError as exc:
        # Report identity errors alongside the first geometric assertion so
        # one bounded model repair can address both, rather than hiding one.
        if not graph_validation['verified']:
            exc.details={**(exc.details or {}),'logical_graph_validation':graph_details}
        raise
    if not graph_validation["verified"]:
        raise ConstructionPlanError(
            "logical_graph_invalid",
            str(graph_validation["errors"]),
            details=graph_details,
        )
    feasibility = check_drawing_feasibility(geometries)
    if not feasibility["ok"]:
        raise ConstructionPlanError(
            "drawing_infeasible", "；".join(feasibility["errors"]),
        )
    return {
        "schema": "cad.construction-result.v1",
        "plan": validated.model_dump(mode="json"),
        "geometries": deepcopy(geometries),
        "logical_objects": deepcopy(objects),
        "topology": topology,
        "symbol_table": deepcopy(refs),
        "assertions": {"ok": True, "count": len(validated.assertions)},
        "constraint_solve": constraint_solve,
        "curve_quality": curve_quality,
        "feasibility": feasibility,
        "graph_validation": graph_validation,
    }


def construction_plan_json_schema() -> dict[str, Any]:
    """Return the exact provider-facing schema for structured LLM output."""
    return CadConstructionPlan.model_json_schema()


def construction_geometry_bounds(
    geometries: list[dict[str, Any]],
) -> dict[str, float]:
    """Return exact axis-aligned bounds for already validated CAD IR."""
    return _bounds(geometries)


def construction_geometry_area(
    geometries: list[dict[str, Any]],
) -> float:
    """Return the enclosed area of validated CAD IR in internal square units."""
    return sum(_closed_geometry_area(item) for item in geometries)


def _apply_free_outline_layout(layout, geometries, refs, scale, curve_quality=()):
    by_id = {g["id"]:g for g in geometries}
    def target(ref):
        selected = [by_id[i] for i in refs.get(ref, [])]
        if len(selected) != 1 or selected[0].get("type") != "polyline" or not selected[0].get("closed"):
            raise ConstructionPlanError("invalid_layout_target", "自由轮廓布局必须绑定唯一闭合多段线")
        return selected[0]
    for item in layout:
        g = target(item.target_ref)
        b = _bounds([g])
        w,h=b["max_x"]-b["min_x"],b["max_y"]-b["min_y"]
        if min(w,h)<=1e-9:
            raise ConstructionPlanError("invalid_layout_target", "退化轮廓不能施加宽高约束")
        resize=item.width is not None
        amplification=max(item.width*scale/w,item.height*scale/h) if resize else 1.0
        for quality in curve_quality:
            if quality.get("output_ref") != item.target_ref:
                continue
            field="observed_sampling_error" if quality.get("kind")=="parametric" else "maximum_sampling_error"
            error=quality[field]*amplification
            quality["post_layout_sampling_error_bound"]=error
            limit=quality.get("max_sampling_error")
            if limit is not None and error>limit:
                raise ConstructionPlanError("sampling_error_exceeded", "尺寸缩放后采样误差上界超过精度限制", step_id=quality["step_id"],
                                            details={"sampling_error_bound":error,"limit":limit,"scale":amplification})
        cx,cy=(b["min_x"]+b["max_x"])/2,(b["min_y"]+b["max_y"])/2
        if resize:
            for p in g["vertices"]:
                p["x"]=cx+(p["x"]-cx)*item.width*scale/w
                p["y"]=cy+(p["y"]-cy)*item.height*scale/h
        if item.right_of_ref is not None:
            reference=_bounds([target(item.right_of_ref)])
            current=_bounds([g])
            dx=(reference["max_x"]+item.gap*scale-current["min_x"] if item.gap_reference=="edge"
                else (reference["min_x"]+reference["max_x"])/2+item.gap*scale-cx)
            dy=(reference["min_y"]+reference["max_y"])/2-cy
            for p in g["vertices"]:
                p["x"]+=dx;p["y"]+=dy
        elif item.center is not None:
            for p in g['vertices']:
                p['x'] += item.center.x*scale-cx
                p['y'] += item.center.y*scale-cy


def _predicted_entity_count(
    step: ConstructionStep, refs: dict[str, list[int]],
) -> int:
    if isinstance(step, RectangularArrayStep):
        placements = step.rows * step.columns - 1
        return len(refs[step.source_ref]) * placements
    return 1


def _execute_step(
    step: ConstructionStep, refs: dict[str, list[int]],
    geometries: list[dict[str, Any]], next_id: int, scale: float,
) -> list[dict[str, Any]]:
    point = lambda value: {"x": value.x * scale, "y": value.y * scale, "z": 0.0}
    base = {"id": next_id, "layer_id": step.layer_id}
    if isinstance(step, AddTemplateStep):
        matches = [{**DRAWING_TEMPLATE_SKILLS[item.template],
                    **item.model_dump(exclude_none=True)} for item in step.matches]
        created = (compose_template_geometries(matches) if len(matches) > 1
                   else drawing_template_geometries(matches[0])) or []
        if step.circumscribed_circle:
            if len(matches) != 1 or matches[0]["template"] != "basketball" or matches[0]["quantity"] != 1:
                raise ValueError("外接圆仅支持单个篮球场")
            match = matches[0]
            created.append({"id": len(created) + 1, "type": "circle", "layer_id": step.layer_id,
                            "center": {"x": 0.0, "y": 0.0, "z": 0.0},
                            "radius": math.hypot(match["width_m"], match["height_m"]) * 500,
                            "template_instance": 1, "template_type": "basketball",
                            "label": "篮球场外接圆", "role": "printing", "path_semantic": "printing"})
        instance_offset = max((int(item.get("template_instance") or 0) for item in geometries), default=0)
        for index, item in enumerate(created):
            item["id"] = next_id + index
            item["layer_id"] = step.layer_id
            if item.get("template_instance"):
                item["template_instance"] += instance_offset
            angle = math.radians(step.rotation_deg)
            def transform(point):
                x, y = point["x"], point["y"]
                point["x"] = math.cos(angle) * x - math.sin(angle) * y + step.origin.x * scale
                point["y"] = math.sin(angle) * x + math.cos(angle) * y + step.origin.y * scale
            for key in ("start", "end", "center", "position"):
                if isinstance(item.get(key), dict):
                    transform(item[key])
            for key in ("vertices", "control_points"):
                for point in item.get(key) or []:
                    transform(point)
            if item["type"] == "arc":
                item["start_angle"] += step.rotation_deg
                item["end_angle"] += step.rotation_deg
            if item["type"] == "ellipse":
                axis = item['major_axis']
                x, y = axis['x'], axis['y']
                axis['x'] = math.cos(angle)*x-math.sin(angle)*y
                axis['y'] = math.sin(angle)*x+math.cos(angle)*y
        return created
    if isinstance(step, AddLineStep):
        return [{**base, "type": "line", "start": point(step.start), "end": point(step.end)}]
    if isinstance(step, AddPolylineStep):
        return [{
            **base, "type": "polyline",
            "vertices": [point(value) for value in step.vertices],
            "closed": step.closed,
        }]
    if isinstance(step, AddRectangleStep):
        vertices = [
            (0.0, 0.0), (step.width, 0.0),
            (step.width, step.height), (0.0, step.height),
        ]
        angle = math.radians(step.rotation_deg)
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        values = [ConstructionPoint(
            x=step.origin.x + x * cos_a - y * sin_a,
            y=step.origin.y + x * sin_a + y * cos_a,
        ) for x, y in vertices]
        return [{
            **base, "type": "polyline",
            "vertices": [point(value) for value in values], "closed": True,
        }]
    if isinstance(step, AddCenteredRectangleStep):
        half_width = step.width / 2.0
        half_height = step.height / 2.0
        vertices = [
            (-half_width, -half_height), (half_width, -half_height),
            (half_width, half_height), (-half_width, half_height),
        ]
        angle = math.radians(step.rotation_deg)
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        values = [ConstructionPoint(
            x=step.center.x + x * cos_a - y * sin_a,
            y=step.center.y + x * sin_a + y * cos_a,
        ) for x, y in vertices]
        return [{
            **base, "type": "polyline",
            "vertices": [point(value) for value in values], "closed": True,
        }]
    if isinstance(step, AddCircleStep):
        return [{
            **base, "type": "circle", "center": point(step.center),
            "radius": step.radius * scale,
        }]
    if isinstance(step, AddArcStep):
        return [{
            **base, "type": "arc", "center": point(step.center),
            "radius": step.radius * scale,
            "start_angle": step.start_angle, "end_angle": step.end_angle,
        }]
    if isinstance(step, AddEllipseStep):
        angle = math.radians(step.rotation_deg)
        return [{
            **base, "type": "ellipse", "center": point(step.center),
            "major_axis": {
                "x": step.major_radius * math.cos(angle) * scale,
                "y": step.major_radius * math.sin(angle) * scale,
                "z": 0.0,
            },
            "ratio": step.minor_radius / step.major_radius,
            "start_angle": step.start_angle, "end_angle": step.end_angle,
        }]
    if isinstance(step, AddBezierStep):
        return [{
            **base, "type": "spline",
            "degree": len(step.control_points) - 1,
            "control_points": [point(value) for value in step.control_points],
            "closed": False,
        }]
    if isinstance(step, AddSplineStep):
        return [{
            **base, "type": "spline", "degree": step.degree,
            "control_points": [point(value) for value in step.control_points],
            "closed": step.closed,
            "periodic":step.closed,
        }]
    if isinstance(step, AddCompositePathStep):
        vertices = _sample_composite_path(step)
        return [{
            **base, "type": "polyline",
            "vertices": [point(value) for value in vertices],
            "closed": step.closed,
        }]
    if isinstance(step, RectangularArrayStep):
        source_ids = set(refs[step.source_ref])
        sources = [item for item in geometries if int(item["id"]) in source_ids]
        created: list[dict[str, Any]] = []
        cursor = next_id
        for row in range(step.rows):
            for column in range(step.columns):
                if row == 0 and column == 0:
                    continue
                dx = column * step.column_spacing * scale
                dy = row * step.row_spacing * scale
                for source in sources:
                    clone = _translate_geometry(source, dx, dy)
                    clone["id"] = cursor
                    clone["layer_id"] = step.layer_id
                    created.append(clone)
                    cursor += 1
        return created
    raise ConstructionPlanError(
        "unsupported_operation", f"不支持操作 {step.op}", step_id=step.step_id,
    )


def _effective_composite_samples(step: AddCompositePathStep) -> int:
    """Allocate the executor's point budget without altering curve controls."""
    curves = sum(not isinstance(segment, CompositeLineSegment) for segment in step.segments)
    lines = len(step.segments) - curves
    # Each connected segment contributes intervals; an open path adds one
    # terminal point. Closure removes that terminal point after sampling.
    available = 500 - lines - (0 if step.closed else 1)
    effective = min(step.samples_per_curve, available // curves) if curves else step.samples_per_curve
    if effective < 8 or available < 0:
        raise ConstructionPlanError(
            "composite_sampling_budget_exceeded",
            "路径复杂度超过500点预算，无法保持每段至少8次采样；请简化曲线表达。",
            step_id=step.step_id,
        )
    # A model's sample count is a starting resolution, not an accuracy
    # guarantee. Refine the same curve within the existing point budget
    # before rejecting it. Never change controls or relax the tolerance.
    if curves and step.max_sampling_error is not None:
        ceiling = available // curves
        while effective < ceiling and _maximum_composite_sampling_error(step, effective) > step.max_sampling_error:
            effective = min(ceiling, effective * 2)
    return effective


def _sample_composite_path(step: AddCompositePathStep) -> list[ConstructionPoint]:
    segments = step.segments
    for index,segment in enumerate(segments):
        if isinstance(segment,CompositeArcSegment) and math.isclose(
                segment.start_angle,segment.end_angle,rel_tol=0,abs_tol=1e-12):
            raise ConstructionPlanError('zero_sweep_composite_arc',
                f'复合路径第 {index+1} 段圆弧起止角相同，角度跨度为零。',step_id=step.step_id,
                details={'segment_index':index,'start_angle_degrees':segment.start_angle,
                    'end_angle_degrees':segment.end_angle,
                    'repair_instruction':'零跨度圆弧不是完整圆。若该段没有长度，应从连接计划中移除；若需要圆弧，按相邻端点计算正确角度。完整圆须明确360度跨度，不能靠重复采样生成。'})
    for index in range(1, len(segments)):
        previous = _segment_end(segments[index - 1])
        current = _segment_start(segments[index])
        if _point_distance(previous, current) > step.connection_tolerance:
            raise ConstructionPlanError(
                "disconnected_composite_path",
                f"复合路径第 {index} 段与第 {index + 1} 段端点未连接",
                step_id=step.step_id,
                details={"previous_segment": index, "next_segment": index + 1,
                         "previous_end": previous.model_dump(), "next_start": current.model_dump(),
                         "gap": _point_distance(previous, current), "tolerance": step.connection_tolerance},
            )
    if step.closed and _point_distance(
        _segment_end(segments[-1]), _segment_start(segments[0]),
    ) > step.connection_tolerance:
        raise ConstructionPlanError(
            "open_composite_path",
            "复合闭合路径的首尾端点未连接",
            step_id=step.step_id,
            details={"previous_segment": len(segments), "next_segment": 1,
                     "previous_end": _segment_end(segments[-1]).model_dump(),
                     "next_start": _segment_start(segments[0]).model_dump(),
                     "tolerance": step.connection_tolerance},
        )

    sampled: list[ConstructionPoint] = []
    effective_samples = _effective_composite_samples(step)
    for segment in segments:
        values = _sample_composite_segment(segment, effective_samples)
        if sampled and values:
            values = values[1:]
        sampled.extend(values)
    if step.closed and len(sampled) > 1 and _point_distance(sampled[0], sampled[-1]) <= step.connection_tolerance:
        sampled.pop()
    if len(sampled) < 2:
        raise ConstructionPlanError(
            "empty_step_result", "复合路径没有生成足够的采样点", step_id=step.step_id,
        )
    if len(sampled) > 500:
        raise ConstructionPlanError(
            "composite_path_too_dense", "复合路径采样点超过 500 个", step_id=step.step_id,
        )
    return sampled


def _validate_composite_path_quality(
    step: AddCompositePathStep,
) -> dict[str, Any]:
    sampled = _sample_composite_path(step)
    edges = _path_edges(sampled, closed=step.closed)
    duplicate_pairs=[];intersection_pairs=[]
    duplicate_count = _duplicate_edge_count(edges, step.connection_tolerance,details=duplicate_pairs)
    self_intersection_count = _self_intersection_count(
        edges, closed=step.closed, tolerance=step.connection_tolerance,details=intersection_pairs,
    )
    continuity = _composite_continuity(step)
    maximum_curvature = _maximum_polyline_curvature(sampled, closed=step.closed)
    maximum_sampling_error = _maximum_composite_sampling_error(step)
    owners=[]
    effective=_effective_composite_samples(step)
    for index,segment in enumerate(step.segments):
        owners.extend([index]*(1 if isinstance(segment,CompositeLineSegment) else effective))
    def conflict_details(pairs):
        return {'conflicts':[{'edge_indices':[a,b],
            'expanded_segment_indices':[owners[a],owners[b]],
            'edges':[[p.model_dump() for p in edges[index]] for index in (a,b)]}
            for a,b in pairs], 'coordinates':'plan.units','diagnostic_pair_limit':16,
            'repair_instruction':'按conflicts定位相交或重复的原始段，修正端点、圆弧角度或段顺序；保留正确段和用户尺寸。不能增加采样点、关闭检查或重画无关部件来绕过检查。'}

    if duplicate_count and not step.allow_duplicate_segments:
        raise ConstructionPlanError(
            "duplicate_composite_segment",
            f"复合路径包含 {duplicate_count} 条重复线段",
            step_id=step.step_id,
            details=conflict_details(duplicate_pairs),
        )
    if self_intersection_count and not step.allow_self_intersection:
        raise ConstructionPlanError(
            "self_intersecting_composite_path",
            f"复合路径包含 {self_intersection_count} 处自相交",
            step_id=step.step_id,
            details=conflict_details(intersection_pairs),
        )
    if step.continuity == "C1" and not continuity["c1"]:
        raise ConstructionPlanError(
            "c1_continuity_failed",
            (
                f"复合路径有 {continuity['failed_joint_count']} 个连接点"
                f"不满足 C1 切向连续"
            ),
            step_id=step.step_id,
            details={"failed_joints": continuity["failed_joints"],
                     "tolerance_degrees": step.tangent_tolerance_deg},
        )
    if step.max_curvature is not None and maximum_curvature > step.max_curvature:
        raise ConstructionPlanError(
            "curvature_limit_exceeded",
            (
                f"最大曲率 {maximum_curvature:.6g} 超过限制"
                f" {step.max_curvature:.6g}"
            ),
            step_id=step.step_id,
        )
    if (
        step.max_sampling_error is not None
        and maximum_sampling_error > step.max_sampling_error
    ):
        raise ConstructionPlanError(
            "sampling_error_exceeded",
            (
                f"最大采样误差 {maximum_sampling_error:.6g} 超过限制"
                f" {step.max_sampling_error:.6g}"
            ),
            step_id=step.step_id,
        )
    return {
        "schema": "cad.curve-quality.v1",
        "step_id": step.step_id,
        "output_ref": step.output_ref,
        "closed": step.closed,
        "requested_samples_per_curve": step.samples_per_curve,
        "effective_samples_per_curve": _effective_composite_samples(step),
        "sampled_point_count": len(sampled),
        "continuity_required": step.continuity,
        "c0": True,
        "c1": continuity["c1"],
        "joint_count": continuity["joint_count"],
        "failed_joint_count": continuity["failed_joint_count"],
        "maximum_tangent_delta_deg": round(
            continuity["maximum_tangent_delta_deg"], 6,
        ),
        "self_intersection_count": self_intersection_count,
        "duplicate_segment_count": duplicate_count,
        "maximum_curvature": round(maximum_curvature, 9),
        "maximum_sampling_error": round(maximum_sampling_error, 9),
        "max_sampling_error": step.max_sampling_error,
        "units": "per_plan_unit",
        "verified": True,
    }


def _sample_composite_segment(
    segment: CompositePathSegment, samples_per_curve: int,
) -> list[ConstructionPoint]:
    if isinstance(segment, CompositeLineSegment):
        return [segment.start, segment.end]
    if isinstance(segment, CompositeArcSegment):
        sweep = ((segment.start_angle - segment.end_angle) % 360.0
                 if segment.clockwise
                 else (segment.end_angle - segment.start_angle) % 360.0)
        if math.isclose(sweep, 0.0, abs_tol=1e-12) and not math.isclose(
            segment.end_angle, segment.start_angle, abs_tol=1e-12,
        ):
            sweep = 360.0
        direction = -1.0 if segment.clockwise else 1.0
        return [
            ConstructionPoint(
                x=segment.center.x + segment.radius * math.cos(math.radians(
                    segment.start_angle + direction * sweep * index / samples_per_curve
                )),
                y=segment.center.y + segment.radius * math.sin(math.radians(
                    segment.start_angle + direction * sweep * index / samples_per_curve
                )),
            )
            for index in range(samples_per_curve + 1)
        ]
    points = segment.control_points
    if isinstance(segment, CompositeBezierSegment):
        return [
            _bezier_point(points, index / samples_per_curve)
            for index in range(samples_per_curve + 1)
        ]
    return [
        _bspline_point(points, segment.degree, index / samples_per_curve)
        for index in range(samples_per_curve + 1)
    ]


def _path_edges(
    points: list[ConstructionPoint], *, closed: bool,
) -> list[tuple[ConstructionPoint, ConstructionPoint]]:
    edges = list(zip(points, points[1:]))
    if closed and len(points) > 2:
        edges.append((points[-1], points[0]))
    return edges


def _duplicate_edge_count(
    edges: list[tuple[ConstructionPoint, ConstructionPoint]], tolerance: float,
    *,details: list | None = None,
) -> int:
    quantum = max(tolerance, 1e-9)

    def point_key(point: ConstructionPoint) -> tuple[int, int]:
        return round(point.x / quantum), round(point.y / quantum)

    signatures = {}
    duplicates = 0
    for index,(start, end) in enumerate(edges):
        left, right = point_key(start), point_key(end)
        signature = (left, right) if left <= right else (right, left)
        if signature in signatures:
            duplicates += 1
            if details is not None and len(details)<16:details.append((signatures[signature],index))
        else:
            signatures[signature]=index
    return duplicates


def _self_intersection_count(
    edges: list[tuple[ConstructionPoint, ConstructionPoint]],
    *, closed: bool, tolerance: float,details: list | None = None,
) -> int:
    intersections = 0
    last_index = len(edges) - 1
    for left_index, left in enumerate(edges):
        for right_index in range(left_index + 1, len(edges)):
            if right_index == left_index + 1:
                continue
            if closed and left_index == 0 and right_index == last_index:
                continue
            right = edges[right_index]
            if _segments_intersect_with_tolerance(
                left[0], left[1], right[0], right[1], tolerance,
            ):
                intersections += 1
                if details is not None and len(details)<16:details.append((left_index,right_index))
    return intersections


def _segments_intersect_with_tolerance(
    a: ConstructionPoint, b: ConstructionPoint,
    c: ConstructionPoint, d: ConstructionPoint,
    tolerance: float,
) -> bool:
    epsilon = max(tolerance, 1e-9)

    def orientation(
        first: ConstructionPoint, second: ConstructionPoint,
        third: ConstructionPoint,
    ) -> float:
        return (
            (second.x - first.x) * (third.y - first.y)
            - (second.y - first.y) * (third.x - first.x)
        )

    def sign(value: float, length: float) -> int:
        # The cross product has units of length squared. Convert the linear
        # distance tolerance using the reference edge length; otherwise dense
        # samples on an ordinary curve are incorrectly treated as collinear.
        return 0 if abs(value) <= epsilon * length else (1 if value > 0.0 else -1)

    def on_segment(
        first: ConstructionPoint, second: ConstructionPoint,
        point: ConstructionPoint,
    ) -> bool:
        return (
            min(first.x, second.x) - epsilon
            <= point.x
            <= max(first.x, second.x) + epsilon
            and min(first.y, second.y) - epsilon
            <= point.y
            <= max(first.y, second.y) + epsilon
        )

    values = (
        orientation(a, b, c), orientation(a, b, d),
        orientation(c, d, a), orientation(c, d, b),
    )
    ab_length = math.hypot(b.x - a.x, b.y - a.y)
    cd_length = math.hypot(d.x - c.x, d.y - c.y)
    signs = tuple(sign(value, length) for value, length in zip(
        values, (ab_length, ab_length, cd_length, cd_length)
    ))
    if signs[0] * signs[1] < 0 and signs[2] * signs[3] < 0:
        return True
    return any((
        signs[0] == 0 and on_segment(a, b, c),
        signs[1] == 0 and on_segment(a, b, d),
        signs[2] == 0 and on_segment(c, d, a),
        signs[3] == 0 and on_segment(c, d, b),
    ))


def _composite_continuity(step: AddCompositePathStep) -> dict[str, Any]:
    joints = list(zip(step.segments, step.segments[1:]))
    if step.closed and len(step.segments) > 1:
        joints.append((step.segments[-1], step.segments[0]))
    deltas: list[float] = []
    failed = 0
    failed_joints = []
    for index, (previous, current) in enumerate(joints):
        incoming = _segment_tangent(previous, at_end=True)
        outgoing = _segment_tangent(current, at_end=False)
        delta = _vector_angle_degrees(incoming, outgoing)
        deltas.append(delta)
        if not math.isfinite(delta) or delta > step.tangent_tolerance_deg:
            failed += 1
            failed_joints.append({
                "previous_segment": index + 1,
                "next_segment": (index + 1) % len(step.segments) + 1,
                "incoming_tangent": list(incoming), "outgoing_tangent": list(outgoing),
                "angle_degrees": delta if math.isfinite(delta) else None,
            })
    return {
        "c1": failed == 0,
        "joint_count": len(joints),
        "failed_joint_count": failed,
        "failed_joints": failed_joints,
        "maximum_tangent_delta_deg": max(deltas, default=0.0),
    }


def _segment_tangent(
    segment: CompositePathSegment, *, at_end: bool,
) -> tuple[float, float]:
    if isinstance(segment, CompositeLineSegment):
        start, end = segment.start, segment.end
    elif isinstance(segment, CompositeArcSegment):
        angle = segment.end_angle if at_end else segment.start_angle
        radians = math.radians(angle)
        direction = -1.0 if segment.clockwise else 1.0
        return -direction * math.sin(radians), direction * math.cos(radians)
    else:
        points = segment.control_points
        start, end = (
            (points[-2], points[-1]) if at_end else (points[0], points[1])
        )
    return end.x - start.x, end.y - start.y


def _vector_angle_degrees(
    left: tuple[float, float], right: tuple[float, float],
) -> float:
    left_length = math.hypot(*left)
    right_length = math.hypot(*right)
    if left_length <= 1e-12 or right_length <= 1e-12:
        return math.inf
    cosine = (
        left[0] * right[0] + left[1] * right[1]
    ) / (left_length * right_length)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _maximum_polyline_curvature(
    points: list[ConstructionPoint], *, closed: bool,
) -> float:
    values = list(points)
    if closed and len(values) > 2:
        values = [values[-1], *values, values[0]]
    maximum = 0.0
    for first, middle, last in zip(values, values[1:], values[2:]):
        a = _point_distance(first, middle)
        b = _point_distance(middle, last)
        c = _point_distance(first, last)
        denominator = a * b * c
        if denominator <= 1e-18:
            continue
        twice_area = abs(
            (middle.x - first.x) * (last.y - first.y)
            - (middle.y - first.y) * (last.x - first.x)
        )
        maximum = max(maximum, 2.0 * twice_area / denominator)
    return maximum


def _maximum_composite_sampling_error(step: AddCompositePathStep, samples_per_curve: int | None = None) -> float:
    maximum = 0.0
    effective_samples = _effective_composite_samples(step) if samples_per_curve is None else samples_per_curve
    for segment in step.segments:
        if isinstance(segment, CompositeLineSegment):
            continue
        samples = _sample_composite_segment(segment, effective_samples)
        for index, (start, end) in enumerate(zip(samples, samples[1:])):
            # Midpoint alone misses an S-shaped interval whose midpoint lies
            # on its chord. Probe both sides as well, using the same intervals
            # that will actually be persisted and displayed.
            for fraction in (.25, .5, .75):
                parameter = (index + fraction) / effective_samples
                if isinstance(segment, CompositeArcSegment):
                    sweep = ((segment.start_angle - segment.end_angle) % 360.0
                             if segment.clockwise
                             else (segment.end_angle - segment.start_angle) % 360.0)
                    if math.isclose(sweep, 0.0, abs_tol=1e-12) and not math.isclose(
                        segment.end_angle, segment.start_angle, abs_tol=1e-12,
                    ):
                        sweep = 360.0
                    angle = segment.start_angle + (-sweep if segment.clockwise else sweep) * parameter
                    midpoint = ConstructionPoint(
                        x=segment.center.x + segment.radius * math.cos(math.radians(angle)),
                        y=segment.center.y + segment.radius * math.sin(math.radians(angle)),
                    )
                elif isinstance(segment, CompositeBezierSegment):
                    midpoint = _bezier_point(segment.control_points, parameter)
                else:
                    midpoint = _bspline_point(
                        segment.control_points, segment.degree, parameter,
                    )
                maximum = max(
                    maximum, _point_to_segment_distance(midpoint, start, end),
                )
    return maximum


def _point_to_segment_distance(
    point: ConstructionPoint, start: ConstructionPoint, end: ConstructionPoint,
) -> float:
    dx, dy = end.x - start.x, end.y - start.y
    denominator = dx * dx + dy * dy
    if denominator <= 1e-24:
        return _point_distance(point, start)
    parameter = max(0.0, min(
        1.0,
        ((point.x - start.x) * dx + (point.y - start.y) * dy) / denominator,
    ))
    projection = ConstructionPoint(
        x=start.x + parameter * dx,
        y=start.y + parameter * dy,
    )
    return _point_distance(point, projection)


def _segment_start(segment: CompositePathSegment) -> ConstructionPoint:
    if isinstance(segment, CompositeLineSegment):
        return segment.start
    if isinstance(segment, CompositeArcSegment):
        angle = math.radians(segment.start_angle)
        return ConstructionPoint(
            x=segment.center.x + segment.radius * math.cos(angle),
            y=segment.center.y + segment.radius * math.sin(angle),
        )
    return segment.control_points[0]


def _segment_end(segment: CompositePathSegment) -> ConstructionPoint:
    if isinstance(segment, CompositeLineSegment):
        return segment.end
    if isinstance(segment, CompositeArcSegment):
        sweep = ((segment.start_angle - segment.end_angle) % 360.0
                 if segment.clockwise
                 else (segment.end_angle - segment.start_angle) % 360.0)
        angle = math.radians(segment.start_angle + (-sweep if segment.clockwise else sweep))
        return ConstructionPoint(
            x=segment.center.x + segment.radius * math.cos(angle),
            y=segment.center.y + segment.radius * math.sin(angle),
        )
    return segment.control_points[-1]


def _point_distance(left: ConstructionPoint, right: ConstructionPoint) -> float:
    return math.hypot(left.x - right.x, left.y - right.y)


def _bezier_point(
    control_points: list[ConstructionPoint], parameter: float,
) -> ConstructionPoint:
    values = [(point.x, point.y) for point in control_points]
    while len(values) > 1:
        values = [
            (
                left[0] + (right[0] - left[0]) * parameter,
                left[1] + (right[1] - left[1]) * parameter,
            )
            for left, right in zip(values, values[1:])
        ]
    return ConstructionPoint(x=values[0][0], y=values[0][1])


def _bspline_point(
    control_points: list[ConstructionPoint], degree: int, parameter: float,
) -> ConstructionPoint:
    count = len(control_points)
    knots = _clamped_uniform_knots(count, degree)
    if parameter >= 1.0:
        return control_points[-1]
    span = degree
    for index in range(degree, count):
        if knots[index] <= parameter < knots[index + 1]:
            span = index
            break
    values = [
        [control_points[index].x, control_points[index].y]
        for index in range(span - degree, span + 1)
    ]
    for level in range(1, degree + 1):
        for index in range(degree, level - 1, -1):
            knot_index = span - degree + index
            denominator = knots[knot_index + degree - level + 1] - knots[knot_index]
            alpha = 0.0 if abs(denominator) < 1e-12 else (
                parameter - knots[knot_index]
            ) / denominator
            values[index][0] = (1.0 - alpha) * values[index - 1][0] + alpha * values[index][0]
            values[index][1] = (1.0 - alpha) * values[index - 1][1] + alpha * values[index][1]
    return ConstructionPoint(x=values[degree][0], y=values[degree][1])


def _clamped_uniform_knots(control_point_count: int, degree: int) -> list[float]:
    interior_count = control_point_count - degree - 1
    knots = [0.0] * (degree + 1)
    if interior_count > 0:
        knots.extend(index / (interior_count + 1) for index in range(1, interior_count + 1))
    knots.extend([1.0] * (degree + 1))
    return knots


def _translate_geometry(geometry: dict[str, Any], dx: float, dy: float) -> dict[str, Any]:
    result = deepcopy(geometry)
    geometry_type = str(result.get("type"))
    keys = {
        "line": ("start", "end"), "circle": ("center",),
        "arc": ("center",), "ellipse": ("center",), "text": ("position",),
    }.get(geometry_type, ())
    for key in keys:
        result[key]["x"] += dx
        result[key]["y"] += dy
    if geometry_type == "polyline":
        for value in result["vertices"]:
            value["x"] += dx
            value["y"] += dy
    if geometry_type == "spline":
        for value in result["control_points"]:
            value["x"] += dx
            value["y"] += dy
    return result


def _logical_object(
    step: ConstructionStep, geometries: list[dict[str, Any]],
) -> dict[str, Any]:
    bounds = _bounds(geometries)
    semantic = step.semantic
    return {
        "object_id": semantic.object_id or _safe_object_id(step.output_ref),
        **({"assembly_id":semantic.assembly_id,"assembly_label":semantic.assembly_label} if semantic.assembly_id else {}),
        "object_type": semantic.object_type,
        "label": semantic.label,
        "geometry_refs": [int(item["id"]) for item in geometries],
        "bounds": bounds,
        "confirmed": True,
        "confidence": 1.0,
    }


def _refresh_logical_object_bounds(
    objects: list[dict[str, Any]], geometries: list[dict[str, Any]],
) -> None:
    by_id = {int(item["id"]): item for item in geometries}
    for logical_object in objects:
        members = [
            by_id[int(geometry_id)]
            for geometry_id in logical_object.get("geometry_refs") or []
            if int(geometry_id) in by_id
        ]
        if members:
            logical_object["bounds"] = _bounds(members)


def _array_logical_objects(
    step: RectangularArrayStep,
    geometries: list[dict[str, Any]],
    source_geometry_count: int,
) -> list[dict[str, Any]]:
    if source_geometry_count <= 0:
        return []
    objects: list[dict[str, Any]] = []
    for index in range(0, len(geometries), source_geometry_count):
        placement = geometries[index:index + source_geometry_count]
        if len(placement) != source_geometry_count:
            raise ConstructionPlanError(
                "invalid_array_result", "阵列副本图元数量不完整",
                step_id=step.step_id,
            )
        placement_number = index // source_geometry_count + 1
        bounds = _bounds(placement)
        base_id = step.semantic.object_id or _safe_object_id(step.output_ref)
        objects.append({
            "object_id": f"{base_id}.{placement_number}",
            "assembly_id":f"{step.semantic.assembly_id or base_id}.placement.{placement_number}",
            "assembly_label":f"{step.semantic.assembly_label or step.semantic.label} {placement_number}",
            "object_type": step.semantic.object_type,
            "label": f"{step.semantic.label} {placement_number}",
            "geometry_refs": [int(item["id"]) for item in placement],
            "bounds": bounds,
            "confirmed": True,
            "confidence": 1.0,
        })
    return objects


def _safe_object_id(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._:-]+", "-", value).strip("-")
    return normalized or "construction-object"


def _run_assertions(
    assertions: list[ConstructionAssertion], geometries: list[dict[str, Any]],
    refs: dict[str, list[int]], scale: float,
) -> None:
    by_id = {int(item["id"]): item for item in geometries}
    for assertion in assertions:
        ids = refs.get(assertion.target_ref, []) if assertion.target_ref else list(by_id)
        selected = [by_id[value] for value in ids if value in by_id]
        if isinstance(assertion, EntityCountAssertion):
            if len(selected) != assertion.equals:
                _fail_assertion(assertion, f"实际图元数 {len(selected)}，要求 {assertion.equals}")
        elif isinstance(assertion, BoundsSizeAssertion):
            bounds = _bounds(selected)
            width = (bounds["max_x"] - bounds["min_x"]) / scale
            height = (bounds["max_y"] - bounds["min_y"]) / scale
            if abs(width - assertion.width) > assertion.tolerance or abs(height - assertion.height) > assertion.tolerance:
                _fail_assertion(
                    assertion,
                    f"实际尺寸 {width:g} x {height:g}，要求 {assertion.width:g} x {assertion.height:g}",
                )
        elif isinstance(assertion, ClosedAssertion):
            if not selected or any(
                item.get("type") not in {"circle", "ellipse"}
                and not (
                    item.get("type") in {"polyline", "spline"}
                    and item.get("closed") is True
                )
                for item in selected
            ):
                _fail_assertion(assertion, "目标包含未闭合图元")
        elif isinstance(assertion, RadialPatternAssertion):
            if len(selected) != 1 or selected[0].get("type") != "polyline" or not selected[0].get("closed"):
                _fail_assertion(assertion, "径向重复轮廓必须是一条可验证的闭合多段线")
            points = selected[0].get("vertices") or []
            if len(points) < assertion.lobes * (8 if assertion.profile == "smooth" else 2):
                minimum = assertion.lobes * (8 if assertion.profile == "smooth" else 2)
                raise ConstructionPlanError(
                    "assertion_failed",
                    (
                        "轮廓采样过少，无法验证平滑的重复结构"
                        if assertion.profile == "smooth"
                        else f"径向多边形至少需要 {minimum} 个有序顶点（每周期一个外峰和一个内谷）"
                    ),
                    assertion_id=assertion.assertion_id,
                    details={
                        "profile": assertion.profile,
                        "expected_lobes": assertion.lobes,
                        "minimum_ordered_vertices": minimum,
                        "observed_vertices": len(points),
                        "target_ref": assertion.target_ref,
                        "repair_instruction": (
                            "修复 target_ref 对应的构造步骤，保留其他对象。"
                            "多边形的一个旋转周期必须显式包含外峰到内谷、内谷到下一外峰两段边。"
                            "constrain_sector_end 会约束最后一段的终点，不能代替遗漏的边；"
                            "不得只增加采样点来满足顶点数量。"
                        ),
                        "required_topology": (
                            "顶点必须沿边界交替排列外峰和内谷；只连接外峰会形成自交星线，"
                            "不是单一无自交外轮廓。"
                        ),
                    },
                )
            bounds = _bounds(selected)
            width, height = bounds["max_x"] - bounds["min_x"], bounds["max_y"] - bounds["min_y"]
            if min(width, height) <= 0:
                _fail_assertion(assertion, "轮廓尺寸退化")
            cx, cy = (bounds["min_x"] + bounds["max_x"]) / 2, (bounds["min_y"] + bounds["max_y"]) / 2
            radii = [math.hypot((p["x"] - cx) / width, (p["y"] - cy) / height) for p in points]
            peaks = [i for i, r in enumerate(radii) if r > radii[i-1] + 1e-9 and r >= radii[(i+1) % len(radii)] - 1e-9]
            if assertion.profile == "polygonal":
                # Alternating outer/inner vertices are the canonical polygon
                # representation. Count its local radial maxima directly;
                # the smooth prominence calculation under-counts this shape.
                if len(peaks) != assertion.lobes:
                    raise ConstructionPlanError(
                        "assertion_failed",
                        f"实际径向凸瓣数 {len(peaks)}，要求 {assertion.lobes}",
                        assertion_id=assertion.assertion_id,
                        details={
                            "profile": "polygonal",
                            "expected_lobes": assertion.lobes,
                            "observed_radial_peaks": len(peaks),
                            "required_topology": (
                                "每个径向周期必须从外峰出发，经过至少一个严格更小半径的内谷，"
                                "再到下一外峰；所有顶点位于同一半径只会形成正多边形。"
                            ),
                        },
                    )
                continue
            count = 0
            for n, i in enumerate(peaks):
                previous, following = peaks[n-1], peaks[(n+1) % len(peaks)]
                left = [radii[j % len(radii)] for j in range(previous, i + 1 if i > previous else i + len(radii) + 1)]
                right = [radii[j % len(radii)] for j in range(i, following + 1 if following > i else following + len(radii) + 1)]
                if radii[i] - max(min(left), min(right)) >= max(radii) * 0.02:
                    count += 1
            if count != assertion.lobes:
                _fail_assertion(assertion, f"实际径向凸瓣数 {count}，要求 {assertion.lobes}")
            for i, point in enumerate(points):
                before, after = points[i-1], points[(i+1) % len(points)]
                ax, ay = point["x"] - before["x"], point["y"] - before["y"]
                bx, by = after["x"] - point["x"], after["y"] - point["y"]
                length = math.hypot(ax, ay) * math.hypot(bx, by)
                if length > 1e-12 and math.degrees(math.acos(max(-1, min(1, (ax*bx+ay*by)/length)))) > 60:
                    _fail_assertion(assertion, "重复轮廓存在尖锐折角，不符合曲线轮廓要求")
        elif isinstance(assertion, CenterDistanceAssertion):
            reference_ids = refs.get(assertion.reference_ref, [])
            reference = [by_id[value] for value in reference_ids if value in by_id]
            if not selected or not reference:
                _fail_assertion(assertion, "中心距断言引用的对象没有实际几何")
            target_bounds, reference_bounds = _bounds(selected), _bounds(reference)
            target_center = (
                (target_bounds["min_x"] + target_bounds["max_x"]) / (2 * scale),
                (target_bounds["min_y"] + target_bounds["max_y"]) / (2 * scale),
            )
            reference_center = (
                (reference_bounds["min_x"] + reference_bounds["max_x"]) / (2 * scale),
                (reference_bounds["min_y"] + reference_bounds["max_y"]) / (2 * scale),
            )
            actual = math.dist(target_center, reference_center)
            if abs(actual - assertion.distance) > assertion.tolerance:
                _fail_assertion(
                    assertion,
                    f"实际中心距 {actual:g}，要求 {assertion.distance:g}",
                )
        elif isinstance(assertion, AreaAssertion):
            area = construction_geometry_area(selected) / (scale * scale)
            if abs(area - assertion.area) > assertion.tolerance:
                _fail_assertion(
                    assertion,
                    f"实际面积 {area:g}，要求 {assertion.area:g}",
                )


def _fail_assertion(assertion: ConstructionAssertion, message: str) -> None:
    raise ConstructionPlanError(
        "assertion_failed", message, assertion_id=assertion.assertion_id,
    )


def _closed_geometry_area(geometry: dict[str, Any]) -> float:
    kind = geometry.get("type")
    if kind == "circle":
        return math.pi * float(geometry["radius"]) ** 2
    if kind == "ellipse":
        major = math.hypot(
            float(geometry["major_axis"]["x"]),
            float(geometry["major_axis"]["y"]),
        )
        return math.pi * major * major * float(geometry["ratio"])
    if kind in {"polyline", "spline"} and geometry.get("closed") is True:
        key = "vertices" if kind == "polyline" else "control_points"
        points = [_xy(value) for value in geometry.get(key) or []]
        if len(points) < 3:
            raise ConstructionPlanError(
                "invalid_area_target", "闭合面积目标至少需要三个边界点",
            )
        return abs(sum(
            first[0] * second[1] - second[0] * first[1]
            for first, second in zip(points, points[1:] + points[:1])
        )) / 2.0
    raise ConstructionPlanError(
        "invalid_area_target", "面积断言只支持闭合多段线、闭合样条、圆或椭圆",
    )


def _bounds(geometries: list[dict[str, Any]]) -> dict[str, float]:
    if not geometries:
        raise ConstructionPlanError("empty_target", "无法计算空目标的边界")
    points: list[tuple[float, float]] = []
    for item in geometries:
        kind = item.get("type")
        if kind == "line":
            points.extend(_xy(item[key]) for key in ("start", "end"))
        elif kind == "polyline":
            points.extend(_xy(value) for value in item["vertices"])
        elif kind == "spline":
            points.extend(_xy(value) for value in item["control_points"])
        elif kind == "circle":
            x, y = _xy(item["center"])
            radius = float(item["radius"])
            points.extend(((x - radius, y - radius), (x + radius, y + radius)))
        elif kind == "arc":
            x, y = _xy(item["center"])
            radius = float(item["radius"])
            start = float(item["start_angle"])
            end = float(item["end_angle"])
            sweep = (end - start) % 360.0
            angles = [start, end]
            if math.isclose(sweep, 0.0, abs_tol=1e-9) and not math.isclose(
                end, start, abs_tol=1e-9,
            ):
                angles.extend((0.0, 90.0, 180.0, 270.0))
            else:
                for candidate in (0.0, 90.0, 180.0, 270.0):
                    if (candidate - start) % 360.0 <= sweep + 1e-9:
                        angles.append(candidate)
            points.extend(
                (
                    x + radius * math.cos(math.radians(angle)),
                    y + radius * math.sin(math.radians(angle)),
                )
                for angle in angles
            )
        elif kind == "ellipse":
            x, y = _xy(item["center"])
            axis_x = float(item["major_axis"]["x"])
            axis_y = float(item["major_axis"]["y"])
            major = math.hypot(axis_x, axis_y)
            minor = major * float(item["ratio"])
            if major <= 0.0:
                raise ConstructionPlanError(
                    "invalid_geometry", "椭圆长轴长度必须大于 0"
                )
            cos_a = axis_x / major
            sin_a = axis_y / major
            half_width = math.sqrt(
                (major * cos_a) ** 2 + (minor * sin_a) ** 2
            )
            half_height = math.sqrt(
                (major * sin_a) ** 2 + (minor * cos_a) ** 2
            )
            points.extend(
                ((x - half_width, y - half_height),
                 (x + half_width, y + half_height))
            )
        elif kind == "text":
            points.append(_xy(item["position"]))
    if not points:
        raise ConstructionPlanError("invalid_geometry", "目标没有可计算边界的图元")
    return {
        "min_x": min(value[0] for value in points),
        "min_y": min(value[1] for value in points),
        "max_x": max(value[0] for value in points),
        "max_y": max(value[1] for value in points),
    }


def _xy(value: dict[str, Any]) -> tuple[float, float]:
    return float(value["x"]), float(value["y"])
