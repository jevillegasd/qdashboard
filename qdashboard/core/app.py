"""
Core Flask application configuration and setup.
"""

import os
from flask import Flask

from ..utils.formatters import size_fmt, time_desc, data_fmt, icon_fmt, time_humanize
from qdashboard.utils.logger import get_logger


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
    PORT_NUMBER = 5005
    home_path = os.environ.get('HOME')
    
    config = {
        'host': os.getenv('QD_BIND', "127.0.0.1"),
        'port': os.getenv('QD_PORT', PORT_NUMBER),
        'root': os.path.normpath(os.getenv('QD_PATH', home_path)),
        'key': os.getenv('QD_KEY', ""),
        'home_path': home_path,
        'user': os.environ.get('USER')
    }
    
    logger.info("Useful information during execution")
    
    return config
