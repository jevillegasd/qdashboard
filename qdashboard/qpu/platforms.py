"""
Utilities for managing qibolab platforms directory using git.
"""

import os
import subprocess
import logging
import glob
from pathlib import Path

# Set up logging
logger = logging.getLogger(__name__)

QIBOLAB_PLATFORMS_REPO = "https://github.com/qiboteam/qibolab_platforms_qrc.git"
DEFAULT_PLATFORMS_DIR = "qibolab_platforms_qrc"


def ensure_platforms_directory(root_path=None):
    """
    Ensure that the qibolab platforms directory exists.
    
    If QIBOLAB_PLATFORMS environment variable is set, use that path.
    Otherwise, create the directory in the specified root_path (or user home)
    and clone the repository if it doesn't exist.
    
    Args:
        root_path (str, optional): Root directory where to create platforms dir.
                                 Defaults to user home directory.
    
    Returns:
        str: Path to the platforms directory
        
    Raises:
        RuntimeError: If unable to create or clone the platforms directory
    """
    # Check if QIBOLAB_PLATFORMS is already defined
    platforms_path = os.environ.get('QIBOLAB_PLATFORMS')
    
    if platforms_path:
        # Environment variable is set, validate it exists
        if os.path.exists(platforms_path):
            logger.info(f"Using existing QIBOLAB_PLATFORMS: {platforms_path}")
            return platforms_path
        else:
            logger.warning(f"QIBOLAB_PLATFORMS points to non-existent path: {platforms_path}")
            logger.info("Will create and populate the directory")
    else:
        # Environment variable not set, create default path
        if root_path is None:
            root_path = os.path.expanduser("~")
        platforms_path = os.path.join(root_path, DEFAULT_PLATFORMS_DIR)
        logger.info(f"QIBOLAB_PLATFORMS not set, using default: {platforms_path}")
    
    # Create the directory if it doesn't exist
    platforms_dir = Path(platforms_path)
    
    if platforms_dir.exists() and platforms_dir.is_dir():
        # Check if it's an empty directory or has content
        if any(platforms_dir.iterdir()):
            logger.info(f"Platforms directory already exists with content: {platforms_path}")
            os.environ['QIBOLAB_PLATFORMS'] = platforms_path
            return str(platforms_path)
        else:
            logger.info(f"Empty platforms directory found: {platforms_path}")
    else:
        # Create the directory
        try:
            platforms_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created platforms directory: {platforms_path}")
        except Exception as e:
            raise RuntimeError(f"Failed to create platforms directory {platforms_path}: {e}")
    
    # Clone the repository
    try:
        clone_platforms_repository(platforms_path)
        return str(platforms_path)
    except Exception as e:
        logger.error(f"Failed to populate platforms directory: {e}")
        raise


