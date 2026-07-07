"""
SSH connection manager for remote execution mode.

Uses ``asyncssh`` (if installed) for async-native SSH connectivity that fits
naturally into FastAPI's event loop.  The manager is attached to
``app.state.ssh_manager`` at startup and shared across all request handlers.

Usage::

    # In a route handler
    manager = request.app.state.ssh_manager
    await manager.connect(settings)
    stdout, stderr, rc = await manager.run("squeue --noheader")
"""

import asyncio
import os
import time
from typing import Optional, Tuple

from ..utils.logger import get_logger

logger = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Custom exception                                                             #
# --------------------------------------------------------------------------- #

class SSHConnectionError(Exception):
    """Raised when an SSH operation cannot be completed."""


# --------------------------------------------------------------------------- #
# Optional asyncssh import                                                     #
# --------------------------------------------------------------------------- #

try:
    import asyncssh  # type: ignore[import]
    _ASYNCSSH_AVAILABLE = True
except ImportError:
    _ASYNCSSH_AVAILABLE = False


# --------------------------------------------------------------------------- #
# Connection manager                                                           #
# --------------------------------------------------------------------------- #

class SSHConnectionManager:
    """
    Persistent asyncssh SSH connection, shared across request handlers.

    Thread-safety: The underlying :class:`asyncio.Lock` ensures that only one
    coroutine opens or closes the connection at a time.  ``run()`` and
    ``get_sftp()`` can be called concurrently once connected.
    """

    def __init__(self) -> None:
        self._connection: Optional["asyncssh.SSHClientConnection"] = None  # type: ignore[name-defined]
        self._jump_connection: Optional["asyncssh.SSHClientConnection"] = None  # type: ignore[name-defined]
        self._settings = None          # RemoteSettings stored at connect time
        self._connected_at: Optional[float] = None
        self._is_connected: bool = False
        self._lock: asyncio.Lock = asyncio.Lock()
        # Separate from `_lock` (which guards close+create inside connect()/
        # disconnect()) — this one coalesces concurrent auto-reconnect
        # attempts from run()/get_sftp() so two overlapping callers don't
        # each tear down and replace the connection out from under the other.
        self._reconnect_lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    @property
    def asyncssh_available(self) -> bool:
        return _ASYNCSSH_AVAILABLE

    def is_connected(self) -> bool:
        """Return True when an active SSH connection is held."""
        return self._is_connected and self._connection is not None

    async def connect(self, settings) -> None:
        """Open (or re-open) an SSH connection using *settings*.

        Args:
            settings: :class:`~qdashboard.remote.settings.RemoteSettings` instance.

        Raises:
            :class:`SSHConnectionError`: If the connection cannot be established.
        """
        if not _ASYNCSSH_AVAILABLE:
            raise SSHConnectionError(
                "asyncssh is not installed.  Run: pip install 'asyncssh>=2.14'"
            )

        async with self._lock:
            await self._close_connections()

            auth_kwargs: dict = {}
            if settings.ssh_key_path:
                key_path = os.path.expanduser(settings.ssh_key_path)
                if not os.path.exists(key_path):
                    raise SSHConnectionError(
                        f"SSH key file not found: {key_path}"
                    )
                auth_kwargs["client_keys"] = [key_path]
            if settings.use_ssh_agent:
                # asyncssh uses the system agent automatically when
                # client_keys is not set, or alongside it.
                auth_kwargs.setdefault("agent_path", None)  # use default agent socket

            conn_kwargs: dict = {
                "host": settings.remote_host,
                "port": settings.remote_port,
                "username": settings.remote_user,
                "known_hosts": None,  # TODO: use known_hosts for production
                **auth_kwargs,
            }

            # ProxyJump: first open a tunnel connection, then use it
            if settings.proxy_jump:
                try:
                    jump_host, jump_port, jump_user = _parse_jump_target(
                        settings.proxy_jump, settings.remote_user
                    )
                    self._jump_connection = await asyncssh.connect(
                        jump_host,
                        port=jump_port,
                        username=jump_user,
                        known_hosts=None,
                        **auth_kwargs,
                    )
                    conn_kwargs["tunnel"] = self._jump_connection
                    logger.debug(
                        "ProxyJump tunnel opened via %s@%s:%d",
                        jump_user, jump_host, jump_port,
                    )
                except Exception as exc:
                    raise SSHConnectionError(
                        f"ProxyJump to '{settings.proxy_jump}' failed: {exc}"
                    ) from exc

            try:
                self._connection = await asyncssh.connect(**conn_kwargs)
                self._settings = settings
                self._connected_at = time.time()
                self._is_connected = True
                logger.info(
                    "SSH connected to %s@%s:%d",
                    settings.remote_user,
                    settings.remote_host,
                    settings.remote_port,
                )
            except asyncssh.DisconnectError as exc:
                raise SSHConnectionError(f"Connection refused: {exc}") from exc
            except asyncssh.PermissionDenied as exc:
                raise SSHConnectionError(f"Authentication failed: {exc}") from exc
            except Exception as exc:
                raise SSHConnectionError(f"Connection failed: {exc}") from exc

    async def disconnect(self) -> None:
        """Close the SSH connection gracefully."""
        async with self._lock:
            await self._close_connections()
            logger.info("SSH connection closed")

    async def _ensure_connected(self) -> None:
        """Reconnect if needed, coalescing concurrent reconnect attempts.

        Multiple coroutines (background sync, route handlers, job
        submission) share one manager. Without coalescing, two callers that
        both observe ``is_connected() == False`` at the same time would each
        call :meth:`connect`, and the second one's close-and-reopen would
        yank the connection out from under the first — every in-flight
        remote operation then fails with a "connection is closing" style
        error. The double-checked lock here ensures only one of them
        actually reconnects; the rest just wait and reuse the result.
        """
        if self.is_connected():
            return
        async with self._reconnect_lock:
            if self.is_connected():
                return
            if self._settings is None:
                raise SSHConnectionError(
                    "Not connected to remote host.  Call connect() first."
                )
            logger.debug("SSH connection lost; attempting reconnect…")
            await self.connect(self._settings)

    async def run(
        self, cmd: str, timeout: int = 30
    ) -> Tuple[str, str, int]:
        """Execute *cmd* on the remote host.

        Returns:
            Tuple of ``(stdout, stderr, exit_code)``.

        Raises:
            :class:`SSHConnectionError`: If not connected or the command fails.
        """
        await self._ensure_connected()

        try:
            result = await asyncio.wait_for(
                self._connection.run(cmd, check=False),
                timeout=timeout,
            )
            return (
                result.stdout or "",
                result.stderr or "",
                result.exit_status if result.exit_status is not None else 0,
            )
        except asyncio.TimeoutError:
            raise SSHConnectionError(
                f"Remote command timed out after {timeout}s: {cmd!r}"
            )
        except Exception as exc:
            # Only tear down the *shared* connection state if the connection
            # itself is actually dead — a single rejected channel (e.g. the
            # server's MaxSessions cap) is a transient, per-call failure and
            # must not make every other concurrent caller think the whole
            # connection is gone.
            if self._connection is None or self._connection.is_closed():
                self._is_connected = False
                self._connection = None
            raise SSHConnectionError(f"Remote command failed: {exc}") from exc

    async def get_sftp(self) -> "asyncssh.SFTPClient":  # type: ignore[name-defined]
        """Return an asyncssh SFTP client for the current connection.

        The caller is responsible for closing the SFTP client (use as async
        context manager: ``async with await manager.get_sftp() as sftp: ...``).
        """
        await self._ensure_connected()
        try:
            return await self._connection.start_sftp_client()
        except Exception as exc:
            if self._connection is None or self._connection.is_closed():
                self._is_connected = False
                self._connection = None
            raise SSHConnectionError(f"Failed to open SFTP session: {exc}") from exc

    def status_dict(self) -> dict:
        """Return a JSON-serialisable connection status summary."""
        return {
            "connected": self.is_connected(),
            "host": self._settings.remote_host if self._settings else None,
            "user": self._settings.remote_user if self._settings else None,
            "port": self._settings.remote_port if self._settings else None,
            "connected_at": self._connected_at,
            "asyncssh_available": _ASYNCSSH_AVAILABLE,
        }

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    async def _close_connections(self) -> None:
        """Close main + jump connections without holding the lock."""
        if self._connection is not None:
            try:
                self._connection.close()
                await self._connection.wait_closed()
            except Exception:
                pass
            self._connection = None
        if self._jump_connection is not None:
            try:
                self._jump_connection.close()
                await self._jump_connection.wait_closed()
            except Exception:
                pass
            self._jump_connection = None
        self._is_connected = False
        self._connected_at = None


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _parse_jump_target(
    jump_str: str, default_user: str
) -> Tuple[str, int, str]:
    """Parse a ProxyJump string like ``user@host:port`` into components.

    Falls back to *default_user* and port 22 when not specified.
    """
    user = default_user
    port = 22
    host = jump_str

    if "@" in jump_str:
        user_part, host_part = jump_str.rsplit("@", 1)
        user = user_part
        host = host_part
    else:
        host_part = jump_str

    if ":" in host:
        host, port_str = host.rsplit(":", 1)
        try:
            port = int(port_str)
        except ValueError:
            pass

    return host, port, user
