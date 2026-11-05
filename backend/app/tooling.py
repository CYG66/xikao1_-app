from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .config import MAX_ANGULAR_VELOCITY, MAX_LINEAR_VELOCITY
from .state import robot_state


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmptyArguments(ToolArguments):
    pass


class RectangleArguments(ToolArguments):
    width_m: float = Field(ge=0.1, le=50.0)
    height_m: float = Field(ge=0.1, le=50.0)


class CadPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float = Field(ge=-100000.0, le=100000.0)
    y: float = Field(ge=-100000.0, le=100000.0)
    z: float = Field(default=0.0, ge=-10000.0, le=10000.0)


class CadGeometryBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int = Field(ge=1, le=1000000)
    layer_id: int = Field(default=1, ge=1, le=1000)


class CadLine(CadGeometryBase):
    type: Literal["line"]
    start: CadPoint
    end: CadPoint


class CadPolyline(CadGeometryBase):
    type: Literal["polyline"]
    vertices: list[CadPoint] = Field(min_length=2, max_length=500)
    closed: bool = False


class CadCircle(CadGeometryBase):
    type: Literal["circle"]
    center: CadPoint
    radius: float = Field(gt=0.0, le=50000.0)


class CadArc(CadGeometryBase):
    type: Literal["arc"]
    center: CadPoint
    radius: float = Field(gt=0.0, le=50000.0)
    start_angle: float = Field(ge=-3600.0, le=3600.0)
    end_angle: float = Field(ge=-3600.0, le=3600.0)


class CadEllipse(CadGeometryBase):
    type: Literal["ellipse"]
    center: CadPoint
    major_axis: CadPoint
    ratio: float = Field(gt=0.0, le=1.0)
    start_angle: float = Field(default=0.0, ge=-3600.0, le=3600.0)
    end_angle: float = Field(default=360.0, ge=-3600.0, le=3600.0)


class CadSpline(CadGeometryBase):
    type: Literal["spline"]
    degree: int = Field(default=3, ge=1, le=5)
    control_points: list[CadPoint] = Field(min_length=2, max_length=100)
    closed: bool = False
    periodic: bool = False


class CadTextAlign(BaseModel):
    model_config = ConfigDict(extra="forbid")
    horizontal: Literal["left", "center", "right"] = "left"
    vertical: Literal["top", "middle", "bottom", "baseline"] = "baseline"


class CadText(CadGeometryBase):
    type: Literal["text"]
    position: CadPoint
    content: str = Field(min_length=1, max_length=200)
    height: float = Field(default=50.0, gt=0.0, le=1000.0)
    rotation: float = Field(default=0.0, ge=-3600.0, le=3600.0)
    style: str = Field(default="Standard", min_length=1, max_length=64)
    width_factor: float = Field(default=1.0, gt=0.0, le=10.0)
    oblique: float = Field(default=0.0, ge=-85.0, le=85.0)
    subtype: Literal["text", "mtext"] = "text"
    align: CadTextAlign = Field(default_factory=CadTextAlign)


CadGeometry = Annotated[
    Union[CadLine, CadPolyline, CadCircle, CadArc, CadEllipse, CadSpline, CadText],
    Field(discriminator="type"),
]


class CadBounds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_x: float = Field(ge=-100000.0, le=100000.0)
    min_y: float = Field(ge=-100000.0, le=100000.0)
    max_x: float = Field(ge=-100000.0, le=100000.0)
    max_y: float = Field(ge=-100000.0, le=100000.0)

    @model_validator(mode="after")
    def validate_order(self) -> "CadBounds":
        if self.min_x > self.max_x or self.min_y > self.max_y:
            raise ValueError("bounds minimums must not exceed maximums")
        return self


class CadLogicalObject(BaseModel):
    """A human-addressable object that may share physical CAD entities."""

    model_config = ConfigDict(extra="forbid")
    assembly_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    assembly_label: str | None = Field(default=None, min_length=1, max_length=100)

    object_id: str = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"
    )
    object_type: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=100)
    geometry_refs: list[int] = Field(min_length=1, max_length=500)
    bounds: CadBounds | None = None
    confirmed: bool = True
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_geometry_refs(self) -> "CadLogicalObject":
        if any(value <= 0 for value in self.geometry_refs):
            raise ValueError("geometry_refs must contain positive IDs")
        if len(self.geometry_refs) != len(set(self.geometry_refs)):
            raise ValueError("geometry_refs must be unique within one object")
        return self


