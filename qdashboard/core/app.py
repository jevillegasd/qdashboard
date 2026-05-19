"""
Core FastAPI application configuration and setup.
"""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
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

    app = FastAPI(title="QDashboard", docs_url=None, redoc_url=None)

    # Store config in app state for access via request.app.state.config
    app.state.config = config or {}

    # Mount static files at /assets
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    # Set up Jinja2 templates with custom filters
    templates = Jinja2Templates(directory=templates_dir)
    templates.env.filters["size_fmt"] = size_fmt
    templates.env.filters["time_fmt"] = time_desc
    templates.env.filters["data_fmt"] = data_fmt
    templates.env.filters["icon_fmt"] = icon_fmt
    templates.env.filters["humanize"] = time_humanize

    logger.debug("App module initialized")

    return app


def get_config():
    """Get application configuration from environment variables."""
    from .config import get_config as _get_config
    return _get_config()
