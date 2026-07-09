"""
Remote execution support for QDashboard.

This package provides SSH-based remote execution, data synchronisation, and
settings persistence so the dashboard can run locally while submitting jobs to
a remote SLURM cluster.
"""

from .settings import RemoteSettings, load_remote_settings, save_remote_settings
from .connection import SSHConnectionManager, SSHConnectionError

__all__ = [
    "RemoteSettings",
    "load_remote_settings",
    "save_remote_settings",
    "SSHConnectionManager",
    "SSHConnectionError",
]