class CadSharedGeometry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    geometry_id: int = Field(ge=1, le=1000000)
    object_ids: list[str] = Field(min_length=2, max_length=50)
    relation: Literal["shared_boundary"] = "shared_boundary"

    @model_validator(mode="after")
    def validate_object_ids(self) -> "CadSharedGeometry":
        if len(self.object_ids) != len(set(self.object_ids)):
            raise ValueError("shared object_ids must be unique")
        return self


class CadTopologyRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_object_id: str = Field(min_length=1, max_length=128)
    target_object_id: str = Field(min_length=1, max_length=128)
    relation: Literal[
        "adjacent", "left_of", "right_of", "above", "below",
        "contains", "inside", "intersects",
    ]

    @model_validator(mode="after")
    def validate_distinct_objects(self) -> "CadTopologyRelation":
        if self.source_object_id == self.target_object_id:
            raise ValueError("topology relation must connect distinct objects")
        return self


class CadTopology(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["cad.topology.v1"] = "cad.topology.v1"
    shared_geometries: list[CadSharedGeometry] = Field(
        default_factory=list, max_length=500
    )
    relations: list[CadTopologyRelation] = Field(default_factory=list, max_length=1000)


class CadDrawingArguments(ToolArguments):
    geometries: list[CadGeometry] = Field(min_length=1, max_length=200)
    logical_objects: list[CadLogicalObject] = Field(default_factory=list, max_length=200)
    topology: CadTopology = Field(default_factory=CadTopology)

    @model_validator(mode="after")
    def validate_logical_object_graph(self) -> "CadDrawingArguments":
        geometry_ids = [item.id for item in self.geometries]
        if len(geometry_ids) != len(set(geometry_ids)):
            raise ValueError("geometry IDs must be unique")
        known_geometry_ids = set(geometry_ids)
        object_ids = [item.object_id for item in self.logical_objects]
        if len(object_ids) != len(set(object_ids)):
            raise ValueError("logical object IDs must be unique")
        known_object_ids = set(object_ids)
        objects_by_id = {item.object_id: item for item in self.logical_objects}
        owners_by_geometry: dict[int, set[str]] = {}
        for item in self.logical_objects:
            missing = sorted(set(item.geometry_refs) - known_geometry_ids)
            if missing:
                raise ValueError(
                    f"logical object {item.object_id} references missing geometries {missing}"
                )
            for geometry_id in item.geometry_refs:
                owners_by_geometry.setdefault(geometry_id, set()).add(item.object_id)
        seen_shared_geometry_ids: set[int] = set()
        for shared in self.topology.shared_geometries:
            if shared.geometry_id not in known_geometry_ids:
                raise ValueError(
                    f"shared topology references missing geometry {shared.geometry_id}"
                )
            if shared.geometry_id in seen_shared_geometry_ids:
                raise ValueError(
                    f"shared geometry {shared.geometry_id} is declared more than once"
                )
            seen_shared_geometry_ids.add(shared.geometry_id)
            missing_objects = sorted(set(shared.object_ids) - known_object_ids)
            if missing_objects:
                raise ValueError(
                    f"shared topology references missing objects {missing_objects}"
                )
            if any(
                shared.geometry_id not in objects_by_id[object_id].geometry_refs
                for object_id in shared.object_ids
            ):
                raise ValueError(
                    f"shared geometry {shared.geometry_id} must be referenced by every object"
                )
            if set(shared.object_ids) != owners_by_geometry.get(shared.geometry_id, set()):
                raise ValueError(
                    f"shared geometry {shared.geometry_id} must declare every owning object"
                )
        undeclared_shared = sorted(
            geometry_id
            for geometry_id, owners in owners_by_geometry.items()
            if len(owners) > 1 and geometry_id not in seen_shared_geometry_ids
        )
        if undeclared_shared:
            raise ValueError(
                f"shared geometries must be declared in topology {undeclared_shared}"
            )
        for relation in self.topology.relations:
            missing_objects = sorted(
                {relation.source_object_id, relation.target_object_id}
                - known_object_ids
            )
            if missing_objects:
                raise ValueError(
                    f"topology relation references missing objects {missing_objects}"
                )
        return self


class CadModificationTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["geometry", "instance", "logical_object"]
    geometry_ids: list[int] = Field(default_factory=list, max_length=200)
    instance_ids: list[int] = Field(default_factory=list, max_length=50)
    object_id: str | None = Field(default=None, min_length=1, max_length=128)
    object_ids: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_ids(self) -> "CadModificationTarget":
        active = self.geometry_ids if self.scope != "instance" else self.instance_ids
        inactive = self.instance_ids if self.scope != "instance" else self.geometry_ids
        if not active or inactive:
            raise ValueError("target must contain IDs for exactly one scope")
        if any(value <= 0 for value in active) or len(active) != len(set(active)):
            raise ValueError("target IDs must be unique positive integers")
        if self.scope == "logical_object":
            object_ids = [value for value in [self.object_id, *self.object_ids] if value]
            if not object_ids or len(object_ids) != len(set(object_ids)):
                raise ValueError("logical_object target requires unique object_id values")
        elif self.object_id is not None or self.object_ids:
            raise ValueError("object_id is only valid for logical_object scope")
        return self


class CadGeometryPatch(BaseModel):
    """Mutable CAD fields only; identity and geometry type cannot be patched."""

    model_config = ConfigDict(extra="forbid")

    layer_id: int | None = Field(default=None, ge=1, le=1000)
    template_instance: int | None = Field(default=None, ge=1, le=50)
    template_type: str | None = Field(default=None, min_length=1, max_length=64)
    start: CadPoint | None = None
    end: CadPoint | None = None
    center: CadPoint | None = None
    position: CadPoint | None = None
    vertices: list[CadPoint] | None = Field(default=None, min_length=2, max_length=500)
    control_points: list[CadPoint] | None = Field(default=None, min_length=2, max_length=100)
    radius: float | None = Field(default=None, gt=0.0, le=50000.0)
    major_axis: CadPoint | None = None
    ratio: float | None = Field(default=None, gt=0.0, le=1.0)
    start_angle: float | None = Field(default=None, ge=-3600.0, le=3600.0)
    end_angle: float | None = Field(default=None, ge=-3600.0, le=3600.0)
    degree: int | None = Field(default=None, ge=1, le=5)
    closed: bool | None = None
    content: str | None = Field(default=None, min_length=1, max_length=200)
    height: float | None = Field(default=None, gt=0.0, le=1000.0)
    rotation: float | None = Field(default=None, ge=-3600.0, le=3600.0)
    style: str | None = Field(default=None, min_length=1, max_length=64)
    width_factor: float | None = Field(default=None, gt=0.0, le=10.0)
    oblique: float | None = Field(default=None, ge=-85.0, le=85.0)
    subtype: Literal["text", "mtext"] | None = None
    align: CadTextAlign | None = None
    role: Literal["printing", "reference", "annotation", "ignored"] | None = None
    path_semantic: Literal["DRAW", "TRAVEL", "SKIP", "AUXILIARY"] | None = None

    @model_validator(mode="after")
    def validate_non_empty(self) -> "CadGeometryPatch":
        if not self.model_dump(exclude_none=True):
            raise ValueError("patch must change at least one mutable field")
        return self


class CadAddOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["add"]
    geometry: CadGeometry


class CadUpdateOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["update"]
    geometry_id: int = Field(ge=1, le=1000000)
    patch: CadGeometryPatch


class CadRemoveOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["remove"]
    geometry_id: int = Field(ge=1, le=1000000)


CadModificationOperation = Annotated[
    Union[CadAddOperation, CadUpdateOperation, CadRemoveOperation],
    Field(discriminator="op"),
]


class ModifyDrawingArguments(ToolArguments):
    source_file_name: str = Field(min_length=1, max_length=255, pattern=r"^[^/\\]+\.json$")
    target: CadModificationTarget
    operations: list[CadModificationOperation] = Field(min_length=1, max_length=100)
    source_sha256: str | None = Field(default=None, min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")
    source_version: int | None = Field(default=None, ge=1, le=1000000)
    operation_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class ApplyCadCandidateEditArguments(ToolArguments):
    project_id: str = Field(min_length=1, max_length=64)
    parent_variant_id: str = Field(min_length=1, max_length=64)
    parent_geometry_sha256: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    edit_contract: dict[str, Any]
    edit_preview: dict[str, Any] | None = None


class DesignRequirementsArguments(ToolArguments):
    prompt: str = Field(min_length=1, max_length=2000)


class CreateCreativeProjectArguments(ToolArguments):
    name: str = Field(min_length=1, max_length=100)
    prompt: str = Field(min_length=1, max_length=2000)
    constraints: dict[str, Any] = Field(default_factory=dict)


class UpdateCreativeProjectArguments(ToolArguments):
    project_id: str = Field(min_length=1, max_length=64)
    requirements: dict[str, Any] | None = None
    constraints: dict[str, Any] | None = None
    missing_parameters: list[str] | None = Field(default=None, max_length=50)


class SelectDesignVariantArguments(ToolArguments):
    project_id: str = Field(min_length=1, max_length=64)
    variant_id: str = Field(min_length=1, max_length=64)


class CreativeProjectPlanArguments(ToolArguments):
    project_id: str = Field(min_length=1, max_length=64)


class DrawingFeasibilityArguments(CadDrawingArguments):
    pass


class ListElementsArguments(DrawingFeasibilityArguments):
    instance_ids: list[int] = Field(default_factory=list, max_length=50)
    semantic: str | None = Field(default=None, min_length=1, max_length=80)


class DiffDrawingArguments(ToolArguments):
    source_geometries: list[CadGeometry] = Field(min_length=1, max_length=200)
    target_geometries: list[CadGeometry] = Field(min_length=1, max_length=200)


class SnapshotDrawingArguments(DrawingFeasibilityArguments):
    label: str = Field(default="", max_length=100)


class DrawingMetadataArguments(ToolArguments):
    file_name: str = Field(min_length=1, max_length=255, pattern=r"^[^/\\]+\.json$")


class PathLayeringArguments(CadDrawingArguments):
    printer: Literal["center"] = "center"


class PreviewPathValidationArguments(ToolArguments):
    paths: list[dict[str, Any]] = Field(min_length=1, max_length=500)


class DriveArguments(ToolArguments):
    linear: float = Field(ge=-MAX_LINEAR_VELOCITY, le=MAX_LINEAR_VELOCITY)
    angular: float = Field(ge=-MAX_ANGULAR_VELOCITY, le=MAX_ANGULAR_VELOCITY)
    duration_seconds: float = Field(ge=0.1, le=30.0)


class DriveSequenceArguments(ToolArguments):
    steps: list[DriveArguments] = Field(min_length=2)


class MissionArguments(ToolArguments):
    running: bool
    file_name: str = Field(min_length=1, max_length=255, pattern=r"^[^/\\]+\.json$")


class PreparedMissionArguments(ToolArguments):
    file_name: str = Field(min_length=1, max_length=255, pattern=r"^[^/\\]+\.json$")


class Ln150Arguments(ToolArguments):
    command_type: int = Field(ge=1, le=3)


class PrinterArguments(ToolArguments):
    printer_name: Literal["center"] = "center"
    action: Literal[
        "beep", "start_print", "stop_print", "clean_nozzle", "test_print", "ink_level"
    ]
    param: int = Field(default=0, ge=0, le=10000)


class PrinterSprayArguments(ToolArguments):
    """持续手动喷墨开关，和一次性的喷码机指令分开。"""

    printer_name: Literal["center"] = "center"
    spraying: bool


Risk = Literal["read", "safe_stop", "configuration", "motion", "hardware"]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    arguments: type[ToolArguments]
    risk: Risk
    requires_confirmation: bool

    def openai_schema(self) -> dict[str, Any]:
        schema = self.arguments.model_json_schema()
        schema.pop("title", None)
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": schema,
            "strict": True,
        }


TOOL_REGISTRY = {
    spec.name: spec
    for spec in (
        ToolSpec("get_robot_status", "读取真实小车和 ROS2 状态。", EmptyArguments, "read", False),
        ToolSpec(
            "parameterize_design",
            "从用户描述中提取图形、尺寸、喷头、单位和缺失参数；只分析，不保存图纸。",
            DesignRequirementsArguments,
            "read",
            False,
        ),
        ToolSpec(
            "clarify_requirements",
            "分析创意需求并返回已识别参数、缺失参数和下一步问题，不控制小车。",
            DesignRequirementsArguments,
            "read",
            False,
        ),
        ToolSpec(
            "create_creative_project",
            "创建并持久化创意设计项目；自动提取需求和缺失参数，不生成图纸、不控制小车。",
            CreateCreativeProjectArguments,
            "read",
            False,
        ),
        ToolSpec(
            "update_creative_project",
            "补充现有创意项目的需求、约束和缺失参数，不生成图纸、不控制小车。"
            "用户已确认图形与参数（含坐标单位）后必须调用本工具把完整 "
            "requirements（shape/dimensions/units 等）写入项目，并传 "
            "missing_parameters=[] 使项目进入就绪；禁止只在聊天文本复述参数而不落库。"
            "坐标单位确认（坐标单位为米/毫米等）写入 requirements.units。"
            "参数仍不齐时传剩余 missing_parameters（如 shape/dimensions/printer）。",
            UpdateCreativeProjectArguments,
            "read",
            False,
        ),
        ToolSpec(
            "select_design_variant",
            "选择项目中的候选方案并将项目推进到待规划状态；不自动保存或执行。",
            SelectDesignVariantArguments,
            "read",
            False,
        ),
        ToolSpec(
            "prepare_project_plan",
            "将已选设计方案固化为版本图纸并提交 ROS2 规划预览；只规划，不启动小车。",
            CreativeProjectPlanArguments,
            "read",
            False,
        ),
        ToolSpec(
            "refresh_project_plan",
            "读取创意项目对应的真实 ROS2 规划结果、质量评分和执行就绪状态。",
            CreativeProjectPlanArguments,
            "read",
            False,
        ),
        ToolSpec(
            "refresh_project_execution",
            "读取创意项目的实时执行进度、分段检查点、验证结果和摆头事件。",
            CreativeProjectPlanArguments,
            "read",
            False,
        ),
        ToolSpec(
            "assess_project_recovery",
            "分析创意项目执行异常并给出人工确认后的恢复建议；禁止自动恢复运动。",
            CreativeProjectPlanArguments,
            "read",
            False,
        ),
        ToolSpec(
            "prepare_project_recovery",
            "跳过账本中已完成的喷墨段，为暂停、失败或取消项目生成恢复图纸并重新规划；不自动执行。",
            CreativeProjectPlanArguments,
            "read",
            False,
        ),
        ToolSpec(
            "generate_project_report",
            "生成创意项目的设计、规划、执行、轨迹偏差和验收结论报告。",
            CreativeProjectPlanArguments,
            "read",
            False,
        ),
        ToolSpec(
            "check_drawing_feasibility",
            "检查 CAD 几何是否可预览、长度是否有效以及小半径转向风险；只分析，不执行。",
            DrawingFeasibilityArguments,
            "read",
            False,
        ),
        ToolSpec(
            "inspect_drawing",
            "读取 CAD 图纸实体、类型、图层、边界、路径和拓扑摘要；只分析，不修改。",
            DrawingFeasibilityArguments,
            "read",
            False,
        ),
        ToolSpec(
            "list_elements",
            "列出 CAD 图纸中的稳定实例、图元、语义名称和空间范围，用于先定位再修改；只读取，不修改。",
            ListElementsArguments,
            "read",
            False,
        ),
        ToolSpec(
            "diff_drawing",
            "比较 CAD 图纸修改前后几何差异和受影响路径；只分析，不修改。",
            DiffDrawingArguments,
            "read",
            False,
        ),
        ToolSpec(
            "validate_drawing",
            "对 CAD 图纸执行确定性几何、边界、拓扑和路径可预览检查；只分析，不执行。",
            DrawingFeasibilityArguments,
            "read",
            False,
        ),
        ToolSpec(
            "snapshot_drawing",
            "生成 CAD 图纸的稳定快照 ID 和摘要，用于修改前后复核；不写文件、不执行。",
            SnapshotDrawingArguments,
            "read",
            False,
        ),
        ToolSpec(
            "inspect_drawing_metadata",
            "读取当前 CAD 图纸的图层、实体统计、跳过实体、边界和可执行性；只分析，不执行。",
            DrawingMetadataArguments,
            "read",
            False,
        ),
        ToolSpec(
            "analyze_geometry_topology",
            "检查 CAD 路径的断线、闭合轮廓、交叉、自相交、重复几何和连通分量；只分析，不执行。",
            DrawingFeasibilityArguments,
            "read",
            False,
        ),
        ToolSpec(
            "layer_drawing_paths",
            "将 CAD 输入几何标记为喷墨层；小车转场路径仍由 xline_ws3 规划器生成。",
            PathLayeringArguments,
            "read",
            False,
        ),
        ToolSpec(
            "validate_preview_paths",
            "校验并规范化 AI/ROS2 路径预览数据，明确区分 printing 与 transition；只分析，不执行。",
            PreviewPathValidationArguments,
            "read",
            False,
        ),
        ToolSpec(
            "recommend_recovery",
            "根据当前真实状态生成停车、重新规划或人工检查建议，禁止自动恢复运动。",
            EmptyArguments,
            "read",
            False,
        ),
        ToolSpec("stop_robot", "立即发布零速度停车。", EmptyArguments, "safe_stop", False),
        ToolSpec("modify_drawing", "基于当前图纸版本和明确 target 执行局部 patch、增加或删除；update 必须指定 geometry_id，禁止整图重写；输出前后差异、受影响路径和风险。",
                 ModifyDrawingArguments, "configuration", False),
        ToolSpec(
            "apply_cad_candidate_edit",
            "内部使用：用户确认高风险候选图纸修改后，重新校验父版本并应用结构化 CAD 命令。",
            ApplyCadCandidateEditArguments,
            "configuration",
            True,
        ),
        ToolSpec(
            "drive_robot",
            "有限时控制真实底盘。正线速度表示前进，正角速度表示左转；可组合成直线、转向或绕圈运动，最长 30 秒。",
            DriveArguments,
            "motion",
            True,
        ),
        ToolSpec(
            "drive_sequence",
            "按顺序执行任意段有限时底盘动作，序列总时长不设上限。多步移动必须使用本工具一次提交，禁止拆成多个 drive_robot 调用。",
            DriveSequenceArguments,
            "motion",
            True,
        ),
        ToolSpec(
            "set_mission",
            "启动或取消完整划线任务。",
            MissionArguments,
            "motion",
            True,
        ),
        ToolSpec(
            "execute_prepared_mission",
            "执行已经完成规划预览并处于 ready 状态的路径。必须再次由用户确认。",
            PreparedMissionArguments,
            "motion",
            True,
        ),
        ToolSpec(
            "control_ln150",
            "控制 LN150：1 初始化，2 自动追踪，3 自动调平。",
            Ln150Arguments,
            "hardware",
            True,
        ),
        ToolSpec(
            "control_printer",
            "控制指定喷码机。",
            PrinterArguments,
            "hardware",
            True,
        ),
        ToolSpec(
            "printer_spray",
            "打开或关闭持续喷墨；基础模式仅在用户明确要求喷墨时可用，运动期间可保持喷墨。",
            PrinterSprayArguments,
            "hardware",
            True,
        ),
    )
}

INTERNAL_TOOL_NAMES = {"apply_cad_candidate_edit"}

def validate_tool_configuration(registry=None, *, base_tools=None, advanced_tools=None, safe_tools=None) -> None:
    """Fail closed when policy names drift from the authoritative registry.

    Mode access and confirmation exemptions remain separate policies. They
    need not contain every registered tool or be identical to one another.
    """
    from .agent_policy import BASE_AGENT_TOOLS, ADVANCED_AGENT_TOOLS
    from .agent_service_policy import SAFE_TOOL_NAMES

    registry = TOOL_REGISTRY if registry is None else registry
    groups = {
        "BASE_AGENT_TOOLS": BASE_AGENT_TOOLS if base_tools is None else base_tools,
        "ADVANCED_AGENT_TOOLS": ADVANCED_AGENT_TOOLS if advanced_tools is None else advanced_tools,
        "SAFE_TOOL_NAMES": SAFE_TOOL_NAMES if safe_tools is None else safe_tools,
    }
    errors = []
    for label, names in groups.items():
        unknown = set(names) - registry.keys()
        if unknown:
            errors.append(f"{label}: unregistered tools {sorted(unknown)}")
    for name, spec in registry.items():
        if name != spec.name:
            errors.append(f"registry key {name} differs from tool name {spec.name}")
        if name in groups["SAFE_TOOL_NAMES"] and spec.requires_confirmation:
            errors.append(f"{name}: confirmation-required tool cannot be in SAFE_TOOL_NAMES")
    if errors:
        raise ValueError("Invalid tool configuration: " + "; ".join(errors))


validate_tool_configuration()


OPENAI_TOOLS = [
    spec.openai_schema() for spec in TOOL_REGISTRY.values()
    if spec.name not in INTERNAL_TOOL_NAMES
]


def tool_catalog() -> list[dict[str, Any]]:
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "risk": spec.risk,
            "requires_confirmation": spec.requires_confirmation,
            "parameters": spec.openai_schema()["parameters"],
        }
        for spec in TOOL_REGISTRY.values()
        if spec.name not in INTERNAL_TOOL_NAMES
    ]


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    message: str = ""


