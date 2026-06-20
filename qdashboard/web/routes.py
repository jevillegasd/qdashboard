"""
Main application routes and endpoints.
"""

import os
import re
import subprocess
import json
import asyncio
import time
import shutil
import yaml
import traceback as _tb
from typing import Optional
from fastapi import APIRouter, Request, Form, File, UploadFile, Query, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse, RedirectResponse
from starlette.responses import HTMLResponse

from ..qpu.monitoring import get_qpu_health, get_available_qpus, get_qibo_versions, get_qpu_details, get_qpu_list, qpu_parameters
from ..qpu.platforms import get_platforms_path, list_repository_branches, switch_repository_branch, get_current_branch_info, commit_changes, push_changes, stash_changes, list_stashes, apply_latest_stash, discard_changes, get_partition
from ..qpu.slurm import get_slurm_status, get_slurm_output
from ..qpu.topology import qpu_connectivity, infer_topology_from_connectivity, generate_topology_visualization
from ..experiments.protocols import get_qibocal_protocols, get_protocol_attributes
from ..experiments import submit_experiment, repeat_experiment, get_experiment_status, list_user_experiments
from ..experiments.job_submission import find_latest_experiment
from ..web.reports import get_latest_report_path, get_report_fragment, check_qibocal_availability
from ..utils.formatters import yaml_response, json_response
from qdashboard.utils.logger import get_logger
from packaging.version import parse as parse_version

logger = get_logger(__name__)

router = APIRouter()


def _get_config(request: Request) -> dict:
    """Helper to retrieve config from app state."""
    return request.app.state.config


def _no_cache_headers() -> dict:
    return {
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'Expires': '0',
    }


def _error_response(
    request: Request,
    exc: Exception,
    body: dict = None,
    status_code: int = 500,
) -> Response:
    """Build a JSON error response.

    In debug mode the full traceback, exception type, and request context are
    included so problems can be diagnosed directly in the browser / API client.
    In production only the safe error message is returned.
    """
    debug = request.app.state.config.get('debug', False)
    trace = _tb.format_exc()
    logger.error("[%s %s] %s: %s\n%s",
                 request.method, request.url.path,
                 type(exc).__name__, exc, trace)
    if body is None:
        body = {'error': str(exc)}
    if debug:
        body['exception_type'] = type(exc).__name__
        body['traceback'] = trace
        body['request'] = f"{request.method} {request.url}"
    return Response(
        content=json.dumps(body),
        status_code=status_code,
        media_type='application/json',
    )


def _html_error_response(
    request: Request,
    exc: Exception,
    status_code: int = 500,
) -> HTMLResponse:
    """Render the themed error page for a caught exception (see core.app.render_error_page).

    Prefer `raise HTTPException(...)` where possible — the app-wide handler
    in core/app.py renders the same page automatically. This is for routes
    that want to keep handling the request after catching the exception
    rather than letting it propagate.
    """
    from ..core.app import render_error_page
    debug = request.app.state.config.get('debug', False)
    trace = _tb.format_exc()
    logger.error("[%s %s] %s: %s\n%s",
                 request.method, request.url.path,
                 type(exc).__name__, exc, trace)
    return render_error_page(
        request, status_code,
        message=str(exc) if debug else None,
        trace=trace if debug else None,
    )


def _safe_path_join(base: str, user_path: str) -> str | None:
    """Return realpath of user_path relative to base, or None if it escapes base."""
    resolved_base = os.path.realpath(base)
    candidate = os.path.realpath(os.path.join(base, user_path))
    if candidate != resolved_base and not candidate.startswith(resolved_base + os.sep):
        return None
    return candidate


# Keys in experiment metadata dicts that hold absolute filesystem paths.
# These must never be forwarded to the frontend.
_FS_PATH_KEYS = frozenset({
    'output_dir', 'experiment_dir', 'runcard_path', 'job_script_path',
    'original_report_path', 'metadata', 'output_files', 'temp_dir',
})


def _sanitize_exp(data: dict) -> dict:
    """Return a copy of *data* with all absolute filesystem path keys removed."""
    return {k: v for k, v in data.items() if k not in _FS_PATH_KEYS}


def register_routes(app, config):
    """Register the APIRouter on the FastAPI app."""
    app.include_router(router)
    logger.debug("Routes module initialized")
    return app


@router.get("/", name="shell", include_in_schema=False)
@router.get("/experiments", name="experiments", include_in_schema=False)
async def shell(request: Request):
    """VS Code-style app shell: activity bar + side panel + tab strip.

    Gathers the data for every singleton tab/panel (Slurm Monitor, QPU Status,
    Action Card Builder, Explorer, Experiment Library, History) in one go,
    since shell.html renders all of them once and toggles visibility in JS
    rather than fetching each on demand.
    """
    from ..core.app import templates

    version_data = get_qibo_versions(request=request)

    # Slurm Monitor tab
    qpu_health = get_qpu_health()
    available_qpus = get_available_qpus()
    slurm_queue_status = get_slurm_status()
    last_slurm_log = get_slurm_output()

    # QPU Status tab
    config = _get_config(request)
    qpu_details = get_qpu_details()
    platforms_path = get_platforms_path(config['root'])
    git_branches_info = list_repository_branches(platforms_path) if platforms_path else None
    git_current_branch_info = get_current_branch_info(platforms_path) if platforms_path else None

    # Action Card Builder tab + Experiment Library panel
    protocols = get_qibocal_protocols()
    qpus_list = get_qpu_list()
    qibolab_version = version_data['versions'].get('qibolab', '0.0.0')
    is_new_qibolab = parse_version(qibolab_version) > parse_version('0.2.0')
    protocols_with_attributes = {}
    for category, protocol_list in protocols.items():
        protocols_with_attributes[category] = []
        for protocol in protocol_list:
            protocol_attrs = get_protocol_attributes(protocol)
            protocol_with_attrs = protocol.copy()
            protocol_with_attrs['attributes'] = protocol_attrs
            protocols_with_attributes[category].append(protocol_with_attrs)

    # History panel (the distinct-QPUs query, when available, also refines the
    # `qpus` list shared with the Action Card Builder's QPU selector)
    history_protocols = []
    try:
        from ..db.database import get_db_connection, get_distinct_protocols, get_distinct_qpus
        with get_db_connection(config) as conn:
            history_protocols = get_distinct_protocols(conn)
            qpus_list = get_distinct_qpus(conn) or qpus_list
    except Exception:
        pass

    logger.info("Shell loaded (Slurm/QPU/Action-builder tabs + Explorer/Library/History panels)")

    html = templates.get_template('shell.html').render(
        request=request,
        qibo_versions=version_data['versions'],
        # Slurm Monitor
        qpu_health=qpu_health,
        available_qpus=available_qpus,
        slurm_queue_status=slurm_queue_status,
        last_slurm_log=last_slurm_log,
        # QPU Status
        qpu_details=qpu_details,
        git_branch=git_current_branch_info['branch'] if git_current_branch_info else None,
        git_commit=git_current_branch_info['commit'] if git_current_branch_info else None,
        platforms_path=platforms_path,
        branches_info=git_branches_info,
        current_branch_info=git_current_branch_info,
        # Action Card Builder + Experiment Library
        protocols=protocols_with_attributes,
        qpus=qpus_list,
        is_new_qibolab=is_new_qibolab,
        # History
        history_protocols=history_protocols,
    )
    response = HTMLResponse(content=html, headers=_no_cache_headers())
    if not version_data.get('from_cache', False):
        response.set_cookie('qibo_versions', version_data['cookie_data'],
                            max_age=24 * 60 * 60, httponly=True, secure=False)
    return response


