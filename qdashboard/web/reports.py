"""
Report viewing and processing utilities.
"""

import os
import re
import subprocess
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



