# QDashboard — Copilot Instructions

QDashboard is a **FastAPI/Uvicorn-based web dashboard** for quantum computing workflows built around the [Qibo](https://github.com/qiboteam/qibo) stack. It is used by quantum researchers and engineers at TII to browse experiment files, monitor QPU/SLURM status, submit calibration jobs, and view qibocal reports.

## Architecture

```
qdashboard/
├── core/           # FastAPI app factory (app.py) + centralized config (config.py)
├── web/            # All routes (~25 endpoints in routes.py), file browser, report viewer
├── qpu/            # QPU health/monitoring, SLURM queue, platform git ops, topology
├── experiments/    # Qibocal protocol discovery, job submission, runcard generation
├── utils/          # Formatters (size, time, icons), logger
├── templates/      # Jinja2 HTML templates (Bootstrap 4 dark theme)
└── assets/         # Static CSS/JS served at /assets/ (Bootstrap, jQuery, custom)
```

Key files to read before touching anything:
- [qdashboard/web/routes.py](../qdashboard/web/routes.py) — all HTTP endpoints
- [qdashboard/core/app.py](../qdashboard/core/app.py) — FastAPI factory, static files, Jinja2 setup
- [qdashboard/core/config.py](../qdashboard/core/config.py) — config constants and helpers
- [ARCHITECTURE.md](../ARCHITECTURE.md) — high-level design overview

## Tech Stack

- **Backend**: Python 3.10+, FastAPI ≥0.111, Uvicorn ≥0.29, python-multipart ≥0.0.9, aiofiles ≥23.0, PyYAML ≥6.0
- **Frontend**: Jinja2 ≥3.1 templates (SSR), Bootstrap 4.5, jQuery 3.5, Font Awesome 5
- **Quantum**: qibo ≥0.2, qibolab ==0.2.8, qibocal ≥0.2.3
- **HPC**: SLURM integration (`squeue`, `sinfo`, `sbatch` shell calls)
- **Dev tools**: black, flake8, mypy, pytest, pre-commit

## Code Conventions

- **Config access**: in routes use `request.app.state.config` (via `_get_config(request)` helper in `routes.py`); outside request context use `qdashboard.core.config.get_config()`.
- **Logging**: use the centralized logger from `qdashboard.utils.logger`; never use bare `print()`.
- **Template rendering**: all routes use `templates.get_template('name.html').render(request=request, **ctx)` returning `HTMLResponse(content=html)`. The `request` kwarg is required for Starlette's Jinja2 `url_for` injection.
- **Template filters**: `size_fmt`, `time_fmt`, `data_fmt`, `icon_fmt`, `humanize` are registered on `templates.env.filters` in `core/app.py` — use them in templates.
- **Static assets**: always reference via `url_for('assets', path='css/x.css')` in templates (not `'static'`).
- **Quantum optional deps**: guard imports with try/except and degrade gracefully when qibo/qibolab/qibocal are not installed.
- **SLURM calls**: always use `subprocess.run` with a timeout; parse stdout text, never assume specific column order.
- **Runcard format**: YAML files following the qibocal schema. Experiment IDs are `exp_<timestamp_hex>_<md5_hash>`.
- **Report asset serving**: qibocal HTML reports are rewritten by `web/reports.py` to route assets through `/report_assets/<path>`.
- **Git/platform operations**: all in `qpu/platforms.py`; the platforms repo path comes from the `QIBOLAB_PLATFORMS` env var or `~/.qdashboard/qibolab_platforms_qrc`.
- **Topology API**: support both old and new qibolab APIs (see `qpu/topology.py` for the dual-path pattern).

## Routing Patterns

New routes go in `qdashboard/web/routes.py`. Follow existing patterns:
- All handlers are `async def` functions decorated with `@router.get/post(...)`.
- JSON API responses: return a plain dict (FastAPI serializes it) or `Response(content=json.dumps(...), media_type='application/json')`.
- HTML page responses: `HTMLResponse(content=templates.get_template('x.html').render(request=request, **ctx))`.
- SSE streaming: return `StreamingResponse(async_generator(), media_type='text/event-stream')` with `await asyncio.sleep(N)` inside.
- File uploads: use `runcard: UploadFile = File(...)` parameter + `await runcard.read()`.
- Auth: check `request.headers.get('X-Auth-Key')` against config when auth key is set.

## Build & Test

```bash
# Install in dev mode
pip install -e ".[dev]"

# Run server
qdashboard --root ~/.qdashboard --port 5005

# Tests
pytest qdashboard/tests/

# Lint/format
black qdashboard/
flake8 qdashboard/
mypy qdashboard/
```

## Templates

All templates extend a shared dark theme (`dashboard.css`, `menu.css`). The sidebar navigation is duplicated across all templates — keep all nav items in sync if adding a new page. The sidebar also renders package versions via the `qibo_versions` template variable, which must be passed from every route.

## Key External Integrations

| Integration | Purpose | Module |
|---|---|---|
| SLURM | Job queue monitoring & submission | `qpu/slurm.py`, `experiments/job_submission.py` |
| qibocal | Protocol discovery, report rendering | `experiments/protocols.py`, `web/reports.py` |
| qibolab | QPU platform config & topology | `qpu/platforms.py`, `qpu/topology.py` |
| GitHub (git) | Platform repo branch management | `qpu/platforms.py` |

## Important Notes

- The SLURM partition/queue name is configured per-deployment and stored in config; don't hardcode queue names.
- qibocal protocol discovery can be slow (subprocess fallback); it is cached thread-safely in `experiments/protocols.py`.
- File browser auto-detects qibocal reports by checking for `meta.json` + `runcard.yml` in a directory.
- Topology visualization uses `rustworkx` + `matplotlib`; both are optional — degrade gracefully if not installed.
- The dashboard supports an optional authentication key (`QD_KEY` env var / `--auth-key` CLI arg).
