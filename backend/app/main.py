from __future__ import annotations

import os
from contextlib import ExitStack, asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .creative_workflow import creative_project_sync
from .ros_adapter import ros_adapter
from .discovery import rover_discovery
from .security import AuthError, ControlAuthMiddleware, auth_manager
from .routers.system import router as system_router
from .routers.projects import router as projects_router
from .routers.drawings import router as drawings_router
from .routers.agent import router as agent_router
from .routers.rosbridge import router as rosbridge_router
from .routers.device import router as device_router
from .routers.missions import router as missions_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start and stop rover services with deterministic cleanup ordering."""
    discovery_enabled = os.getenv("XLINE_EMBEDDED_DISCOVERY", "1") != "0"
    # Authentication must be admitted before any hardware runtime can start.
    auth_manager.assert_ready()
    with ExitStack() as cleanup:
        cleanup.callback(ros_adapter.stop)
        ros_adapter.start()

        cleanup.callback(creative_project_sync.stop)
        creative_project_sync.start()

        if discovery_enabled:
            cleanup.callback(rover_discovery.stop)
            rover_discovery.start()

        yield


app = FastAPI(title="XLine Rover Backend", version="0.1.0", lifespan=lifespan)


@app.exception_handler(AuthError)
async def _auth_error_response(_request: Request, error: AuthError) -> JSONResponse:
    """Keep route-level defense-in-depth denials on the same API contract."""
    return JSONResponse(
        status_code=error.status_code,
        content={"ok": False, "code": error.code, "detail": str(error)},
    )


from .web_demo import WebDemoMiddleware
app.add_middleware(WebDemoMiddleware)


_cors_raw = os.getenv("XLINE_CORS_ORIGINS")
_cors_origins = [
    item.strip()
    for item in (_cors_raw or "").split(",")
    if item.strip()
]
if not _cors_origins:
    # Fail closed in production: an unset CORS allow-list must not become a
    # wildcard.  Development/test retains the historical wildcard for local
    # tooling and the packaged web demo.
    _cors_origins = ["*"] if os.getenv("XLINE_DEPLOYMENT_PROFILE", "").strip().lower() != "production" else []
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Keep the authentication middleware outermost so it runs before WebDemo,
# CORS and every route/WebSocket accepted by the application.
app.add_middleware(ControlAuthMiddleware)


app.include_router(system_router)
app.include_router(projects_router)
app.include_router(drawings_router)
app.include_router(agent_router)
app.include_router(missions_router)
app.include_router(device_router)
app.include_router(rosbridge_router)
