"""
QPU health monitoring and status utilities.
"""

import os
import json
import subprocess
from .slurm import check_queue_running_jobs
from .platforms import get_platforms_path

# Optional qibolab imports
try:
    from qibolab._core.backends import QibolabBackend
    from qibolab._core.platform.platform import Platform as QibolabPlatform
    QIBOLAB_AVAILABLE = True
except ImportError:
    QIBOLAB_AVAILABLE = False

def get_qpu_health():
    """Get overall QPU health status."""
    # Placeholder for now - could be expanded to check multiple health metrics
    return "N/A"


def get_available_qpus():
    """Get count of available QPUs from the platforms directory."""
    root = os.path.normpath(os.environ.get('HOME'))
    qrc_path = get_platforms_path(root)
    
    # Check if platforms directory exists
    if not qrc_path or not os.path.exists(qrc_path):
        return "N/A"
    
    try:
        with open(os.path.join(qrc_path, 'queues.json'), 'r') as f:
            queues = json.load(f)
    except (IOError, json.JSONDecodeError):
        queues = {}
    
    total_qpus = 0
    online_qpus = 0
    
    try:
       
        for qpu_name in os.listdir(qrc_path):
            if qpu_name.startswith(('_', '.')):
                continue
            qpu_path = os.path.join(qrc_path, qpu_name)
            if os.path.isdir(qpu_path) and 'platform.py' in os.listdir(qpu_path):
                total_qpus += 1
                
                # Check if QPU is online based on SLURM queue status
                queue_name = queues.get(qpu_name, 'N/A')
                if queue_name != 'N/A':
                    try:
                        sinfo_output = subprocess.check_output(['sinfo', '-p', queue_name]).decode()
                        if queue_name in sinfo_output:
                            online_qpus += 1
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        pass  # Keep as offline if sinfo fails
    except OSError:
        return "N/A"
    
    return f"{online_qpus} / {total_qpus}"


