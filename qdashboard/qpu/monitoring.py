"""
QPU health monitoring and status utilities.
"""

import os
import json
import subprocess
import traceback
import signal
from datetime import datetime
from packaging import version
from qdashboard.utils.logger import get_logger
from .slurm import check_queue_running_jobs
from .platforms import get_platforms_path
from .utils import detect_and_save_qibolab_version, is_qibolab_new_api, get_qibolab_version_from_file
from .topology import get_topology_from_platform, get_topology_from_qpu_config

# Optional qibolab imports
try:
    from qibolab._core.backends import QibolabBackend
    from qibolab._core.platform.platform import Platform as QibolabPlatform
    from qibolab import create_platform
    QIBOLAB_AVAILABLE = True
except ImportError:
    QIBOLAB_AVAILABLE = False

logger = get_logger(__name__)

def get_qpu_health():
    """Get overall QPU health status."""
    # Placeholder for now - could be expanded to check multiple health metrics
    return "N/A"


def check_qpu_queue_status(qpu_name, queue_name):
    """
    Check if a QPU is online based on SLURM queue status.
    
    Args:
        qpu_name: Name of the QPU
        queue_name: Name of the SLURM queue for this QPU
        
    Returns:
        str: Status - 'online', 'running', 'connection error', or 'offline'
    """
    if queue_name == 'N/A':
        return 'offline'
    
    try:
        sinfo_output = subprocess.check_output(['sinfo', '-p', queue_name]).decode()
        if queue_name in sinfo_output:
            # Check if there are running jobs in this queue
            if check_queue_running_jobs(queue_name):
                return 'running'
            else:
                # For more detailed connection checking, we can optionally add ping tests
                # For now, just return online if queue is available
                return 'online'
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass  # Keep as offline if sinfo fails
    
    return 'offline'


