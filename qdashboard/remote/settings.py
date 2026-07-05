"""
Remote execution settings — persistence and access helpers.

Settings are stored in ``<qd_root>/remote_settings.json`` so they can be
updated at runtime via the Settings UI without requiring a server restart.
"""

import json
import os
from dataclasses import dataclass, asdict, fields as dc_fields
from typing import Optional

SETTINGS_FILE = "remote_settings.json"

# Valid execution modes
EXECUTION_MODES = frozenset(
    {"local_slurm", "local_direct", "remote_slurm", "remote_direct"}
)


@dataclass
class RemoteSettings:
    """All settings that control how/where experiments are executed."""

    # ------------------------------------------------------------------ #
    # Execution mode                                                       #
    # ------------------------------------------------------------------ #
    # local_slurm   — existing behaviour: sbatch runs on this machine
    # local_direct  — run `qq` directly on this machine (no sbatch)
    # remote_slurm  — SSH to remote; submit via sbatch there
    # remote_direct — SSH to remote; run `qq` directly there
    execution_mode: str = "local_slurm"

    # ------------------------------------------------------------------ #
    # Remote server                                                        #
    # ------------------------------------------------------------------ #
    remote_host: str = ""
    remote_user: str = ""
    remote_port: int = 22
    # Working root directory on the remote machine (~ is resolved on remote)
    remote_root: str = "~/.qdashboard"
    # Path to venv or conda env on the remote machine (e.g. ~/envs/qibocal)
    remote_environment: str = ""
    # Path to QIBOLAB_PLATFORMS on the remote machine.
    # Leave empty to reuse the same path as the local QIBOLAB_PLATFORMS env var
    # (works for NFS-mounted or identically-structured remote systems).
    remote_platforms_path: str = ""

    # ------------------------------------------------------------------ #
    # SSH authentication                                                   #
    # ------------------------------------------------------------------ #
    # Path to the private key file on the LOCAL machine
    ssh_key_path: str = ""
    # Whether to attempt SSH agent authentication in addition to key file
    use_ssh_agent: bool = True

    # ------------------------------------------------------------------ #
    # Proxy jump                                                           #
    # ------------------------------------------------------------------ #
    # ProxyJump destination (e.g. "user@jumphost.example.com" or just
    # the alias in ~/.ssh/config).  Leave empty for direct connections.
    proxy_jump: str = ""

    # ------------------------------------------------------------------ #
    # Data sync                                                            #
    # ------------------------------------------------------------------ #
    auto_sync: bool = True
    sync_interval: int = 30  # seconds between background poll cycles

    # ------------------------------------------------------------------ #
    # Convenience helpers                                                  #
    # ------------------------------------------------------------------ #
    def is_remote(self) -> bool:
        """Return True when experiments run on a remote machine."""
        return self.execution_mode.startswith("remote_")

    def uses_slurm(self) -> bool:
        """Return True when job submission goes through sbatch."""
        return self.execution_mode.endswith("_slurm")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "RemoteSettings":
        known = {f.name for f in dc_fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known}
        instance = cls(**filtered)
        if instance.execution_mode not in EXECUTION_MODES:
            instance.execution_mode = "local_slurm"
        return instance


# --------------------------------------------------------------------------- #
# Persistence                                                                  #
# --------------------------------------------------------------------------- #

def _settings_path(qd_root: str) -> str:
    return os.path.join(os.path.expanduser(qd_root), SETTINGS_FILE)


def load_remote_settings(qd_root: str) -> RemoteSettings:
    """Load remote settings from disk.  Returns defaults if file is missing or corrupt."""
    path = _settings_path(qd_root)
    if not os.path.exists(path):
        return RemoteSettings()
    try:
        with open(path, "r") as fh:
            data = json.load(fh)
        return RemoteSettings.from_dict(data)
    except Exception:
        return RemoteSettings()


def save_remote_settings(settings: RemoteSettings, qd_root: str) -> None:
    """Persist remote settings to disk (atomic write)."""
    path = _settings_path(qd_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(settings.to_dict(), fh, indent=2)
    os.replace(tmp, path)
