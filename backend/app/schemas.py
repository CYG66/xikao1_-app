from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .config import MAX_ANGULAR_VELOCITY, MAX_LINEAR_VELOCITY


class PhysicalCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: str = Field(min_length=1, max_length=128)


class VelocityCommand(PhysicalCommand):
    linear: float = Field(
        default=0.0, ge=-MAX_LINEAR_VELOCITY, le=MAX_LINEAR_VELOCITY
    )
    angular: float = Field(
        default=0.0, ge=-MAX_ANGULAR_VELOCITY, le=MAX_ANGULAR_VELOCITY
    )


class PrinterCommand(PhysicalCommand):
    action: str = Field(
        default="beep",
        pattern="^(beep|start_print|stop_print|clean_nozzle|test_print|ink_level)$",
    )
    printer_name: str = Field(default="center", pattern="^center$")
    param: int = Field(default=0, ge=0, le=10000)


class Ln150Command(PhysicalCommand):
    command_type: int = Field(default=1, ge=1, le=3)


class MissionCommand(PhysicalCommand):
    running: bool | None = None
    action: str = Field(default="start", pattern="^(start|pause|resume|cancel)$")
    file_name: str = Field(default="test_pattern.json", min_length=1, max_length=255)


class EmergencyStopCommand(PhysicalCommand):
    active: bool = True


class PrinterActiveCommand(PhysicalCommand):
    printer_name: str = Field(default="center", pattern="^center$")
    active: bool


class ApiResult(BaseModel):
    ok: bool
    message: str


class AgentMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=4000)


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[AgentMessage] = Field(default_factory=list, max_length=200)
    mode: Literal["base", "advanced", "chat", "work"] = "base"


class DeviceDiagnosticRequest(BaseModel):
    snapshot: dict[str, object] = Field(default_factory=dict)


class WifiProvisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ssid: str = Field(min_length=1, max_length=32)
    password: str = Field(default="", max_length=63)
    hidden: bool = False


class AgentConfirmRequest(BaseModel):
    action_id: str = Field(min_length=1, max_length=64)
    approved: bool
    client_id: str | None = Field(default=None, max_length=100)


class AgentDrawingPlanRequest(BaseModel):
    file_name: str = Field(min_length=1, max_length=255, pattern=r"^[^/\\]+\.json$")


class AgentConfigCommand(BaseModel):
    mode: str = Field(
        pattern="^(openai|anthropic|gemini|deepseek|qwen|kimi|glm|minimax|local)$"
    )
    model: str = Field(min_length=1, max_length=100)
    api_key: str | None = Field(default=None, max_length=500)
    clear_api_key: bool = False


class DrawingSegment(BaseModel):
    start_x: float = Field(ge=-100.0, le=100.0)
    start_y: float = Field(ge=-100.0, le=100.0)
    end_x: float = Field(ge=-100.0, le=100.0)
    end_y: float = Field(ge=-100.0, le=100.0)


class DrawingSaveRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60, pattern=r"^[\w\-\u4e00-\u9fff]+$")
    segments: list[DrawingSegment] = Field(min_length=1, max_length=1000)
    # Optional editor metadata is preserved for round-trip editing; planning
    # continues to use the validated flat segments below.
    path_metadata: list[dict[str, Any]] = Field(default_factory=list, max_length=1000)
    # Editing keeps the original drawing identity while the version store
    # writes a new immutable version instead of destroying history.
    overwrite: bool = False
    file_name: str | None = Field(
        default=None,
        max_length=100,
        pattern=r"^[\w\-\u4e00-\u9fff]+\.json$",
    )


class DrawingGenerateRequest(BaseModel):
    prompt: str = Field(min_length=2, max_length=500)


class DrawingJsonImportRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60, pattern=r"^[\w\-\u4e00-\u9fff]+$")
    payload: dict[str, object]


class DrawingVersionRollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str | None = Field(default=None, min_length=1, max_length=64)


class CreativeProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    original_prompt: str = Field(min_length=1, max_length=2000)
    requirements: dict[str, object] = Field(default_factory=dict)
    constraints: dict[str, object] = Field(default_factory=dict)
    missing_parameters: list[str] = Field(default_factory=list, max_length=50)


class CreativeProjectUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=100)
    requirements: dict[str, object] | None = None
    constraints: dict[str, object] | None = None
    missing_parameters: list[str] | None = Field(default=None, max_length=50)
    status: str | None = Field(
        default=None,
        pattern="^(draft|clarifying|ready_for_design|designing|ready_for_planning|planning|planning_ready|planning_failed|pending_execution|executing|paused|execution_failed|completed|cancelled)$",
    )


class CreativeProjectVariantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    rationale: str = Field(default="", max_length=1000)
    geometries: list[dict[str, object]] = Field(min_length=1, max_length=200)


class CreativeProjectVariantSelectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variant_id: str = Field(min_length=1, max_length=64)


class RecoveryInspectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: bool
