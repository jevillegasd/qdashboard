"""
SLURM queue management and monitoring utilities.
"""

import os
import subprocess


def get_slurm_status():
    """Get SLURM queue status as structured data for table display."""
    try:
        # Get current user
        current_user = os.environ.get('USER', 'unknown')
        
        # Get squeue output with specific format
        result = subprocess.check_output(['squeue', '--format=%i %.18j %.8u %.8T %.10M %.9l %.6D %P %R', '--noheader'], 
                                       stderr=subprocess.DEVNULL).decode()
        
        jobs = []
        for line in result.strip().split('\n'):
            if line.strip() and 'sim' not in line.lower():
                parts = line.split()
                if len(parts) >= 8:
                    # Create a job object with attributes that match the template expectations
                    class Job:
                        def __init__(self, job_id, name, user, state, time, time_limit, nodes, nodelist, current_user, partition):
                            self.job_id = job_id
                            self.name = name
                            self.user = user
                            self.state = state
                            self.time = time
                            self.time_limit = time_limit
                            self.nodes = nodes
                            self.nodelist = nodelist
                            self.partition = partition
                            # Handle username truncation in SLURM output
                            # Check if truncated user matches the beginning of current_user
                            self.is_current_user = (user == current_user or current_user.startswith(user))
                    
                    if parts[7] == 'sim':
                        continue # skip simualtion jobs
                    job = Job(
                        job_id=parts[0],
                        name=parts[1],
                        user=parts[2],
                        state=parts[3],
                        time=parts[4],
                        time_limit=parts[5],
                        nodes=parts[6],
                        partition=parts[7],  # Partition is the 8th part
                        nodelist=' '.join(parts[8:]),  # Join remaining parts for node list
                        current_user=current_user
                    )
                    jobs.append(job)
        
        return jobs
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Return empty list if squeue command fails
        return []


def check_queue_running_jobs(queue_name):
    """Check if there are running jobs in a specific SLURM queue."""
    try:
        # Use squeue to check for running jobs in the specific partition
        squeue_output = subprocess.check_output(['squeue', '-p', queue_name, '-t', 'RUNNING'], 
                                               stderr=subprocess.DEVNULL).decode()
        # If there's output beyond the header line, there are running jobs
        lines = squeue_output.strip().split('\n')
        return len(lines) > 1  # More than just the header line means there are running jobs
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False  # If command fails, assume no running jobs


def slurm_log_path():
    home_path = os.environ.get('HOME')
    return os.path.join(home_path, ".qdashboard/logs/slurm_output.log")

def get_slurm_output(slurm_output_path=None):
    """Get SLURM output log content."""
    if slurm_output_path is None:
        slurm_output_path = slurm_log_path()
    
    try:
        with open(slurm_output_path, 'r') as file:
            log_content = file.read()
        return log_content.replace('\n', '<br>')
    except (IOError, OSError):
        return "No SLURM output available"


def parse_slurm_log_for_errors(slurm_output_path=None):
    """
    Parse SLURM log file to extract error information from the last entries.
    Returns a tuple (has_error, error_message)
    """
    if slurm_output_path is None:
        slurm_output_path = slurm_log_path()
    
    try:
        with open(slurm_output_path, 'r') as file:
            log_content = file.read().strip()
        
        if not log_content:
            return False, "No log content available"
        
        # Split into lines and get the last few entries
        lines = log_content.split('\n')
        last_lines = lines[-10:]  # Check last 10 lines for errors
        
        # Common error patterns in SLURM logs
        error_patterns = [
            r'error', r'failed', r'exception', r'traceback', r'stderr',
            r'cannot', r'unable', r'permission denied', r'no such file',
            r'command not found', r'killed', r'timeout', r'cancelled'
        ]
        
        error_messages = []
        
        # Check for error patterns in the last lines
        for line in reversed(last_lines):  # Check from newest to oldest
            line_lower = line.lower().strip()
            if any(pattern in line_lower for pattern in error_patterns):
                error_messages.append(line.strip())
                if len(error_messages) >= 3:  # Limit to 3 most recent errors
                    break
        
        if error_messages:
            # Return the most recent meaningful error
            return True, error_messages[0]
        else:
            # Check if the log ends with any completion indicators
            last_line = lines[-1].lower().strip() if lines else ""
            if any(word in last_line for word in ['completed', 'finished', 'done', 'success']):
                return False, "Job completed successfully"
            else:
                return False, "No errors detected in recent logs"
                
    except (IOError, OSError):
        return True, "Unable to read SLURM log file"
    except Exception as e:
        return True, f"Error parsing log: {str(e)}"
