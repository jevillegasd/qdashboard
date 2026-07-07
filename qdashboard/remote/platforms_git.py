"""
Remote-host git operations for the qibolab platforms repository, plus the
local read-only mirror sync.

Mirrors the shape of the sync, subprocess-based functions in
``qdashboard/qpu/platforms.py`` but executes every git command on the remote
host via :class:`~qdashboard.remote.connection.SSHConnectionManager`, so that
when ``execution_mode`` is ``remote_*`` all git mutations (branch switch,
commit, stash, discard, push) happen on the machine that actually owns the
platform files — never on the local dashboard host.

Local mode is completely unaffected: ``qpu/platforms.py`` keeps running
unmodified subprocess-based git commands against the local checkout.
"""

import os
import shlex
import shutil
from typing import List, Optional

from ..utils.logger import get_logger
from .file_sync import _resolve_remote_home, _expand_remote, _sftp_download_dir, sftp_upload_text

logger = get_logger(__name__)


def _q(value: str) -> str:
    """Shell-quote a value for interpolation into a remote command string."""
    return shlex.quote(value)


# --------------------------------------------------------------------------- #
# Path resolution                                                              #
# --------------------------------------------------------------------------- #

async def resolve_remote_platforms_path(settings, ssh_manager) -> str:
    """Resolve the qibolab platforms directory on the remote host.

    Resolution order:
      1. ``settings.remote_platforms_path`` (with ``~`` expanded to the
         remote ``$HOME``), if set.
      2. The remote host's own ``$QIBOLAB_PLATFORMS`` environment variable.
      3. ``~/qibolab_platforms_qrc`` on the remote host.
    """
    remote_home = await _resolve_remote_home(ssh_manager)

    if settings.remote_platforms_path:
        return _expand_remote(settings.remote_platforms_path, remote_home)

    try:
        stdout, _, rc = await ssh_manager.run("echo $QIBOLAB_PLATFORMS", timeout=10)
        env_path = stdout.strip()
        if rc == 0 and env_path:
            return env_path
    except Exception as exc:
        logger.debug("Could not read remote $QIBOLAB_PLATFORMS: %s", exc)

    return _expand_remote("~/qibolab_platforms_qrc", remote_home)


async def write_remote_file(ssh_manager, platforms_path: str, relative_path: str, content: str) -> None:
    """Write *content* to ``platforms_path/relative_path`` on the remote host.

    Used for non-git config edits (``parameters.json``, ``action_nodes.json``)
    made through the dashboard's JSON editors — these must land on the actual
    remote file, never on the local read-only mirror, or the edit would be
    silently discarded on the next mirror sync.
    """
    remote_path = f"{platforms_path.rstrip('/')}/{relative_path}"
    await sftp_upload_text(content, remote_path, ssh_manager)


# --------------------------------------------------------------------------- #
# Mirror sync                                                                  #
# --------------------------------------------------------------------------- #

async def sync_platforms_mirror(settings, ssh_manager, mirror_dir: str) -> dict:
    """Mirror the remote platforms directory into *mirror_dir* via SFTP.

    The mirror is a plain file cache (no ``.git``) used for fast local reads
    (QPU monitoring, topology, ``queues.json`` partition lookup) — it is never
    written to directly, and no git command is ever run against it locally.

    Returns ``{'success': bool, 'files_synced': int, 'error': str|None}``.
    """
    try:
        remote_path = await resolve_remote_platforms_path(settings, ssh_manager)
        sftp = await ssh_manager.get_sftp()
    except Exception as exc:
        logger.warning("Cannot sync platforms mirror: %s", exc)
        return {'success': False, 'files_synced': 0, 'error': str(exc)}

    os.makedirs(mirror_dir, exist_ok=True)
    copied: List[str] = []
    try:
        import asyncssh  # type: ignore[import]

        async with sftp:
            entries = await sftp.readdir(remote_path)
            # Download everything except .git (walk manually so we can skip it)
            for entry in entries:
                name = entry.filename
                if name in ('.', '..', '.git'):
                    continue
                remote_entry_path = f"{remote_path}/{name}"
                local_entry_path = os.path.join(mirror_dir, name)
                if entry.attrs.type == asyncssh.FILEXFER_TYPE_DIRECTORY:
                    copied.extend(
                        await _sftp_download_dir(sftp, remote_entry_path, local_entry_path, mirror=True)
                    )
                else:
                    try:
                        await sftp.get(remote_entry_path, local_entry_path)
                        copied.append(local_entry_path)
                    except Exception as exc:
                        logger.warning("SFTP get failed for %s: %s", remote_entry_path, exc)

        # Prune stale top-level entries no longer present on the remote (skip .git — we never write it)
        remote_names = {e.filename for e in entries if e.filename not in ('.', '..')}
        remote_names.add('.git')
        for name in os.listdir(mirror_dir):
            if name in remote_names:
                continue
            stale_path = os.path.join(mirror_dir, name)
            try:
                if os.path.isdir(stale_path):
                    shutil.rmtree(stale_path)
                else:
                    os.remove(stale_path)
            except OSError as exc:
                logger.warning("Failed to remove stale mirror entry %s: %s", stale_path, exc)

        logger.info("Synced %d file(s) into platforms mirror: %s", len(copied), mirror_dir)
        return {'success': True, 'files_synced': len(copied), 'error': None}
    except Exception as exc:
        logger.warning("Platforms mirror sync failed: %s", exc)
        return {'success': False, 'files_synced': len(copied), 'error': str(exc)}


