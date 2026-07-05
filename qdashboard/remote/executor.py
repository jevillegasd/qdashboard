"""
Command executor abstraction and SLURM client.

Provides a uniform interface for running shell commands either locally
(via asyncio subprocess) or on a remote host (via SSHConnectionManager).
The ``RemoteSlurmClient`` wraps the SLURM commands through either executor.
"""

import asyncio
from typing import List, Tuple

from ..utils.logger import get_logger

logger = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Executor base classes                                                        #
# --------------------------------------------------------------------------- #

class LocalExecutor:
    """Run commands as local asyncio subprocesses."""

    async def run(self, cmd: str, timeout: int = 30) -> Tuple[str, str, int]:
        """Execute *cmd* in a local shell.

        Returns:
            ``(stdout, stderr, exit_code)``
        """
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            return stdout_b.decode(errors="replace"), stderr_b.decode(errors="replace"), proc.returncode
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return "", f"Command timed out after {timeout}s", -1
        except Exception as exc:
            return "", str(exc), -1


class RemoteExecutor:
    """Run commands via :class:`~qdashboard.remote.connection.SSHConnectionManager`."""

    def __init__(self, ssh_manager) -> None:
        self._manager = ssh_manager

    async def run(self, cmd: str, timeout: int = 30) -> Tuple[str, str, int]:
        """Execute *cmd* on the remote host.

        Returns:
            ``(stdout, stderr, exit_code)``
        """
        return await self._manager.run(cmd, timeout=timeout)


def get_executor(settings, ssh_manager):
    """Return the appropriate executor for the current execution mode.

    Args:
        settings: :class:`~qdashboard.remote.settings.RemoteSettings` instance.
        ssh_manager: :class:`~qdashboard.remote.connection.SSHConnectionManager`
            instance attached to ``app.state``.

    Returns:
        :class:`LocalExecutor` or :class:`RemoteExecutor`.
    """
    if settings.is_remote():
        return RemoteExecutor(ssh_manager)
    return LocalExecutor()


# --------------------------------------------------------------------------- #
# SLURM client                                                                 #
# --------------------------------------------------------------------------- #

class RemoteSlurmClient:
    """
    SLURM command wrapper that executes via a :class:`LocalExecutor` or
    :class:`RemoteExecutor`.

    This replaces the direct ``subprocess`` calls in ``qpu/slurm.py`` when
    running in remote mode.
    """

    #: SLURM states that mean a job is still alive in the queue
    ACTIVE_STATES = frozenset(
        {"PENDING", "RUNNING", "COMPLETING", "CONFIGURING", "RESIZING", "SUSPENDED"}
    )

    def __init__(self, executor) -> None:
        self._exec = executor

    async def get_queue(self) -> List[dict]:
        """Return the current SLURM queue as a list of job dicts."""
        stdout, _, rc = await self._exec.run(
            "squeue --format='%i %.18j %.8u %.8T %.10M %.9l %.6D %P %R' --noheader",
            timeout=15,
        )
        if rc != 0:
            return []

        jobs = []
        for line in stdout.strip().splitlines():
            # Strip surrounding quotes that some squeue versions emit
            line = line.strip("'\" ")
            parts = line.split()
            if len(parts) >= 8 and parts[7] != "sim":
                jobs.append(
                    {
                        "job_id": parts[0],
                        "name": parts[1],
                        "user": parts[2],
                        "state": parts[3],
                        "time": parts[4],
                        "time_limit": parts[5],
                        "nodes": parts[6],
                        "partition": parts[7],
                        "nodelist": " ".join(parts[8:]),
                    }
                )
        return jobs

    async def check_job_status(self, job_id: str) -> str:
        """Return the SLURM state of *job_id*, or ``'UNKNOWN'`` if not in queue."""
        stdout, _, _ = await self._exec.run(
            f"squeue -j {job_id} --noheader --format=%T",
            timeout=10,
        )
        lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
        return lines[0] if lines else "UNKNOWN"

    async def submit(self, script_path: str) -> Tuple[bool, str, str]:
        """Submit *script_path* via ``sbatch``.

        Returns:
            ``(success, message, job_id)`` — *job_id* is empty on failure.
        """
        stdout, stderr, rc = await self._exec.run(
            f"sbatch {script_path}", timeout=30
        )
        if rc == 0:
            job_id = ""
            for line in stdout.splitlines():
                if "Submitted batch job" in line:
                    job_id = line.split()[-1]
                    break
            logger.info("SLURM job submitted: job_id=%s", job_id)
            return True, stdout.strip(), job_id
        logger.error("sbatch failed (rc=%d): %s", rc, stderr.strip())
        return False, stderr.strip(), ""

    async def cancel(self, job_id: str) -> Tuple[bool, str]:
        """Cancel a SLURM job via ``scancel``.

        Returns:
            ``(success, message)``
        """
        _, stderr, rc = await self._exec.run(
            f"scancel {job_id}", timeout=15
        )
        if rc == 0:
            return True, "Job cancelled."
        return False, stderr.strip()

    async def run_direct(self, cmd: str, timeout: int = 3600) -> Tuple[bool, str]:
        """Run *cmd* directly (no sbatch) — used in ``*_direct`` execution modes.

        The command is launched via ``nohup … &`` so it continues running
        after the SSH session ends.  Returns immediately; no job ID is
        available.

        Returns:
            ``(success, message)``
        """
        wrapped = f"nohup {cmd} > /dev/null 2>&1 & echo $!"
        stdout, stderr, rc = await self._exec.run(wrapped, timeout=30)
        if rc == 0:
            pid = stdout.strip()
            return True, f"Process started (PID {pid})"
        return False, stderr.strip()
