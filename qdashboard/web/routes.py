"""
Main application routes and endpoints.
"""

import os
import subprocess
import json
import asyncio
import time
import shutil
import yaml
import traceback as _tb
from typing import Optional
from fastapi import APIRouter, Request, Form, File, UploadFile, Query
from fastapi.responses import FileResponse, Response, StreamingResponse
from starlette.responses import HTMLResponse

from ..qpu.monitoring import get_qpu_health, get_available_qpus, get_qibo_versions, get_qpu_details, get_qpu_list, qpu_parameters
from ..qpu.platforms import get_platforms_path, list_repository_branches, switch_repository_branch, get_current_branch_info, commit_changes, push_changes, stash_changes, list_stashes, apply_latest_stash, discard_changes, get_partition
from ..qpu.slurm import get_slurm_status, get_slurm_output, parse_slurm_log_for_errors, slurm_log_path
from ..qpu.topology import qpu_connectivity, infer_topology_from_connectivity, generate_topology_visualization
from ..experiments.protocols import get_qibocal_protocols, get_protocol_attributes
from ..experiments import submit_experiment, repeat_experiment, get_experiment_status, list_user_experiments
from ..web.reports import report_viewer, get_latest_report_path
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
    """Return an HTML error page.

    In debug mode a styled traceback page is rendered so developers can see
    the full stack without leaving the browser.
    """
    debug = request.app.state.config.get('debug', False)
    trace = _tb.format_exc()
    logger.error("[%s %s] %s: %s\n%s",
                 request.method, request.url.path,
                 type(exc).__name__, exc, trace)
    if debug:
        import html as _html
        safe_trace = _html.escape(trace)
        safe_msg   = _html.escape(str(exc))
        safe_type  = _html.escape(type(exc).__name__)
        content = (
            '<html><head><title>QDashboard Error</title>'
            '<style>body{background:#1a1a2e;color:#e0e0e0;font-family:monospace;padding:2rem}'
            'h2{color:#ff6b6b}pre{background:#0d0d1a;padding:1.2rem;overflow:auto;'
            'border-left:3px solid #ff6b6b;white-space:pre-wrap}'
            '.ctx{color:#888;font-size:.85em;margin-bottom:1rem}</style></head><body>'
            f'<h2>&#9888; {safe_type}</h2>'
            f'<p class="ctx">{request.method} {request.url}</p>'
            f'<pre>{safe_trace}</pre>'
            '</body></html>'
        )
    else:
        content = (
            f'<html><body><h2>Internal Server Error</h2>'
            f'<p>{status_code}: {type(exc).__name__}</p></body></html>'
        )
    return HTMLResponse(content=content, status_code=status_code)


def register_routes(app, config):
    """Register the APIRouter on the FastAPI app."""
    app.include_router(router)
    logger.debug("Routes module initialized")
    return app


@router.get("/", name="dashboard", include_in_schema=False)
async def dashboard(request: Request):
    """Main dashboard route with QPU health and SLURM status."""
    from ..core.app import templates

    qpu_health = get_qpu_health()
    available_qpus = get_available_qpus()
    version_data = get_qibo_versions(request=request)
    slurm_queue_status = get_slurm_status()
    last_slurm_log = get_slurm_output()

    logger.info("Dashboard loaded with QPU health and SLURM status")

    html = templates.get_template('dashboard.html').render(
        request=request,
        qpu_health=qpu_health,
        available_qpus=available_qpus,
        qibo_versions=version_data['versions'],
        slurm_queue_status=slurm_queue_status,
        last_slurm_log=last_slurm_log,
    )
    response = HTMLResponse(content=html, headers=_no_cache_headers())
    if not version_data.get('from_cache', False):
        response.set_cookie('qibo_versions', version_data['cookie_data'],
                            max_age=24 * 60 * 60, httponly=True, secure=False)
    return response