_QPU_NAME_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')


@router.get("/qqsubmit", name="qqsubmit", include_in_schema=False)
async def qqsubmit(request: Request, qpu: Optional[str] = Query(None)):
    """Submit a job to the SLURM queue."""
    from ..core.app import templates

    if not qpu or not _QPU_NAME_RE.match(qpu):
        logger.warning(f"Invalid QPU name rejected: {qpu!r}")
        raise HTTPException(400, detail='Invalid QPU name')

    config = _get_config(request)
    script_path = os.path.realpath(os.path.join(config['root'], "work/qqsubmit.sh"))
    resolved_root = os.path.realpath(config['root'])
    if not script_path.startswith(resolved_root + os.sep) and script_path != resolved_root:
        logger.error(f"Script path escapes root: {script_path}")
        raise HTTPException(403, detail='Forbidden')

    os_process = subprocess.Popen(
        ["bash", script_path, config['home_path'], qpu],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        stdout, stderr = os_process.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        os_process.kill()
        os_process.communicate()
        logger.error(f"qqsubmit timed out for QPU: {qpu}")
        raise HTTPException(504, detail='Job submission timed out')
    out_string = stdout.decode('utf-8', errors='replace').replace('\n', '<br>')
    logger.info(f"Job submitted to SLURM queue for QPU: {qpu}")
    html = templates.get_template('job_submission.html').render(
        request=request, output_content=out_string)
    return HTMLResponse(content=html)


@router.get("/latest_report_page", name="latest_report_page", include_in_schema=False)
async def latest_report_page(request: Request):
    """Resolve the latest report to an experiment_id and hand off to the
    iframe-friendly /experiment_report_page/{id} route, so "Latest Report"
    can open as a shell tab instead of navigating to the full /latest page."""
    last_path = get_latest_report_path()
    if not last_path:
        raise HTTPException(404, detail='No reports yet — run an experiment first.')
    # last_path follows the same data_dir/<platform>/<date>/<experiment_id>/output
    # convention as experiment_report_page's glob match.
    experiment_id = os.path.basename(os.path.dirname(last_path.rstrip('/')))
    return RedirectResponse(url=f"/experiment_report_page/{experiment_id}", status_code=307)


@router.post("/cancel_job", name="cancel_job", tags=["SLURM"],
             summary="Cancel a SLURM job")
async def cancel_job(request: Request):
    """Cancel a SLURM job."""
    try:
        data = await request.json()
        job_id = data.get('job_id')
        if job_id:
            result = subprocess.run(['scancel', str(job_id)],
                                    capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                logger.info(f"Job {job_id} cancelled successfully")
                return {'status': 'success', 'message': f'Job {job_id} cancelled'}
            else:
                logger.error(f"Failed to cancel job {job_id}: {result.stderr}")
                return {'status': 'error', 'message': f'Failed to cancel job: {result.stderr}'}
        logger.warning("No job ID provided for cancellation")
        return {'status': 'error', 'message': 'No job ID provided'}
    except subprocess.TimeoutExpired:
        return _error_response(request, TimeoutError('Cancel command timed out'),
                               {'status': 'error', 'message': 'Cancel command timed out'})
    except Exception as e:
        return _error_response(request, e, {'status': 'error', 'message': str(e)})


@router.get("/api/slurm_status", name="api_slurm_status", tags=["SLURM"],
            summary="Snapshot of the current SLURM queue and last log")
async def api_slurm_status(request: Request):
    """API endpoint to get fresh SLURM status data."""
    try:
        slurm_queue_status = get_slurm_status()
        last_slurm_log = get_slurm_output()
        logger.info("Fresh SLURM status data retrieved via API")
        data = {
            'status': 'success',
            'queue_status': [
                {
                    'job_id': job.job_id, 'name': job.name, 'user': job.user,
                    'state': job.state, 'time': job.time, 'time_limit': job.time_limit,
                    'nodes': job.nodes, 'nodelist': job.nodelist,
                    'is_current_user': job.is_current_user
                } for job in slurm_queue_status
            ],
            'last_log': last_slurm_log,
        }
        return Response(content=json.dumps(data), media_type='application/json',
                        headers=_no_cache_headers())
    except Exception as e:
        return _error_response(request, e, {'status': 'error', 'message': str(e)})


@router.get("/api/slurm_stream", name="api_slurm_stream", tags=["SLURM"],
            summary="Server-Sent Events stream of live SLURM queue updates")
async def api_slurm_stream(request: Request):
    """Server-Sent Events endpoint for streaming SLURM status updates."""
    async def slurm_event_stream():
        last_data = None
        last_log = None
        try:
            while True:
                try:
                    slurm_queue_status = get_slurm_status()
                    current_log = get_slurm_output()
                    queue_status = [
                        {
                            'job_id': job.job_id, 'name': job.name, 'user': job.user,
                            'state': job.state, 'time': job.time, 'time_limit': job.time_limit,
                            'nodes': job.nodes, 'nodelist': job.nodelist,
                            'is_current_user': job.is_current_user
                        } for job in slurm_queue_status
                    ]
                    current_data = json.dumps(queue_status, sort_keys=True)
                    if current_data != last_data or current_log != last_log:
                        last_data = current_data
                        last_log = current_log
                        event_data = {
                            'queue_status': queue_status,
                            'last_log': current_log,
                            'timestamp': time.time(),
                        }
                        yield f"data: {json.dumps(event_data)}\n\n"
                except Exception as e:
                    trace = _tb.format_exc() if request.app.state.config.get('debug') else None
                    payload = {'error': str(e), 'timestamp': time.time()}
                    if trace:
                        payload['traceback'] = trace
                    logger.warning(f"Error in SLURM stream: {str(e)}")
                    yield f"data: {json.dumps(payload)}\n\n"
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            logger.info("Client disconnected from SLURM stream")

    logger.info("SLURM stream connection established")
    return StreamingResponse(
        slurm_event_stream(),
        media_type='text/event-stream',
        headers={**_no_cache_headers(), 'X-Accel-Buffering': 'no'},
    )


@router.get("/qpus", name="qpus", include_in_schema=False)
async def qpus(request: Request):
    """QPU Status is now a tab inside the shell — redirect there, opening it."""
    return RedirectResponse(url="/?open=qpu_status", status_code=307)


@router.get("/api/platforms/branches", name="api_platforms_branches", tags=["Platforms"],
            summary="List all branches in the platforms repository")
async def api_platforms_branches(request: Request):
    """API endpoint to get available branches."""
    try:
        config = _get_config(request)
        platforms_path = get_platforms_path(config['root'])
        if not platforms_path:
            return Response(content=json.dumps({'error': 'Platforms directory not available'}),
                            status_code=404, media_type='application/json')
        branches_info = list_repository_branches(platforms_path)
        if not branches_info:
            return Response(content=json.dumps({'error': 'Failed to retrieve branch information'}),
                            status_code=500, media_type='application/json')
        return branches_info
    except Exception as e:
        return _error_response(request, e)


@router.post("/api/platforms/switch", name="api_platforms_switch", tags=["Platforms"],
             summary="Switch the platforms repository to a different branch")
async def api_platforms_switch(request: Request):
    """API endpoint to switch platform branch."""
    try:
        config = _get_config(request)
        data = await request.json()
        if not data or 'branch' not in data:
            return Response(content=json.dumps({'error': 'Branch name is required'}),
                            status_code=400, media_type='application/json')
        branch_name = data['branch']
        create_if_not_exists = data.get('create', False)
        handle_changes = data.get('handle_changes', 'fail')
        platforms_path = get_platforms_path(config['root'])
        if not platforms_path:
            return Response(content=json.dumps({'error': 'Platforms directory not available'}),
                            status_code=404, media_type='application/json')
        switch_result = switch_repository_branch(platforms_path, branch_name, create_if_not_exists, handle_changes)
        if not switch_result['success']:
            return Response(
                content=json.dumps({
                    'error': switch_result.get('error', f'Failed to switch to branch: {branch_name}'),
                    'has_changes': switch_result.get('has_changes', False),
                }),
                status_code=400, media_type='application/json')
        current_branch_info = get_current_branch_info(platforms_path)
        qpu_details = get_qpu_details()
        response_data = {
            'success': True, 'branch': branch_name,
            'branch_info': current_branch_info, 'qpus': qpu_details,
            'platforms_path': platforms_path,
        }
        if switch_result.get('changes_handled') == 'stashed':
            response_data['stash_created'] = switch_result.get('stash_created')
            response_data['changes_handled'] = 'stashed'
        if switch_result.get('stash_restored'):
            response_data['stash_applied'] = switch_result.get('stash_applied')
            response_data['stash_restored'] = True
        logger.info(f"Switched to branch: {branch_name}")
        return response_data
    except Exception as e:
        return _error_response(request, e)


@router.get("/api/platforms/current", name="api_platforms_current", tags=["Platforms"],
            summary="Get the currently checked-out branch and its metadata")
async def api_platforms_current(request: Request):
    """API endpoint to get current branch information."""
    try:
        config = _get_config(request)
        platforms_path = get_platforms_path(config['root'])
        if not platforms_path:
            return Response(content=json.dumps({'error': 'Platforms directory not available'}),
                            status_code=404, media_type='application/json')
        current_branch_info = get_current_branch_info(platforms_path)
        if not current_branch_info:
            return Response(content=json.dumps({'error': 'Failed to get current branch information'}),
                            status_code=500, media_type='application/json')
        return current_branch_info
    except Exception as e:
        return _error_response(request, e)


@router.post("/api/platforms/commit", name="api_platforms_commit", tags=["Platforms"],
             summary="Commit pending changes in the platforms repository")
async def api_platforms_commit(request: Request):
    """API endpoint to commit changes to the platforms repository."""
    try:
        config = _get_config(request)
        platforms_path = get_platforms_path(config['root'])
        if not platforms_path:
            return Response(content=json.dumps({'error': 'Platforms directory not available'}),
                            status_code=404, media_type='application/json')
        data = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        commit_message = data.get('message', 'Update platform configurations (qibolab version detection)')
        result = commit_changes(platforms_path, commit_message)
        if not result['success']:
            return Response(content=json.dumps({'error': result.get('error', 'Commit failed')}),
                            status_code=400, media_type='application/json')
        return result
    except Exception as e:
        return _error_response(request, e)


@router.post("/api/platforms/stash", name="api_platforms_stash", tags=["Platforms"],
             summary="Stash uncommitted changes in the platforms repository")
async def api_platforms_stash(request: Request):
    """API endpoint to stash changes in the platforms repository."""
    try:
        config = _get_config(request)
        platforms_path = get_platforms_path(config['root'])
        if not platforms_path:
            return Response(content=json.dumps({'error': 'Platforms directory not available'}),
                            status_code=404, media_type='application/json')
        data = await request.json() if request.headers.get('content-type', '').startswith('application/json') else {}
        stash_message = data.get('message', 'WIP: Stashed via QDashboard')
        result = stash_changes(platforms_path, stash_message)
        if not result['success']:
            return Response(content=json.dumps({'error': result.get('error', 'Stash failed')}),
                            status_code=400, media_type='application/json')
        return result
    except Exception as e:
        return _error_response(request, e)


@router.post("/api/platforms/discard", name="api_platforms_discard", tags=["Platforms"],
             summary="Discard all uncommitted changes in the platforms repository")
async def api_platforms_discard(request: Request):
    """API endpoint to discard all uncommitted changes."""
    try:
        config = _get_config(request)
        platforms_path = get_platforms_path(config['root'])
        if not platforms_path:
            return Response(content=json.dumps({'error': 'Platforms directory not available'}),
                            status_code=404, media_type='application/json')
        result = discard_changes(platforms_path)
        if not result['success']:
            return Response(content=json.dumps({'error': result.get('error', 'Discard failed')}),
                            status_code=400, media_type='application/json')
        return result
    except Exception as e:
        return _error_response(request, e)


@router.get("/api/platforms/stashes", name="api_platforms_list_stashes", tags=["Platforms"],
            summary="List all stash entries in the platforms repository")
async def api_platforms_list_stashes(request: Request):
    """API endpoint to list all stashes."""
    try:
        config = _get_config(request)
        platforms_path = get_platforms_path(config['root'])
        if not platforms_path:
            return Response(content=json.dumps({'error': 'Platforms directory not available'}),
                            status_code=404, media_type='application/json')
        result = list_stashes(platforms_path)
        if not result['success']:
            return Response(content=json.dumps({'error': result.get('error', 'Failed to list stashes')}),
                            status_code=400, media_type='application/json')
        return result
    except Exception as e:
        return _error_response(request, e)


@router.post("/api/platforms/push", name="api_platforms_push", tags=["Platforms"],
             summary="Push the current branch to the remote platforms repository")
async def api_platforms_push(request: Request):
    """API endpoint to push changes to the remote repository."""
    try:
        config = _get_config(request)
        platforms_path = get_platforms_path(config['root'])
        if not platforms_path:
            return Response(content=json.dumps({'error': 'Platforms directory not available'}),
                            status_code=404, media_type='application/json')
        result = push_changes(platforms_path)
        if not result['success']:
            return Response(content=json.dumps({'error': result.get('error', 'Push failed')}),
                            status_code=400, media_type='application/json')
        return result
    except Exception as e:
        return _error_response(request, e)


@router.get("/api/protocols", name="api_protocols", tags=["Protocols"],
            summary="List all available qibocal calibration protocols grouped by category")
async def api_protocols():
    """API endpoint to get all available protocols."""
    protocols = get_qibocal_protocols()
    jsonifiable_protocols = {}
    for category in protocols:
        jsonifiable_protocols[category] = {
            item['name']: {
                'id': item['id'], 'class_name': item['class_name'],
                'module_name': item['module_name'], 'module_path': item['module_path'],
            } for item in protocols[category]
        }
    logger.info(f"Protocols retrieved successfully: {jsonifiable_protocols}")
    return jsonifiable_protocols


@router.get("/api/protocols/{protocol_id}", name="api_protocol_details", tags=["Protocols"],
            summary="Get the parameter schema for a single qibocal protocol")
async def api_protocol_details(protocol_id: str):
    """API endpoint to get details of a specific protocol."""
    try:
        attributes = get_protocol_attributes(protocol_id)
        return attributes
    except Exception as e:
        logger.warning(f"Protocol not found: {protocol_id}")
        return Response(content=json.dumps({'error': 'Protocol not found'}),
                        status_code=404, media_type='application/json')


@router.get("/api/qpu_parameters/{platform}", name="qpu_parameters_api", tags=["QPU"],
            summary="Retrieve gate parameters for a specific QPU platform")
async def qpu_parameters_api(platform: str):
    """API endpoint to get parameters for a specific QPU."""
    platform_params = qpu_parameters(platform)
    logger.info(f"QPU parameters retrieved for platform: {platform}")
    return platform_params


@router.get("/api/qpu_topology/{platform}", name="qpu_topology_visualization_api", tags=["QPU"],
            summary="Generate a base-64 topology graph image for a QPU platform")
async def qpu_topology_visualization_api(request: Request, platform: str):
    """API endpoint to generate topology visualization for a specific QPU."""
    config = _get_config(request)
    qrc_path = get_platforms_path(config['root'])
    if not qrc_path:
        return Response(content=json.dumps({'error': 'QPU platforms directory not available'}),
                        status_code=404, media_type='application/json')
    qpu_path = _safe_path_join(qrc_path, platform)
    if qpu_path is None or not os.path.exists(qpu_path):
        return Response(content=json.dumps({'error': 'QPU not found'}),
                        status_code=404, media_type='application/json')
    connectivity_data = qpu_connectivity(platform)
    if not connectivity_data:
        return Response(content=json.dumps({'error': 'No connectivity data found for this QPU'}),
                        status_code=404, media_type='application/json')
    topology_type = infer_topology_from_connectivity(connectivity_data)
    if topology_type in ('N/A', 'unknown'):
        return Response(content=json.dumps({'error': 'Could not determine topology type'}),
                        status_code=404, media_type='application/json')
    try:
        img_base64 = generate_topology_visualization(connectivity_data, topology_type)
    except Exception as e:
        return _error_response(request, e,
                               {'error': 'Failed to generate topology visualization'})
    return {
        'topology_type': topology_type,
        'num_qubits': len(set([q for conn in connectivity_data for q in conn[:2]])),
        'num_connections': len(connectivity_data),
        'image': img_base64,
    }


@router.get("/api/qpu_qubits/{platform}", name="qpu_qubits_api", tags=["QPU"],
            summary="List the qubits available on a QPU platform")
async def qpu_qubits_api(request: Request, platform: str):
    """API endpoint to get the list of available qubits for a specific QPU."""
    config = _get_config(request)
    qrc_path = get_platforms_path(config['root'])
    if not qrc_path:
        return Response(content=json.dumps({'error': 'QPU platforms directory not available'}),
                        status_code=404, media_type='application/json')
    qpu_path = _safe_path_join(qrc_path, platform)
    if qpu_path is None or not os.path.exists(qpu_path):
        return Response(content=json.dumps({'error': 'QPU not found'}),
                        status_code=404, media_type='application/json')

    def qubit_sort_key(qubit):
        if isinstance(qubit, (int, float)):
            return (0, qubit)
        try:
            return (0, int(qubit))
        except (ValueError, TypeError):
            return (1, str(qubit))

    connectivity_data = qpu_connectivity(platform)
    if connectivity_data:
        raw_qubits = list(set([q for conn in connectivity_data for q in conn[:2]]))
        qubits = sorted(raw_qubits, key=qubit_sort_key)
    else:
        params = qpu_parameters(platform)
        sq_gates = params.get('single_qubit_gates', {}) if params else {}
        all_qubits = set()
        for gate_qubits in sq_gates.values():
            all_qubits.update(gate_qubits)
        if not all_qubits:
            return Response(content=json.dumps({'error': 'No qubit data found for this QPU'}),
                            status_code=404, media_type='application/json')
        qubits = sorted(all_qubits, key=qubit_sort_key)

    return {'qubits': qubits, 'num_qubits': len(qubits)}


@router.get("/api/qpu_calibration/{platform}", name="qpu_calibration_api", tags=["QPU"],
            summary="Return the calibration.json data for a QPU platform")
async def qpu_calibration_api(request: Request, platform: str):
    """API endpoint to get calibration data for a specific QPU."""
    config = _get_config(request)
    platforms_path = get_platforms_path(config['root'])
    if not platforms_path:
        return Response(content=json.dumps({'error': 'QPU platforms directory not available'}),
                        status_code=404, media_type='application/json')
    calibration_path = _safe_path_join(platforms_path, os.path.join(platform, 'calibration.json'))
    if calibration_path and os.path.exists(calibration_path):
        with open(calibration_path, 'r') as f:
            calibration_data = json.load(f)
        return calibration_data
    return Response(content=json.dumps({'error': 'Calibration data not found'}),
                    status_code=404, media_type='application/json')


def _action_nodes_path(config: dict, platform: str) -> str | None:
    """Return the path to the action_nodes.json file for a QPU platform, or None if invalid."""
    qrc_path = get_platforms_path(config['root'])
    if not qrc_path:
        return None
    qpu_path = _safe_path_join(qrc_path, platform)
    if qpu_path is None or not os.path.isdir(qpu_path):
        return None
    return os.path.join(qpu_path, 'action_nodes.json')


def _load_action_nodes(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, 'r') as f:
        return json.load(f)


@router.get("/api/action_nodes/{platform}", name="api_action_nodes_list", tags=["Experiments"],
            summary="List saved action nodes for a QPU platform")
async def api_action_nodes_list(request: Request, platform: str):
    """Return all saved action nodes for a QPU platform."""
    config = _get_config(request)
    path = _action_nodes_path(config, platform)
    if path is None:
        return Response(content=json.dumps({'error': 'QPU not found'}),
                        status_code=404, media_type='application/json')
    try:
        return {'nodes': _load_action_nodes(path)}
    except Exception as e:
        return _error_response(request, e, {'error': str(e)})


@router.post("/api/action_nodes/{platform}", name="api_action_nodes_save", tags=["Experiments"],
             summary="Save (or rename into) an action node for a QPU platform")
async def api_action_nodes_save(request: Request, platform: str):
    """Create or overwrite a saved action node for a QPU platform."""
    config = _get_config(request)
    path = _action_nodes_path(config, platform)
    if path is None:
        return Response(content=json.dumps({'success': False, 'error': 'QPU not found'}),
                        status_code=404, media_type='application/json')
    try:
        body = await request.json()
        node_name = (body.get('node_name') or '').strip()
        action_card = body.get('action_card')
        if not node_name:
            return Response(content=json.dumps({'success': False, 'error': 'node_name is required'}),
                            status_code=400, media_type='application/json')
        if not isinstance(action_card, list):
            return Response(content=json.dumps({'success': False, 'error': 'action_card must be a list'}),
                            status_code=400, media_type='application/json')

        nodes = _load_action_nodes(path)
        nodes[node_name] = {'action_card': action_card}
        with open(path, 'w') as f:
            json.dump(nodes, f, indent=2)
        return {'success': True, 'nodes': nodes}
    except Exception as e:
        return _error_response(request, e, {'success': False, 'error': str(e)})


@router.delete("/api/action_nodes/{platform}/{node_name}", name="api_action_nodes_delete", tags=["Experiments"],
               summary="Delete a saved action node for a QPU platform")
async def api_action_nodes_delete(request: Request, platform: str, node_name: str):
    """Delete a saved action node for a QPU platform."""
    config = _get_config(request)
    path = _action_nodes_path(config, platform)
    if path is None:
        return Response(content=json.dumps({'success': False, 'error': 'QPU not found'}),
                        status_code=404, media_type='application/json')
    try:
        nodes = _load_action_nodes(path)
        if node_name not in nodes:
            return Response(content=json.dumps({'success': False, 'error': 'Action node not found'}),
                            status_code=404, media_type='application/json')
        del nodes[node_name]
        with open(path, 'w') as f:
            json.dump(nodes, f, indent=2)
        return {'success': True, 'nodes': nodes}
    except Exception as e:
        return _error_response(request, e, {'success': False, 'error': str(e)})


@router.post("/qibocal/{action}", name="qibocal_cli_action", tags=["Experiments"],
             summary="Run a qibocal CLI action (fit / report / update) on an existing report")
async def qibocal_cli_action(request: Request, action: str,
                              report_path: str = Form(...)):
    """Execute qibocal CLI commands."""
    config = _get_config(request)
    full_report_path = _safe_path_join(config.get('data_dir', config['root']), report_path)
    if full_report_path is None:
        logger.warning(f"Path traversal attempt in qibocal_cli_action: {report_path!r}")
        return Response(content=json.dumps({'success': False,
                        'message': 'Invalid report path'}),
                        status_code=400, media_type='application/json')
    if not os.path.exists(full_report_path):
        return Response(content=json.dumps({'success': False,
                        'message': f'Report path does not exist: {report_path}'}),
                        status_code=404, media_type='application/json')
    if not (os.path.exists(os.path.join(full_report_path, 'meta.json')) and
            os.path.exists(os.path.join(full_report_path, 'runcard.yml'))):
        return Response(content=json.dumps({'success': False,
                        'message': f'Path is not a valid qibocal report: {report_path}'}),
                        status_code=400, media_type='application/json')
    valid_actions = ['fit', 'report', 'update']
    if action not in valid_actions:
        return Response(content=json.dumps({'success': False,
                        'message': f'Invalid action: {action}'}),
                        status_code=400, media_type='application/json')
    try:
        if not check_qibocal_availability():
            return Response(content=json.dumps({'success': False,
                            'message': 'Qibocal CLI (qq) is not available.'}),
                            status_code=503, media_type='application/json')
        cmd = ['qq', action, full_report_path]
        if action == 'fit':
            cmd.append('-f')
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                                cwd=full_report_path)
        if result.returncode == 0:
            success_messages = {'fit': 'Fit completed.', 'report': 'Report regenerated.',
                                'update': 'Platform updated.'}
            return {'success': True, 'message': success_messages[action],
                    'stdout': result.stdout, 'stderr': result.stderr}
        error_msg = f"Qibocal {action} failed (exit {result.returncode}): {result.stderr}"
        return Response(content=json.dumps({'success': False, 'message': error_msg,
                        'stdout': result.stdout, 'stderr': result.stderr}),
                        status_code=500, media_type='application/json')
    except subprocess.TimeoutExpired:
        return Response(content=json.dumps({'success': False,
                        'message': f'Qibocal {action} timed out (5 minutes)'}),
                        status_code=408, media_type='application/json')
    except Exception as e:
        return _error_response(request, e,
                               {'success': False, 'message': f'Error executing qibocal {action}: {str(e)}'})


@router.post("/repeat_experiment", name="repeat_experiment_route", tags=["Experiments"],
             summary="Re-submit an existing experiment runcard to SLURM")
async def repeat_experiment_route(request: Request,
                                   report_path: str = Form(...)):
    """Repeat an experiment by submitting it to SLURM."""
    try:
        config = _get_config(request)
        safe = _safe_path_join(config.get('data_dir', config['root']), report_path)
        if safe is None:
            logger.warning(f"Path traversal attempt in repeat_experiment_route: {report_path!r}")
            return Response(content=json.dumps({'success': False,
                            'message': 'Invalid report path'}),
                            status_code=400, media_type='application/json')
        result = repeat_experiment(safe, config)
        if result['success']:
            logger.info(f"Experiment repeat submitted: {result['experiment_id']}")
            return _sanitize_exp(result)
        logger.error(f"Failed to repeat experiment: {result['message']}")
        return Response(content=json.dumps(_sanitize_exp(result)), status_code=400,
                        media_type='application/json')
    except Exception as e:
        return _error_response(request, e,
                               {'success': False, 'message': f'Error repeating experiment: {str(e)}'})


@router.post("/submit_experiment", name="submit_experiment_route", tags=["Experiments"],
             summary="Submit a new experiment to SLURM via an uploaded YAML runcard")
async def submit_experiment_route(request: Request,
                                   runcard: UploadFile = File(...),
                                   environment: Optional[str] = Form(None)):
    """Submit a new experiment to SLURM via uploaded runcard file."""
    import tempfile
    try:
        config = _get_config(request)
        if not runcard.filename:
            return Response(content=json.dumps({'success': False,
                            'message': 'No runcard file selected'}),
                            status_code=400, media_type='application/json')
        runcard_content = (await runcard.read()).decode('utf-8')
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as tmp:
            tmp.write(runcard_content)
            tmp_path = tmp.name
        try:
            result = submit_experiment(tmp_path, config, environment)
            if result['success']:
                logger.info(f"New experiment submitted: {result['experiment_id']}")
                return _sanitize_exp(result)
            return Response(content=json.dumps(_sanitize_exp(result)), status_code=400,
                            media_type='application/json')
        finally:
            os.unlink(tmp_path)
    except Exception as e:
        return _error_response(request, e,
                               {'success': False, 'message': f'Error submitting experiment: {str(e)}'})


@router.post("/api/submit_experiment_data", name="submit_experiment_data_route", tags=["Experiments"],
             summary="Submit a new experiment to SLURM using a JSON runcard payload")
async def submit_experiment_data_route(request: Request):
    """Submit a new experiment to SLURM using runcard data (JSON body)."""
    try:
        config = _get_config(request)
        if not request.headers.get('content-type', '').startswith('application/json'):
            return Response(content=json.dumps({'success': False,
                            'message': 'Request must be JSON'}),
                            status_code=400, media_type='application/json')
        data = await request.json()
        if not data:
            return Response(content=json.dumps({'success': False, 'message': 'No data provided'}),
                            status_code=400, media_type='application/json')
        runcard_data = data.get('runcard_data')
        environment = data.get('environment')
        auto_update = data.get('auto_update', True)
        if not runcard_data:
            return Response(content=json.dumps({'success': False,
                            'message': 'No runcard_data provided'}),
                            status_code=400, media_type='application/json')
        if 'platform' not in runcard_data:
            return Response(content=json.dumps({'success': False,
                            'message': 'Missing required field: platform'}),
                            status_code=400, media_type='application/json')
        result = submit_experiment(runcard_data=runcard_data, config=config, environment=environment,
                                   auto_update=auto_update)
        if result['success']:
            logger.info(f"New experiment submitted with data: {result['experiment_id']}")
            return _sanitize_exp(result)
        return Response(content=json.dumps(_sanitize_exp(result)), status_code=400,
                        media_type='application/json')
    except Exception as e:
        return _error_response(request, e,
                               {'success': False, 'message': f'Error submitting experiment: {str(e)}'})


@router.get("/api/experiments", name="api_list_experiments", tags=["Experiments"],
            summary="List all submitted experiments")
async def api_list_experiments(request: Request):
    """API endpoint to list user experiments."""
    try:
        config = _get_config(request)
        experiments = list_user_experiments(config)
        safe = [_sanitize_exp(e) for e in experiments]
        return {'success': True, 'experiments': safe, 'count': len(safe)}
    except Exception as e:
        return _error_response(request, e,
                               {'success': False, 'message': f'Error listing experiments: {str(e)}'})


# ------------------------------------------------------------------ #
# Latest experiment for a given protocol/platform/qubits              #
# ------------------------------------------------------------------ #

@router.get("/api/experiments/latest", name="api_experiments_latest", tags=["Experiments"],
            summary="Find the most recent completed experiment for a protocol on a platform/qubits")
async def api_experiments_latest(
    request: Request,
    platform: str = Query(...),
    protocol: str = Query(...),
    qubits: str = Query(""),
):
    """Return metadata for the latest completed experiment matching the filters."""
    try:
        config = _get_config(request)
        qubit_list = [q.strip() for q in qubits.split(',') if q.strip()] if qubits else []
        result = find_latest_experiment(platform, protocol, qubit_list, config)
        if result is None:
            return Response(content=json.dumps({'found': False}),
                            status_code=404, media_type='application/json')
        data_dir = config.get('data_dir', os.path.join(config.get('root', ''), 'data'))
        abs_output = result.get('output_dir', '')
        rel = os.path.relpath(os.path.realpath(abs_output), os.path.realpath(data_dir)) if abs_output else ''
        result['report_url'] = '/files/' + rel if rel else ''
        return {'found': True, **_sanitize_exp(result)}
    except Exception as e:
        return _error_response(request, e, {'found': False, 'error': str(e)})


@router.get("/api/experiments/{experiment_id}", name="api_experiment_status", tags=["Experiments"],
            summary="Get the status and metadata of a single experiment")
async def api_experiment_status(request: Request, experiment_id: str):
    """API endpoint to get experiment status."""
    try:
        config = _get_config(request)
        status = get_experiment_status(experiment_id, config)
        if status:
            # Attach a web-accessible report_url derived from output_dir
            output_dir = status.get('output_dir', '')
            if output_dir:
                data_dir = config.get('data_dir', os.path.join(config.get('root', ''), 'data'))
                status['report_url'] = '/files/' + os.path.relpath(os.path.realpath(output_dir), os.path.realpath(data_dir))
            return {'success': True, 'experiment': _sanitize_exp(status)}
        return Response(content=json.dumps({'success': False, 'message': 'Experiment not found'}),
                        status_code=404, media_type='application/json')
    except Exception as e:
        return _error_response(request, e,
                               {'success': False, 'message': f'Error getting experiment status: {str(e)}'})

# ------------------------------------------------------------------ #
# QPU raw parameters file (JSONEditor)                                #
# ------------------------------------------------------------------ #

@router.get("/api/qpu_parameters_file/{platform}", name="qpu_parameters_file_get", tags=["QPU"],
            summary="Read raw parameters.json for a platform")
async def qpu_parameters_file_get(request: Request, platform: str):
    """Return the raw contents of the platform's parameters.json."""
    try:
        config = _get_config(request)
        platforms_path = get_platforms_path(config.get('root', ''))
        if not platforms_path:
            return Response(content=json.dumps({'error': 'Platforms directory not configured'}),
                            status_code=503, media_type='application/json')
        params_file = _safe_path_join(platforms_path, os.path.join(platform, 'parameters.json'))
        if params_file is None:
            return Response(content=json.dumps({'error': 'Invalid platform path'}),
                            status_code=400, media_type='application/json')
        if not os.path.exists(params_file):
            return Response(content=json.dumps({'error': f'parameters.json not found for {platform}'}),
                            status_code=404, media_type='application/json')
        with open(params_file) as f:
            data = json.load(f)
        return Response(content=json.dumps(data), media_type='application/json')
    except Exception as e:
        return _error_response(request, e, {'error': str(e)})


@router.put("/api/qpu_parameters_file/{platform}", name="qpu_parameters_file_put", tags=["QPU"],
            summary="Write raw parameters.json for a platform")
async def qpu_parameters_file_put(request: Request, platform: str):
    """Overwrite the platform's parameters.json with the request body JSON."""
    try:
        config = _get_config(request)
        platforms_path = get_platforms_path(config.get('root', ''))
        if not platforms_path:
            return Response(content=json.dumps({'success': False,
                            'message': 'Platforms directory not configured'}),
                            status_code=503, media_type='application/json')
        params_file = _safe_path_join(platforms_path, os.path.join(platform, 'parameters.json'))
        if params_file is None:
            return Response(content=json.dumps({'success': False, 'message': 'Invalid platform path'}),
                            status_code=400, media_type='application/json')
        if not os.path.exists(params_file):
            return Response(content=json.dumps({'success': False,
                            'message': f'parameters.json not found for {platform}'}),
                            status_code=404, media_type='application/json')
        try:
            new_data = await request.json()
        except Exception:
            return Response(content=json.dumps({'success': False, 'message': 'Invalid JSON body'}),
                            status_code=400, media_type='application/json')
        # Atomic write via temp file
        tmp_path = params_file + '.tmp'
        with open(tmp_path, 'w') as f:
            json.dump(new_data, f, indent=2)
        os.replace(tmp_path, params_file)
        logger.info(f"Updated parameters.json for platform '{platform}'")
        return {'success': True, 'message': 'Parameters saved successfully'}
    except Exception as e:
        return _error_response(request, e, {'success': False, 'message': str(e)})


# ------------------------------------------------------------------ #
# Report fragment (inline embedding)                                  #
# ------------------------------------------------------------------ #

@router.get("/api/experiment_report/{experiment_id}", name="api_experiment_report", tags=["Experiments"],
            summary="Return extracted head CSS and body HTML for a qibocal report")
async def api_experiment_report(request: Request, experiment_id: str):
    """Return head_css and body_html for embedding a report inline."""
    try:
        config = _get_config(request)
        data_dir = config.get('data_dir') or os.path.join(config.get('root', ''), 'data')
        import glob as _glob
        matches = _glob.glob(os.path.join(data_dir, '*', '*', experiment_id, 'output'))
        if not matches:
            return Response(content=json.dumps({'error': 'Experiment not found'}),
                            status_code=404, media_type='application/json')
        output_dir = matches[0]
        if not os.path.exists(os.path.join(output_dir, 'index.html')):
            return Response(content=json.dumps({'error': 'Report not ready'}),
                            status_code=404, media_type='application/json')
        fragment = get_report_fragment(experiment_id, output_dir)
        return Response(content=json.dumps(fragment), media_type='application/json')
    except Exception as e:
        return _error_response(request, e, {'error': str(e)})


# ------------------------------------------------------------------ #
# Experiment output asset serving                                     #
# ------------------------------------------------------------------ #

@router.get("/api/experiment_assets/{experiment_id}/{filename:path}",
            name="api_experiment_assets", include_in_schema=False)
async def api_experiment_assets(request: Request, experiment_id: str, filename: str):
    """Serve static assets from an experiment's output directory."""
    try:
        config = _get_config(request)
        data_dir = config.get('data_dir') or os.path.join(config.get('root', ''), 'data')
        import glob as _glob
        matches = _glob.glob(os.path.join(data_dir, '*', '*', experiment_id, 'output'))
        if not matches:
            return Response(status_code=404)
        output_dir = matches[0]
        asset_path = _safe_path_join(output_dir, filename)
        if asset_path is None or not os.path.isfile(asset_path):
            return Response(status_code=404)
        return FileResponse(asset_path)
    except Exception:
        return Response(status_code=404)


# ------------------------------------------------------------------ #
# Full report page (for iframe embedding)                             #
# ------------------------------------------------------------------ #

@router.get("/experiment_report_page/{experiment_id}", name="experiment_report_page",
            include_in_schema=False)
async def experiment_report_page(request: Request, experiment_id: str):
    """Serve an iframe-friendly report page with qibocal CLI action buttons."""
    try:
        config = _get_config(request)
        data_dir = config.get('data_dir') or os.path.join(config.get('root', ''), 'data')
        import glob as _glob
        matches = _glob.glob(os.path.join(data_dir, '*', '*', experiment_id, 'output'))
        if not matches:
            raise HTTPException(404, detail=f'Report not found: {experiment_id}')
        output_dir = matches[0]
        fragment = get_report_fragment(experiment_id, output_dir)
        # Compute path relative to data_dir — must match the base used by qibocal_cli_action
        try:
            report_path_for_link = os.path.relpath(output_dir, data_dir)
        except ValueError:
            report_path_for_link = output_dir
        qibocal_ok = check_qibocal_availability()
        from ..core.app import templates
        html = templates.get_template('report_embed.html').render(
            request=request,
            experiment_id=experiment_id,
            report_path_for_link=report_path_for_link,
            report_head_content=fragment.get('head_css', ''),
            report_body_content=fragment.get('body_html', ''),
            qibocal_available=qibocal_ok,
        )
        return HTMLResponse(content=html)
    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(404, detail='Report not available.')
    except Exception as e:
        logger.exception("experiment_report_page error for %s", experiment_id)
        raise HTTPException(500, detail=str(e))


# ------------------------------------------------------------------ #
# Experiment log streaming                                            #
# ------------------------------------------------------------------ #

def _extract_traceback(text: str, re_mod) -> dict:
    """Scan log text for the last Python exception traceback.

    Returns a dict with keys: found, error_type, error_message, traceback.
    Matches (in order of preference):
      1. Full traceback block ending with 'XxxError: message'
      2. Bare 'raise SomeError(...)' lines
      3. Standalone 'XxxError: message' lines
    """
    # 1. Full traceback block (greedy-last)
    tb_re = re_mod.compile(
        r'(Traceback \(most recent call last\):.*?)'
        r'^([\w][\w.]*(?:Error|Exception|Warning)[^\n]*)',
        re_mod.DOTALL | re_mod.MULTILINE)
    matches = list(tb_re.finditer(text))
    if matches:
        m = matches[-1]
        error_line = m.group(2).strip()
        error_type = error_line.split(':')[0].strip()
        error_msg = error_line[len(error_type):].lstrip(': ').strip()
        return {'found': True, 'error_type': error_type,
                'error_message': error_msg,
                'traceback': (m.group(1) + m.group(2)).rstrip()}
    # 2. 'raise SomeError' / 'raise SomeError(...)' lines
    raise_re = re_mod.compile(r'^\s*raise\s+([\w.]+)', re_mod.MULTILINE)
    raise_matches = list(raise_re.finditer(text))
    if raise_matches:
        m = raise_matches[-1]
        ls = text.rfind('\n', 0, m.start()) + 1
        le = text.find('\n', m.end())
        error_line = text[ls: le if le >= 0 else len(text)].strip()
        return {'found': True, 'error_type': m.group(1),
                'error_message': error_line, 'traceback': error_line}
    # 3. Standalone 'XxxError: message'
    err_re = re_mod.compile(r'^([\w][\w.]*(?:Error|Exception)):\s*(.+)$', re_mod.MULTILINE)
    err_matches = list(err_re.finditer(text))
    if err_matches:
        m = err_matches[-1]
        return {'found': True, 'error_type': m.group(1),
                'error_message': m.group(2).strip(),
                'traceback': f'{m.group(1)}: {m.group(2).strip()}'}
    return {'found': False, 'error_type': '', 'error_message': '', 'traceback': ''}


@router.get("/api/experiment_log/{experiment_id}", name="api_experiment_log",
            tags=["Experiments"], summary="Return the SLURM log for an experiment")
async def api_experiment_log(request: Request, experiment_id: str):
    """Return tail of the SLURM output log for a running/completed experiment."""
    try:
        config = _get_config(request)
        data_dir = config.get('data_dir') or os.path.join(config.get('root', ''), 'data')
        import glob as _glob
        import re as _re
        log_matches = _glob.glob(
            os.path.join(data_dir, '*', '*', experiment_id, 'logs', 'slurm_output.log'))
        if not log_matches:
            return Response(
                content=json.dumps({'found': False, 'lines': [], 'error_info': {'found': False}}),
                media_type='application/json')
        log_path = log_matches[0]
        with open(log_path, 'r', errors='replace') as fh:
            lines = fh.readlines()
        tail = lines[-200:]
        error_info = _extract_traceback(''.join(lines), _re)
        return Response(
            content=json.dumps({'found': True, 'lines': tail, 'error_info': error_info}),
            media_type='application/json')
    except Exception as e:
        return Response(
            content=json.dumps({'found': False, 'lines': [], 'error_info': {'found': False}, 'error': str(e)}),
            media_type='application/json')


# ------------------------------------------------------------------ #
# Experiment history UI + API                                         #
# ------------------------------------------------------------------ #

@router.get("/history", name="history", include_in_schema=False)
async def history_page(request: Request):
    """History is now a side panel inside the shell — redirect there, opening it."""
    return RedirectResponse(url="/?panel=history", status_code=307)


@router.get("/api/history", name="api_history_list", tags=["Experiments"],
            summary="Paginated experiment history")
async def api_history_list(
    request: Request,
    platform: str = Query(""),
    protocol: str = Query(""),
    status: str = Query(""),
    fit: str = Query(""),
    date_from: str = Query(""),
    date_to: str = Query(""),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
):
    """Return paginated experiment history rows from the DB."""
    try:
        config = _get_config(request)
        data_dir = config.get('data_dir') or os.path.join(config.get('root', ''), 'data')
        from ..db.database import get_db_connection, query_runs, count_runs
        offset = (page - 1) * per_page
        with get_db_connection(config) as conn:
            rows = query_runs(conn, platform=platform, protocol=protocol,
                              status=status, fit=fit, date_from=date_from,
                              date_to=date_to, limit=per_page, offset=offset)
            total = count_runs(conn, platform=platform, protocol=protocol,
                               status=status, fit=fit, date_from=date_from, date_to=date_to)
        # explorer_path is the experiment dir (parent of "output") relative to
        # data_dir, for the Explorer panel's "open directory" link — computed
        # here so the raw absolute output_dir never has to reach the client.
        for row in rows:
            output_dir = row.get('output_dir')
            if output_dir:
                try:
                    row['explorer_path'] = os.path.relpath(os.path.dirname(output_dir), data_dir)
                except ValueError:
                    row['explorer_path'] = None
            else:
                row['explorer_path'] = None
        rows = [_sanitize_exp(row) for row in rows]
        return {
            'runs': rows,
            'total': total,
            'page': page,
            'per_page': per_page,
            'pages': max(1, (total + per_page - 1) // per_page),
        }
    except Exception as e:
        return _error_response(request, e, {'error': str(e)})


@router.get("/api/history/{experiment_id}", name="api_history_detail", tags=["Experiments"],
            summary="Get a single experiment history record")
async def api_history_detail(request: Request, experiment_id: str):
    """Return a single experiment run record from the history DB."""
    try:
        config = _get_config(request)
        from ..db.database import get_db_connection, get_run
        with get_db_connection(config) as conn:
            run = get_run(conn, experiment_id)
        if run is None:
            return Response(content=json.dumps({'error': 'Not found'}),
                            status_code=404, media_type='application/json')
        return run
    except Exception as e:
        return _error_response(request, e, {'error': str(e)})


@router.post("/api/history/{experiment_id}/refresh", name="api_history_refresh", tags=["Experiments"],
             summary="Re-scan an experiment directory and update the history DB")
async def api_history_refresh(request: Request, experiment_id: str):
    """Re-scan experiment directory and update the DB row."""
    try:
        config = _get_config(request)
        from ..db.database import get_db_connection, refresh_run_status
        data_dir = config.get('data_dir') or os.path.join(config.get('root', ''), 'data')
        import glob as _glob
        matches = _glob.glob(os.path.join(data_dir, '*', '*', experiment_id))
        if not matches:
            return Response(content=json.dumps({'success': False, 'error': 'Experiment not found'}),
                            status_code=404, media_type='application/json')
        exp_dir = matches[0]
        with get_db_connection(config) as conn:
            updated = refresh_run_status(conn, experiment_id, exp_dir)
        if updated is None:
            return Response(content=json.dumps({'success': False, 'error': 'Could not scan experiment'}),
                            status_code=500, media_type='application/json')
        return {'success': True, 'run': updated}
    except Exception as e:
        return _error_response(request, e, {'success': False, 'error': str(e)})


@router.post("/api/history/backfill", name="api_history_backfill", tags=["Experiments"],
             summary="Re-scan all experiment directories and update the history DB")
async def api_history_backfill(request: Request):
    """Walk data_dir and upsert any experiment records that are missing or stale."""
    try:
        config = _get_config(request)
        from ..db.database import backfill_from_disk
        count = backfill_from_disk(config)
        return {'success': True, 'updated': count}
    except Exception as e:
        return _error_response(request, e, {'success': False, 'error': str(e)})