# --------------------------------------------------------------------------- #
# Git read/write operations (executed on the remote host)                     #
# --------------------------------------------------------------------------- #

async def _is_git_repo(ssh_manager, platforms_path: str) -> bool:
    _, _, rc = await ssh_manager.run(f"test -d {_q(platforms_path)}/.git", timeout=10)
    return rc == 0


async def list_repository_branches(ssh_manager, platforms_path: str) -> Optional[dict]:
    """Remote equivalent of ``qpu.platforms.list_repository_branches``."""
    if not await _is_git_repo(ssh_manager, platforms_path):
        logger.warning("Not a git repository (remote): %s", platforms_path)
        return None

    path_q = _q(platforms_path)
    try:
        stdout, _, rc = await ssh_manager.run(f"git -C {path_q} branch --show-current", timeout=15)
        current_branch = stdout.strip()

        stdout, _, rc = await ssh_manager.run(
            f"git -C {path_q} branch --format='%(refname:short)'", timeout=15
        )
        local_branches = [b.strip() for b in stdout.splitlines() if b.strip()]

        await ssh_manager.run(f"git -C {path_q} fetch --all", timeout=30)

        stdout, _, rc = await ssh_manager.run(
            f"git -C {path_q} branch -r --format='%(refname:short)'", timeout=15
        )
        remote_branches = [
            b.strip() for b in stdout.splitlines()
            if b.strip() and not b.strip().endswith('/HEAD')
        ]

        return {'current': current_branch, 'local': local_branches, 'remote': remote_branches}
    except Exception as exc:
        logger.error("Unexpected error listing remote branches: %s", exc)
        return None


async def get_current_branch_info(ssh_manager, platforms_path: str) -> Optional[dict]:
    """Remote equivalent of ``qpu.platforms.get_current_branch_info``."""
    if not await _is_git_repo(ssh_manager, platforms_path):
        logger.warning("Not a git repository (remote): %s", platforms_path)
        return None

    path_q = _q(platforms_path)
    try:
        stdout, _, _ = await ssh_manager.run(f"git -C {path_q} branch --show-current", timeout=15)
        current_branch = stdout.strip()

        stdout, _, _ = await ssh_manager.run(f"git -C {path_q} rev-parse --short HEAD", timeout=15)
        current_commit = stdout.strip()

        stdout, _, _ = await ssh_manager.run(
            f"git -C {path_q} log -1 --pretty=format:%s", timeout=15
        )
        commit_message = stdout.strip()

        stdout, _, _ = await ssh_manager.run(f"git -C {path_q} status --porcelain", timeout=15)
        is_clean = not bool(stdout.strip())

        ahead, behind = 0, 0
        try:
            await ssh_manager.run(f"git -C {path_q} fetch", timeout=30)
            stdout, _, rc = await ssh_manager.run(
                f"git -C {path_q} rev-parse --abbrev-ref {shlex.quote(current_branch)}@{{upstream}}",
                timeout=15,
            )
            if rc == 0:
                upstream_branch = stdout.strip()
                stdout, _, rc = await ssh_manager.run(
                    f"git -C {path_q} rev-list --left-right --count "
                    f"{shlex.quote(upstream_branch)}...{shlex.quote(current_branch)}",
                    timeout=15,
                )
                if rc == 0 and stdout.strip():
                    behind, ahead = map(int, stdout.strip().split())
        except Exception:
            pass

        return {
            'branch': current_branch,
            'commit': current_commit,
            'commit_message': commit_message,
            'behind': behind,
            'ahead': ahead,
            'clean': is_clean,
        }
    except Exception as exc:
        logger.error("Unexpected error getting remote branch info: %s", exc)
        return None


