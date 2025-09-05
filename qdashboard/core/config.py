"""
Centralized configuration management for QDashboard.

This module provides utilities for accessing configuration consistently
across all modules and avoiding hardcoded values.
"""

import os
from typing import Dict, Any, Optional
from flask import current_app


class ConfigError(Exception):
    """Exception raised for configuration-related errors."""
    pass


def get_app_config() -> Dict[str, Any]:
    """
    Get the current application configuration.
    
    Returns:
        Dict containing the application configuration
        
    Raises:
        ConfigError: If configuration is not available
    """
    try:
        return current_app.config['QDASHBOARD_CONFIG']
    except (RuntimeError, KeyError) as e:
        raise ConfigError(
            "Application configuration not available. "
            "This function must be called within a Flask application context."
        ) from e


def get_config_value(key: str, default: Any = None) -> Any:
    """
    Get a specific configuration value.
    
    Args:
        key: Configuration key to retrieve
        default: Default value if key is not found
        
    Returns:
        Configuration value or default
    """
    try:
        config = get_app_config()
        return config.get(key, default)
    except ConfigError:
        # Fallback for cases outside Flask context
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
    """
    Ensure a directory exists, creating it if necessary.
    
    Args:
        directory_path: Path to the directory
        
    Returns:
        The absolute path to the directory
        
    Raises:
        OSError: If directory cannot be created
    """
    abs_path = os.path.abspath(directory_path)
    os.makedirs(abs_path, exist_ok=True)  # Core implementation - don't change to avoid recursion
    return abs_path


def validate_config(config: Dict[str, Any]) -> None:
    """
    Validate configuration values and ensure required directories exist.
    
    Args:
        config: Configuration dictionary to validate
        
    Raises:
        ConfigError: If configuration is invalid
    """
    # Validate port range
    port = config.get('port', 5005)
    if not isinstance(port, int) or not (1 <= port <= 65535):
        raise ConfigError(f"Port number must be between 1 and 65535, got {port}")
    
    # Validate root directory
    root = config.get('root')
    if root and not os.path.exists(root):
        raise ConfigError(f"Root directory does not exist: {root}")
    
    # Ensure QDashboard directories exist
    qd_root = config.get('qd_root')
    if qd_root:
        try:
            ensure_directory_exists(os.path.join(qd_root, 'logs'))
            ensure_directory_exists(os.path.join(qd_root, 'data'))
            ensure_directory_exists(os.path.join(qd_root, 'temp'))
        except OSError as e:
            raise ConfigError(f"Cannot create QDashboard directories: {e}") from e


# Constants for default values - centralized in one place
DEFAULT_PORT = 5005
DEFAULT_HOST = '127.0.0.1'
DEFAULT_QD_ROOT = os.path.expanduser('~/.qdashboard')
DEFAULT_TEMP_DIR = '/tmp'