def build_action_preflight(
    name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Expose the current safety gates without granting execution permission."""
    checks: list[dict[str, Any]] = []

    def check(code: str, label: str, ok: bool, detail: str) -> None:
        checks.append({"code": code, "label": label, "ok": ok, "detail": detail})

    physical = name in {
        "drive_robot", "drive_sequence", "set_mission", "execute_prepared_mission",
        "control_ln150", "control_printer", "printer_spray",
    }
    if not physical:
        return {"ready": True, "checks": []}
    check(
        "control_owner", "控制权",
        bool(robot_state.control_owner),
        "当前 App 已取得控制权" if robot_state.control_owner else "当前没有 App 取得控制权",
    )
    check(
        "ros_available", "ROS2 运行层",
        robot_state.ros_available,
        "ROS2 可用" if robot_state.ros_available else "ROS2 后端不可用",
    )
    check(
        "emergency_stop", "急停状态",
        not robot_state.emergency_stopped,
        "急停已解除" if not robot_state.emergency_stopped else "急停仍处于锁定状态",
    )
    if name in {"drive_robot", "drive_sequence", "set_mission", "execute_prepared_mission"}:
        check(
            "control_ready", "底盘控制",
            robot_state.control_ready and robot_state.drive_device_connected,
            "CAN 与底盘驱动已就绪"
            if robot_state.control_ready and robot_state.drive_device_connected
            else "CAN 或底盘驱动未就绪",
        )
    if name in {"set_mission", "execute_prepared_mission"} and (
        name == "execute_prepared_mission" or arguments.get("running") is True
    ):
        check(
            "localization", "定位状态",
            robot_state.localization_valid,
            "定位有效" if robot_state.localization_valid else "定位无效",
        )
        check(
            "mission_nodes", "任务节点",
            robot_state.mission_nodes_ready,
            "任务节点已就绪" if robot_state.mission_nodes_ready else "任务节点未全部就绪",
        )
    if name in {"control_printer", "printer_spray"}:
        printer = robot_state.printer_status.get("printer_center", {})
        connected = isinstance(printer, dict) and printer.get("connected") is True
        online = isinstance(printer, dict) and printer.get("is_online") is not False
        check(
            "printer", "喷码机状态",
            robot_state.printer_ready and connected and online,
            "喷码机已连接并在线"
            if robot_state.printer_ready and connected and online
            else "喷码机未连接、离线或节点未就绪",
        )
    if name == "control_ln150":
        check(
            "ln150", "全站仪状态",
            robot_state.ln150_ready and robot_state.localization_source != "odom_imu_relative",
            "LN150 已就绪" if robot_state.ln150_ready else "LN150 未就绪或当前为相对定位",
        )
    return {
        "ready": all(item["ok"] for item in checks),
        "checks": checks,
    }


def validate_tool_arguments(name: str, arguments: Any) -> tuple[dict[str, Any] | None, str]:
    spec = TOOL_REGISTRY.get(name)
    if spec is None:
        return None, f"未知工具：{name}"
    try:
        validated = spec.arguments.model_validate(arguments)
    except ValidationError as error:
        return None, f"工具参数不符合 Schema：{error.errors(include_url=False)}"
    return validated.model_dump(), ""


def authorize_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    confirmed: bool,
    client_id: str | None = None,
) -> GateDecision:
    spec = TOOL_REGISTRY.get(name)
    if spec is None:
        return GateDecision(False, f"未知工具：{name}")
    if spec.requires_confirmation and not confirmed:
        return GateDecision(False, "该操作需要用户确认")
    if spec.risk in {"motion", "hardware"}:
        if not robot_state.control_owner:
            return GateDecision(False, "当前没有 App 取得小车控制权")
        if client_id is not None and robot_state.control_owner != client_id:
            return GateDecision(False, "当前控制权属于其他客户端")

    if name in {"drive_robot", "drive_sequence"}:
        if robot_state.emergency_stopped:
            return GateDecision(False, "急停已锁定，禁止移动")
        if not robot_state.control_ready:
            return GateDecision(False, "CAN 接口或电机驱动未就绪")
        if robot_state.mission_running:
            return GateDecision(False, "任务执行期间禁止人工速度指令")

    if (
        (name == "set_mission" and arguments.get("running") is True)
        or name == "execute_prepared_mission"
    ):
        if robot_state.emergency_stopped:
            return GateDecision(False, "急停已锁定，禁止启动任务")
        if not robot_state.control_ready:
            return GateDecision(False, "底盘控制未就绪")
        if not robot_state.mission_nodes_ready:
            return GateDecision(False, "任务节点未全部就绪")
        if not robot_state.localization_valid:
            return GateDecision(False, "定位无效，禁止执行规划路径")
        if name == "execute_prepared_mission":
            if robot_state.mission_stage != "ready":
                return GateDecision(False, "路径尚未完成规划预览")
            if robot_state.mission_file != arguments.get("file_name"):
                return GateDecision(False, "准备好的路径与请求图纸不一致")

    if name == "control_ln150":
        if not robot_state.ln150_ready:
            return GateDecision(False, "LN150 节点或服务未就绪")
        if robot_state.localization_source == "odom_imu_relative":
            return GateDecision(False, "当前为相对定位模式，不能调用 LN150 工具")

    if name == "control_printer" and not robot_state.printer_ready:
        return GateDecision(False, "喷码机节点未就绪")

    return GateDecision(True)


def authorize_emergency_stop(active: bool, client_id: str | None) -> GateDecision:
    if active:
        return GateDecision(True)
    if not robot_state.control_owner:
        return GateDecision(False, "当前没有 App 取得小车控制权，禁止解除急停")
    if client_id is not None and robot_state.control_owner != client_id:
        return GateDecision(False, "只有当前控制权持有者可以解除急停")
    # Releasing the software stop is also the transition that starts the ws3
    # runtime. Requiring control_ready here creates a deadlock: the drive nodes
    # cannot become ready until that startup transition is allowed to run.
    if not robot_state.ros_available:
        return GateDecision(False, "ROS2 后端不可用，急停保持锁定")
    if not robot_state.drive_device_connected:
        return GateDecision(False, "CAN 接口未连接，急停保持锁定")
    return GateDecision(True)
