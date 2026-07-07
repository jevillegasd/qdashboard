"""
Experiment job submission and management functionality.
"""

import os
import glob
import shutil
import subprocess
import tempfile
import json
import yaml
import hashlib
import time
import traceback
from datetime import datetime
from typing import Dict, Any, Tuple, Optional, List

from ..qpu.platforms import get_platforms_path, get_partition
from ..qpu.monitoring import get_qpu_list
from ..utils.logger import get_logger
from ..core.config import get_temp_dir, ensure_directory_exists

logger = get_logger(__name__)


def generate_experiment_id(runcard_path: str, platform: str) -> str:
    """Generate a unique experiment ID: YYYYmmDD-<6-char hex hash>."""
    now = datetime.now()
    date_str = now.strftime('%Y%m%d')

    hasher = hashlib.md5()
    hasher.update(platform.encode())
    hasher.update(now.isoformat().encode())
    if os.path.exists(runcard_path):
        with open(runcard_path, 'rb') as f:
            hasher.update(f.read())

    return f"{date_str}-{hasher.hexdigest()[:6]}"


def create_experiment_directory(experiment_id: str, platform: str, config: Dict[str, Any]) -> str:
    """Create experiment directory: data_dir/<platform>/<YYYYMMDD>/<experiment_id>/"""
    data_dir = config.get('data_dir') or os.path.join(config['qd_root'], 'data')
    date_str = experiment_id.split('-')[0]  # YYYYmmDD prefix
    experiment_dir = os.path.join(data_dir, platform, date_str, experiment_id)
    ensure_directory_exists(experiment_dir)
    return experiment_dir


def prepare_runcard_from_path(runcard_path: str, experiment_dir: str) -> Tuple[str, Dict[str, Any]]:
    """Copy runcard to experiment directory and extract metadata."""
    if not os.path.exists(runcard_path):
        raise FileNotFoundError(f"Runcard not found: {runcard_path}")
    
    # Copy runcard to experiment directory
    dest_runcard_path = os.path.join(experiment_dir, 'runcard.yml')
    shutil.copy2(runcard_path, dest_runcard_path)
    
    # Read and validate runcard
    with open(dest_runcard_path, 'r') as f:
        runcard_data = yaml.safe_load(f)
    
    required_fields = ['platform']
    for field in required_fields:
        if field not in runcard_data:
            raise ValueError(f"Missing required field in runcard: {field}")
    
    return dest_runcard_path, runcard_data


def prepare_runcard_from_data(runcard_data: Dict[str, Any], experiment_dir: str) -> Tuple[str, Dict[str, Any]]:
    """Create runcard file from data in experiment directory."""
    # Validate runcard data
    required_fields = ['platform']
    for field in required_fields:
        if field not in runcard_data:
            raise ValueError(f"Missing required field in runcard: {field}")
    
    # Create runcard file in experiment directory
    dest_runcard_path = os.path.join(experiment_dir, 'runcard.yml')
    with open(dest_runcard_path, 'w') as f:
        yaml.dump(runcard_data, f, default_flow_style=False, sort_keys=False)
    
    return dest_runcard_path, runcard_data


def create_temp_runcard_from_data(runcard_data: Dict[str, Any], temp_dir: str) -> str:
    """Create temporary runcard file from data."""
    # Validate runcard data
    required_fields = ['platform']
    for field in required_fields:
        if field not in runcard_data:
            raise ValueError(f"Missing required field in runcard: {field}")
    
    # Create temporary runcard file
    temp_runcard_path = os.path.join(temp_dir, 'temp_runcard.yml')
    ensure_directory_exists(temp_dir)
    
    with open(temp_runcard_path, 'w') as f:
        yaml.dump(runcard_data, f, default_flow_style=False, sort_keys=False)
    
    return temp_runcard_path


# Legacy function for backward compatibility
def prepare_runcard(runcard_path: str, experiment_dir: str) -> Tuple[str, Dict[str, Any]]:
    """Copy runcard to experiment directory and extract metadata."""
    return prepare_runcard_from_path(runcard_path, experiment_dir)


def create_slurm_script(experiment_id: str, experiment_dir: str, runcard_path: str, 
                       platform: str, partition: str, platforms_base: str, 
                       environment: str = None, logs_dir: str = None,
                       auto_update: bool = True) -> str:
    """Create SLURM job submission script."""
   
    output_dir = os.path.join(experiment_dir, 'output')
    ensure_directory_exists(output_dir)

    # Create logs directory for SLURM output
    if not logs_dir:
        logs_dir = os.path.join(experiment_dir, 'logs')
    ensure_directory_exists(logs_dir)

    # `environment` is a venv path (explicitly set via QD_ENVIRONMENT, or
    # auto-detected from the dashboard's own launch environment when
    # QD_ENVIRONMENT was unset/'default').
    activate_path = os.path.join(os.path.expanduser(environment), 'bin', 'activate') if environment else None

    job_script_content = f"""#!/bin/bash
#SBATCH --job-name={experiment_id}
#SBATCH --partition={partition}
#SBATCH --output={logs_dir}/slurm_output.log
# #SBATCH --error={logs_dir}/slurm_error.log
#SBATCH --time=01:00:00

# Set environment variables
export QIBOLAB_PLATFORMS={platforms_base}
export QIBO_PLATFORM={platform}

# Log job information
echo "Job ID: $SLURM_JOB_ID"
echo "Experiment ID: {experiment_id}"
echo "Platform: {platform}"
echo "Partition: {partition}"
echo "Start time: $(date)"
echo "Working directory: $(pwd)"
echo "Output directory: {output_dir}"

# Change to experiment directory
cd {experiment_dir}

# Activate environment if specified
{f'source {activate_path}' if activate_path else '# No environment specified'}
echo "Activated environment: $(which python) ($(python --version 2>&1))"

# Run the experiment
echo "Running experiment..."
qq run {runcard_path} -o {output_dir} -f{'' if auto_update else ' --no-update'}

# Log completion
echo "End time: $(date)"
echo "Exit code: $?"

exit 0
"""
    
    job_script_path = os.path.join(experiment_dir, 'job_script.sh')
    with open(job_script_path, 'w') as f:
        f.write(job_script_content)
    
    # Make script executable
    os.chmod(job_script_path, 0o755)
    
    return job_script_path