def get_connection_status(qpu_name, queue_name):
    """
    Get connection status for a QPU including detailed connection tests.
    
    Args:
        qpu_name: Name of the QPU
        queue_name: Name of the SLURM queue for this QPU
        
    Returns:
        str: Connection status - 'online', 'running', 'connection error', or 'offline'
    """
    # First check basic queue status
    basic_status = check_qpu_queue_status(qpu_name, queue_name)
    
    if basic_status == 'offline':
        return 'offline'
    elif basic_status == 'running':
        return 'running'
    else:
        # For 'online' status, do additional connection tests
        try:
            # Get the electronics IP from the configuration
            electronics_ip = get_instruments_ip(qpu_name)
            logger.debug(f"Electronics IP for {qpu_name}: {electronics_ip}")
            
            # Create ping script
            job_script = f"""#!/bin/bash
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
                return 'connection error'
            else:
                return 'online'
                
        except subprocess.TimeoutExpired:
            return 'connection error'
        except (subprocess.CalledProcessError, FileNotFoundError, Exception):
            return 'offline'


def get_qpu_queue_mapping(qrc_path):
    """
    Get the mapping of QPU names to queue names from queues.json.
    
    Args:
        qrc_path: Path to the platforms directory
        
    Returns:
        dict: Mapping of QPU names to queue names
    """
    try:
        with open(os.path.join(qrc_path, 'queues.json'), 'r') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError):
        return {}


def get_available_qpus():
    """Get count of available QPUs from the platforms directory."""
    root = os.path.normpath(os.environ.get('HOME'))
    qrc_path = get_platforms_path(root)
    
    # Check if platforms directory exists
    if not qrc_path or not os.path.exists(qrc_path):
        return "N/A"
    
    queues = get_qpu_queue_mapping(qrc_path)
    total_qpus = 0
    online_qpus = 0
    
    try:
        for qpu_name in os.listdir(qrc_path):
            if qpu_name.startswith(('_', '.')):
                continue
            qpu_path = os.path.join(qrc_path, qpu_name)
            if os.path.isdir(qpu_path) and 'platform.py' in os.listdir(qpu_path):
                total_qpus += 1
                
                # Check if QPU is online using shared function
                queue_name = queues.get(qpu_name, 'N/A')
                status = get_connection_status(qpu_name, queue_name)
                if status in ['online', 'running']:
                    online_qpus += 1
    except OSError:
        return "N/A"
    
    return f"{online_qpus} / {total_qpus}"


def get_qibo_versions(force_refresh=False, request=None):
    """
    Get versions of qibo, qibolab, and qibocal packages.
    Uses cookie caching for efficiency.
    
    Args:
        force_refresh: Force refresh of versions (bypass cache)
        request: Flask request object for cookie handling
        
    Returns:
        dict: Package versions and cookie update info
    """
    import time
    import json
    
    # Cookie settings
    COOKIE_NAME = 'qibo_versions'
    CACHE_DURATION = 24 * 60 * 60  # 24 hours in seconds
    
    # Check if we can use cached versions
    if not force_refresh and request and COOKIE_NAME in request.cookies:
        try:
            cookie_data = json.loads(request.cookies[COOKIE_NAME])
            cached_time = cookie_data.get('timestamp', 0)
            current_time = time.time()
            
            # Use cached data if it's not expired
            if current_time - cached_time < CACHE_DURATION:
                logger.debug("Using cached qibo versions from cookie")
                return {
                    'versions': cookie_data.get('versions', {}),
                    'from_cache': True,
                    'cached_at': cached_time
                }
        except (json.JSONDecodeError, KeyError) as e:
            logger.debug(f"Error reading qibo versions cookie: {e}")
    
    # Fetch fresh versions
    logger.debug("Fetching fresh qibo versions")
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
                logger.warning(f"Threading error while fetching {package} version: {error_msg}")
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
    
    # Prepare cookie data
    current_time = time.time()
    cookie_data = {
        'versions': versions,
        'timestamp': current_time
    }
    
    return {
        'versions': versions,
        'from_cache': False,
        'cookie_data': json.dumps(cookie_data),
        'cached_at': current_time
    }


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


def get_instruments_ip(platform):
    # Create a qibolab platform and read the address of the controller
    backend:QibolabBackend = QibolabBackend(platform=platform)
    platform:QibolabPlatform = backend.platform

    instruments = platform.instruments
    ips = []
    for inst_name in instruments:
        instrument = instruments[inst_name]
        # Check if the instrument has a key 'ADDRESS' or 'address'
        if hasattr(instrument, 'address'):
            ips.append(instrument.address)
        elif hasattr(instrument, 'ADDRESS'):
            ips.append(instrument.ADDRESS)
    return ips if ips else 'N/A'


def qpu_parameters(qpu_name) -> dict:
    
    qpu_path = os.path.join(get_platforms_path(), qpu_name)
    
    # Detect qibolab version for this platform
    qibolab_version = detect_and_save_qibolab_version(qpu_path)
    
    # Check if version supports new API using PEP 440 compliant comparison
    is_new_api = is_qibolab_new_api(qibolab_version)
    
    if QIBOLAB_AVAILABLE and is_new_api:
        try:
            qpu_params = __get_parameters(qpu_name)
            logger.debug(f"Retrieved parameters for {qpu_name} using qibolab {qibolab_version} (new API)")
            return qpu_params
        except Exception as e:
            logger.warning(f"Failed to get parameters for {qpu_name} using qibolab method: {e}")
            # Fallback to manual method
            return __get_parameters_manual(qpu_path)
    else:
        # Use manual method for older qibolab versions or when qibolab not available
        logger.debug(f"Using manual method for {qpu_name} (qibolab_version: {qibolab_version})")
        qpu_params = __get_parameters_manual(qpu_path)
    return qpu_params


def __get_parameters_manual(qpu_path: str):
    """
    Manually extract QPU parameters from configuration files.
    Used as fallback when qibolab is not available or version is <0.2.0.    
    
    Args:
        qpu_path (str): Path to the QPU configuration directory
        
    Returns:
        tuple: (num_qubits, topology) where num_qubits is int or 'N/A',
               and topology is string or 'N/A'
    """
    num_qubits = 'N/A'
    topology = 'N/A'
    
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
    qpu_name = qpu_path.split(os.sep)[-1]  # Get the last part of the path as the QPU name
    return {
                    'name': qpu_name,
                    'nqubits': num_qubits,
                    'topology': topology,
                    'gates': [],
                    'error': None
                }


def __get_parameters(platform) -> dict:
    """Get available parameters for a specific qibolab Platform."""
    class SignalDisabler:
        def __enter__(self):
            self.old_signal = signal.signal
            signal.signal = lambda sig, handler: None
            return self
        
        def __exit__(self, exc_type, exc_val, exc_tb):
            signal.signal = self.old_signal

    parameters = {
                    'name': platform,
                    'nqubits': 'Unknown',
                    'topology': 'Unknown',
                    'gates': [],
                    'error': None
                }
    
    try:
        # Try to create the platform to get its parameters
        with SignalDisabler():
            try:
                qpu: QibolabPlatform = create_platform(platform)
            except Exception as e:
                logger.warning(f"Could not create platform {platform}: {e}")
                logger.debug(f"Full traceback:\n{traceback.format_exc()}")
                parameters['error'] = traceback.format_exc()
                return parameters

            try:
                # Extract information about the platform
                parameters = {
                    'name': platform,
                    'nqubits': len(qpu.qubits) if hasattr(qpu, 'qubits') else 'Unknown',
                    'topology': 'Connected' if hasattr(qpu, 'pairs') and qpu.pairs else 'Not available',
                    'single_qubit_gates': {},  # Format: {gate_name: [list_of_qubits]}
                    'two_qubit_gates': {},     # Format: {gate_name: [list_of_qubit_pairs]}
                    'gates': []  # Keep for backward compatibility
                }

                from qibolab._core.parameters import NativeGates, SingleQubitNatives, TwoQubitNatives
                # Try to get available gates/operations per qubit 
                if hasattr(qpu, 'natives') and qpu.natives:
                    natives: NativeGates = qpu.natives
                    single_qubit_natives: SingleQubitNatives = natives.single_qubit
                    two_qubit_natives: TwoQubitNatives = natives.two_qubit

                    logger.debug(f"Processing single-qubit gates for {qpu.nqubits} qubits")
                    
                    # Process single-qubit gates
                    for qubit in range(qpu.nqubits):
                        qubit_name, _= qpu.qubit(qubit)
                        qubit_gates:SingleQubitNatives = single_qubit_natives[qubit_name]
                        
                        # Handle different formats of gate storage
                        if hasattr(qubit_gates, 'items'):
                            # Dictionary-like access
                            for gate_name, gate_info in qubit_gates.items():
                                if gate_info is not None:  # Only include gates that are not None
                                    if gate_name not in parameters['single_qubit_gates']:
                                        parameters['single_qubit_gates'][gate_name] = []
                                    parameters['single_qubit_gates'][gate_name].append(qubit_name)
                                    
                                    # Add to legacy gates list for backward compatibility
                                    if gate_name not in parameters['gates']:
                                        parameters['gates'].append(gate_name)
                        else:
                            # Iterable format
                            for gate_name, gate_info in qubit_gates:
                                if gate_info is not None:  # Only include gates that are not None
                                    if gate_name not in parameters['single_qubit_gates']:
                                        parameters['single_qubit_gates'][gate_name] = []
                                    parameters['single_qubit_gates'][gate_name].append(qubit_name)
                                    
                                    # Add to legacy gates list for backward compatibility
                                    if gate_name not in parameters['gates']:
                                        parameters['gates'].append(gate_name)

                    # Process two-qubit gates
                    logger.debug("Processing two-qubit gates")
                    if hasattr(two_qubit_natives, 'items'):
                        # Dictionary-like access
                        for qubit_pair, pair_gates in two_qubit_natives.items():
                            if hasattr(pair_gates, 'items'):
                                for gate_name, gate_info in pair_gates.items():
                                    if gate_info is not None:  # Only include gates that are not None
                                        if gate_name not in parameters['two_qubit_gates']:
                                            parameters['two_qubit_gates'][gate_name] = []
                                        parameters['two_qubit_gates'][gate_name].append(qubit_pair)
                                        
                                        # Add to legacy gates list for backward compatibility
                                        if gate_name not in parameters['gates']:
                                            parameters['gates'].append(gate_name)
                            else:
                                # Iterable format
                                for gate_name, gate_info in pair_gates:
                                    if gate_info is not None:  # Only include gates that are not None
                                        if gate_name not in parameters['two_qubit_gates']:
                                            parameters['two_qubit_gates'][gate_name] = []
                                        parameters['two_qubit_gates'][gate_name].append(qubit_pair)
                                        
                                        # Add to legacy gates list for backward compatibility
                                        if gate_name not in parameters['gates']:
                                            parameters['gates'].append(gate_name)

                    logger.info(f"Found {len(parameters['single_qubit_gates'])} single-qubit gate types and {len(parameters['two_qubit_gates'])} two-qubit gate types")
                
                # Infer topology from configuration files
                topology = get_topology_from_platform(qpu)
                parameters['topology'] = topology

                return parameters
                
            except Exception as platform_error:
                logger.warning(f"Error processing platform {platform}: {platform_error}")
                logger.debug(f"Full traceback:\n{traceback.format_exc()}")
                parameters['error'] = str(e.with_traceback)
                return parameters
            
    except ImportError:
        logger.warning("qibolab is not available. Cannot retrieve QPU parameters.")
        return {
            'name': platform,
            'nqubits': 'Unknown',
            'topology': 'Unknown', 
            'gates': [],
            'error': 'qibolab not available'
        }
    

def get_qpu_details():
    """Get detailed information about all available QPUs."""
    
    root = os.path.normpath(os.environ.get('HOME'))
    platforms_path = get_platforms_path(root)
    qpus_list = []
    qpu_names = get_qpu_list()

    # Get queue mapping using shared function
    queues = get_qpu_queue_mapping(platforms_path)

    if os.path.exists(platforms_path):
        for qpu_name in qpu_names:
                queue_name = queues.get(qpu_name, 'N/A')
                status = get_connection_status(qpu_name, queue_name)
                qpu_params = qpu_parameters(qpu_name)
                qpus_list.append({
                    'name': qpu_name,
                    'qubits': qpu_params.get('nqubits', 'N/A'),
                    'status': status,
                    'queue': queue_name,
                    'topology': qpu_params.get('topology', 'N/A'),
                    'calibration_time': 'N/A'
                })

    return  qpus_list