async def switch_repository_branch(
    ssh_manager, platforms_path: str, branch_name: str,
    create_if_not_exists: bool = False, handle_changes: str = 'fail',
    auto_apply_stash: bool = True,
) -> dict:
    """Remote equivalent of ``qpu.platforms.switch_repository_branch``."""
    if not await _is_git_repo(ssh_manager, platforms_path):
        logger.warning("Not a git repository (remote): %s", platforms_path)
        return {'success': False, 'error': 'Not a git repository'}

    path_q = _q(platforms_path)
    branch_q = _q(branch_name)
    result = {
        'success': False, 'has_changes': False, 'changes_handled': None,
        'stash_created': None, 'stash_applied': None, 'stash_restored': False,
    }

    try:
        await ssh_manager.run(f"git -C {path_q} fetch --all", timeout=30)

        stdout, _, _ = await ssh_manager.run(f"git -C {path_q} status --porcelain", timeout=15)
        has_local_changes = bool(stdout.strip())
        result['has_changes'] = has_local_changes

        if has_local_changes:
            if handle_changes == 'fail':
                result['error'] = 'Local changes detected. Please choose how to handle them.'
                return result
            elif handle_changes == 'stash':
                stash_result = await stash_changes(
                    ssh_manager, platforms_path, f"Auto-stash before switching to {branch_name}"
                )
                if not stash_result['success']:
                    result['error'] = f"Failed to stash changes: {stash_result.get('error', 'Unknown error')}"
                    return result
                result['changes_handled'] = 'stashed'
                result['stash_created'] = stash_result.get('stash_name')
            elif handle_changes == 'commit':
                result['error'] = 'Commit option requires explicit commit message handling'
                return result

        _, _, local_rc = await ssh_manager.run(
            f"git -C {path_q} show-ref --verify --quiet refs/heads/{branch_q}", timeout=10
        )
        branch_exists_locally = local_rc == 0

        _, _, remote_rc = await ssh_manager.run(
            f"git -C {path_q} show-ref --verify --quiet refs/remotes/origin/{branch_q}", timeout=10
        )
        branch_exists_remotely = remote_rc == 0

        if branch_exists_locally:
            _, stderr, rc = await ssh_manager.run(f"git -C {path_q} checkout {branch_q}", timeout=30)
        elif branch_exists_remotely:
            _, stderr, rc = await ssh_manager.run(
                f"git -C {path_q} checkout -b {branch_q} origin/{branch_q}", timeout=30
            )
        elif create_if_not_exists:
            _, stderr, rc = await ssh_manager.run(f"git -C {path_q} checkout -b {branch_q}", timeout=30)
        else:
            result['error'] = f"Branch '{branch_name}' not found locally or remotely"
            return result

        if rc != 0:
            result['error'] = f"Failed to switch branch: {stderr.strip()}"
            return result

        if branch_exists_locally or branch_exists_remotely:
            await ssh_manager.run(f"git -C {path_q} pull", timeout=30)

        result['success'] = True

        if auto_apply_stash:
            stash_result = await apply_latest_stash(ssh_manager, platforms_path, pop=True)
            if stash_result['success']:
                result['stash_applied'] = stash_result.get('stash_applied')
                result['stash_restored'] = True
            # No stashes, or apply failed — non-fatal either way.

        return result
    except Exception as exc:
        logger.error("Unexpected error switching remote branch: %s", exc)
        result['error'] = f"Unexpected error switching branch: {exc}"
        return result


async def stash_changes(ssh_manager, platforms_path: str, stash_message: str = "WIP: Temporary stash") -> dict:
    """Remote equivalent of ``qpu.platforms.stash_changes``."""
    if not await _is_git_repo(ssh_manager, platforms_path):
        return {'success': False, 'error': 'Not a git repository'}

    path_q = _q(platforms_path)
    try:
        stdout, _, _ = await ssh_manager.run(f"git -C {path_q} status --porcelain", timeout=15)
        if not stdout.strip():
            return {'success': False, 'error': 'No changes to stash'}

        _, stderr, rc = await ssh_manager.run(
            f"git -C {path_q} stash push -u -m {_q(stash_message)}", timeout=30
        )
        if rc != 0:
            return {'success': False, 'error': f"Failed to stash changes: {stderr.strip()}"}

        stdout, _, _ = await ssh_manager.run(
            f"git -C {path_q} stash list --oneline -1", timeout=15
        )
        stash_name = stdout.split(':')[0].strip() if stdout else 'stash@{0}'

        return {'success': True, 'stash_name': stash_name}
    except Exception as exc:
        logger.error("Unexpected error during remote stash: %s", exc)
        return {'success': False, 'error': str(exc)}


