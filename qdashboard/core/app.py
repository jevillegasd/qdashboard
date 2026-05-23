"""
Core FastAPI application configuration and setup.
"""

import html as _html
import json
import os
import traceback as _tb
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..utils.formatters import size_fmt, time_desc, data_fmt, icon_fmt, time_humanize
from qdashboard.utils.logger import get_logger
from .config import DEFAULT_PORT, DEFAULT_HOST, DEFAULT_QD_ROOT, set_config


logger = get_logger(__name__)

# Module-level templates instance — imported by route modules
templates: Jinja2Templates = None  # type: ignore[assignment]


def create_app(config: dict = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    global templates

    package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assets_dir = os.path.join(package_dir, "assets")
    templates_dir = os.path.join(package_dir, "templates")

    if config is not None:
        set_config(config)

    app = FastAPI(
        title="QDashboard",
        version="0.0.3",
        description=(
            "REST API for the QDashboard quantum computing dashboard.\n\n"
            "QDashboard exposes endpoints for monitoring QPU health, browsing\n"
            "calibration experiment files, managing platform Git repositories,\n"
            "submitting and tracking SLURM jobs, and discovering qibocal protocols.\n\n"
            "**Authentication** — when the server is started with an auth key\n"
            "(`QD_KEY` env var / `--auth-key` CLI flag), all API requests must\n"
            "include the header `X-Auth-Key: <key>` or the query parameter `key=<key>`.\n"
            "The same check applies to this documentation page."
        ),
        contact={
            "name": "TII Quantum Research Center",
            "email": "quantum@tii.ae",
            "url": "https://github.com/tii-qcomp",
        },
        license_info={
            "name": "Technology Innovation Institute General License (TII-GL)",
        },
        openapi_version="3.1.0",
        docs_url=None,   # served by custom auth-aware route below
        redoc_url=None,
        openapi_url=None,  # served by custom auth-aware route below
        openapi_tags=[
            {
                "name": "SLURM",
                "description": "SLURM queue monitoring and job management.",
            },
            {
                "name": "Platforms",
                "description": (
                    "QPU platform Git repository operations — branch switching, "
                    "commits, stashes, pushes."
                ),
            },
            {
                "name": "QPU",
                "description": (
                    "QPU parameters, qubit topology visualisation, and "
                    "calibration data."
                ),
            },
            {
                "name": "Protocols",
                "description": "Qibocal calibration protocol discovery.",
            },
            {
                "name": "Experiments",
                "description": (
                    "Experiment submission to SLURM and experiment status tracking."
                ),
            },
        ],
    )

    # Store config in app state for access via request.app.state.config
    app.state.config = config or {}

    # Startup: initialise experiment history DB in a thread-pool executor
    # so it does not block the event loop. Errors are non-fatal.
    @app.on_event("startup")
    async def _startup_init_db():
        import asyncio
        from ..db.database import init_db as _init_db
        _cfg = config or {}
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _init_db, _cfg)
        except Exception as _exc:
            logger.warning(f"DB init failed (non-fatal): {_exc}")

    # Mount static files at /assets
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    # Set up Jinja2 templates with custom filters
    templates = Jinja2Templates(directory=templates_dir)
    templates.env.filters["size_fmt"] = size_fmt
    templates.env.filters["time_fmt"] = time_desc
    templates.env.filters["data_fmt"] = data_fmt
    templates.env.filters["icon_fmt"] = icon_fmt
    templates.env.filters["humanize"] = time_humanize

    # Global exception handler — catches anything not caught by route handlers.
    # In debug mode the full traceback is returned so issues can be triaged
    # directly from the browser or API client.
    @app.exception_handler(Exception)
    async def _global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        trace = _tb.format_exc()
        logger.error("[%s %s] Unhandled %s: %s\n%s",
                     request.method, request.url.path,
                     type(exc).__name__, exc, trace)
        debug = app.state.config.get('debug', False)
        if debug:
            body = {
                'error': str(exc),
                'exception_type': type(exc).__name__,
                'traceback': trace,
                'request': f"{request.method} {request.url}",
            }
        else:
            body = {'error': 'Internal server error'}
        return JSONResponse(content=body, status_code=500)

    logger.debug("App module initialized")

    # ------------------------------------------------------------------ #
    # Auth-guarded OpenAPI schema + documentation endpoints               #
    # ------------------------------------------------------------------ #
    def _check_docs_auth(request: Request) -> bool:
        """Return True when the request is authorised to view the API docs."""
        key = (config or {}).get('key', '')
        if not key:
            return True
        provided = (
            request.headers.get('X-Auth-Key')
            or request.query_params.get('key', '')
        )
        return provided == key

    @app.get("/openapi.json", include_in_schema=False)
    async def _openapi_schema(request: Request) -> JSONResponse:
        if not _check_docs_auth(request):
            return JSONResponse({'error': 'Unauthorized'}, status_code=401)
        return JSONResponse(app.openapi())

    @app.get("/docs", include_in_schema=False)
    async def _swagger_ui(request: Request) -> HTMLResponse:
        if not _check_docs_auth(request):
            return HTMLResponse(
                '<html><head><title>401</title></head>'
                '<body style="font-family:sans-serif;padding:2rem">'
                '<h2>401 — Unauthorised</h2>'
                '<p>Provide the auth key via the <code>X-Auth-Key</code> '
                'header or the <code>key</code> query parameter.</p>'
                '</body></html>',
                status_code=401,
            )
        return get_swagger_ui_html(
            openapi_url="/openapi.json",
            title="QDashboard — API Docs",
            swagger_favicon_url="/assets/favicon.ico",
        )

    @app.get("/redoc", include_in_schema=False)
    async def _redoc_ui(request: Request) -> HTMLResponse:
        if not _check_docs_auth(request):
            return HTMLResponse(
                '<html><body><h2>401 Unauthorised</h2></body></html>',
                status_code=401,
            )
        return get_redoc_html(
            openapi_url="/openapi.json",
            title="QDashboard — API Reference",
        )

    return app


def get_config():
    """Get application configuration from environment variables."""
    from .config import get_config as _get_config
    return _get_config()
