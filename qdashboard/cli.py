#!/usr/bin/env python3
"""
QDashboard CLI - Command Line Interface

Entry point for the QDashboard application when installed as a package.
"""

import sys
import os
import argparse
from typing import Optional, List

import uvicorn
from qdashboard.core.app import create_app
from qdashboard.core.config import (
    DEFAULT_PORT, DEFAULT_HOST, DEFAULT_QD_ROOT,
    validate_config, set_config, ensure_directory_exists,
)
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
        default=None,
        help=f'Port number to run the server on (default: {DEFAULT_PORT}, env: QD_PORT)'
    )

    parser.add_argument(
        '--host',
        type=str,
        default=None,
        help=f'Host address to bind the server to (default: {DEFAULT_HOST}, env: QD_HOST)'
    )

    parser.add_argument(
        '--root',
        type=str,
        default=None,
        help='QDashboard root directory (default: ~/.qdashboard, env: QD_ROOT)'
    )

    parser.add_argument(
        '--auth-key',
        type=str,
        default=None,
        help='Authentication key for accessing the dashboard (env: QD_KEY)'
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
        help='Environment name (env: QD_ENVIRONMENT)'
    )

    parser.add_argument(
        '--home-path',
        type=str,
        default=None,
        help='Home directory path for the user (env: QD_HOME_PATH)'
    )

    parser.add_argument(
        '--log-path',
        type=str,
        default=None,
        help='Path to the SLURM log file (env: QD_LOG_PATH)'
    )

    return parser


def _load_env() -> None:
    """Load .env file if present. Searches CWD then ~/.qdashboard/."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    candidates = [
        os.path.join(os.getcwd(), '.env'),
        os.path.expanduser('~/.qdashboard/.env'),
    ]
    for path in candidates:
        if os.path.isfile(path):
            load_dotenv(path, override=False)  # env already set takes priority
            logger.info(f'Loaded .env from {path}')
            break


def get_default_config(args: argparse.Namespace) -> dict:
    """Build config: .env / env vars provide defaults; CLI args override."""
    # Resolve QDashboard root — the single source of truth for all dirs
    qd_root = os.path.expanduser(
        args.root
        or os.environ.get('QD_ROOT', '')
        or DEFAULT_QD_ROOT
    )
    qd_root = os.path.abspath(qd_root)

    data_dir  = os.path.expanduser(os.environ.get('QD_DATA_DIR',  os.path.join(qd_root, 'data')))
    logs_dir  = os.path.expanduser(os.environ.get('QD_LOGS_DIR',  os.path.join(qd_root, 'logs')))
    temp_dir  = os.path.expanduser(os.environ.get('QD_TEMP_DIR',  os.path.join(qd_root, 'tmp')))
    log_path  = os.path.expanduser(
        args.log_path
        or os.environ.get('QD_LOG_PATH', os.path.join(logs_dir, 'slurm_output.txt'))
    )

    config = {
        'qd_root':     qd_root,
        'root':        qd_root,
        'data_dir':    data_dir,
        'logs_dir':    logs_dir,
        'temp_dir':    temp_dir,
        'log_path':    log_path,
        'key':         args.auth_key  or os.environ.get('QD_KEY',         ''),
        'debug':       args.debug     or os.environ.get('QD_DEBUG',       'false').lower() == 'true',
        'environment': args.environment or os.environ.get('QD_ENVIRONMENT', 'default'),
        'home_path':   os.path.expanduser(
                           args.home_path or os.environ.get('QD_HOME_PATH', '~')
                       ),
        'host':        args.host or os.environ.get('QD_HOST', os.environ.get('QD_BIND', DEFAULT_HOST)),
        'port':        int(args.port or os.environ.get('QD_PORT', DEFAULT_PORT)),
    }
    config['version'] = __import__('qdashboard').__version__
    return config


def validate_config_legacy(config: dict) -> None:
    """Legacy validation function - moved to core.config module."""
    logger.warning("Using legacy validation function. Consider migrating to core.config.validate_config()")
    try:
        from qdashboard.core.config import validate_config
        validate_config(config)
    except Exception as e:
        # Fallback to legacy validation
        if not (1 <= config['port'] <= 65535):
            logger.warning(f"Error: Port number must be between 1 and 65535, got {config['port']}")
            sys.exit(1)
        
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
    # Load .env before building config so env vars are available
    _load_env()

    # Parse command line arguments
    parser = create_parser()
    args = parser.parse_args(argv)
    
    # Get configuration
    config = get_default_config(args)

    # Ensure required directories exist (first-run setup)
    for d in ('qd_root', 'data_dir', 'logs_dir', 'temp_dir'):
        ensure_directory_exists(config[d])

    # Validate configuration
    try:
        validate_config(config)
    except Exception as e:
        logger.error(f"Configuration validation failed: {e}")
        sys.exit(1)
    
    try:
        # Import here to avoid import errors if package is not fully installed
        from .core.app import create_app
        from .web.routes import register_routes
        from .web.file_browser import make_file_router
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

        # Set config before creating app
        set_config(config)

        # Create FastAPI application (also calls set_config internally)
        app = create_app(config)

        # Register main routes
        register_routes(app, config)

        # Register file browser router — serve the data directory
        file_router = make_file_router(config['data_dir'], config.get('key', ''))
        app.include_router(file_router)

        # Print startup information
        logger.info('QDashboard server starting...')
        logger.info(f'Server running on: http://{config["host"]}:{config["port"]}')
        logger.info(f'Serving directory: {config["root"]}')
        logger.info(f'QDashboard root: {config["root"]}')
        logger.info(f'Logs directory: {config["logs_dir"]}')
        if config.get('key'):
            logger.info(f'Authentication key: {config["key"]}')
        logger.info(f'Environment: {config.get("environment", "default")}')
        logger.info('Press Ctrl+C to stop the server')

        if 'debug' not in config:
            config['debug'] = False

        # Start the Uvicorn ASGI server via the Server API so we can ensure
        # Ctrl+C always triggers a clean shutdown even when a third-party library
        # (e.g. qibolab) has replaced the SIGINT signal handler with one that
        # raises RuntimeError instead of KeyboardInterrupt.
        import signal as _signal

        uv_cfg = uvicorn.Config(
            app,
            host=config['host'],
            port=int(config['port']),
            reload=False,
            log_level='debug' if config['debug'] else 'info',
        )
        server = uvicorn.Server(uv_cfg)

        # Monkey-patch signal.signal so that whenever any library installs a
        # SIGINT handler we wrap it: our wrapper sets server.should_exit first,
        # then calls the library handler (swallowing any RuntimeError from it).
        _real_signal = _signal.signal

        def _intercept_signal(sig, handler):
            if sig == _signal.SIGINT and callable(handler):
                _lib_handler = handler

                def _wrapped(s, f):
                    server.should_exit = True
                    try:
                        _lib_handler(s, f)
                    except (SystemExit, KeyboardInterrupt):
                        raise
                    except Exception:
                        pass  # swallow qibolab's RuntimeError

                return _real_signal(sig, _wrapped)
            return _real_signal(sig, handler)

        _signal.signal = _intercept_signal
        try:
            server.run()
        finally:
            _signal.signal = _real_signal

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
