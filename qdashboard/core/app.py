"""
Core FastAPI application configuration and setup.
"""

import os
import traceback as _tb
from fastapi import FastAPI, Request
from starlette.exceptions import HTTPException
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..utils.formatters import size_fmt, time_desc, data_fmt, icon_fmt, time_humanize
from qdashboard.utils.logger import get_logger
from .config import DEFAULT_PORT, DEFAULT_HOST, DEFAULT_QD_ROOT, set_config
from ..remote.connection import SSHConnectionManager


logger = get_logger(__name__)

# Module-level templates instance — imported by route modules
templates: Jinja2Templates = None  # type: ignore[assignment]

_ERROR_ICONS = {404: 'fa-compass', 403: 'fa-lock', 401: 'fa-key', 400: 'fa-exclamation-circle'}
_ERROR_TITLES = {400: 'Bad Request', 401: 'Unauthorized', 403: 'Forbidden',
                 404: 'Page Not Found', 500: 'Internal Server Error'}


def render_error_page(request: Request, status_code: int, message: str = None,
                       trace: str = None) -> HTMLResponse:
    """Render the themed error page (templates/error.html) for HTML routes.

    JSON/API routes use their own JSON error shape instead — see the
    exception handlers below, which branch on the request path before
    calling this.
    """
    title = _ERROR_TITLES.get(status_code, 'Something Went Wrong')
    html = templates.get_template('error.html').render(
        request=request,
        status_code=status_code,
        title=title,
        message=message or title,
        icon=_ERROR_ICONS.get(status_code, 'fa-exclamation-triangle'),
        trace=trace,
    )
    return HTMLResponse(content=html, status_code=status_code)


def _wants_json(request: Request) -> bool:
    """API routes (and anything actually expecting JSON) get a JSON error
    body instead of the themed HTML page."""
    return request.url.path.startswith('/api/')


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

    # Attach the SSH connection manager (used in remote execution mode)
    app.state.ssh_manager = SSHConnectionManager()

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

    @app.on_event("startup")
    async def _startup_background_sync():
        """Start the background experiment-sync loop when remote + auto_sync is on."""
        import asyncio
        asyncio.ensure_future(_background_sync_loop(app))

    @app.on_event("shutdown")
    async def _shutdown_ssh():
        """Disconnect the SSH manager cleanly on server shutdown."""
        try:
            await app.state.ssh_manager.disconnect()
        except Exception:
            pass

    # Mount static files at /assets
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    # Set up Jinja2 templates with custom filters
    templates = Jinja2Templates(directory=templates_dir)
    templates.env.filters["size_fmt"] = size_fmt
    templates.env.filters["time_fmt"] = time_desc
    templates.env.filters["data_fmt"] = data_fmt
    templates.env.filters["icon_fmt"] = icon_fmt
    templates.env.filters["humanize"] = time_humanize

    # HTTPException covers both raised-by-route-code errors (raise HTTPException(404, ...))
    # and Starlette's own "no route matched" 404 — one handler for both.
    @app.exception_handler(HTTPException)
    async def _http_exception_handler(request: Request, exc: HTTPException):
        if _wants_json(request):
            return JSONResponse(content={'error': exc.detail}, status_code=exc.status_code)
        return render_error_page(request, exc.status_code, message=exc.detail)

    # Catches anything not caught by route handlers or the HTTPException
    # handler above. In debug mode the full traceback is shown so issues can
    # be triaged directly from the browser or API client.
    @app.exception_handler(Exception)
    async def _global_exception_handler(request: Request, exc: Exception):
        trace = _tb.format_exc()
        logger.error("[%s %s] Unhandled %s: %s\n%s",
                     request.method, request.url.path,
                     type(exc).__name__, exc, trace)
        debug = app.state.config.get('debug', False)

        if _wants_json(request):
            if debug:
                body = {'error': str(exc), 'exception_type': type(exc).__name__,
                        'traceback': trace, 'request': f"{request.method} {request.url}"}
            else:
                body = {'error': 'Internal server error'}
            return JSONResponse(content=body, status_code=500)

        return render_error_page(request, 500, message=str(exc) if debug else None,
                                  trace=trace if debug else None)

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