@router.get("/qqsubmit", name="qqsubmit", include_in_schema=False)
async def qqsubmit(request: Request, qpu: Optional[str] = Query(None)):
    """Submit a job to the SLURM queue."""
    from ..core.app import templates

    config = _get_config(request)
    os_process = subprocess.Popen(
        ["bash", os.path.join(config['root'], "work/qqsubmit.sh"), config['home_path'], qpu],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    stdout, stderr = os_process.communicate()
    out_string = stdout.decode('utf-8').replace('\n', '<br>')
    logger.info(f"Job submitted to SLURM queue for QPU: {qpu}")
    html = templates.get_template('job_submission.html').render(
        request=request, output_content=out_string)
    return HTMLResponse(content=html)


@router.get("/latest", name="latest", include_in_schema=False)
async def latest(request: Request):
    """View the latest report."""
    from ..core.app import templates

    config = _get_config(request)
    last_path = get_latest_report_path()
    version_data = get_qibo_versions(request=request)

    def _not_found_response(last_path):
        slurm_queue_status = get_slurm_status()
        last_slurm_log = get_slurm_output()
        has_error, error_message = parse_slurm_log_for_errors()
        html = templates.get_template('latest_not_found.html').render(
            request=request,
            has_error=has_error,
            error_message=error_message,
            last_path=last_path,
            slurm_queue_status=slurm_queue_status,
            last_slurm_log=last_slurm_log,
            qibo_versions=version_data['versions'],
        )
        response = HTMLResponse(content=html)
        if not version_data.get('from_cache', False):
            response.set_cookie('qibo_versions', version_data['cookie_data'],
                                max_age=24 * 60 * 60, httponly=True, secure=False)
        return response

    if not last_path:
        last_path = config.get('home_path', os.path.expanduser('~'))
        logger.warning(f"Last report not found, using default path: {last_path}")
        return _not_found_response(last_path)

    try:
        res = report_viewer(last_path, config['root'], request, version_data['versions'], access_mode="latest")
        logger.info(f"Latest report viewed: {last_path}")
        return res
    except FileNotFoundError:
        data_dir = config.get('data_dir', os.path.join(config['root'], 'data'))
        last_path = "/" + last_path.replace(data_dir, "").lstrip("/")
        logger.warning(f"Report not found: {last_path}")
        return _not_found_response(last_path)
    except Exception as e:
        return _html_error_response(request, e)


@router.get("/report_assets/{filename:path}", name="report_assets", include_in_schema=False)
async def report_assets(request: Request, filename: str):
    """Serve assets from the latest report directory."""
    config = _get_config(request)
    try:
        latest_path = get_latest_report_path()
        if latest_path:
            asset_path = os.path.join(latest_path, filename)
            if os.path.exists(asset_path):
                logger.info(f"Serving asset: {asset_path}")
                return FileResponse(asset_path)
        logger.warning(f"Asset not found: {filename}")
        return Response(content='Asset not found', status_code=404)
    except Exception as e:
        return _html_error_response(request, e)


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
    """QPU status and monitoring page."""
    from ..core.app import templates

    config = _get_config(request)
    qpu_details = get_qpu_details()
    version_data = get_qibo_versions(request=request)
    platforms_path = get_platforms_path(config['root'])
    git_branches_info = list_repository_branches(platforms_path) if platforms_path else None
    git_current_branch_info = get_current_branch_info(platforms_path) if platforms_path else None

    logger.info("QPU status page loaded")
    html = templates.get_template('qpus.html').render(
        request=request,
        qpus=qpu_details,
        git_branch=git_current_branch_info['branch'] if git_current_branch_info else None,
        git_commit=git_current_branch_info['commit'] if git_current_branch_info else None,
        platforms_path=platforms_path,
        branches_info=git_branches_info,
        current_branch_info=git_current_branch_info,
        qibo_versions=version_data['versions'],
    )
    response = HTMLResponse(content=html)
    if not version_data.get('from_cache', False):
        response.set_cookie('qibo_versions', version_data['cookie_data'],
                            max_age=24 * 60 * 60, httponly=True, secure=False)
    return response


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


@router.get("/experiments", name="experiments", include_in_schema=False)
async def experiments(request: Request):
    """Experiment builder page."""
    from ..core.app import templates

    protocols = get_qibocal_protocols()
    qpus_list = get_qpu_list()
    version_data = get_qibo_versions(request=request)
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

    logger.info("Experiment builder page loaded")
    html = templates.get_template('experiments.html').render(
        request=request,
        protocols=protocols_with_attributes,
        qpus=qpus_list,
        qibo_versions=version_data['versions'],
        is_new_qibolab=is_new_qibolab,
    )
    response = HTMLResponse(content=html)
    if not version_data.get('from_cache', False):
        response.set_cookie('qibo_versions', version_data['cookie_data'],
                            max_age=24 * 60 * 60, httponly=True, secure=False)
    return response


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
    qpu_path = os.path.join(qrc_path, platform)
    if not os.path.exists(qpu_path):
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
    qpu_path = os.path.join(qrc_path, platform)
    if not os.path.exists(qpu_path):
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
    calibration_path = os.path.join(platforms_path, platform, 'calibration.json')
    if os.path.exists(calibration_path):
        with open(calibration_path, 'r') as f:
            calibration_data = json.load(f)
        return calibration_data
    return Response(content=json.dumps({'error': 'Calibration data not found'}),
                    status_code=404, media_type='application/json')


@router.post("/qibocal/{action}", name="qibocal_cli_action", tags=["Experiments"],
             summary="Run a qibocal CLI action (fit / report / update) on an existing report")
async def qibocal_cli_action(request: Request, action: str,
                              report_path: str = Form(...)):
    """Execute qibocal CLI commands."""
    config = _get_config(request)
    full_report_path = os.path.join(config['root'], report_path)
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
        from ..web.reports import check_qibocal_availability
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
        result = repeat_experiment(report_path, config)
        if result['success']:
            logger.info(f"Experiment repeat submitted: {result['experiment_id']}")
            return result
        logger.error(f"Failed to repeat experiment: {result['message']}")
        return Response(content=json.dumps(result), status_code=400,
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
                return result
            return Response(content=json.dumps(result), status_code=400,
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
        if not runcard_data:
            return Response(content=json.dumps({'success': False,
                            'message': 'No runcard_data provided'}),
                            status_code=400, media_type='application/json')
        if 'platform' not in runcard_data:
            return Response(content=json.dumps({'success': False,
                            'message': 'Missing required field: platform'}),
                            status_code=400, media_type='application/json')
        result = submit_experiment(runcard_data=runcard_data, config=config, environment=environment)
        if result['success']:
            logger.info(f"New experiment submitted with data: {result['experiment_id']}")
            return result
        return Response(content=json.dumps(result), status_code=400,
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
        return {'success': True, 'experiments': experiments, 'count': len(experiments)}
    except Exception as e:
        return _error_response(request, e,
                               {'success': False, 'message': f'Error listing experiments: {str(e)}'})


@router.get("/api/experiments/{experiment_id}", name="api_experiment_status", tags=["Experiments"],
            summary="Get the status and metadata of a single experiment")
async def api_experiment_status(request: Request, experiment_id: str):
    """API endpoint to get experiment status."""
    try:
        config = _get_config(request)
        status = get_experiment_status(experiment_id, config)
        if status:
            return {'success': True, 'experiment': status}
        return Response(content=json.dumps({'success': False, 'message': 'Experiment not found'}),
                        status_code=404, media_type='application/json')
    except Exception as e:
        return _error_response(request, e,
                               {'success': False, 'message': f'Error getting experiment status: {str(e)}'})


