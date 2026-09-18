"""SPECTRA API application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from spectra_config import get_settings
from spectra_config.logging import configure_logging, get_logger

from .background import drain
from .container import build_container, shutdown_container
from .errors import register_error_handlers
from .middleware import CorrelationMiddleware
from .routers import (
    agents,
    assets,
    cases,
    database,
    demo,
    entities,
    evaluation,
    evidence,
    graph,
    health,
    investigations,
    models,
    search,
    sources,
    stream,
    uploads,
)

log = get_logger(__name__)

API_TITLE = "SPECTRA"
API_DESCRIPTION = (
    "Hypothesis-driven multimodal enterprise investigation agent. "
    "Resolves entities across documents, images, audio, video and structured databases; "
    "states only what the evidence supports and actively searches for evidence against it; "
    "detects contradictions; and returns every claim with its provenance."
)
API_VERSION = "1.0.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    log.info("api.starting", version=API_VERSION, mode=settings.deployment_mode.value)
    container = await build_container(settings)
    app.state.container = container
    if container.degraded:
        log.warning("api.started_degraded", reasons=container.degraded)
    else:
        log.info("api.started")
    try:
        yield
    finally:
        await drain()
        await shutdown_container()
        log.info("api.stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=API_TITLE,
        description=API_DESCRIPTION,
        version=API_VERSION,
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(CorrelationMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Investigation-ID", "X-Response-Time-Ms"],
    )
    register_error_handlers(app)

    for router in (
        health.router,
        search.router,
        database.router,
        uploads.router,
        assets.router,
        investigations.router,
        stream.router,
        cases.router,
        entities.router,
        evidence.router,
        graph.router,
        sources.router,
        models.router,
        agents.router,
        demo.router,
        evaluation.router,
    ):
        app.include_router(router, prefix="/api")

    return app


app = create_app()