async def apply_latest_stash(ssh_manager, platforms_path: str, pop: bool = True) -> dict:
    """Remote equivalent of ``qpu.platforms.apply_latest_stash``."""
    if not await _is_git_repo(ssh_manager, platforms_path):
        return {'success': False, 'error': 'Not a git repository'}

    path_q = _q(platforms_path)
    try:
        stdout, _, _ = await ssh_manager.run(f"git -C {path_q} stash list", timeout=15)
        if not stdout.strip():
            return {'success': False, 'error': 'No stashes available'}

        latest_stash = stdout.splitlines()[0].split(':')[0]

        stash_command = 'pop' if pop else 'apply'
        stdout, stderr, rc = await ssh_manager.run(f"git -C {path_q} stash {stash_command}", timeout=30)

        conflicts = rc != 0
        if conflicts:
            return {
                'success': True, 'stash_applied': latest_stash, 'conflicts': True,
                'error': f"Applied with conflicts: {stderr.strip()}",
            }
        return {'success': True, 'stash_applied': latest_stash, 'conflicts': False}
    except Exception as exc:
        logger.error("Unexpected error applying remote stash: %s", exc)
        return {'success': False, 'error': str(exc)}


async def discard_changes(ssh_manager, platforms_path: str) -> dict:
    """Remote equivalent of ``qpu.platforms.discard_changes``."""
    if not await _is_git_repo(ssh_manager, platforms_path):
        return {'success': False, 'error': 'Not a git repository'}

    path_q = _q(platforms_path)
    try:
        stdout, _, _ = await ssh_manager.run(f"git -C {path_q} status --porcelain", timeout=15)
        changed_files = []
        for line in stdout.splitlines():
            if line.strip():
                filename = line[3:].strip()
                changed_files.append(filename)

        if not changed_files:
            return {'success': False, 'error': 'No changes to discard'}

        _, stderr, rc = await ssh_manager.run(f"git -C {path_q} reset --hard HEAD", timeout=30)
        if rc != 0:
            return {'success': False, 'error': f"Failed to discard changes: {stderr.strip()}"}

        _, stderr, rc = await ssh_manager.run(f"git -C {path_q} clean -fd", timeout=30)
        if rc != 0:
            return {'success': False, 'error': f"Failed to discard changes: {stderr.strip()}"}

        return {'success': True, 'discarded_files': changed_files}
    except Exception as exc:
        logger.error("Unexpected error during remote discard: %s", exc)
        return {'success': False, 'error': str(exc)}


async def list_stashes(ssh_manager, platforms_path: str) -> dict:
    """Remote equivalent of ``qpu.platforms.list_stashes``."""
    if not await _is_git_repo(ssh_manager, platforms_path):
        return {'success': False, 'error': 'Not a git repository'}

    path_q = _q(platforms_path)
    try:
        stdout, stderr, rc = await ssh_manager.run(
            f"git -C {path_q} stash list --pretty=format:'%gd: %gs (%cr)'", timeout=15
        )
        if rc != 0:
            return {'success': False, 'error': f"Failed to list stashes: {stderr.strip()}"}

        stashes = []
        for line in stdout.splitlines():
            if line.strip():
                parts = line.split(': ', 2)
                if len(parts) >= 2:
                    stashes.append({
                        'name': parts[0],
                        'message': parts[1] if len(parts) == 2 else parts[1],
                        'date': parts[2] if len(parts) == 3 else '',
                    })
        return {'success': True, 'stashes': stashes}
    except Exception as exc:
        logger.error("Unexpected error listing remote stashes: %s", exc)
        return {'success': False, 'error': str(exc)}


async def _changed_files(ssh_manager, platforms_path: str) -> List[str]:
    """Return changed file paths (relative to repo root) on the remote host."""
    stdout, _, _ = await ssh_manager.run(f"git -C {_q(platforms_path)} status --porcelain", timeout=15)
    files = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip()
        if ' -> ' in path:
            path = path.split(' -> ')[-1]
        files.append(path)
    return files


