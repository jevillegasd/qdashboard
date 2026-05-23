"""
Centralized configuration management for QDashboard.

This module provides utilities for accessing configuration consistently
across all modules and avoiding hardcoded values.
"""

import os
from typing import Dict, Any, Optional


class ConfigError(Exception):
    """Exception raised for configuration-related errors."""
    pass


# Module-level config store — set once at startup via set_config()
_config: Dict[str, Any] = {}


def set_config(config: Dict[str, Any]) -> None:
    """Store the application configuration at startup."""
    global _config
    _config = config


def get_config() -> Dict[str, Any]:
    """Return the current application configuration, or raise ConfigError if not set."""
    if not _config:
        raise ConfigError(
            "Application configuration not available. "
            "Call set_config() before accessing config values."
        )
    return _config


def get_config_value(key: str, default: Any = None) -> Any:
    """Return config[key], or *default* if the key is absent or config is unset."""
    try:
        return get_config().get(key, default)
    except ConfigError:
        return default


def get_temp_dir() -> str:
    """Get the temporary directory path from config."""
    return get_config_value('temp_dir', '/tmp')


def get_data_dir() -> str:
    """Get the data directory path from config."""
    return get_config_value('data_dir', os.path.expanduser('~/.qdashboard/data'))


def get_logs_dir() -> str:
    """Get the logs directory path from config."""
    return get_config_value('logs_dir', os.path.expanduser('~/.qdashboard/logs'))


def get_home_path() -> str:
    """Get the home path from config."""
    return get_config_value('home_path', os.path.expanduser('~'))


def get_root_path() -> str:
    """Get the root serving path from config."""
    return get_config_value('root', os.path.expanduser('~'))


def get_qd_root() -> str:
    """Get the QDashboard root directory from config."""
    return get_config_value('qd_root', os.path.expanduser('~/.qdashboard'))


def get_host() -> str:
    """Get the server host from config."""
    return get_config_value('host', '127.0.0.1')


def get_port() -> int:
    """Get the server port from config."""
    return get_config_value('port', 5005)


def get_auth_key() -> str:
    """Get the authentication key from config."""
    return get_config_value('key', '')


def get_environment() -> Optional[str]:
    """Get the environment from config."""
    return get_config_value('environment')


def ensure_directory_exists(directory_path: str) -> str:
    """Create *directory_path* if it does not exist and return its absolute path."""
    abs_path = os.path.abspath(directory_path)
    os.makedirs(abs_path, exist_ok=True)
    return abs_path


def validate_config(config: Dict[str, Any]) -> None:
    """Validate *config* values and create required runtime directories."""
    port = config.get('port', 5005)
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise ConfigError(f"Port number must be between 1 and 65535, got {port}")

    root = config.get('root')
    if root and not os.path.exists(root):
        raise ConfigError(f"Root directory does not exist: {root}")

    qd_root = config.get('qd_root')
    if qd_root:
        try:
            for subdir in ('logs', 'data', 'temp'):
                ensure_directory_exists(os.path.join(qd_root, subdir))
        except OSError as e:
            raise ConfigError(f"Cannot create QDashboard directories: {e}") from e


DEFAULT_PORT = 5005
DEFAULT_HOST = '127.0.0.1'
DEFAULT_QD_ROOT = os.path.expanduser('~/.qdashboard')
DEFAULT_TEMP_DIR = '/tmp'