def get_qibo_versions():
    """Get versions of qibo, qibolab, and qibocal packages."""
    versions = {}
    packages = ['qibo', 'qibolab', 'qibocal']
    
    for package in packages:
        try:
            import importlib
            module = importlib.import_module(package)
            versions[package] = getattr(module, '__version__', 'Unknown')
        except ImportError as e:
            # print(f"DEBUG {package}: {e}")
            versions[package] = 'Not installed'
        except Exception as e:
            error_msg = str(e)
            if "signal only works in main thread" in error_msg:
                # Try pip show as fallback for version detection
                try:
                    import subprocess
                    result = subprocess.run(['pip', 'show', package], 
                                          capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        for line in result.stdout.split('\n'):
                            if line.startswith('Version:'):
                                versions[package] = line.split(':', 1)[1].strip()
                                break
                        else:
                            versions[package] = 'Version unknown'
                    else:
                        versions[package] = 'Threading error'
                except Exception:
                    versions[package] = 'Threading error'
            else:
                versions[package] = f'Error: {error_msg[:50]}'
    
    return versions


def get_qpu_list():
    """Get list of available QPU platforms from the qibolab platforms directory."""
    root = os.path.normpath(os.environ.get('HOME'))
    qrc_path = get_platforms_path(root)
    qpus = []
    
    if qrc_path and os.path.exists(qrc_path):
        try:
            for qpu_name in os.listdir(qrc_path):
                if qpu_name.startswith(('_', '.')):
                    continue
                qpu_path = os.path.join(qrc_path, qpu_name)
                if os.path.isdir(qpu_path) and 'platform.py' in os.listdir(qpu_path):
                    qpus.append(qpu_name)
        except OSError:
            pass
    
    # Fallback to default QPUs if directory doesn't exist or is empty
    if not qpus:
        qpus = ["qpu_dummy"]
    
    return sorted(qpus)


def get_qpu_details():
    """Get detailed information about all available QPUs."""
    root = os.path.normpath(os.environ.get('HOME'))
    qrc_path = get_platforms_path(root)
    qpus_list = []
    qpu_names = get_qpu_list()

    # Get git branch information
    git_branch = 'N/A'
    git_commit = 'N/A'
    
    if qrc_path and os.path.exists(qrc_path):
        try:
            # Check if the directory is a git repository
            git_dir = os.path.join(qrc_path, '.git')
            if os.path.exists(git_dir) or os.path.exists(os.path.join(os.path.dirname(qrc_path), '.git')):
                # Get current branch
                branch_output = subprocess.check_output(['git', 'branch', '--show-current'], 
                                                      cwd=qrc_path, stderr=subprocess.DEVNULL).decode().strip()
                if branch_output:
                    git_branch = branch_output
                
                # Get short commit hash
                commit_output = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], 
                                                      cwd=qrc_path, stderr=subprocess.DEVNULL).decode().strip()
                if commit_output:
                    git_commit = commit_output
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            pass  # Keep defaults if git commands fail
    
    try:
        with open(os.path.join(qrc_path, 'queues.json'), 'r') as f:
            queues = json.load(f)
    except (IOError, json.JSONDecodeError):
        queues = {}

    if os.path.exists(qrc_path):
        # Import topology functions here to avoid circular imports
        from .topology import get_topology_from_qpu_config

        for qpu_name in qpu_names:
                qpu_path = os.path.join(qrc_path, qpu_name)
            
                # Defaults
                num_qubits = 'N/A'
                topology = 'N/A'
                calibration_time = 'N/A'
                status = 'offline'
                
                # Get queue info and check status
                queue_name = queues.get(qpu_name, 'N/A')
                if queue_name != 'N/A':
                    try:
                        sinfo_output = subprocess.check_output(['sinfo', '-p', queue_name]).decode()
                        if queue_name in sinfo_output:
                            # Check if there are running jobs in this queue
                            if check_queue_running_jobs(queue_name):
                                status = 'running'
                            else:
                                # Ping the connection and test if its available using a srun submission
                                try:
                                    # Get the electronics IP from the configuration
                                    electronics_ip = get_instruments_ip(qpu_name)
                                    print(f"DEBUG: Electronics IP for {qpu_name}: {electronics_ip}")
                                    # ping all the ips in electronics_ip in a single slurm job
                                    job_script = f"""
#!/bin/bash
# Job script to ping electronics IPs for {qpu_name}
for ip in {electronics_ip}; do
    ping -c 1 $ip > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        echo "Connection error to $ip"
        exit 1
    fi
done
echo "All electronics IPs are reachable"
                                        """
                                    with open('ping_electronics.sh', 'w') as script_file:
                                        script_file.write(job_script)
                                    os_process = subprocess.run(
                                        ["bash", "ping_electronics.sh"],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5
                                    )
                                    if os_process.returncode != 0:
                                        status = 'connection error'
                                    else:
                                        status = 'online'
                                except subprocess.TimeoutExpired:
                                    # If the ping command times out, set status to connection error
                                    status = 'connection error'
                                except subprocess.CalledProcessError:
                                    # If the ping command fails, set status to connection error
                                    status = 'connection error'
                                except FileNotFoundError:
                                    # If the script file is not found, set status to connection error
                                    status = 'connection error'
                                except Exception as e:
                                    # Catch any other exceptions and set status to connection error
                                    print(f"Unexpected error: {e}")
                                    status = 'offline'
                                except subprocess.TimeoutExpired:
                                    status = 'connection error'

                                status = 'online'
                    except (subprocess.CalledProcessError, FileNotFoundError):
                        pass  # Keep status as offline if sinfo fails or queue not found

                # Get qubit count from platform.py
                platform_py_path = os.path.join(qpu_path, 'platform.py')
                if os.path.exists(platform_py_path):
                    with open(platform_py_path, 'r') as f:
                        for line in f:
                            if 'NUM_QUBITS' in line:
                                try:
                                    num_qubits = int(line.split('=')[1].strip())
                                except (ValueError, IndexError):
                                    continue
                
                # Infer topology from configuration files
                topology = get_topology_from_qpu_config(qpu_path)
                
                qpus_list.append({
                    'name': qpu_name,
                    'qubits': num_qubits,
                    'status': status,
                    'queue': queue_name,
                    'topology': topology,
                    'calibration_time': calibration_time
                })

    return {
        'qpus': qpus_list,
        'git_branch': git_branch,
        'git_commit': git_commit,
        'platforms_path': qrc_path
    }

def get_instruments_ip(platform):
    # CReate a qibolab platform and read the address of the controller
   

    backend:QibolabBackend = QibolabBackend(platform=platform)
    platform:QibolabPlatform = backend.platform

    instruments = platform.instruments
    ips = []
    for inst_name in instruments:
        instrument = instruments[inst_name]
        # Check i fthe instrument has a key 'ADDRESS' or 'address'
        if hasattr(instrument, 'address'):
            ips.append(instrument.address)
        elif hasattr(instrument, 'ADDRESS'):
            ips.append(instrument.ADDRESS)
    return ips if ips else 'N/A'

