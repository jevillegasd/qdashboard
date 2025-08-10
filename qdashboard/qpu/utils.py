import os
import json
from packaging import version
from qdashboard.utils.logger import get_logger

logger = get_logger(__name__)

def is_qibolab_new_api(version_string):
    """
    Check if qibolab version supports the new API (>=0.2.0).
    
    Uses packaging.version for PEP 440 compliant version comparison.
    
    Args:
        version_string: Version string (e.g., '0.1.45', '0.2.0', '1.0.0')
        
    Returns:
        bool: True if version >= 0.2.0, False otherwise
    """
    try:
        # Parse the version string
        parsed_version = version.parse(version_string)
        minimum_version = version.parse("0.2.0")
        
        # Compare versions
        is_compatible = parsed_version >= minimum_version
        
        logger.debug(f"Version {version_string} -> new API: {is_compatible}")
        return is_compatible
        
    except version.InvalidVersion as e:
        logger.warning(f"Invalid version string '{version_string}': {e}")
        # Default to old API for invalid versions
        return False
    except Exception as e:
        logger.warning(f"Error parsing version '{version_string}': {e}")
        return False


def detect_and_save_qibolab_version(qpu_path):
    """
    Detect qibolab version for a platform and save it to versions.json.
    
    This function handles both explicit version specifications and automatic detection:
    - If versions.json already contains a qibolab_version, use it (e.g., '0.1.45')
    - Otherwise, auto-detect based on platform structure and save '0.1.0' or '0.2.0'
    
    Args:
        qpu_path: Path to the QPU platform directory
        
    Returns:
        str: Qibolab version (specific version like '0.1.45' or auto-detected '0.1.0'/'0.2.0')
    """
    versions_json_path = os.path.join(qpu_path, 'versions.json')
    
    # Try to read existing versions.json
    versions_data = {}
    if os.path.exists(versions_json_path):
        try:
            with open(versions_json_path, 'r') as f:
                versions_data = json.load(f)
        except (IOError, json.JSONDecodeError) as e:
            logger.warning(f"Could not read versions.json: {e}")
    
    # Check if qibolab_version is already explicitly set
    if 'qibolab_version' in versions_data:
        existing_version = versions_data['qibolab_version']
        logger.debug(f"Found existing qibolab_version: {existing_version}")
        
        # If it's an explicit version (not our auto-detected ones), keep it
        if existing_version not in ['0.1.0', '0.2.0']:
            logger.info(f"Using explicit qibolab version: {existing_version}")
            return existing_version
        
        # If it's one of our auto-detected versions, we can re-detect if needed
        logger.debug(f"Found auto-detected version {existing_version}, checking if re-detection needed")
    
    # Auto-detect version based on platform structure
    calibration_json_path = os.path.join(qpu_path, 'calibration.json')
    if os.path.exists(calibration_json_path):
        detected_version = '0.2.0'
        logger.info(f"Auto-detected qibolab version 0.2.0 (calibration.json found)")
    else:
        detected_version = '0.1.0'
        logger.info(f"Auto-detected qibolab version 0.1.0 (no calibration.json)")
    
    # Only update if we don't have an explicit version or if the detection changed
    current_version = versions_data.get('qibolab_version')
    if current_version != detected_version:
        versions_data['qibolab_version'] = detected_version
        try:
            with open(versions_json_path, 'w') as f:
                json.dump(versions_data, f, indent=2)
            logger.debug(f"Saved qibolab_version {detected_version} to {versions_json_path}")
        except IOError as e:
            logger.warning(f"Could not save qibolab_version to versions.json: {e}")
    
    return detected_version


def get_qibolab_version_from_file(qpu_path):
    """
    Read qibolab version from versions.json file.
    
    Args:
        qpu_path: Path to the QPU platform directory
        
    Returns:
        str: Qibolab version if found, None otherwise
    """
    versions_json_path = os.path.join(qpu_path, 'versions.json')
    
    if not os.path.exists(versions_json_path):
        return None
        
    try:
        with open(versions_json_path, 'r') as f:
            versions_data = json.load(f)
        return versions_data.get('qibolab_version')
    except (IOError, json.JSONDecodeError) as e:
        logger.warning(f"Could not read qibolab_version from versions.json: {e}")
        return None