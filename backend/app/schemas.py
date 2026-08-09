from pydantic import BaseModel, Field


class VelocityCommand(BaseModel):
    linear: float = Field(default=0.0, ge=-1.0, le=1.0)
    angular: float = Field(default=0.0, ge=-1.5, le=1.5)


class PrinterCommand(BaseModel):
    action: str = Field(default="beep")
    printer_name: str = Field(default="center")
    param: int = Field(default=0)


class Ln150Command(BaseModel):
    command_type: int = Field(default=1, ge=1, le=10)


class MissionCommand(BaseModel):
    running: bool
    file_name: str = Field(default="test_pattern.json", min_length=1, max_length=255)


class PrinterActiveCommand(BaseModel):
    printer_name: str = Field(default="center", pattern="^(left|center|right|all)$")
    active: bool


class ApiResult(BaseModel):
    ok: bool
    message: str


class AgentMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=4000)


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[AgentMessage] = Field(default_factory=list, max_length=20)


class AgentConfirmRequest(BaseModel):
    action_id: str = Field(min_length=1, max_length=64)
    approved: bool


class AgentConfigCommand(BaseModel):
    mode: str = Field(
        pattern="^(openai|anthropic|gemini|deepseek|qwen|kimi|glm|minimax|local)$"
    )
    model: str = Field(min_length=1, max_length=100)
    api_key: str | None = Field(default=None, max_length=500)
    clear_api_key: bool = False