def save_experiment_metadata(experiment_dir: str, metadata: Dict[str, Any]) -> str:
    """Save experiment metadata to JSON file."""
    metadata_path = os.path.join(experiment_dir, 'experiment_metadata.json')
    
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)
    
    return metadata_path


def submit_slurm_job(job_script_path: str) -> Tuple[bool, str, Optional[str]]:
    """Submit job to SLURM and return success status, message, and job ID."""
    try:
        result = subprocess.run(['sbatch', job_script_path], 
                              capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            # Extract job ID from sbatch output
            job_id = None
            for line in result.stdout.split('\n'):
                if 'Submitted batch job' in line:
                    job_id = line.split()[-1]
                    break
            
            if job_id:
                logger.info(f"SLURM job submitted successfully: {job_id}")
                return True, f"Job submitted successfully with ID: {job_id}", job_id
            else:
                logger.warning("Job submitted but could not extract job ID")
                return True, "Job submitted successfully", None
        else:
            error_msg = f"SLURM submission failed: {result.stderr}"
            logger.error(error_msg)
            return False, error_msg, None
            
    except subprocess.TimeoutExpired:
        error_msg = "SLURM submission timed out"
        logger.error(error_msg)
        return False, error_msg, None
    except Exception as e:
        error_msg = f"Error submitting to SLURM: {str(e)}"
        logger.error(error_msg)
        return False, error_msg, None


def submit_experiment(runcard_path: str = None, runcard_data: Dict[str, Any] = None, 
                     config: Dict[str, Any] = None, environment: str = None,
                     auto_update: bool = True) -> Dict[str, Any]:
    """
    Submit a new experiment to SLURM.
    
    This function supports two modes of operation:
    1. Traditional mode: Pass runcard_path to use an existing YAML file
    2. Data mode: Pass runcard_data dictionary to create the runcard dynamically
    
    Args:
        runcard_path: Path to the runcard YAML file (optional if runcard_data provided)
        runcard_data: Runcard data as dictionary (optional if runcard_path provided)
        config: Application configuration
        environment: Environment name to activate (optional)
    
    Returns:
        Dictionary with submission results
        
    Examples:
        # Traditional mode with existing file
        result = submit_experiment(
            runcard_path="/path/to/runcard.yml",
            config=app_config
        )
        
        # Data mode with dynamic runcard
        runcard_data = {
            'platform': 'my_platform',
            'actions': {'randomized_benchmarking': {...}},
            'nshots': 1000
        }
        result = submit_experiment(
            runcard_data=runcard_data,
            config=app_config
        )
    """
    try:
        # Validate input parameters
        if not runcard_path and not runcard_data:
            return {
                'success': False,
                'message': 'Either runcard_path or runcard_data must be provided'
            }
        
        if runcard_path and runcard_data:
            return {
                'success': False,
                'message': 'Cannot provide both runcard_path and runcard_data, choose one'
            }
        
        # Ensure QDashboard directories exist
        ensure_directory_exists(config.get('data_dir', os.path.join(config['qd_root'], 'data')))
        ensure_directory_exists(config.get('logs_dir', os.path.join(config['qd_root'], 'logs')))
        
        # Use configured temp directory or fallback
        temp_dir = config.get('temp_dir') or get_temp_dir()
        temp_files_to_cleanup = []
        
        try:
            # Handle runcard preparation based on input type
            if runcard_path:
                # Traditional path: copy existing file to temp directory
                temp_runcard_path, runcard_data_parsed = prepare_runcard_from_path(runcard_path, temp_dir)
                temp_files_to_cleanup.append(temp_runcard_path)
            else:
                # New path: create runcard file from data in temp directory
                temp_runcard_path = create_temp_runcard_from_data(runcard_data, temp_dir)
                runcard_data_parsed = runcard_data
                temp_files_to_cleanup.append(temp_runcard_path)
            
            platform = runcard_data_parsed['platform']
            if platform not in get_qpu_list():
                return {
                    'success': False,
                    'message': f'Unknown platform "{platform}": not tracked in the platforms repository'
                }

            # Generate experiment ID and create directory
            experiment_id = generate_experiment_id(temp_runcard_path, platform)
            experiment_dir = create_experiment_directory(experiment_id, platform, config)
            
            # Create final runcard in experiment directory
            if runcard_path:
                final_runcard_path, _ = prepare_runcard_from_path(runcard_path, experiment_dir)
            else:
                final_runcard_path, _ = prepare_runcard_from_data(runcard_data, experiment_dir)
            
            # Get platform information
            platforms_base = get_platforms_path(config['root'])
            if not platforms_base:
                return {
                    'success': False,
                    'message': 'Platforms directory not available'
                }
            
            # Determine partition
            partition = runcard_data_parsed.get('partition')
            if not partition:
                partition = get_partition(platform)
                if not partition:
                    return {
                        'success': False,
                        'message': f'No partition specified and could not infer partition for platform {platform}'
                    }
            
            # Use environment from runcard or config
            if not environment:
                environment = runcard_data_parsed.get('environment') or config.get('environment')
            
            # Create SLURM script — logs go inside the experiment directory so
            # the per-experiment log API can find them at <experiment_dir>/logs/
            job_script_path = create_slurm_script(
                experiment_id, experiment_dir, final_runcard_path,
                platform, partition, platforms_base, environment, logs_dir=None,
                auto_update=auto_update
            )
            
            # Submit job
            success, message, job_id = submit_slurm_job(job_script_path)
            
            if not success:
                return {
                    'success': False,
                    'message': message
                }
            
            # Save experiment metadata
            metadata = {
                'experiment_id': experiment_id,
                'job_id': job_id,
                'platform': platform,
                'partition': partition,
                'environment': environment,
                'submitted_at': time.time(),
                'experiment_dir': experiment_dir,
                'output_dir': os.path.join(experiment_dir, 'output'),
                'runcard_path': final_runcard_path,
                'job_script_path': job_script_path,
                'type': 'new_experiment',
                'source': 'runcard_path' if runcard_path else 'runcard_data'
            }
            
            save_experiment_metadata(experiment_dir, metadata)

            # Write to experiment history DB (non-fatal)
            try:
                from ..db.database import (get_db_connection, get_or_create_qpu,
                                           upsert_experiment_run, add_qpu_qubits,
                                           _extract_protocol_info)
                with get_db_connection(config) as conn:
                    qpu_id = get_or_create_qpu(conn, platform)
                    protocol_id, protocol_name, qubit_list = _extract_protocol_info(runcard_data_parsed)
                    if qubit_list:
                        add_qpu_qubits(conn, qpu_id, qubit_list)
                    upsert_experiment_run(conn, {
                        'experiment_id': experiment_id,
                        'qpu_id': qpu_id,
                        'protocol_id': protocol_id,
                        'protocol_name': protocol_name,
                        'target_qubits': qubit_list,
                        'submitted_at': metadata['submitted_at'],
                        'slurm_job_id': job_id,
                        'status': 'pending',
                        'runcard_path': final_runcard_path,
                        'output_dir': metadata['output_dir'],
                    })
            except Exception as _db_exc:
                logger.warning(f"DB write failed (non-fatal): {_db_exc}")

            # Update last report path using config
            last_report_path_file = config.get('last_report_path') or os.path.join(config['logs_dir'], 'last_report_path')
            ensure_directory_exists(os.path.dirname(last_report_path_file))
            with open(last_report_path_file, 'w') as f:
                f.write(metadata['output_dir'])
            
            logger.info(f"New experiment submitted: {experiment_id}")
            
            return {
                'success': True,
                'message': 'Experiment submitted successfully',
                'experiment_id': experiment_id,
                'job_id': job_id,
                'experiment_dir': experiment_dir,
                'output_dir': metadata['output_dir'],
                'metadata': metadata
            }
            
        finally:
            # Clean up temporary files
            for temp_file in temp_files_to_cleanup:
                try:
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                        logger.debug(f"Cleaned up temporary file: {temp_file}")
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup temporary file {temp_file}: {cleanup_error}")
        
    except Exception as e:
        error_msg = f"Error submitting experiment: {str(e)}"
        logger.error(error_msg)
        return {
            'success': False,
            'message': error_msg
        }


def repeat_experiment(report_path: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Repeat an existing experiment by resubmitting it to SLURM.
    
    Args:
        report_path: Path to the original experiment report
        config: Application configuration
    
    Returns:
        Dictionary with submission results
    """
    try:
        # Ensure QDashboard directories exist
        os.makedirs(config.get('data_dir', os.path.join(config['qd_root'], 'data')), exist_ok=True)
        os.makedirs(config.get('logs_dir', os.path.join(config['qd_root'], 'logs')), exist_ok=True)
        logs_dir = config.get('logs_dir', os.path.join(config['qd_root'], 'logs'))

        # Construct full path
        full_report_path = os.path.join(config['root'], report_path.lstrip('/'))
        
        if not os.path.exists(full_report_path):
            return {
                'success': False,
                'message': f'Report path does not exist: {report_path}'
            }
        
        # Find runcard in the report directory
        runcard_path = None
        for filename in os.listdir(full_report_path):
            if filename.startswith('runcard') and filename.endswith('.yml'):
                runcard_path = os.path.join(full_report_path, filename)
                break
        
        if not runcard_path:
            return {
                'success': False,
                'message': 'No runcard.yml file found in report directory'
            }
        
        # Read runcard to get platform and environment info
        with open(runcard_path, 'r') as f:
            runcard_data = yaml.safe_load(f)
        
        platform = runcard_data.get('platform')
        if not platform:
            return {
                'success': False,
                'message': 'No platform specified in runcard'
            }
        if platform not in get_qpu_list():
            return {
                'success': False,
                'message': f'Unknown platform "{platform}": not tracked in the platforms repository'
            }

        # Generate experiment ID for repeat experiment
        experiment_id = generate_experiment_id(runcard_path, platform)
        experiment_dir = create_experiment_directory(experiment_id, platform, config)
        
        # Copy runcard to experiment directory
        final_runcard_path, _ = prepare_runcard_from_path(runcard_path, experiment_dir)
        
        # Get platform information
        platforms_base = get_platforms_path(config['root'])
        if not platforms_base:
            return {
                'success': False,
                'message': 'Platforms directory not available'
            }
        
        # Determine partition
        partition = runcard_data.get('partition')
        if not partition:
            partition = get_partition(platform)
            if not partition:
                return {
                    'success': False,
                    'message': f'No partition specified and could not infer partition for platform {platform}'
                }
        
        # Use environment from runcard or config
        environment = runcard_data.get('environment') or config.get('environment')
        
        # Handle parameters.json backup if needed
        report_parameters_path = os.path.join(full_report_path, 'parameters.json')
        if os.path.exists(report_parameters_path):
            backup_parameters_path = os.path.join(experiment_dir, 'original_parameters.json')
            shutil.copy2(report_parameters_path, backup_parameters_path)
            logger.info(f"Backed up original parameters.json for reference")
        
        # Create SLURM script — logs go inside the experiment directory
        job_script_path = create_slurm_script(
            experiment_id, experiment_dir, final_runcard_path,
            platform, partition, platforms_base, environment, 
            logs_dir=None
        )
        
        # Submit job
        success, message, job_id = submit_slurm_job(job_script_path)
        
        if not success:
            return {
                'success': False,
                'message': message
            }
        
        # Save experiment metadata
        metadata = {
            'experiment_id': experiment_id,
            'job_id': job_id,
            'platform': platform,
            'partition': partition,
            'environment': environment,
            'submitted_at': time.time(),
            'experiment_dir': experiment_dir,
            'output_dir': os.path.join(experiment_dir, 'output'),
            'runcard_path': final_runcard_path,
            'job_script_path': job_script_path,
            'original_report_path': full_report_path,
            'type': 'repeat_experiment'
        }
        
        save_experiment_metadata(experiment_dir, metadata)
        
        # Update last report path using config
        last_report_path_file = config.get('last_report_path') or os.path.join(config['logs_dir'], 'last_report_path')
        ensure_directory_exists(os.path.dirname(last_report_path_file))
        with open(last_report_path_file, 'w') as f:
            f.write(metadata['output_dir'])
        
        logger.info(f"Repeat experiment submitted: {experiment_id} (original: {report_path})")
        
        return {
            'success': True,
            'message': 'Experiment repeat submitted successfully',
            'experiment_id': experiment_id,
            'job_id': job_id,
            'experiment_dir': experiment_dir,
            'output_dir': metadata['output_dir'],
            'original_report_path': full_report_path,
            'metadata': metadata
        }
        
    except Exception as e:
        error_msg = f"Error repeating experiment: {traceback.format_exc() if 'traceback' in globals() else str(e)}"
        logger.error(error_msg)
        return {
            'success': False,
            'message': error_msg
        }


def get_experiment_status(experiment_id: str, config: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
    """Get status information for an experiment."""
    try:
        if config:
            data_dir = config.get('data_dir') or os.path.join(config['qd_root'], 'data')
        else:
            qd_root = os.path.normpath(os.getenv('QD_ROOT', os.path.expanduser('~/.qdashboard')))
            data_dir = os.path.join(qd_root, 'data')

        # Search across nested platform/date structure.
        # Try two-level (data_dir/<platform>/<date>/<id>) first,
        # then one-level (data_dir/<date>/<id>) for deployments where
        # data_dir already embeds the platform name.
        pattern2 = os.path.join(data_dir, '*', '*', experiment_id, 'experiment_metadata.json')
        pattern1 = os.path.join(data_dir, '*', experiment_id, 'experiment_metadata.json')
        matches = glob.glob(pattern2) or glob.glob(pattern1)
        if not matches:
            return None
        metadata_path = matches[0]
        
        with open(metadata_path, 'r') as f:
            metadata = json.load(f)
        
        # Check if output directory exists and has results
        output_dir = metadata.get('output_dir')
        if output_dir and os.path.exists(output_dir):
            metadata['has_output'] = True
            metadata['output_files'] = os.listdir(output_dir)
        else:
            metadata['has_output'] = False
            metadata['output_files'] = []

        # --- SLURM-aware status ---
        # If the experiment was submitted via SLURM, check the live job state
        # first so we can short-circuit the filesystem poll while the job is
        # still in the queue.
        slurm_job_id = metadata.get('job_id')
        slurm_state = None
        if slurm_job_id:
            try:
                from ..qpu.slurm import check_slurm_job_status, _SLURM_ACTIVE_STATES
                slurm_state = check_slurm_job_status(slurm_job_id)
                metadata['slurm_state'] = slurm_state
                if slurm_state in _SLURM_ACTIVE_STATES:
                    # Job is still alive — no need to touch the filesystem
                    metadata['status'] = 'running' if slurm_state == 'RUNNING' else 'pending'
                    metadata['report_available'] = False
                    # Still expose the log path so the UI can tail it
                    exp_dir = metadata.get('experiment_dir', '')
                    slurm_log = os.path.join(exp_dir, 'logs', 'slurm_output.log')
                    metadata['has_slurm_log'] = os.path.exists(slurm_log)
                    return metadata
                # Job has left the queue (COMPLETED / FAILED / CANCELLED / UNKNOWN)
                # Fall through to filesystem check; treat missing output as failed.
            except Exception as _slurm_err:
                logger.debug("SLURM status check failed for job %s: %s", slurm_job_id, _slurm_err)

        # Compute dynamic status from filesystem
        report_index = os.path.join(output_dir or '', 'index.html') if output_dir else ''
        meta_json = os.path.join(output_dir or '', 'meta.json') if output_dir else ''
        if os.path.exists(report_index) or os.path.exists(meta_json):
            metadata['status'] = 'completed'
            metadata['report_available'] = os.path.exists(report_index)
        elif metadata.get('has_output'):
            # Output dir exists but no report yet — could still be post-processing
            metadata['status'] = 'running'
            metadata['report_available'] = False
        elif slurm_state is not None:
            # Job left the queue but produced no output → it failed
            metadata['status'] = 'failed'
            metadata['report_available'] = False
        else:
            metadata['status'] = metadata.get('status', 'pending')
            metadata['report_available'] = False

        # Check SLURM log if available
        exp_dir = metadata.get('experiment_dir', '')
        logs_dir = os.path.join(exp_dir, 'logs')
        slurm_log_path = os.path.join(logs_dir, 'slurm_output.log')
        if os.path.exists(slurm_log_path):
            metadata['has_slurm_log'] = True
        else:
            metadata['has_slurm_log'] = False

        return metadata
        
    except Exception as e:
        logger.error(f"Error getting experiment status: {str(e)}")
        return None


def list_user_experiments(config: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    """List all experiments, walking data_dir/<platform>/<date>/<id> structure."""
    try:
        if config:
            data_dir = config.get('data_dir') or os.path.join(config['qd_root'], 'data')
        else:
            qd_root = os.path.normpath(os.getenv('QD_ROOT', os.path.expanduser('~/.qdashboard')))
            data_dir = os.path.join(qd_root, 'data')

        if not os.path.exists(data_dir):
            return []

        experiments = []
        for metadata_path in glob.glob(os.path.join(data_dir, '*', '*', '*', 'experiment_metadata.json')):
            try:
                with open(metadata_path) as f:
                    metadata = json.load(f)
                experiment_id = metadata.get('experiment_id')
                if experiment_id:
                    status = get_experiment_status(experiment_id, config)
                    if status:
                        experiments.append(status)
            except Exception:
                pass
        
        # Sort by submission time (newest first)
        experiments.sort(key=lambda x: x.get('submitted_at', 0), reverse=True)
        
        return experiments
        
    except Exception as e:
        logger.error(f"Error listing user experiments: {str(e)}")
        return []


def find_latest_experiment(
    platform: str,
    protocol_id: str,
    qubits: List[str],
    config: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Find the most recent completed experiment for a given platform, protocol, and qubit set.

    Walks data_dir/<platform>/<date>/<experiment_id>/ in reverse-chronological order,
    reads each runcard.yml, and returns metadata for the first match where:
      - runcard platform matches *platform*
      - any action has id == *protocol_id*
      - qubit set is a subset of that action's targets
      - output/index.html exists (report is available)

    Returns None if no matching experiment is found.
    """
    data_dir = config.get("data_dir") or os.path.join(
        config.get("root", os.path.expanduser("~/.qdashboard")), "data"
    )
    platform_dir = os.path.join(data_dir, platform)
    if not os.path.isdir(platform_dir):
        return None

    qubit_set = set(qubits)

    # Collect all experiment dirs, sort newest-first
    date_dirs = sorted(
        [d for d in os.listdir(platform_dir) if os.path.isdir(os.path.join(platform_dir, d))],
        reverse=True,
    )

    scanned = 0
    for date_dir in date_dirs:
        full_date_dir = os.path.join(platform_dir, date_dir)
        exp_ids = sorted(os.listdir(full_date_dir), reverse=True)
        for exp_id in exp_ids:
            exp_dir = os.path.join(full_date_dir, exp_id)
            if not os.path.isdir(exp_dir):
                continue
            scanned += 1
            if scanned > 200:
                return None

            # Must have a completed report
            if not os.path.exists(os.path.join(exp_dir, "output", "index.html")):
                continue

            # Read runcard
            runcard_path = os.path.join(exp_dir, "runcard.yml")
            if not os.path.exists(runcard_path):
                continue
            try:
                with open(runcard_path) as f:
                    rc = yaml.safe_load(f)
                if not rc or rc.get("platform") != platform:
                    continue
                actions = rc.get("actions") or []
                match = False
                for action in (actions if isinstance(actions, list) else actions.values()):
                    if action.get("id") != protocol_id:
                        continue
                    targets = action.get("targets") or action.get("qubits") or []
                    if qubit_set and not qubit_set.issubset(set(str(q) for q in targets)):
                        continue
                    match = True
                    break
                if not match:
                    continue
            except Exception:
                continue

            # Read metadata
            meta_path = os.path.join(exp_dir, "experiment_metadata.json")
            try:
                with open(meta_path) as f:
                    metadata = json.load(f)
            except Exception:
                metadata = {}

            return {
                "experiment_id": exp_id,
                "experiment_dir": exp_dir,
                "output_dir": os.path.join(exp_dir, "output"),
                "platform": platform,
                "protocol_id": protocol_id,
                "submitted_at": metadata.get("submitted_at"),
                "job_id": metadata.get("job_id"),
            }

    return None


# =========================================================================== #
# Remote submission (remote_slurm / remote_direct modes)                      #
# =========================================================================== #

def _build_remote_slurm_script(
    experiment_id: str,
    remote_exp_dir: str,
    remote_runcard_path: str,
    platform: str,
    partition: str,
    remote_platforms_base: str,
    environment: str = None,
    auto_update: bool = True,
) -> str:
    """Return the text of a SLURM batch script for execution on the remote host."""
    remote_output_dir = f"{remote_exp_dir}/output"
    remote_logs_dir = f"{remote_exp_dir}/logs"
    activate_line = (
        f"source {environment}/bin/activate" if environment else "# No environment specified"
    )

    return f"""#!/bin/bash
#SBATCH --job-name={experiment_id}
#SBATCH --partition={partition}
#SBATCH --output={remote_logs_dir}/slurm_output.log
#SBATCH --time=01:00:00

export QIBOLAB_PLATFORMS={remote_platforms_base}
export QIBO_PLATFORM={platform}

mkdir -p {remote_output_dir} {remote_logs_dir}

echo "Job ID: $SLURM_JOB_ID"
echo "Experiment ID: {experiment_id}"
echo "Platform: {platform}"
echo "Start time: $(date)"

cd {remote_exp_dir}

{activate_line}

echo "Running experiment..."
qq run {remote_runcard_path} -o {remote_output_dir} -f{'' if auto_update else ' --no-update'}

echo "End time: $(date)"
echo "Exit code: $?"
exit 0
"""


async def submit_experiment_remote(
    runcard_data: Dict[str, Any],
    config: Dict[str, Any],
    settings,
    ssh_manager,
    environment: str = None,
    auto_update: bool = True,
) -> Dict[str, Any]:
    """Submit an experiment to a remote host via SSH.

    Supports both ``remote_slurm`` (sbatch) and ``remote_direct`` (qq run via
    nohup) execution modes as indicated by *settings*.

    The experiment directory is created both locally (for tracking and future
    sync target) and on the remote (for actual execution).  The runcard is
    uploaded via SFTP before submission.

    Returns the same dict shape as :func:`submit_experiment`.
    """
    try:
        if 'platform' not in runcard_data:
            return {'success': False, 'message': 'Missing required field: platform'}

        if not ssh_manager.is_connected():
            return {
                'success': False,
                'message': 'Not connected to remote host.  Open Settings → Remote and click Connect.',
            }

        platform = runcard_data['platform']
        effective_env = (
            environment
            or runcard_data.get('environment')
            or settings.remote_environment
            or None
        )

        # ------------------------------------------------------------------ #
        # 1. Create local experiment directory (tracking + sync target)       #
        # ------------------------------------------------------------------ #
        ensure_directory_exists(config.get('data_dir', os.path.join(config['qd_root'], 'data')))
        temp_dir = config.get('temp_dir') or get_temp_dir()
        temp_runcard = create_temp_runcard_from_data(runcard_data, temp_dir)
        try:
            experiment_id = generate_experiment_id(temp_runcard, platform)
        finally:
            try:
                os.unlink(temp_runcard)
            except OSError:
                pass

        local_exp_dir = create_experiment_directory(experiment_id, platform, config)
        local_runcard_path, _ = prepare_runcard_from_data(runcard_data, local_exp_dir)
        date_str = experiment_id.split('-')[0]

        # ------------------------------------------------------------------ #
        # 2. Resolve remote home and build remote paths                       #
        # ------------------------------------------------------------------ #
        from ..remote.file_sync import _resolve_remote_home
        remote_home = await _resolve_remote_home(ssh_manager)

        def _rexpand(path: str) -> str:
            return path.replace('~', remote_home, 1) if remote_home and path.startswith('~') else path

        remote_root = _rexpand(settings.remote_root)
        remote_exp_dir = f"{remote_root}/{platform}/{date_str}/{experiment_id}"
        remote_runcard = f"{remote_exp_dir}/runcard.yml"
        remote_script = f"{remote_exp_dir}/job_script.sh"

        # ------------------------------------------------------------------ #
        # 3. Create remote directories                                        #
        # ------------------------------------------------------------------ #
        _, _, rc = await ssh_manager.run(
            f"mkdir -p {remote_exp_dir}/output {remote_exp_dir}/logs",
            timeout=15,
        )
        if rc != 0:
            return {
                'success': False,
                'message': f'Failed to create remote directory: {remote_exp_dir}',
            }

        # ------------------------------------------------------------------ #
        # 4. Upload runcard via SFTP                                          #
        # ------------------------------------------------------------------ #
        from ..remote.file_sync import sftp_upload_file, sftp_upload_text
        try:
            await sftp_upload_file(local_runcard_path, remote_runcard, ssh_manager)
        except Exception as _upload_err:
            return {
                'success': False,
                'message': f'Failed to upload runcard to remote: {_upload_err}',
            }

        # ------------------------------------------------------------------ #
        # 5. Determine SLURM partition and remote platforms path              #
        # ------------------------------------------------------------------ #
        partition = runcard_data.get('partition') or get_partition(platform) or 'default'
        from ..remote.platforms_git import resolve_remote_platforms_path
        remote_platforms_base = await resolve_remote_platforms_path(settings, ssh_manager)

        # ------------------------------------------------------------------ #
        # 6. Submit via sbatch or direct exec                                 #
        # ------------------------------------------------------------------ #
        job_id: Optional[str] = None
        execution_note = ''

        if settings.uses_slurm():
            script_content = _build_remote_slurm_script(
                experiment_id, remote_exp_dir, remote_runcard,
                platform, partition, remote_platforms_base,
                effective_env, auto_update,
            )
            try:
                await sftp_upload_text(script_content, remote_script, ssh_manager)
            except Exception as _script_err:
                return {
                    'success': False,
                    'message': f'Failed to upload job script to remote: {_script_err}',
                }
            await ssh_manager.run(f"chmod +x {remote_script}", timeout=10)
            stdout, stderr, rc = await ssh_manager.run(f"sbatch {remote_script}", timeout=30)
            if rc != 0:
                return {'success': False, 'message': f'sbatch failed: {stderr.strip()}'}
            for line in stdout.splitlines():
                if 'Submitted batch job' in line:
                    job_id = line.split()[-1]
                    break
            execution_note = f'SLURM job {job_id} on {settings.remote_host}'
            logger.info('Remote SLURM job: %s → job_id=%s', experiment_id, job_id)

        else:
            # remote_direct — launch qq run detached via nohup
            if effective_env:
                env_activate = f"source {effective_env}/bin/activate && "
            else:
                env_activate = ''
            remote_output_dir = f"{remote_exp_dir}/output"
            remote_log = f"{remote_exp_dir}/logs/slurm_output.log"
            no_upd = '' if auto_update else ' --no-update'
            direct_cmd = (
                f"nohup bash -c '"
                f"export QIBOLAB_PLATFORMS={remote_platforms_base}; "
                f"{env_activate}"
                f"qq run {remote_runcard} -o {remote_output_dir} -f{no_upd}"
                f"' >> {remote_log} 2>&1 & echo $!"
            )
            stdout, stderr, rc = await ssh_manager.run(direct_cmd, timeout=30)
            if rc != 0:
                return {'success': False, 'message': f'Remote direct exec failed: {stderr.strip()}'}
            pid = stdout.strip()
            job_id = f"pid_{pid}"
            execution_note = f'Direct exec PID {pid} on {settings.remote_host}'
            logger.info('Remote direct exec: %s → PID %s', experiment_id, pid)

        # ------------------------------------------------------------------ #
        # 7. Save local metadata                                              #
        # ------------------------------------------------------------------ #
        metadata = {
            'experiment_id': experiment_id,
            'job_id': job_id,
            'platform': platform,
            'partition': partition,
            'environment': effective_env,
            'submitted_at': time.time(),
            'experiment_dir': local_exp_dir,
            'output_dir': os.path.join(local_exp_dir, 'output'),
            'runcard_path': local_runcard_path,
            'remote_exp_dir': remote_exp_dir,
            'remote_host': settings.remote_host,
            'execution_mode': settings.execution_mode,
            'type': 'new_experiment',
            'source': 'runcard_data',
            'note': execution_note,
        }
        save_experiment_metadata(local_exp_dir, metadata)

        # ------------------------------------------------------------------ #
        # 8. Write to local DB                                                #
        # ------------------------------------------------------------------ #
        try:
            from ..db.database import (
                get_db_connection, get_or_create_qpu, upsert_experiment_run,
                add_qpu_qubits, _extract_protocol_info,
            )
            with get_db_connection(config) as conn:
                qpu_id = get_or_create_qpu(conn, platform)
                proto_id, proto_name, qubit_list = _extract_protocol_info(runcard_data)
                if qubit_list:
                    add_qpu_qubits(conn, qpu_id, qubit_list)
                upsert_experiment_run(conn, {
                    'experiment_id': experiment_id,
                    'qpu_id': qpu_id,
                    'protocol_id': proto_id,
                    'protocol_name': proto_name,
                    'target_qubits': qubit_list,
                    'submitted_at': metadata['submitted_at'],
                    'slurm_job_id': job_id,
                    'status': 'pending',
                    'runcard_path': local_runcard_path,
                    'output_dir': metadata['output_dir'],
                })
        except Exception as _db_exc:
            logger.warning('Remote submit DB write failed (non-fatal): %s', _db_exc)

        return {
            'success': True,
            'message': f'Experiment submitted: {execution_note}',
            'experiment_id': experiment_id,
            'job_id': job_id,
            'experiment_dir': local_exp_dir,
            'output_dir': metadata['output_dir'],
            'metadata': metadata,
        }

    except Exception as exc:
        logger.exception('submit_experiment_remote error')
        return {'success': False, 'message': f'Remote submission error: {exc}'}


# =========================================================================== #
# Local direct submission (local_direct mode)                                 #
# =========================================================================== #

def submit_experiment_direct(
    runcard_data: Dict[str, Any],
    config: Dict[str, Any],
    environment: str = None,
    auto_update: bool = True,
) -> Dict[str, Any]:
    """Submit an experiment directly (no SLURM) on the local machine.

    Launches ``qq run`` as a background process with ``start_new_session=True``
    so it survives if the dashboard restarts.  The PID is stored as the
    pseudo job-ID (prefixed ``local_``).

    Returns the same dict shape as :func:`submit_experiment`.
    """
    try:
        if 'platform' not in runcard_data:
            return {'success': False, 'message': 'Missing required field: platform'}

        platform = runcard_data['platform']
        effective_env = environment or runcard_data.get('environment') or config.get('environment')

        ensure_directory_exists(config.get('data_dir', os.path.join(config['qd_root'], 'data')))
        temp_dir = config.get('temp_dir') or get_temp_dir()
        temp_runcard = create_temp_runcard_from_data(runcard_data, temp_dir)
        try:
            experiment_id = generate_experiment_id(temp_runcard, platform)
        finally:
            try:
                os.unlink(temp_runcard)
            except OSError:
                pass

        local_exp_dir = create_experiment_directory(experiment_id, platform, config)
        local_runcard_path, _ = prepare_runcard_from_data(runcard_data, local_exp_dir)
        output_dir = os.path.join(local_exp_dir, 'output')
        logs_dir = os.path.join(local_exp_dir, 'logs')
        ensure_directory_exists(output_dir)
        ensure_directory_exists(logs_dir)
        log_file = os.path.join(logs_dir, 'slurm_output.log')

        platforms_base = get_platforms_path(config.get('root', '')) or ''

        cmd_parts = ['qq', 'run', local_runcard_path, '-o', output_dir, '-f']
        if not auto_update:
            cmd_parts.append('--no-update')

        env_vars = os.environ.copy()
        if platforms_base:
            env_vars['QIBOLAB_PLATFORMS'] = platforms_base
        env_vars['QIBO_PLATFORM'] = platform

        # If a venv/conda environment is specified, wrap in a bash source
        if effective_env:
            activate = os.path.join(os.path.expanduser(effective_env), 'bin', 'activate')
            if os.path.exists(activate):
                cmd_parts = ['bash', '-c', f"source {activate} && " + ' '.join(cmd_parts)]

        with open(log_file, 'w') as log_fh:
            proc = subprocess.Popen(
                cmd_parts,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                env=env_vars,
                start_new_session=True,
            )

        job_id = f"local_{proc.pid}"
        metadata = {
            'experiment_id': experiment_id,
            'job_id': job_id,
            'platform': platform,
            'environment': effective_env,
            'submitted_at': time.time(),
            'experiment_dir': local_exp_dir,
            'output_dir': output_dir,
            'runcard_path': local_runcard_path,
            'execution_mode': 'local_direct',
            'type': 'new_experiment',
            'source': 'runcard_data',
        }
        save_experiment_metadata(local_exp_dir, metadata)

        try:
            from ..db.database import (
                get_db_connection, get_or_create_qpu, upsert_experiment_run,
                add_qpu_qubits, _extract_protocol_info,
            )
            with get_db_connection(config) as conn:
                qpu_id = get_or_create_qpu(conn, platform)
                proto_id, proto_name, qubit_list = _extract_protocol_info(runcard_data)
                if qubit_list:
                    add_qpu_qubits(conn, qpu_id, qubit_list)
                upsert_experiment_run(conn, {
                    'experiment_id': experiment_id,
                    'qpu_id': qpu_id,
                    'protocol_id': proto_id,
                    'protocol_name': proto_name,
                    'target_qubits': qubit_list,
                    'submitted_at': metadata['submitted_at'],
                    'slurm_job_id': job_id,
                    'status': 'running',
                    'runcard_path': local_runcard_path,
                    'output_dir': output_dir,
                })
        except Exception as _db_exc:
            logger.warning('Direct submit DB write failed (non-fatal): %s', _db_exc)

        logger.info('Local direct experiment started: %s (PID %s)', experiment_id, proc.pid)
        return {
            'success': True,
            'message': f'Experiment started locally (PID {proc.pid})',
            'experiment_id': experiment_id,
            'job_id': job_id,
            'experiment_dir': local_exp_dir,
            'output_dir': output_dir,
            'metadata': metadata,
        }

    except Exception as exc:
        logger.exception('submit_experiment_direct error')
        return {'success': False, 'message': f'Direct submission error: {exc}'}


