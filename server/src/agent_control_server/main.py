"""Main server application entry point."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from agent_control_engine import discover_evaluators, list_evaluators
from agent_control_models import HealthResponse
from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from starlette_exporter import PrometheusMiddleware, handle_metrics

from .auth import require_api_key
from .config import observability_settings, settings
from .db import AsyncSessionLocal
from .endpoints.agents import router as agent_router
from .endpoints.controls import router as control_router
from .endpoints.evaluation import router as evaluation_router
from .endpoints.evaluator_configs import router as evaluator_config_router
from .endpoints.evaluators import router as evaluator_router
from .endpoints.observability import router as observability_router
from .endpoints.policies import router as policy_router
from .endpoints.system import router as system_router
from .errors import (
    APIError,
    api_error_handler,
    generic_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)
from .logging_utils import configure_logging
from .observability.ingest import DirectEventIngestor
from .observability.store import PostgresEventStore
from .ui_assets import configure_ui_routes

logger = logging.getLogger(__name__)

METRICS_PATH = "/metrics"
PROMETHEUS_BUCKETS = [
    0.1,
    0.5,
    1.0,
    2.0,
    5.0,
    10.0,
    30.0,
    60.0,
    float("inf"),
]
PROMETHEUS_SKIP_PATHS = [
    METRICS_PATH,
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
]


def add_prometheus_metrics(app: FastAPI, metrics_prefix: str) -> None:
    """Configure Prometheus metrics for the FastAPI app."""
    app.add_middleware(
        PrometheusMiddleware,
        app_name="agent-control-server",
        prefix=metrics_prefix,
        group_paths=True,
        filter_unhandled_paths=True,
        buckets=PROMETHEUS_BUCKETS,
        skip_paths=PROMETHEUS_SKIP_PATHS,
    )
    app.add_route(METRICS_PATH, handle_metrics)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan context manager for FastAPI app startup and shutdown."""
    # Startup: Configure logging
    log_level = "DEBUG" if settings.debug else "INFO"
    configure_logging(level=log_level)

    # Discover evaluators at startup
    discover_evaluators()
    available = list(list_evaluators().keys())
    logger.info(f"Evaluator discovery complete. Available evaluators: {available}")

    # Initialize observability components (stored on app.state)
    if observability_settings.enabled:
        logger.info("Initializing observability components...")

        # 1. Create event store
        store = PostgresEventStore(AsyncSessionLocal)
        app.state.event_store = store
        logger.info("PostgresEventStore initialized")

        # 2. Create event ingestor
        ingestor = DirectEventIngestor(
            store=store,
            log_to_stdout=observability_settings.stdout,
        )
        app.state.event_ingestor = ingestor
        logger.info(
            f"DirectEventIngestor initialized (stdout={observability_settings.stdout})"
        )

        logger.info("Observability initialization complete")

    yield

    # Shutdown: Clean up observability
    if observability_settings.enabled and hasattr(app.state, "event_store"):
        logger.info("Shutting down observability components...")
        await app.state.event_store.close()
        logger.info("EventStore closed")


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
5. Query agent's active controls with `/api/v1/agents/{agent_name}/controls`
    """,
    version="0.1.0",
    lifespan=lifespan,
)

add_prometheus_metrics(app, settings.prometheus_metrics_prefix)

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


# =============================================================================
# Exception Handlers (RFC 7807 / Kubernetes / GitHub-style)
# =============================================================================

# Register custom API error handler (highest priority for our errors)
app.add_exception_handler(APIError, api_error_handler)  # type: ignore[arg-type]

# Register handler for FastAPI's RequestValidationError (Pydantic validation)
app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]

# Register handler for standard HTTPException (legacy code, FastAPI internals)
app.add_exception_handler(HTTPException, http_exception_handler)  # type: ignore[arg-type]

# Register catch-all handler for unexpected exceptions
app.add_exception_handler(Exception, generic_exception_handler)

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
    evaluator_config_router,
    prefix=api_v1_prefix,
    dependencies=[Depends(require_api_key)],
)
app.include_router(
    evaluation_router,
    prefix=api_v1_prefix,
    dependencies=[Depends(require_api_key)],
)

app.include_router(
    evaluator_router,
    prefix=api_v1_prefix,
    dependencies=[Depends(require_api_key)],
)

# Observability routes (already has auth dependency in router)
app.include_router(
    observability_router,
    prefix=api_v1_prefix,
)

# System routes (config, login, logout) — no auth required
app.include_router(
    system_router,
    prefix=settings.api_prefix,
)

# Override OpenAPI to avoid recursive JSONValue schema issues in TS generators.
def custom_openapi() -> dict[str, Any]:
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    schemas = openapi_schema.get("components", {}).get("schemas", {})
    if "JSONValue" in schemas:
        schemas["JSONValue"] = {"description": "Any JSON value"}

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi  # type: ignore[assignment]

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


configure_ui_routes(app)


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
