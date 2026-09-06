from pydantic import BaseModel, Field


class VelocityCommand(BaseModel):
    linear: float = Field(default=0.0, ge=-3.0, le=3.0)
    angular: float = Field(default=0.0, ge=-3.0, le=3.0)


class PrinterCommand(BaseModel):
    action: str = Field(default="beep")
    printer_name: str = Field(default="center")
    param: int = Field(default=0)


class Ln150Command(BaseModel):
    command_type: int = Field(default=1, ge=1, le=10)


class MissionCommand(BaseModel):
    running: bool


class ApiResult(BaseModel):
    ok: bool
    message: str