def clone_platforms_repository(target_path):
    """
    Clone the qibolab platforms repository to the target path.
    
    Args:
        target_path (str): Path where to clone the repository
        
    Raises:
        RuntimeError: If git clone fails
    """
    logger.info(f"Cloning qibolab platforms repository to: {target_path}")
    
    try:
        # Check if git is available
        subprocess.run(['git', '--version'], check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise RuntimeError("Git is not available. Please install git to automatically clone platforms.")
    
    try:
        # Clone the repository
        cmd = ['git', 'clone', QIBOLAB_PLATFORMS_REPO, target_path]
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.info(f"Successfully cloned qibolab platforms repository")
        logger.debug(f"Git clone output: {result.stdout}")
        
        # Verify the clone was successful by checking for key files
        if not os.path.exists(os.path.join(target_path, '.git')):
            raise RuntimeError("Repository was cloned but .git directory not found")
        os.environ['QIBOLAB_PLATFORMS'] = target_path    
        logger.info("Repository verification successful")
        
    except subprocess.CalledProcessError as e:
        error_msg = f"Git clone failed: {e.stderr if e.stderr else str(e)}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)
    except Exception as e:
        error_msg = f"Unexpected error during clone: {e}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)


def update_platforms_repository(platforms_path):
    """
    Update the platforms repository by pulling latest changes.
    
    Args:
        platforms_path (str): Path to the platforms repository
        
    Returns:
        bool: True if update was successful, False otherwise
    """
    if not os.path.exists(os.path.join(platforms_path, '.git')):
        logger.warning(f"Not a git repository: {platforms_path}")
        return False
    
    try:
        # Pull latest changes
        cmd = ['git', '-C', platforms_path, 'pull', 'origin', 'main']
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.info(f"Successfully updated platforms repository")
        logger.debug(f"Git pull output: {result.stdout}")

        return True
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to update repository: {e.stderr if e.stderr else str(e)}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during update: {e}")
        return False


def get_platforms_path(root_path=None):
    """
    Get the path to the qibolab platforms directory.
    
    This is a convenience function that calls ensure_platforms_directory()
    and handles some errors.
    
    Args:
        root_path (str, optional): Root directory where to create platforms dir.
                                 Defaults to user home directory.
    
    Returns:
        str: Path to platforms directory, or None if unable to ensure it exists
    """
    try:
        return ensure_platforms_directory(root_path)
    except Exception as e:
        logger.error(f"Unable to ensure platforms directory: {e}")
        return None


def list_repository_branches(platforms_path):
    """
    List all available branches in the platforms repository.
    
    Args:
        platforms_path (str): Path to the platforms repository
        
    Returns:
        dict: Dictionary with 'local' and 'remote' branches, or None if error
        {
            'current': 'main',
            'local': ['main', 'feature-branch'],
            'remote': ['origin/main', 'origin/feature-branch', 'origin/develop']
        }
    """
    if not os.path.exists(os.path.join(platforms_path, '.git')):
        logger.warning(f"Not a git repository: {platforms_path}")
        return None
    
    try:
        # Get current branch
        current_cmd = ['git', '-C', platforms_path, 'branch', '--show-current']
        current_result = subprocess.run(current_cmd, check=True, capture_output=True, text=True)
        current_branch = current_result.stdout.strip()
        
        # Get local branches
        local_cmd = ['git', '-C', platforms_path, 'branch', '--format=%(refname:short)']
        local_result = subprocess.run(local_cmd, check=True, capture_output=True, text=True)
        local_branches = [branch.strip() for branch in local_result.stdout.split('\n') if branch.strip()]
        
        # Fetch latest remote information
        fetch_cmd = ['git', '-C', platforms_path, 'fetch', '--all']
        subprocess.run(fetch_cmd, check=True, capture_output=True, text=True)
        
        # Get remote branches
        remote_cmd = ['git', '-C', platforms_path, 'branch', '-r', '--format=%(refname:short)']
        remote_result = subprocess.run(remote_cmd, check=True, capture_output=True, text=True)
        remote_branches = [branch.strip() for branch in remote_result.stdout.split('\n') 
                          if branch.strip() and not branch.strip().endswith('/HEAD')]
        
        logger.info(f"Retrieved branch information for platforms repository")
        
        return {
            'current': current_branch,
            'local': local_branches,
            'remote': remote_branches
        }
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to list repository branches: {e.stderr if e.stderr else str(e)}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error listing branches: {e}")
        return None


def stash_changes(platforms_path, stash_message="WIP: Temporary stash"):
    """
    Stash uncommitted changes in the platforms repository.
    
    Args:
        platforms_path (str): Path to the platforms repository
        stash_message (str): Message for the stash
        
    Returns:
        dict: Result information
        {
            'success': True/False,
            'error': 'error_message' (if success=False),
            'stash_name': 'stash@{0}' (if success=True)
        }
    """
    if not os.path.exists(os.path.join(platforms_path, '.git')):
        logger.warning(f"Not a git repository: {platforms_path}")
        return {'success': False, 'error': 'Not a git repository'}
    
    try:
        # Check if there are any changes to stash
        status_cmd = ['git', '-C', platforms_path, 'status', '--porcelain']
        status_result = subprocess.run(status_cmd, check=True, capture_output=True, text=True)
        
        if not status_result.stdout.strip():
            logger.info("No changes to stash")
            return {'success': False, 'error': 'No changes to stash'}
        
        # Stash changes (including untracked files)
        stash_cmd = ['git', '-C', platforms_path, 'stash', 'push', '-u', '-m', stash_message]
        stash_result = subprocess.run(stash_cmd, check=True, capture_output=True, text=True)
        logger.info(f"Successfully stashed changes with message: {stash_message}")
        
        # Get the stash name (should be stash@{0} after creation)
        stash_list_cmd = ['git', '-C', platforms_path, 'stash', 'list', '--oneline', '-1']
        stash_list_result = subprocess.run(stash_list_cmd, check=True, capture_output=True, text=True)
        stash_name = stash_list_result.stdout.split(':')[0].strip() if stash_list_result.stdout else 'stash@{0}'
        
        return {
            'success': True,
            'stash_name': stash_name
        }
        
    except subprocess.CalledProcessError as e:
        error_msg = f"Failed to stash changes: {e.stderr if e.stderr else str(e)}"
        logger.error(error_msg)
        return {'success': False, 'error': error_msg}
    except Exception as e:
        error_msg = f"Unexpected error during stash: {e}"
        logger.error(error_msg)
        return {'success': False, 'error': error_msg}


def apply_latest_stash(platforms_path, pop=True):
    """
    Apply (pop) the latest stash in the platforms repository.
    
    Args:
        platforms_path (str): Path to the platforms repository
        pop (bool): If True, removes the stash after applying (git stash pop)
                   If False, keeps the stash (git stash apply)
        
    Returns:
        dict: Result information
        {
            'success': True/False,
            'error': 'error_message' (if success=False),
            'stash_applied': 'stash@{0}' (if success=True),
            'conflicts': True/False (if conflicts occurred during apply)
        }
    """
    if not os.path.exists(os.path.join(platforms_path, '.git')):
        logger.warning(f"Not a git repository: {platforms_path}")
        return {'success': False, 'error': 'Not a git repository'}
    
    try:
        # Check if there are any stashes
        stash_list_cmd = ['git', '-C', platforms_path, 'stash', 'list']
        stash_list_result = subprocess.run(stash_list_cmd, check=True, capture_output=True, text=True)
        
        if not stash_list_result.stdout.strip():
            logger.info("No stashes to apply")
            return {'success': False, 'error': 'No stashes available'}
        
        # Get the latest stash name
        latest_stash = stash_list_result.stdout.split('\n')[0].split(':')[0]
        
        # Apply or pop the stash
        stash_command = 'pop' if pop else 'apply'
        apply_cmd = ['git', '-C', platforms_path, 'stash', stash_command]
        apply_result = subprocess.run(apply_cmd, capture_output=True, text=True)
        
        # Check if there were conflicts
        conflicts = apply_result.returncode != 0
        
        if conflicts:
            # Stash application had conflicts, but this might be acceptable
            logger.warning(f"Stash application had conflicts: {apply_result.stderr}")
            return {
                'success': True,  # We still consider this a success, just with conflicts
                'stash_applied': latest_stash,
                'conflicts': True,
                'error': f"Applied with conflicts: {apply_result.stderr}"
            }
        else:
            logger.info(f"Successfully applied stash: {latest_stash}")
            return {
                'success': True,
                'stash_applied': latest_stash,
                'conflicts': False
            }
        
    except subprocess.CalledProcessError as e:
        error_msg = f"Failed to apply stash: {e.stderr if e.stderr else str(e)}"
        logger.error(error_msg)
        return {'success': False, 'error': error_msg}
    except Exception as e:
        error_msg = f"Unexpected error applying stash: {e}"
        logger.error(error_msg)
        return {'success': False, 'error': error_msg}

 
def discard_changes(platforms_path):
    """
    Discard all uncommitted changes in the platforms repository.
    This includes both staged and unstaged changes, and removes untracked files.
    
    Args:
        platforms_path (str): Path to the platforms repository
        pop (bool): Whether to pop the latest stash (default: True)
        
    Returns:
        dict: Result information
        {
            'success': True/False,
            'error': 'error_message' (if success=False),
            'discarded_files': ['file1.py', 'file2.json'] (if success=True)
        }
    """
    if not os.path.exists(os.path.join(platforms_path, '.git')):
        logger.warning(f"Not a git repository: {platforms_path}")
        return {'success': False, 'error': 'Not a git repository'}
    
    try:
        # First, get list of changed files for reporting
        status_cmd = ['git', '-C', platforms_path, 'status', '--porcelain']
        status_result = subprocess.run(status_cmd, check=True, capture_output=True, text=True)
        
        changed_files = []
        if status_result.stdout.strip():
            for line in status_result.stdout.split('\n'):
                if line.strip():
                    # Extract filename from git status output (format: "XY filename")
                    filename = line[3:].strip()
                    changed_files.append(filename)
        
        if not changed_files:
            logger.info("No changes to discard")
            return {'success': False, 'error': 'No changes to discard'}
        
        # Reset all staged changes
        reset_cmd = ['git', '-C', platforms_path, 'reset', '--hard', 'HEAD']
        subprocess.run(reset_cmd, check=True, capture_output=True, text=True)
        logger.info("Reset staged and unstaged changes")
        
        # Clean untracked files and directories
        clean_cmd = ['git', '-C', platforms_path, 'clean', '-fd']
        subprocess.run(clean_cmd, check=True, capture_output=True, text=True)
        logger.info("Cleaned untracked files and directories")
        
        logger.info(f"Successfully discarded all changes: {', '.join(changed_files)}")
        
        return {
            'success': True,
            'discarded_files': changed_files
        }
        
    except subprocess.CalledProcessError as e:
        error_msg = f"Failed to discard changes: {e.stderr if e.stderr else str(e)}"
        logger.error(error_msg)
        return {'success': False, 'error': error_msg}
    except Exception as e:
        error_msg = f"Unexpected error during discard: {e}"
        logger.error(error_msg)
        return {'success': False, 'error': error_msg}
    

def list_stashes(platforms_path):
    """
    List all stashes in the platforms repository.
    
    Args:
        platforms_path (str): Path to the platforms repository
        
    Returns:
        dict: Result with list of stashes or error
        {
            'success': True/False,
            'error': 'error_message' (if success=False),
            'stashes': [{'name': 'stash@{0}', 'message': 'WIP: ...', 'date': '...'}]
        }
    """
    if not os.path.exists(os.path.join(platforms_path, '.git')):
        logger.warning(f"Not a git repository: {platforms_path}")
        return {'success': False, 'error': 'Not a git repository'}
    
    try:
        # Get stash list with format: stash@{0}: message
        stash_cmd = ['git', '-C', platforms_path, 'stash', 'list', '--pretty=format:%gd: %gs (%cr)']
        stash_result = subprocess.run(stash_cmd, check=True, capture_output=True, text=True)
        
        stashes = []
        if stash_result.stdout.strip():
            for line in stash_result.stdout.split('\n'):
                if line.strip():
                    parts = line.split(': ', 2)
                    if len(parts) >= 2:
                        stashes.append({
                            'name': parts[0],
                            'message': parts[1] if len(parts) == 2 else parts[1],
                            'date': parts[2] if len(parts) == 3 else ''
                        })
        
        return {
            'success': True,
            'stashes': stashes
        }
        
    except subprocess.CalledProcessError as e:
        error_msg = f"Failed to list stashes: {e.stderr if e.stderr else str(e)}"
        logger.error(error_msg)
        return {'success': False, 'error': error_msg}
    except Exception as e:
        error_msg = f"Unexpected error listing stashes: {e}"
        logger.error(error_msg)
        return {'success': False, 'error': error_msg}


def switch_repository_branch(platforms_path, branch_name, create_if_not_exists=False, handle_changes='fail', auto_apply_stash=True):
    """
    Switch to a specific branch in the platforms repository.
    
    Args:
        platforms_path (str): Path to the platforms repository
        branch_name (str): Name of the branch to switch to
        create_if_not_exists (bool): Create branch if it doesn't exist locally
        handle_changes (str): How to handle uncommitted changes: 'fail', 'stash', 'commit'
        auto_apply_stash (bool): Whether to automatically apply the latest stash after switching
        
    Returns:
        dict: Result information with success status and details
        {
            'success': True/False,
            'error': 'error_message' (if success=False),
            'has_changes': True/False,
            'changes_handled': 'stashed'/'committed'/None,
            'stash_created': 'stash_name' (if stashed),
            'stash_applied': 'stash_name' (if stash was applied),
            'stash_restored': True/False
        }
    """
    if not os.path.exists(os.path.join(platforms_path, '.git')):
        logger.warning(f"Not a git repository: {platforms_path}")
        return {'success': False, 'error': 'Not a git repository'}
    
    try:
        # First, fetch latest information
        fetch_cmd = ['git', '-C', platforms_path, 'fetch', '--all']
        subprocess.run(fetch_cmd, check=True, capture_output=True, text=True)
        
        # Check if local changes need to be handled
        local_changes_cmd = ['git', '-C', platforms_path, 'status', '--porcelain']
        local_changes_result = subprocess.run(local_changes_cmd, capture_output=True, text=True)
        has_local_changes = bool(local_changes_result.stdout.strip())
        
        result = {
            'success': False,
            'has_changes': has_local_changes,
            'changes_handled': None,
            'stash_created': None,
            'stash_applied': None,
            'stash_restored': False
        }
        
        if has_local_changes:
            if handle_changes == 'fail':
                logger.warning(f"Local changes detected in {platforms_path}. Please commit or stash them before switching branches.")
                result['error'] = 'Local changes detected. Please choose how to handle them.'
                return result
            elif handle_changes == 'stash':
                # Stash the changes
                stash_result = stash_changes(platforms_path, f"Auto-stash before switching to {branch_name}")
                if not stash_result['success']:
                    result['error'] = f"Failed to stash changes: {stash_result.get('error', 'Unknown error')}"
                    return result
                result['changes_handled'] = 'stashed'
                result['stash_created'] = stash_result.get('stash_name')
                logger.info(f"Stashed changes before switching to {branch_name}")
            elif handle_changes == 'commit':
                # Commit the changes (this would require a commit message)
                result['error'] = 'Commit option requires explicit commit message handling'
                return result

        
        # Check if branch exists locally
        local_check_cmd = ['git', '-C', platforms_path, 'branch', '--list', branch_name]
        local_check_result = subprocess.run(local_check_cmd, capture_output=True, text=True)
        branch_exists_locally = bool(local_check_result.stdout.strip())
        
        # Check if branch exists remotely
        remote_check_cmd = ['git', '-C', platforms_path, 'branch', '-r', '--list', f'origin/{branch_name}']
        remote_check_result = subprocess.run(remote_check_cmd, capture_output=True, text=True)
        branch_exists_remotely = bool(remote_check_result.stdout.strip())
        
        if branch_exists_locally:
            # Branch exists locally, just checkout
            checkout_cmd = ['git', '-C', platforms_path, 'checkout', branch_name]
            subprocess.run(checkout_cmd, check=True, capture_output=True, text=True)
            logger.info(f"Switched to existing local branch: {branch_name}")
            
        elif branch_exists_remotely:
            # Branch exists remotely, create local tracking branch
            checkout_cmd = ['git', '-C', platforms_path, 'checkout', '-b', branch_name, f'origin/{branch_name}']
            subprocess.run(checkout_cmd, check=True, capture_output=True, text=True)
            logger.info(f"Created and switched to new local branch tracking origin/{branch_name}")
            
        elif create_if_not_exists:
            # Create new branch from current HEAD
            checkout_cmd = ['git', '-C', platforms_path, 'checkout', '-b', branch_name]
            subprocess.run(checkout_cmd, check=True, capture_output=True, text=True)
            logger.info(f"Created and switched to new branch: {branch_name}")
            
        else:
            logger.error(f"Branch '{branch_name}' not found locally or remotely")
            result['error'] = f"Branch '{branch_name}' not found locally or remotely"
            return result
        
        # Pull latest changes if switching to an existing branch
        if branch_exists_locally or branch_exists_remotely:
            try:
                pull_cmd = ['git', '-C', platforms_path, 'pull']
                subprocess.run(pull_cmd, check=True, capture_output=True, text=True)
                logger.info(f"Pulled latest changes for branch: {branch_name}")
            except subprocess.CalledProcessError:
                # Pull might fail if there's no upstream, that's okay
                logger.debug(f"Could not pull for branch {branch_name} (no upstream configured)")
        
        
        result['success'] = True
        
        # Auto-apply latest stash if requested and available
        if auto_apply_stash:
            stash_result = apply_latest_stash(platforms_path, pop=True)
            if stash_result['success']:
                result['stash_applied'] = stash_result['stash_applied']
                result['stash_restored'] = True
                logger.info(f"Automatically restored stash: {stash_result['stash_applied']} after switching to {branch_name}")
            elif stash_result['had_stashes']:
                # There were stashes but failed to apply - log warning but don't fail the switch
                logger.warning(f"Could not apply stash after switching to {branch_name}: {stash_result.get('error', 'Unknown error')}")
            # If no stashes, that's fine - no action needed
        
        return result
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to switch branch: {e.stderr if e.stderr else str(e)}")
        result['error'] = f"Failed to switch branch: {e.stderr if e.stderr else str(e)}"
        return result
    except Exception as e:
        logger.error(f"Unexpected error switching branch: {e}")
        result['error'] = f"Unexpected error switching branch: {e}"
        return result


def get_current_branch_info(platforms_path):
    """
    Get information about the current branch and its status.
    
    Args:
        platforms_path (str): Path to the platforms repository
        
    Returns:
        dict: Information about current branch, or None if error
        {
            'branch': 'main',
            'commit': 'abc123...',
            'commit_message': 'Latest commit message',
            'behind': 0,
            'ahead': 0,
            'clean': True
        }
    """
    if not os.path.exists(os.path.join(platforms_path, '.git')):
        logger.warning(f"Not a git repository: {platforms_path}")
        return None
    
    try:
        # Get current branch
        branch_cmd = ['git', '-C', platforms_path, 'branch', '--show-current']
        branch_result = subprocess.run(branch_cmd, check=True, capture_output=True, text=True)
        current_branch = branch_result.stdout.strip()
        
        # Get current commit hash
        commit_cmd = ['git', '-C', platforms_path, 'rev-parse', '--short', 'HEAD']
        commit_result = subprocess.run(commit_cmd, check=True, capture_output=True, text=True)
        current_commit = commit_result.stdout.strip()
        
        # Get commit message
        message_cmd = ['git', '-C', platforms_path, 'log', '-1', '--pretty=format:%s']
        message_result = subprocess.run(message_cmd, check=True, capture_output=True, text=True)
        commit_message = message_result.stdout.strip()
        
        # Check if repository is clean
        status_cmd = ['git', '-C', platforms_path, 'status', '--porcelain']
        status_result = subprocess.run(status_cmd, check=True, capture_output=True, text=True)
        is_clean = not bool(status_result.stdout.strip())
        
        # Get ahead/behind information if there's an upstream
        ahead, behind = 0, 0
        try:
            # Fetch first to get latest remote info
            subprocess.run(['git', '-C', platforms_path, 'fetch'], 
                          check=True, capture_output=True, text=True)
            
            # Check if there's an upstream branch
            upstream_cmd = ['git', '-C', platforms_path, 'rev-parse', '--abbrev-ref', f'{current_branch}@{{upstream}}']
            upstream_result = subprocess.run(upstream_cmd, capture_output=True, text=True)
            
            if upstream_result.returncode == 0:
                upstream_branch = upstream_result.stdout.strip()
                
                # Get ahead/behind counts
                counts_cmd = ['git', '-C', platforms_path, 'rev-list', '--left-right', '--count', 
                             f'{upstream_branch}...{current_branch}']
                counts_result = subprocess.run(counts_cmd, check=True, capture_output=True, text=True)
                behind, ahead = map(int, counts_result.stdout.strip().split())
                
        except subprocess.CalledProcessError:
            # No upstream or other error, keep defaults
            pass
        
        return {
            'branch': current_branch,
            'commit': current_commit,
            'commit_message': commit_message,
            'behind': behind,
            'ahead': ahead,
            'clean': is_clean
        }
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to get branch info: {e.stderr if e.stderr else str(e)}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error getting branch info: {e}")
        return None


def commit_changes(platforms_path, commit_message="Update platform configurations"):
    """
    Commit all changes in the platforms repository.
    
    Args:
        platforms_path (str): Path to the platforms repository
        commit_message (str): Commit message to use
        
    Returns:
        dict: Result information with commit hash, or error
        {
            'success': True,
            'commit_hash': 'abc123...',
            'message': 'Commit message',
            'branch_info': {...}
        }
    """
    if not os.path.exists(os.path.join(platforms_path, '.git')):
        logger.warning(f"Not a git repository: {platforms_path}")
        return {'success': False, 'error': 'Not a git repository'}
    
    try:
        # Check if there are any changes to commit
        status_cmd = ['git', '-C', platforms_path, 'status', '--porcelain']
        status_result = subprocess.run(status_cmd, check=True, capture_output=True, text=True)
        
        if not status_result.stdout.strip():
            logger.info("No changes to commit")
            return {'success': False, 'error': 'No changes to commit'}
        
        # Add all changes
        add_cmd = ['git', '-C', platforms_path, 'add', '.']
        subprocess.run(add_cmd, check=True, capture_output=True, text=True)
        logger.info("Staged all changes for commit")
        
        # Commit changes
        commit_cmd = ['git', '-C', platforms_path, 'commit', '-m', commit_message]
        commit_result = subprocess.run(commit_cmd, check=True, capture_output=True, text=True)
        logger.info(f"Successfully committed changes: {commit_message}")
        
        # Get the new commit hash
        hash_cmd = ['git', '-C', platforms_path, 'rev-parse', '--short', 'HEAD']
        hash_result = subprocess.run(hash_cmd, check=True, capture_output=True, text=True)
        commit_hash = hash_result.stdout.strip()
        
        # Get updated branch info
        branch_info = get_current_branch_info(platforms_path)
        
        return {
            'success': True,
            'commit_hash': commit_hash,
            'message': commit_message,
            'branch_info': branch_info
        }
        
    except subprocess.CalledProcessError as e:
        error_msg = f"Failed to commit changes: {e.stderr if e.stderr else str(e)}"
        logger.error(error_msg)
        return {'success': False, 'error': error_msg}
    except Exception as e:
        error_msg = f"Unexpected error during commit: {e}"
        logger.error(error_msg)
        return {'success': False, 'error': error_msg}


def push_changes(platforms_path):
    """
    Push committed changes to the remote repository.
    
    Args:
        platforms_path (str): Path to the platforms repository
        
    Returns:
        dict: Result information, or error
        {
            'success': True,
            'remote': 'origin',
            'branch': 'main',
            'branch_info': {...}
        }
    """
    if not os.path.exists(os.path.join(platforms_path, '.git')):
        logger.warning(f"Not a git repository: {platforms_path}")
        return {'success': False, 'error': 'Not a git repository'}
    
    try:
        # Get current branch
        branch_cmd = ['git', '-C', platforms_path, 'branch', '--show-current']
        branch_result = subprocess.run(branch_cmd, check=True, capture_output=True, text=True)
        current_branch = branch_result.stdout.strip()
        
        # Check if there are any commits to push
        ahead_cmd = ['git', '-C', platforms_path, 'rev-list', '--count', f'origin/{current_branch}..HEAD']
        ahead_result = subprocess.run(ahead_cmd, capture_output=True, text=True)
        
        if ahead_result.returncode == 0:
            ahead_count = int(ahead_result.stdout.strip())
            if ahead_count == 0:
                logger.info("No commits to push")
                return {'success': False, 'error': 'No commits to push'}
        
        # Push changes to origin
        push_cmd = ['git', '-C', platforms_path, 'push', 'origin', current_branch]
        push_result = subprocess.run(push_cmd, check=True, capture_output=True, text=True)
        logger.info(f"Successfully pushed changes to origin/{current_branch}")
        
        # Get updated branch info
        branch_info = get_current_branch_info(platforms_path)
        
        return {
            'success': True,
            'remote': 'origin',
            'branch': current_branch,
            'branch_info': branch_info
        }
        
    except subprocess.CalledProcessError as e:
        error_msg = f"Failed to push changes: {e.stderr if e.stderr else str(e)}"
        logger.error(error_msg)
        return {'success': False, 'error': error_msg}
    except Exception as e:
        error_msg = f"Unexpected error during push: {e}"
        logger.error(error_msg)
        return {'success': False, 'error': error_msg}

def get_partition(platform):
    """
    Get the partition name from a platform name by reading the queues.json file.

    Args:
        platform (str): The name of the platform.

    Returns:
        str: The partition name for the platform, or default if not found.
    """
    if not isinstance(platform, str):
        return None

    # Get the platforms path
    platforms_path = get_platforms_path()
    if not platforms_path:
        logger.warning(f"Could not get platforms path to read the partition (queue) for {platform}")
        return None  # Default fallback
    
    # Try to read partition from queues.json
    queues_file = os.path.join(platforms_path, 'queues.json')
    
    if os.path.exists(queues_file):
        try:
            import json
            with open(queues_file, 'r') as f:
                queues_data = json.load(f)
            
            # Look up the platform in the queues mapping
            if platform in queues_data:
                partition = queues_data[platform]
                logger.info(f"Found partition '{partition}' for platform '{platform}' in queues.json")
                return partition
            else:
                logger.warning(f"Platform '{platform}' not found in queues.json")
                
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Could not read queues.json: {e}")
    else:
        logger.warning(f"queues.json not found at {queues_file}")
    
    # Fallback to no partition defined
    return None