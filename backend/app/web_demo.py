"""Refuse website proxy traffic unless this backend is hardware-isolated."""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from .config import RUNTIME_PROFILE


class WebDemoMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.headers.get("x-xline-web-demo") == "1":
            if RUNTIME_PROFILE != "virtual_sim":
                return JSONResponse(
                    {"ok": False, "detail": "在线体验仅允许连接虚拟仿真后端"},
                    status_code=503,
                )
            if request.url.path == "/health":
                return JSONResponse({"ok": True, "mode": "web_cad", "runtime_profile": RUNTIME_PROFILE})
        return await call_next(request)
