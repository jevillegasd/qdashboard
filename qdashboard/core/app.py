"""
Core Flask application configuration and setup.
"""

import os
from flask import Flask

from ..utils.formatters import size_fmt, time_desc, data_fmt, icon_fmt, time_humanize
from qdashboard.utils.logger import get_logger
from .config import DEFAULT_PORT, DEFAULT_HOST, DEFAULT_QD_ROOT


logger = get_logger(__name__)


def create_app():
    """Create and configure Flask application."""
    # Get the absolute path to the project root
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    app = Flask(__name__, 
                static_url_path='/assets', 
                static_folder=os.path.join(project_root, 'assets'),
                template_folder=os.path.join(project_root, 'templates'))
    
    app.config['APPLICATION_NAME'] = 'QDashboard'
    
    # Register template filters
    app.template_filter('size_fmt')(size_fmt)
    app.template_filter('time_fmt')(time_desc)
    app.template_filter('data_fmt')(data_fmt)
    app.template_filter('icon_fmt')(icon_fmt)
    app.template_filter('humanize')(time_humanize)
    
    logger.debug("App module initialized")
    
    return app


def get_config():
    """Get application configuration from environment variables."""
    home_path = os.environ.get('HOME')
    
    # QDashboard root directory - can be overridden with QD_PATH
    qd_root = os.path.normpath(os.getenv('QD_PATH', DEFAULT_QD_ROOT))
    files_root = os.getenv('QD_PATH', home_path) # We serve files from home by default otherwise is the same as the QD root

    # Standard QDashboard directories
    config = {
        'host': os.getenv('QD_BIND', DEFAULT_HOST),
        'port': os.getenv('QD_PORT', DEFAULT_PORT),
        'root': files_root, # Root directory for serving files
        'qd_root': qd_root, # QDashboard root directory
        'key': os.getenv('QD_KEY', ""),
        'home_path': home_path,
        'user': os.environ.get('USER'),
        'environment': os.environ.get('VIRTUAL_ENV', None),
        'logs_dir': os.path.join(qd_root, 'logs'),
        'data_dir': os.path.join(qd_root, 'data'),
        'temp_dir': os.path.join(qd_root, 'temp'),
        'log_path': os.path.join(qd_root, 'logs', 'slurm_output.txt'),
        'last_report_path': os.path.join(qd_root, 'logs', 'last_report_path')
    }
    
    return config
