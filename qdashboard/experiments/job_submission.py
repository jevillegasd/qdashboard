"""
Experiment job submission and management functionality.
"""

import os
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
from ..utils.logger import get_logger
from ..core.config import get_temp_dir, ensure_directory_exists

logger = get_logger(__name__)


def generate_experiment_id(runcard_path: str, platform: str) -> str:
    """Generate a unique experiment ID based on runcard content and timestamp."""
    timestamp = int(time.time())
    
    # Create hash from runcard content and platform
    hasher = hashlib.md5()
    hasher.update(platform.encode())
    hasher.update(str(timestamp).encode())
    
    if os.path.exists(runcard_path):
        with open(runcard_path, 'rb') as f:
            hasher.update(f.read())
    
    experiment_hash = hasher.hexdigest()[:8]
    timestamp_hex = format(timestamp, '08x')
    
    return f"exp_{timestamp_hex}_{experiment_hash}"


def create_experiment_directory(experiment_id: str, config: Dict[str, Any]) -> str:
    """Create experiment directory using standardized QDashboard paths."""
    data_dir = config.get('data_dir') or os.path.join(config['qd_root'], 'data')
    experiment_dir = os.path.join(data_dir, experiment_id)
    
    # Create directory structure
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
                       environment: str = None, logs_dir: str = None) -> str:
    """Create SLURM job submission script."""
   
    output_dir = os.path.join(experiment_dir, 'output')
    ensure_directory_exists(output_dir)
    
    # Create logs directory for SLURM output
    if not logs_dir:
        logs_dir = os.path.join(experiment_dir, 'logs')
    ensure_directory_exists(logs_dir)
    
    job_script_content = f"""#!/bin/bash
#SBATCH --job-name={experiment_id}
#SBATCH --partition={partition}
#SBATCH --output={logs_dir}/slurm_output.log
#SBATCH --error={logs_dir}/slurm_error.log
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
{f'source ~/.env/{environment}/bin/activate' if environment else '# No environment specified'}

# Run the experiment
echo "Running experiment..."
qq run {runcard_path} -o {output_dir} -f --no-update

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
                     config: Dict[str, Any] = None, environment: str = None) -> Dict[str, Any]:
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
            
            # Generate experiment ID and create directory
            experiment_id = generate_experiment_id(temp_runcard_path, platform)
            experiment_dir = create_experiment_directory(experiment_id, config)
            
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
            
            # Create SLURM script
            job_script_path = create_slurm_script(
                experiment_id, experiment_dir, final_runcard_path,
                platform, partition, platforms_base, environment, logs_dir=config.get('logs_dir')
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
        
        # Generate experiment ID for repeat experiment
        experiment_id = generate_experiment_id(runcard_path, platform)
        experiment_dir = create_experiment_directory(experiment_id, config)
        
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
        
        # Create SLURM script
        job_script_path = create_slurm_script(
            experiment_id, experiment_dir, final_runcard_path,
            platform, partition, platforms_base, environment, 
            logs_dir=logs_dir
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
            user_home = os.path.expanduser("~")
            qd_root = os.path.normpath(os.getenv('QD_PATH', os.path.join(user_home, '.qdashboard')))
            data_dir = os.path.join(qd_root, 'data')
            
        experiment_dir = os.path.join(data_dir, experiment_id)
        metadata_path = os.path.join(experiment_dir, 'experiment_metadata.json')
        
        if not os.path.exists(metadata_path):
            return None
        
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
        
        # Check SLURM log if available
        logs_dir = os.path.join(experiment_dir, 'logs')
        slurm_log_path = os.path.join(logs_dir, 'slurm_output.log')
        if os.path.exists(slurm_log_path):
            metadata['has_slurm_log'] = True
            # Could read last few lines of log for status
        else:
            metadata['has_slurm_log'] = False
        
        return metadata
        
    except Exception as e:
        logger.error(f"Error getting experiment status: {str(e)}")
        return None


def list_user_experiments(config: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    """List all experiments for the current user."""
    try:
        if config:
            data_dir = config.get('data_dir') or os.path.join(config['qd_root'], 'data')
        else:
            user_home = os.path.expanduser("~")
            qd_root = os.path.normpath(os.getenv('QD_PATH', os.path.join(user_home, '.qdashboard')))
            data_dir = os.path.join(qd_root, 'data')
        
        if not os.path.exists(data_dir):
            return []
        
        experiments = []
        for experiment_id in os.listdir(data_dir):
            experiment_path = os.path.join(data_dir, experiment_id)
            if os.path.isdir(experiment_path):
                status = get_experiment_status(experiment_id, config)
                if status:
                    experiments.append(status)
        
        # Sort by submission time (newest first)
        experiments.sort(key=lambda x: x.get('submitted_at', 0), reverse=True)
        
        return experiments
        
    except Exception as e:
        logger.error(f"Error listing user experiments: {str(e)}")
        return []
