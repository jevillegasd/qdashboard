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
    """Check if qibocal CLI is available."""
    try:
        result = subprocess.run(['qq', '--help'], 
                              capture_output=True, 
                              text=True, 
                              timeout=5)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
        return False
 

def report_viewer(report_path, root_path, request, qibo_versions=None, access_mode="latest"):
    """
    Generate report viewer with proper asset handling.
    
    This function processes Qibocal HTML reports by:
    1. Extracting head content (CSS/JS dependencies)
    2. Extracting body content (main report)
    3. Fixing asset paths to work with Flask routing
    4. Rendering using a single template call with proper variables
    
    Args:
        report_path (str): Path to the report directory
        root_path (str): Root path for asset resolution
        qibo_versions (dict): Pre-fetched qibo versions (optional)
        access_mode (str): How the report was accessed ("latest" or "file_browser")
        
    Returns:
        Flask Response: Rendered report page
    """
    with open(os.path.join(report_path, "index.html"), 'r') as file:
        report_viewer_content = file.read()
    
    # Extract the head section to get CSS and JS dependencies
    head_content = ""
    if '<head>' in report_viewer_content and '</head>' in report_viewer_content:
        head_content = report_viewer_content.split('<head>')[1].split('</head>')[0]
    
    # Extract main content
    report_viewer_body = report_viewer_content
    if '<body>' in report_viewer_content and '</body>' in report_viewer_content:
        report_viewer_body = report_viewer_content.split('<body>')[1].split('</body>')[0]
        
        # Remove header if present
        if '<header' in report_viewer_body and '</header>' in report_viewer_body:
            report_viewer_body = report_viewer_body.split('</header>')[1]
    
    # Remove the original report's sidebar menu if it exists
    report_viewer_body = re.sub(r'<nav id="sidebarMenu".*?</nav>', '', report_viewer_body, flags=re.DOTALL)

    # Fix CSS links
    head_content = re.sub(r'''href=(['"])(?!/|http|https|data:)([^'"]+\.css[^'"]*)['"]''', r'href="/report_assets/\2"', head_content)
    
    # Fix JS script sources
    head_content = re.sub(r'''src=(['"])(?!/|http|https|data:)([^'"]+\.js[^'"]*)['"]''', r'src="/report_assets/\2"', head_content)
    report_viewer_body = re.sub(r'''src=(['"])(?!/|http|https|data:)([^'"]+\.js[^'"]*)['"]''', r'src="/report_assets/\2"', report_viewer_body)
    
    # Fix image sources
    report_viewer_body = re.sub(r'''src=(['"])(?!/|http|https|data:)([^'"]+\.(?:png|jpg|jpeg|gif|svg)[^'"]*)['"]''', r'src="/report_assets/\2"', report_viewer_body)
    
    # Fix any other asset references (like data files for plots)
    report_viewer_body = re.sub(r'''(['"])(?!/|http|https|data:)([^'"]+\.(?:json|csv|data|yml|yaml)[^'"]*)['"]''', r'"/report_assets/\2"', report_viewer_body)

    # Prepare the report path for the file browser link (remove root prefix and ensure it starts with /)
    # Use realpath on root_path so it matches report_path (which is already realpath-resolved)
    resolved_root = os.path.realpath(root_path)
    report_path_for_link = report_path.replace(resolved_root, "").lstrip("/")

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
    """
    Extract head CSS and body HTML from a qibocal report output directory,
    rewriting asset paths to use /api/experiment_assets/{experiment_id}/.

    Returns a dict with keys 'head_css' and 'body_html', or raises FileNotFoundError
    if the report index does not exist.
    """
    index_path = os.path.join(report_path, "index.html")
    if not os.path.exists(index_path):
        raise FileNotFoundError(f"Report index not found: {index_path}")

    with open(index_path, "r", errors="replace") as fh:
        content = fh.read()

    # Extract <head> section
    head_content = ""
    if "<head>" in content and "</head>" in content:
        head_content = content.split("<head>")[1].split("</head>")[0]

    # Extract <body> section
    body = content
    if "<body>" in content and "</body>" in content:
        body = content.split("<body>")[1].split("</body>")[0]
        if "<header" in body and "</header>" in body:
            body = body.split("</header>")[1]

    # Remove original sidebar nav
    body = re.sub(r'<nav id="sidebarMenu".*?</nav>', "", body, flags=re.DOTALL)

    base = f"/api/experiment_assets/{experiment_id}"

    # Rewrite relative asset paths in head_content
    head_content = re.sub(
        r'''href=(['"])(?!/|http|https|data:)([^'"]+\.css[^'"]*)['"]''',
        rf'href="{base}/\2"',
        head_content,
    )
    head_content = re.sub(
        r'''src=(['"])(?!/|http|https|data:)([^'"]+\.js[^'"]*)['"]''',
        rf'src="{base}/\2"',
        head_content,
    )

    # Rewrite relative asset paths in body
    body = re.sub(
        r'''src=(['"])(?!/|http|https|data:)([^'"]+\.js[^'"]*)['"]''',
        rf'src="{base}/\2"',
        body,
    )
    body = re.sub(
        r'''src=(['"])(?!/|http|https|data:)([^'"]+\.(?:png|jpg|jpeg|gif|svg|webp)[^'"]*)['"]''',
        rf'src="{base}/\2"',
        body,
    )
    body = re.sub(
        r'''(['"])(?!/|http|https|data:)([^'"]+\.(?:json|csv|data)[^'"]*)['"]''',
        rf'"{base}/\2"',
        body,
    )

    return {"head_css": head_content, "body_html": body}


def get_full_report_html(experiment_id: str, report_path: str) -> str:
    """
    Return a complete standalone HTML page for embedding in an iframe.
    Rewrites all relative asset paths to /api/experiment_assets/{experiment_id}/.
    """
    index_path = os.path.join(report_path, "index.html")
    if not os.path.exists(index_path):
        raise FileNotFoundError(f"Report index not found: {index_path}")

    with open(index_path, "r", errors="replace") as fh:
        content = fh.read()

    base = f"/api/experiment_assets/{experiment_id}"

    def _rewrite(html: str) -> str:
        # CSS href
        html = re.sub(
            r'''href=(['"])(?!/|http|https|data:)([^'"]+\.css[^'"]*)['"]''',
            rf'href="{base}/\2"', html)
        # JS src
        html = re.sub(
            r'''src=(['"])(?!/|http|https|data:)([^'"]+\.js[^'"]*)['"]''',
            rf'src="{base}/\2"', html)
        # images
        html = re.sub(
            r'''src=(['"])(?!/|http|https|data:)([^'"]+\.(?:png|jpg|jpeg|gif|svg|webp)[^'"]*)['"]''',
            rf'src="{base}/\2"', html)
        # data files
        html = re.sub(
            r'''(['"])(?!/|http|https|data:)([^'"]+\.(?:json|csv|data)[^'"]*)['"]''',
            rf'"{base}/\2"', html)
        return html

    return _rewrite(content)

