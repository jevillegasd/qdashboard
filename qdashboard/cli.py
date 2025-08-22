#!/usr/bin/env python3
"""
QDashboard CLI - Command Line Interface

Entry point for the QDashboard application when installed as a package.
"""

import sys
import os
import argparse
from typing import Optional, List

from qdashboard.core.app import create_app, get_config
from qdashboard.utils.logger import get_logger

logger = get_logger(__name__)

def create_parser() -> argparse.ArgumentParser:
    """Create the command line argument parser."""
    parser = argparse.ArgumentParser(
        prog='qdashboard',
        description='QDashboard - Quantum Computing Dashboard',
        epilog='For more information, visit: https://github.com/jevillegasd/qdashboard'
    )
    
    parser.add_argument(
        '--port',
        nargs='?',
        type=int,
        default=8080,
        help='Port number to run the server on (default: 8080)'
    )
    
    parser.add_argument(
        '--host',
        type=str,
        default='127.0.0.1',
        help='Host address to bind the server to (default: 127.0.0.1)'
    )
    
    parser.add_argument(
        '--root',
        type=str,
        default=None,
        help='Root directory to serve files from (default: user home directory)'
    )
    
    parser.add_argument(
        '--auth-key',
        type=str,
        default='',
        help='Authentication key for accessing the dashboard'
    )
    
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug mode'
    )

    parser.add_argument(
        '--environment',
        type=str,
        default=None,
        help='Environment to run the dashboard in (default: None)'
    )

    parser.add_argument(
        '--home-path',
        type=str,
        default=None,
        help='Home directory path for the user (default: user home directory)'
    )

    parser.add_argument(
        '--log-path',
        type=str,
        default='~/.qdashboard/logs/slurm_output.txt',
        help='Path to the log directory (default: ~/.qdashboard/logs/slurm_output.txt)'
    )

    return parser


def get_default_config(args: argparse.Namespace) -> dict:
    """Get default configuration based on command line arguments."""
    # Set default root path to user's home directory if not specified
    root_path = args.root or os.path.expanduser('~')
    root_path = os.path.abspath(root_path)
    config = get_config()
    if args.root:
        config['root'] = root_path
    if args.auth_key:
        config['key'] = args.auth_key
    if args.debug:
        config['debug'] = args.debug
    if args.environment:
        config['environment'] = args.environment
    if args.home_path:
        config['home_path'] = args.home_path
    if args.host:
        config['host'] = args.host
    if args.log_path:
        config['log_path'] = args.log_path
    if args.port:
        config['port'] = args.port
    config['version'] = __import__("qdashboard").__version__
    return config


def validate_config(config: dict) -> None:
    """Validate the configuration parameters."""
    # Validate port range
    if not (1 <= config['port'] <= 65535):
        logger.warning(f"Error: Port number must be between 1 and 65535, got {config['port']}")
        sys.exit(1)
    
    # Validate root directory
    if not os.path.exists(config['root']):
        logger.warning(f"Error: Root directory does not exist: {config['root']}")
        sys.exit(1)
    
    if not os.path.isdir(config['root']):
        logger.warning(f"Error: Root path is not a directory: {config['root']}")
        sys.exit(1)


def main(argv: Optional[List[str]] = None) -> None:
    """
    Main entry point for the QDashboard CLI.
    
    Args:
        argv: Command line arguments (defaults to sys.argv)
    """
    # Parse command line arguments
    parser = create_parser()
    args = parser.parse_args(argv)
    
    # Get configuration
    config = get_default_config(args)
    print(config)

    # Validate configuration
    validate_config(config)
    
    try:
        # Import here to avoid import errors if package is not fully installed
        from .core.app import create_app
        from .web.routes import register_routes
        from .web.file_browser import PathView
        from .qpu.platforms import get_platforms_path
        
        # Ensure qibolab platforms directory is available
        logger.info('QDashboard - CLI - Quantum Computing Dashboard')
        logger.info('Initializing QPU platforms...')
        
        try:
            platforms_path = get_platforms_path(config['root'])
            if not platforms_path:
                logger.warning('Could not initialize QPU platforms directory')
        except Exception as e:
            logger.warning(f'Error setting up QPU platforms: {e}')

        # Create Flask application
        app = create_app()
        
        # Store config for routes to access
        app.config['QDASHBOARD_CONFIG'] = config
        
        # Register routes
        register_routes(app, config)
        
        # Register file browser - create a proper class-based view
        class ConfiguredPathView(PathView):
            def __init__(self):
                super().__init__(root_path=config['root'], key=config['key'])
        path_view = ConfiguredPathView.as_view('path_view')

        app.add_url_rule('/files/', defaults={'p': ''}, view_func=path_view)
        app.add_url_rule('/files/<path:p>', view_func=path_view)
        
        # Print startup information
        logger.info('QDashboard server starting...')
        logger.info(f'Server running on: http://{config["host"]}:{config["port"]}')
        logger.info(f'Serving directory: {config["root"]}')
        logger.info(f'Slurm Log: {config["log_path"]}')
        if config['key']:
            logger.info(f'Authentication key: {config["key"]}')
        logger.info(f'Environment: {config["environment"]}')
        logger.info('Press Ctrl+C to stop the server')

        if 'debug' not in config:
            config['debug'] = False
        # Start the Flask application
        app.run(
            host=config['host'],
            port=config['port'],
            debug=config['debug'],
            threaded=True
        )
        
    except KeyboardInterrupt:
        logger.error('\nQDashboard server stopped by user')
        sys.exit(0)
    except ImportError as e:
        logger.error(f'Error: Required dependencies not found: {e}')
        logger.error('Please install qdashboard with: pip install qdashboard')
        sys.exit(1)
    except Exception as e:
        logger.error(f'Error starting QDashboard server: {e}')
        sys.exit(1)


if __name__ == '__main__':
    main()
