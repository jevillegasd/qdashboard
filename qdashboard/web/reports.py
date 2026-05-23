"""
Report viewing and processing utilities.
"""

import os
import re
import subprocess
from starlette.responses import HTMLResponse, FileResponse, Response
from ..qpu.monitoring import get_qibo_versions
from ..core.config import get_config


def check_qibocal_availability():
    """Return True if the `qq` CLI is available."""
    try:
        result = subprocess.run(['qq', '--help'],
                               capture_output=True,
                               text=True,
                               timeout=5)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
        return False


def _rewrite_asset_paths(html: str, base: str) -> str:
    """Rewrite relative asset paths in *html* to be rooted at *base*."""
    html = re.sub(
        r"""href=(['"])(?!/|http|https|data:)([^'"]+\.css[^'"]*)['"]""",
        rf'href="{base}/\2"', html)
    html = re.sub(
        r"""src=(['"])(?!/|http|https|data:)([^'"]+\.js[^'"]*)['"]""",
        rf'src="{base}/\2"', html)
    html = re.sub(
        r"""src=(['"])(?!/|http|https|data:)([^'"]+\.(?:png|jpg|jpeg|gif|svg|webp)[^'"]*)['"]""",
        rf'src="{base}/\2"', html)
    html = re.sub(
        r"""(['"])(?!/|http|https|data:)([^'"]+\.(?:json|csv|data)[^'"]*)['"]""",
        rf'"{base}/\2"', html)
    return html
 

def report_viewer(report_path, root_path, request, qibo_versions=None, access_mode="latest"):
    """Render a Qibocal HTML report inside the dashboard template."""
    with open(os.path.join(report_path, "index.html"), 'r') as file:
        report_viewer_content = file.read()

    head_content = ""
    if '<head>' in report_viewer_content and '</head>' in report_viewer_content:
        head_content = report_viewer_content.split('<head>')[1].split('</head>')[0]

    report_viewer_body = report_viewer_content
    if '<body>' in report_viewer_content and '</body>' in report_viewer_content:
        report_viewer_body = report_viewer_content.split('<body>')[1].split('</body>')[0]
        if '<header' in report_viewer_body and '</header>' in report_viewer_body:
            report_viewer_body = report_viewer_body.split('</header>')[1]

    report_viewer_body = re.sub(r'<nav id="sidebarMenu".*?</nav>', '', report_viewer_body, flags=re.DOTALL)

    head_content = _rewrite_asset_paths(head_content, '/report_assets')
    report_viewer_body = _rewrite_asset_paths(report_viewer_body, '/report_assets')

    # Compute path relative to root_path for display and qibocal actions.
    # Use relpath (not string replace) so symlinks don't cause a mismatch.
    # Resolve both sides through realpath first so symlink differences
    # (e.g. /home/... vs /nfs/...) do not produce spurious ../.. sequences.
    try:
        report_path_for_link = os.path.relpath(os.path.realpath(report_path),
                                                os.path.realpath(root_path))
    except ValueError:
        # Different drives on Windows — fall back to basename
        report_path_for_link = os.path.basename(report_path)

    # Check qibocal availability
    qibocal_available = check_qibocal_availability()

    # Render the template with all variables in a single call
    if qibo_versions is None:
        qibo_versions = get_qibo_versions()
    from ..core.app import templates
    report_viewer_template = templates.get_template('latest_report.html').render(
                                                     request=request,
                                                     qibo_versions=qibo_versions,
                                                     report_head_content=head_content,
                                                     report_body_content=report_viewer_body,
                                                     report_path_for_link=report_path_for_link,
                                                     access_mode=access_mode,
                                                     qibocal_available=qibocal_available)

    return HTMLResponse(content=report_viewer_template, status_code=200)


def get_latest_report_path():
    """Get the path to the latest report from .last_report_path file."""
    from ..core.config import ConfigError, DEFAULT_QD_ROOT
    try:
        config = get_config()
        logs_dir = config.get('logs_dir', os.path.join(config['root'], 'logs'))
        last_report_path = config.get('last_report_path', os.path.join(logs_dir, 'last_report_path'))
    except ConfigError:
        root = os.path.expanduser(os.environ.get('QD_ROOT', DEFAULT_QD_ROOT))
        logs_dir = os.path.expanduser(os.environ.get('QD_LOGS_DIR', os.path.join(root, 'logs')))
        last_report_path = os.path.join(logs_dir, 'last_report_path')

    try:
        with open(last_report_path, 'r') as file:
            latest_path = file.read().strip()
        return latest_path
    except FileNotFoundError:
        return None


def get_report_fragment(experiment_id: str, report_path: str) -> dict:
    """Extract head CSS and body HTML from a qibocal report, rewriting asset
    paths to use /api/experiment_assets/{experiment_id}/.

    Returns a dict with keys 'head_css' and 'body_html', or raises
    FileNotFoundError if the report index does not exist.
    """
    index_path = os.path.join(report_path, "index.html")
    if not os.path.exists(index_path):
        raise FileNotFoundError(f"Report index not found: {index_path}")

    with open(index_path, "r", errors="replace") as fh:
        content = fh.read()

    head_content = ""
    if "<head>" in content and "</head>" in content:
        head_content = content.split("<head>")[1].split("</head>")[0]

    body = content
    if "<body>" in content and "</body>" in content:
        body = content.split("<body>")[1].split("</body>")[0]
        if "<header" in body and "</header>" in body:
            body = body.split("</header>")[1]

    body = re.sub(r'<nav id="sidebarMenu".*?</nav>', "", body, flags=re.DOTALL)

    base = f"/api/experiment_assets/{experiment_id}"
    return {"head_css": _rewrite_asset_paths(head_content, base),
            "body_html": _rewrite_asset_paths(body, base)}


def get_full_report_html(experiment_id: str, report_path: str) -> str:
    """Return a complete standalone HTML page for embedding in an iframe,
    with all relative asset paths rewritten to /api/experiment_assets/{experiment_id}/.
    """
    index_path = os.path.join(report_path, "index.html")
    if not os.path.exists(index_path):
        raise FileNotFoundError(f"Report index not found: {index_path}")

    with open(index_path, "r", errors="replace") as fh:
        content = fh.read()

    return _rewrite_asset_paths(content, f"/api/experiment_assets/{experiment_id}")

