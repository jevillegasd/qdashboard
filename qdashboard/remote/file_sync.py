"""
Experiment data synchronisation — pull results from the remote to local storage.

After a job completes on the remote cluster the ``output/`` directory (qibocal
results), ``runcard.yml``, and ``experiment_metadata.json`` are downloaded
via asyncssh SFTP into the local ``data_dir`` so that all visualisation,
history queries, and DB operations work entirely locally.
"""

import asyncio
import os
from typing import List, Tuple

from ..utils.logger import get_logger

logger = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Low-level SFTP helpers                                                       #
# --------------------------------------------------------------------------- #

async def _resolve_remote_home(ssh_manager) -> str:
    """Return the home directory on the remote machine."""
    try:
        stdout, _, _ = await ssh_manager.run("echo $HOME", timeout=10)
        return stdout.strip()
    except Exception:
        return ""


def _expand_remote(path: str, remote_home: str) -> str:
    """Expand a leading ``~`` in *path* using *remote_home*."""
    if path.startswith("~/") or path == "~":
        return path.replace("~", remote_home, 1)
    return path


async def _sftp_download_dir(
    sftp, remote_dir: str, local_dir: str
) -> List[str]:
    """Recursively download *remote_dir* into *local_dir* via SFTP.

    Returns the list of local paths written.
    """
    try:
        import asyncssh  # type: ignore[import]
    except ImportError:
        logger.error("asyncssh not available; cannot download via SFTP.")
        return []

    os.makedirs(local_dir, exist_ok=True)
    copied: List[str] = []

    try:
        entries = await sftp.readdir(remote_dir)
    except Exception as exc:
        logger.debug("Cannot list remote dir %s: %s", remote_dir, exc)
        return copied

    for entry in entries:
        name = entry.filename
        if name in (".", ".."):
            continue
        remote_path = f"{remote_dir}/{name}"
        local_path = os.path.join(local_dir, name)

        # Directory — recurse
        if entry.attrs.type == asyncssh.FILEXFER_TYPE_DIRECTORY:
            sub = await _sftp_download_dir(sftp, remote_path, local_path)
            copied.extend(sub)
        else:
            try:
                await sftp.get(remote_path, local_path)
                copied.append(local_path)
            except Exception as exc:
                logger.warning(
                    "SFTP get failed for %s → %s: %s", remote_path, local_path, exc
                )

    return copied


# --------------------------------------------------------------------------- #
# Public sync functions                                                        #
# --------------------------------------------------------------------------- #

async def sync_experiment_from_remote(
    experiment_id: str,
    platform: str,
    date_str: str,
    settings,
    ssh_manager,
    local_data_dir: str,
) -> List[str]:
    """Pull one experiment's data from the remote to *local_data_dir*.

    Downloads ``output/``, ``runcard.yml``, and ``experiment_metadata.json``
    (skipping files that already exist locally).

    Returns:
        List of local file paths that were written.
    """
    try:
        sftp = await ssh_manager.get_sftp()
    except Exception as exc:
        logger.error("Cannot open SFTP client: %s", exc)
        return []

    remote_home = await _resolve_remote_home(ssh_manager)
    remote_exp_dir = _expand_remote(
        f"{settings.remote_root}/{platform}/{date_str}/{experiment_id}",
        remote_home,
    )
    local_exp_dir = os.path.abspath(
        os.path.join(local_data_dir, platform, date_str, experiment_id)
    )
    os.makedirs(local_exp_dir, exist_ok=True)

    copied: List[str] = []

    async with sftp:
        # Download the qibocal output directory
        remote_output = f"{remote_exp_dir}/output"
        local_output = os.path.join(local_exp_dir, "output")
        output_files = await _sftp_download_dir(sftp, remote_output, local_output)
        copied.extend(output_files)

        # Download ancillary files (skip if already present locally)
        for fname in ("experiment_metadata.json", "runcard.yml"):
            local_file = os.path.join(local_exp_dir, fname)
            if os.path.exists(local_file):
                continue
            remote_file = f"{remote_exp_dir}/{fname}"
            try:
                await sftp.get(remote_file, local_file)
                copied.append(local_file)
            except Exception:
                pass  # file may not exist; non-fatal

    logger.info(
        "Synced %d file(s) for experiment %s", len(copied), experiment_id
    )
    return copied


async def check_remote_experiment_complete(
    experiment_id: str,
    platform: str,
    date_str: str,
    settings,
    ssh_manager,
) -> bool:
    """Return ``True`` if ``output/meta.json`` exists on the remote."""
    remote_home = await _resolve_remote_home(ssh_manager)
    remote_exp_dir = _expand_remote(
        f"{settings.remote_root}/{platform}/{date_str}/{experiment_id}",
        remote_home,
    )
    meta_path = f"{remote_exp_dir}/output/meta.json"
    stdout, _, _ = await ssh_manager.run(
        f"test -f {meta_path} && echo exists || echo missing",
        timeout=10,
    )
    return stdout.strip() == "exists"


async def sync_all_completed(
    settings,
    ssh_manager,
    local_data_dir: str,
) -> dict:
    """Scan the remote data directory and pull any completed experiments that are
    not yet fully present locally.

    Returns:
        Dict with ``synced`` (int) and ``errors`` (int) counts.
    """
    remote_home = await _resolve_remote_home(ssh_manager)
    remote_data_dir = _expand_remote(
        f"{settings.remote_root}/data",
        remote_home,
    )

    stdout, _, rc = await ssh_manager.run(
        f"find {remote_data_dir} -name 'experiment_metadata.json' 2>/dev/null",
        timeout=30,
    )
    if rc != 0 and not stdout.strip():
        return {"synced": 0, "errors": 0}

    synced = 0
    errors = 0
    for metadata_path in stdout.strip().splitlines():
        # Expected layout:  remote_data_dir/<platform>/<date>/<exp_id>/experiment_metadata.json
        parts = metadata_path.split("/")
        if len(parts) < 4:
            continue
        experiment_id = parts[-2]
        date_str = parts[-3]
        platform = parts[-4]

        # Skip if already fully synced (output/meta.json exists locally)
        local_meta = os.path.join(
            local_data_dir, platform, date_str, experiment_id, "output", "meta.json"
        )
        if os.path.exists(local_meta):
            continue

        # Only sync if the experiment is actually complete on the remote
        complete = await check_remote_experiment_complete(
            experiment_id, platform, date_str, settings, ssh_manager
        )
        if not complete:
            continue

        try:
            files = await sync_experiment_from_remote(
                experiment_id, platform, date_str,
                settings, ssh_manager, local_data_dir,
            )
            if files:
                synced += 1
        except Exception as exc:
            logger.warning("Sync failed for %s: %s", experiment_id, exc)
            errors += 1

    return {"synced": synced, "errors": errors}


# --------------------------------------------------------------------------- #
# SFTP upload helpers (used during remote submission)                          #
# --------------------------------------------------------------------------- #

async def sftp_upload_file(
    local_path: str, remote_path: str, ssh_manager
) -> None:
    """Upload a single local file to *remote_path* via SFTP."""
    sftp = await ssh_manager.get_sftp()
    async with sftp:
        # Ensure the remote directory exists
        remote_dir = "/".join(remote_path.split("/")[:-1])
        if remote_dir:
            await sftp.makedirs(remote_dir, exist_ok=True)
        await sftp.put(local_path, remote_path)


async def sftp_upload_text(
    content: str, remote_path: str, ssh_manager
) -> None:
    """Write *content* as a UTF-8 text file at *remote_path* via SFTP."""
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".tmp", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        await sftp_upload_file(tmp_path, remote_path, ssh_manager)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
