"""
SSH config file parser and raw editor helpers.

Parses ``~/.ssh/config`` (or any OpenSSH client config) into structured
``SSHHostEntry`` objects for display in the Settings UI.  Also provides
read/write helpers for the raw file editor.
"""

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class SSHHostEntry:
    """A single ``Host`` block parsed from an SSH config file."""

    alias: str                           # The pattern after ``Host``
    hostname: str = ""                   # HostName directive
    user: str = ""                       # User directive
    port: int = 22                       # Port directive (default 22)
    identity_file: str = ""             # IdentityFile directive
    proxy_jump: str = ""                 # ProxyJump directive
    extra: dict = field(default_factory=dict)  # Any other directives

    def to_dict(self) -> dict:
        return {
            "alias": self.alias,
            "hostname": self.hostname,
            "user": self.user,
            "port": self.port,
            "identity_file": self.identity_file,
            "proxy_jump": self.proxy_jump,
        }


def parse_ssh_config(path: Optional[str] = None) -> List[SSHHostEntry]:
    """Parse an SSH config file and return concrete (non-wildcard) host entries.

    Args:
        path: Path to the SSH config file.  Defaults to ``~/.ssh/config``.

    Returns:
        List of :class:`SSHHostEntry` objects, one per non-wildcard ``Host``
        block found in the file.
    """
    if path is None:
        path = os.path.expanduser("~/.ssh/config")
    else:
        path = os.path.expanduser(path)

    if not os.path.exists(path):
        return []

    entries: List[SSHHostEntry] = []
    current: Optional[SSHHostEntry] = None

    with open(path, "r", errors="replace") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            # Accept both "Key Value" and "Key=Value" (with optional spaces)
            m = re.match(r"^(\w+)\s*[=\s]\s*(.+)$", line)
            if not m:
                continue

            key = m.group(1).strip().lower()
            value = m.group(2).strip()

            if key == "host":
                if current is not None and "*" not in current.alias:
                    entries.append(current)
                current = SSHHostEntry(alias=value)
            elif current is not None:
                if key == "hostname":
                    current.hostname = value
                elif key == "user":
                    current.user = value
                elif key == "port":
                    try:
                        current.port = int(value)
                    except ValueError:
                        pass
                elif key == "identityfile":
                    current.identity_file = value
                elif key == "proxyjump":
                    current.proxy_jump = value
                else:
                    current.extra[key] = value

    if current is not None and "*" not in current.alias:
        entries.append(current)

    return entries


def read_ssh_config_raw(path: Optional[str] = None) -> str:
    """Return the raw text content of the SSH config file.

    Returns an empty string if the file does not exist.
    """
    if path is None:
        path = os.path.expanduser("~/.ssh/config")
    else:
        path = os.path.expanduser(path)

    if not os.path.exists(path):
        return ""
    with open(path, "r", errors="replace") as fh:
        return fh.read()


def write_ssh_config_raw(content: str, path: Optional[str] = None) -> None:
    """Write *content* to the SSH config file (atomic write with .bak backup).

    Args:
        content: New file content.
        path: Destination path.  Defaults to ``~/.ssh/config``.

    Raises:
        OSError: If the file cannot be written.
    """
    if path is None:
        path = os.path.expanduser("~/.ssh/config")
    else:
        path = os.path.expanduser(path)

    ssh_dir = os.path.dirname(path)
    os.makedirs(ssh_dir, exist_ok=True)

    # Back up the existing file before overwriting
    if os.path.exists(path):
        backup = path + ".bak"
        with open(path, "r", errors="replace") as src, open(backup, "w") as dst:
            dst.write(src.read())

    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(content)
    os.replace(tmp, path)