async def _background_sync_loop(app) -> None:
    """Periodically poll remote SLURM and sync completed experiments to local storage.

    Runs as a fire-and-forget asyncio task for the lifetime of the server.
    Only active when execution_mode is ``remote_*`` and ``auto_sync`` is True.
    Errors are caught and logged; the loop always continues.
    """
    import asyncio

    while True:
        try:
            from .config import get_remote_settings, get_qd_root, get_data_dir
            settings = get_remote_settings()

            if not settings.is_remote() or not settings.auto_sync:
                await asyncio.sleep(settings.sync_interval or 30)
                continue

            ssh_manager = app.state.ssh_manager
            if not ssh_manager.is_connected():
                await asyncio.sleep(settings.sync_interval)
                continue

            # Keep the local read-only platforms mirror in sync with the
            # remote qibolab_platforms_qrc directory (QPU monitoring,
            # topology, and partition lookups all read from this mirror).
            try:
                from ..remote.platforms_git import sync_platforms_mirror
                mirror_dir = os.path.join(get_qd_root(), 'platforms_mirror')
                await sync_platforms_mirror(settings, ssh_manager, mirror_dir)
            except Exception as _mirror_err:
                logger.debug("Background platforms mirror sync error (non-fatal): %s", _mirror_err)

            # Query local DB for pending/running remote experiments
            try:
                from ..db.database import get_db_connection, query_runs
                config = app.state.config
                data_dir = config.get('data_dir') or get_data_dir()

                with get_db_connection(config) as conn:
                    pending = query_runs(
                        conn,
                        status=['pending', 'running'],
                        limit=100,
                    )

                for exp in pending:
                    job_id = exp.get('slurm_job_id')
                    experiment_id = exp.get('experiment_id')
                    if not job_id or not experiment_id:
                        continue

                    # Check SLURM state on remote
                    from ..remote.executor import RemoteSlurmClient, RemoteExecutor
                    slurm = RemoteSlurmClient(RemoteExecutor(ssh_manager))
                    state = await slurm.check_job_status(job_id)

                    if state in RemoteSlurmClient.ACTIVE_STATES:
                        continue  # still running

                    # Job finished — resolve platform/date from experiment_id
                    platform = exp.get('platform') or exp.get('qpu_name', '')
                    # experiment_id format: YYYYMMDD-<hex>
                    date_str = experiment_id.split('-')[0] if '-' in experiment_id else ''

                    if not platform or not date_str:
                        continue

                    from ..remote.file_sync import sync_experiment_from_remote
                    files = await sync_experiment_from_remote(
                        experiment_id, platform, date_str,
                        settings, ssh_manager, data_dir,
                    )

                    if files:
                        # Update DB status
                        output_meta = __import__('os').path.join(
                            data_dir, platform, date_str, experiment_id, 'output', 'meta.json'
                        )
                        new_status = 'completed' if __import__('os').path.exists(output_meta) else 'failed'
                        with get_db_connection(config) as conn:
                            from ..db.database import upsert_experiment_run
                            upsert_experiment_run(conn, {
                                'experiment_id': experiment_id,
                                'status': new_status,
                                'report_available': new_status == 'completed',
                            })
                        logger.info(
                            "Auto-sync: %s → %s (%d files)",
                            experiment_id, new_status, len(files),
                        )
            except Exception as _inner:
                logger.debug("Background sync inner error (non-fatal): %s", _inner)

        except Exception as _outer:
            logger.debug("Background sync outer error (non-fatal): %s", _outer)

        try:
            from .config import get_remote_settings as _gs
            interval = _gs().sync_interval or 30
        except Exception:
            interval = 30
        await asyncio.sleep(interval)
