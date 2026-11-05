from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class AgentAttachment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["image", "cad"]
    attachment_id: str | None = Field(
        default=None, min_length=16, max_length=64, pattern=r"^[a-f0-9]+$"
    )
    file_name: str | None = Field(
        default=None, min_length=1, max_length=255, pattern=r"^[^/\\]+\.json$"
    )
    display_name: str = Field(min_length=1, max_length=255)

    @model_validator(mode="after")
    def validate_reference(self) -> "AgentAttachment":
        if self.kind == "image" and not self.attachment_id:
            raise ValueError("image attachment requires attachment_id")
        if self.kind == "cad" and not self.file_name:
            raise ValueError("cad attachment requires file_name")
        return self


class AgentChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=2000)
    history: list[AgentMessage] = Field(default_factory=list, max_length=200)
    attachments: list[AgentAttachment] = Field(default_factory=list, max_length=4)
    mode: Literal["base", "advanced", "chat", "work"] = "base"
    conversation_id: str | None = Field(
        default=None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$"
    )
    # Until account authentication is introduced, the app supplies its stable
    # client id. The backend treats it as a request owner, not as proof of login.
    client_id: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"
    )
    project_id: str | None = Field(
        default=None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$"
    )
    # The canvas sends the variant currently being previewed so a follow-up
    # such as "改成短边并排" has an explicit, deterministic parent.
    variant_id: str | None = Field(
        default=None, min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$"
    )
    drawing_selection: "AgentDrawingSelection | None" = None


class AgentDrawingSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_file_name: str | None = Field(
        default=None, min_length=1, max_length=255, pattern=r"^[^/\\]+\.json$"
    )
    project_id: str | None = Field(
        default=None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$"
    )
    variant_id: str | None = Field(
        default=None, min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$"
    )
    object_id: str | None = Field(default=None, min_length=1, max_length=160)
    object_ids: list[str] = Field(default_factory=list, max_length=100)
    instance_id: int | None = Field(default=None, ge=1)
    scope: Literal["entity", "group", "logical_object"]
    geometry_ids: list[int] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_geometry_ids(self) -> "AgentDrawingSelection":
        if any(value <= 0 for value in self.geometry_ids):
            raise ValueError("geometry_ids must contain positive IDs")
        if len(self.geometry_ids) != len(set(self.geometry_ids)):
            raise ValueError("geometry_ids must be unique")
        if self.scope == "entity" and len(self.geometry_ids) != 1:
            raise ValueError("entity scope requires exactly one geometry ID")
        if self.scope=='logical_object':
            identities=[v for v in [self.object_id,*self.object_ids] if v is not None]
            if not identities or any(not v.strip() for v in identities) or len(identities)!=len(set(identities)):
                raise ValueError('logical_object scope requires unique nonempty object identities')
        has_file = self.source_file_name is not None
        has_candidate = self.project_id is not None and self.variant_id is not None
        if not has_file and not has_candidate:
            raise ValueError(
                "drawing selection requires source_file_name or project_id + variant_id"
            )
        if (self.project_id is None) != (self.variant_id is None):
            raise ValueError("project_id and variant_id must be provided together")
        return self


class AgentRequirementDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accepted: bool


class DeviceDiagnosticRequest(BaseModel):
    snapshot: dict[str, object] = Field(default_factory=dict)


class WifiProvisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ssid: str = Field(min_length=1, max_length=32)
    password: str = Field(default="", max_length=63)
    hidden: bool = False


class WifiNetworkCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ssid: str = Field(min_length=1, max_length=32)


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
    cad_planning_model: Literal["deepseek-chat", "deepseek-reasoner"] | None = None
    client_id: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"
    )


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


class DrawingJsonImportRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60, pattern=r"^[\w\-\u4e00-\u9fff]+$")
    payload: dict[str, object]


class DrawingLayerRoleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    roles: dict[str, Literal[
        "printing", "reference", "annotation", "ignored",
        "DRAW", "TRAVEL", "SKIP", "AUXILIARY",
    ]] = Field(
        min_length=1, max_length=500
    )


class CadLayerFilteredImportRequest(DrawingLayerRoleRequest):
    import_token: str = Field(min_length=16, max_length=64, pattern=r"^[a-f0-9]+$")
    excluded_entity_types: list[Literal[
        "TEXT", "MTEXT", "DIMENSION", "LEADER", "HATCH", "SOLID", "TRACE",
    ]] = Field(default_factory=list, max_length=7)


class DrawingVersionRollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str | None = Field(default=None, min_length=1, max_length=64)


class CreativeProjectCreateRequest(BaseModel):
    owner_conversation_id: str | None = Field(default=None, min_length=1, max_length=200)
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    original_prompt: str = Field(min_length=1, max_length=2000)
    requirements: dict[str, object] = Field(default_factory=dict)
    constraints: dict[str, object] = Field(default_factory=dict)
    missing_parameters: list[str] = Field(default_factory=list, max_length=50)
    source_drawing: dict[str, object] | None = None
    source_file_name: str | None = Field(
        default=None,
        max_length=255,
        pattern=r"^[^/\\]+\.json$",
    )


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


class CreativeProjectVariantSelectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variant_id: str = Field(min_length=1, max_length=64)
    conversation_id: str | None = Field(
        default=None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$"
    )
    drawing_selection: "AgentDrawingSelection | None" = None


class CreativeProjectIterationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parent_variant_id: str = Field(min_length=1, max_length=64)
    conversation_id: str | None = Field(
        default=None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$"
    )
    drawing_selection: "AgentDrawingSelection | None" = None


class CreativeProjectSaveDrawingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="", max_length=160)
    conversation_id: str | None = Field(
        default=None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$"
    )
    drawing_selection: "AgentDrawingSelection | None" = None


class CreativeProjectInstanceGroupsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    groups: list[dict[str, object]] = Field(min_length=1, max_length=50)


class RecoveryInspectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: bool


class DatabaseCleanupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    retention_days: int = Field(default=30, ge=1, le=365)
    targets: list[Literal["telemetry", "audit_logs", "ai_case_memory"]] = Field(
        min_length=1,
        max_length=3,
    )
