from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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


class CreateDrawingArguments(ToolArguments):
    file_name: str = Field(
        min_length=1, max_length=64, pattern=r"^[\w\-\u4e00-\u9fff]+\.json$"
    )
    geometries: list[CadGeometry] = Field(min_length=1, max_length=200)


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


class AddDesignVariantArguments(ToolArguments):
    project_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=100)
    rationale: str = Field(default="", max_length=1000)
    geometries: list[CadGeometry] = Field(min_length=1, max_length=200)


class SelectDesignVariantArguments(ToolArguments):
    project_id: str = Field(min_length=1, max_length=64)
    variant_id: str = Field(min_length=1, max_length=64)


class CreativeProjectPlanArguments(ToolArguments):
    project_id: str = Field(min_length=1, max_length=64)


class DrawingFeasibilityArguments(ToolArguments):
    geometries: list[CadGeometry] = Field(min_length=1, max_length=200)


class PathLayeringArguments(ToolArguments):
    geometries: list[CadGeometry] = Field(min_length=1, max_length=200)
    printer: Literal["left", "center", "right"] = "center"


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
    printer_name: Literal["left", "center", "right", "all"] = "center"
    action: Literal[
        "beep", "start_print", "stop_print", "clean_nozzle", "test_print", "ink_level"
    ]
    param: int = Field(default=0, ge=0, le=10000)


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
            "补充现有创意项目的需求、约束和缺失参数，不生成图纸、不控制小车。",
            UpdateCreativeProjectArguments,
            "read",
            False,
        ),
        ToolSpec(
            "add_design_variant",
            "向创意项目加入一个 CAD 候选方案，计算设计阶段评分并生成预览；不保存正式图纸、不规划。",
            AddDesignVariantArguments,
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
            "layer_drawing_paths",
            "将 CAD 输入几何标记为喷墨层；小车转场路径仍由 xline_cyg 规划器生成。",
            PathLayeringArguments,
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
        ToolSpec(
            "create_drawing",
            "根据用户要求生成 xline_cyg 支持的 CAD JSON 图纸。坐标和尺寸单位必须是毫米；只保存草稿，不启动小车。",
            CreateDrawingArguments,
            "configuration",
            True,
        ),
        ToolSpec(
            "create_rectangle_drawing",
            "创建矩形 CAD JSON，只保存图纸，不启动小车。",
            RectangleArguments,
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
    )
}

OPENAI_TOOLS = [spec.openai_schema() for spec in TOOL_REGISTRY.values()]


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
    ]


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    message: str = ""


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
    if not robot_state.control_ready:
        return GateDecision(False, "底盘运行环境未就绪，急停保持锁定")
    return GateDecision(True)
