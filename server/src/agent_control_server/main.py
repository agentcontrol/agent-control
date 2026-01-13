"""Main server application entry point."""

import traceback
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import uvicorn
from agent_control_models import HealthResponse
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .auth import require_api_key
from .config import settings
from .endpoints.agents import router as agent_router
from .endpoints.controls import router as control_router
from .endpoints.evaluation import router as evaluation_router
from .endpoints.plugins import router as plugin_router
from .endpoints.policies import router as policy_router
from .logging_utils import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan context manager for FastAPI app startup and shutdown."""
    # Startup: Configure logging
    log_level = "DEBUG" if settings.debug else "INFO"
    configure_logging(level=log_level)

    yield


app = FastAPI(
    title="Agent Control Server",
    description="""Server component for Agent Control - policy-based control for AI agents.

## Architecture

The system uses a simple hierarchical model:
- **Agents**: AI systems that need control
- **Policies**: Collections of controls assigned to agents
- **Controls**: Individual control configurations

## Hierarchy

```
Agent → Policy → Control(s)
```

## Quick Start

1. Register your agent with `/api/v1/agents/initAgent`
2. Create controls with `/api/v1/controls` and configure them
3. Create a policy and add controls to it
4. Assign the policy to your agent
5. Query agent's active controls with `/api/v1/agents/{agent_id}/controls`
    """,
    version="0.1.0",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=settings.allow_methods,
    allow_headers=settings.allow_headers,
)

# Configure logging
log_level = "DEBUG" if settings.debug else "INFO"
configure_logging(level=log_level)


@app.exception_handler(Exception)
async def debug_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    import logging
    logging.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "traceback": traceback.format_exc().splitlines()},
    )

# API v1 prefix for all routes
api_v1_prefix = f"{settings.api_prefix}/{settings.api_version}"

# Protected routes (require valid API key)
app.include_router(
    agent_router,
    prefix=api_v1_prefix,
    dependencies=[Depends(require_api_key)],
)
app.include_router(
    policy_router,
    prefix=api_v1_prefix,
    dependencies=[Depends(require_api_key)],
)
app.include_router(
    control_router,
    prefix=api_v1_prefix,
    dependencies=[Depends(require_api_key)],
)
app.include_router(
    evaluation_router,
    prefix=api_v1_prefix,
    dependencies=[Depends(require_api_key)],
)

app.include_router(
    plugin_router,
    prefix=api_v1_prefix,
    dependencies=[Depends(require_api_key)],
)

# Health check at root level (common convention)
@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["system"],
    summary="Health check",
    response_description="Server health status",
)
async def health_check() -> HealthResponse:
    """
    Check if the server is running and responsive.

    This endpoint does not check database connectivity.

    Returns:
        HealthResponse with status and version
    """
    return HealthResponse(status="healthy", version="0.1.0")






def run() -> None:
    """Run the server application."""
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level="debug" if settings.debug else "info",
    )


if __name__ == "__main__":
    run()
