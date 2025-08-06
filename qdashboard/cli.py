#!/usr/bin/env python3
"""
QDashboard CLI - Command Line Interface

Entry point for the QDashboard application when installed as a package.
"""

import sys
import os
import argparse
from typing import Optional, List


def create_parser() -> argparse.ArgumentParser:
    """Create the command line argument parser."""
    parser = argparse.ArgumentParser(
        prog='qdashboard',
        description='QDashboard - Quantum Computing Dashboard',
        epilog='For more information, visit: https://github.com/jevillegasdatTII/qdashboard'
    )
    
    parser.add_argument(
        'port',
        nargs='?',
        type=int,
        default=5005,
        help='Port number to run the server on (default: 5005)'
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
        '--version',
        action='version',
        version=f'%(prog)s {__import__("qdashboard").__version__}'
    )
    
    return parser


def get_default_config(args: argparse.Namespace) -> dict:
    """Get default configuration based on command line arguments."""
    # Set default root path to user's home directory if not specified
    root_path = args.root or os.path.expanduser('~')
    root_path = os.path.abspath(root_path)
    
    config = {
        'host': args.host,
        'port': args.port,
        'root': root_path,
        'key': args.auth_key,
        'debug': args.debug,
        'home_path': root_path
    }
    
    return config


def validate_config(config: dict) -> None:
    """Validate the configuration parameters."""
    # Validate port range
    if not (1 <= config['port'] <= 65535):
        print(f"Error: Port number must be between 1 and 65535, got {config['port']}")
        sys.exit(1)
    
    # Validate root directory
    if not os.path.exists(config['root']):
        print(f"Error: Root directory does not exist: {config['root']}")
        sys.exit(1)
    
    if not os.path.isdir(config['root']):
        print(f"Error: Root path is not a directory: {config['root']}")
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
    
    # Validate configuration
    validate_config(config)
    
    try:
        # Import here to avoid import errors if package is not fully installed
        from .core.app import create_app
        from .web.routes import register_routes
        from .web.file_browser import PathView
        
        # Create Flask application
        app = create_app(config)
        
        # Register routes
        register_routes(app, config)
        
        # Register file browser
        app.add_url_rule('/files/', defaults={'p': ''}, view_func=PathView.as_view('path_view', root=config['root']))
        app.add_url_rule('/files/<path:p>', view_func=PathView.as_view('path_view_with_path', root=config['root']))
        
        # Print startup information
        print('QDashboard - Quantum Computing Dashboard')
        print('=' * 50)
        print(f'Server running on: http://{config["host"]}:{config["port"]}')
        print(f'Serving directory: {config["root"]}')
        if config['key']:
            print(f'Authentication key: {config["key"]}')
        print('Press Ctrl+C to stop the server')
        print('=' * 50)
        
        # Start the Flask application
        app.run(
            host=config['host'],
            port=config['port'],
            debug=config['debug'],
            threaded=True
        )
        
    except KeyboardInterrupt:
        print('\nQDashboard server stopped by user')
        sys.exit(0)
    except ImportError as e:
        print(f'Error: Required dependencies not found: {e}')
        print('Please install qdashboard with: pip install qdashboard')
        sys.exit(1)
    except Exception as e:
        print(f'Error starting QDashboard server: {e}')
        sys.exit(1)


if __name__ == '__main__':
    main()