async def generate_commit_message(ssh_manager, platforms_path: str) -> str:
    """Remote equivalent of ``qpu.platforms.generate_commit_message``."""
    files = await _changed_files(ssh_manager, platforms_path)
    if not files:
        return ""

    kind_by_filename = {
        'platform.py': 'configuration',
        'calibration.json': 'calibration',
        'parameters.json': 'parameters',
    }
    kind_order = ['configuration', 'calibration', 'parameters']

    changes_by_platform = {}
    other_files = []
    for file_path in files:
        parts = file_path.split('/')
        if len(parts) < 2:
            other_files.append(file_path)
            continue
        platform_name, filename = parts[0], parts[-1]
        kind = kind_by_filename.get(filename)
        if kind:
            changes_by_platform.setdefault(platform_name, set()).add(kind)
        else:
            other_files.append(file_path)

    platform_summaries = []
    for platform_name in sorted(changes_by_platform):
        kinds = changes_by_platform[platform_name]
        ordered_kinds = [k for k in kind_order if k in kinds]
        platform_summaries.append(f"{platform_name} ({', '.join(ordered_kinds)})")

    message = "Update " + "; ".join(platform_summaries) if platform_summaries else "Update platform configurations"
    if other_files:
        message += f" [+{len(other_files)} other file(s)]"
    return message


async def commit_changes(ssh_manager, platforms_path: str, commit_message: Optional[str] = None) -> dict:
    """Remote equivalent of ``qpu.platforms.commit_changes``."""
    if not await _is_git_repo(ssh_manager, platforms_path):
        return {'success': False, 'error': 'Not a git repository'}

    path_q = _q(platforms_path)
    try:
        stdout, _, _ = await ssh_manager.run(f"git -C {path_q} status --porcelain", timeout=15)
        if not stdout.strip():
            return {'success': False, 'error': 'No changes to commit'}

        if not commit_message:
            commit_message = await generate_commit_message(ssh_manager, platforms_path)

        _, stderr, rc = await ssh_manager.run(f"git -C {path_q} add .", timeout=30)
        if rc != 0:
            return {'success': False, 'error': f"Failed to stage changes: {stderr.strip()}"}

        _, stderr, rc = await ssh_manager.run(
            f"git -C {path_q} commit -m {_q(commit_message)}", timeout=30
        )
        if rc != 0:
            return {'success': False, 'error': f"Failed to commit changes: {stderr.strip()}"}

        stdout, _, _ = await ssh_manager.run(f"git -C {path_q} rev-parse --short HEAD", timeout=15)
        commit_hash = stdout.strip()

        branch_info = await get_current_branch_info(ssh_manager, platforms_path)

        return {
            'success': True, 'commit_hash': commit_hash,
            'message': commit_message, 'branch_info': branch_info,
        }
    except Exception as exc:
        logger.error("Unexpected error during remote commit: %s", exc)
        return {'success': False, 'error': str(exc)}


async def push_changes(ssh_manager, platforms_path: str) -> dict:
    """Remote equivalent of ``qpu.platforms.push_changes``."""
    if not await _is_git_repo(ssh_manager, platforms_path):
        return {'success': False, 'error': 'Not a git repository'}

    path_q = _q(platforms_path)
    try:
        stdout, _, _ = await ssh_manager.run(f"git -C {path_q} branch --show-current", timeout=15)
        current_branch = stdout.strip()

        stdout, _, rc = await ssh_manager.run(
            f"git -C {path_q} rev-list --count origin/{shlex.quote(current_branch)}..HEAD", timeout=15
        )
        if rc == 0 and stdout.strip().isdigit() and int(stdout.strip()) == 0:
            return {'success': False, 'error': 'No commits to push'}

        _, stderr, rc = await ssh_manager.run(
            f"git -C {path_q} push origin {shlex.quote(current_branch)}", timeout=60
        )
        if rc != 0:
            return {'success': False, 'error': f"Failed to push changes: {stderr.strip()}"}

        branch_info = await get_current_branch_info(ssh_manager, platforms_path)

        return {'success': True, 'remote': 'origin', 'branch': current_branch, 'branch_info': branch_info}
    except Exception as exc:
        logger.error("Unexpected error during remote push: %s", exc)
        return {'success': False, 'error': str(exc)}
