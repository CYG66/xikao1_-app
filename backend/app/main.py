from __future__ import annotations

import os
from contextlib import ExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .creative_workflow import creative_project_sync
from .ros_adapter import ros_adapter
from .discovery import rover_discovery
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
from .web_demo import WebDemoMiddleware
app.add_middleware(WebDemoMiddleware)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(system_router)
app.include_router(projects_router)
app.include_router(drawings_router)
app.include_router(agent_router)
app.include_router(missions_router)
app.include_router(device_router)
app.include_router(rosbridge_router)
