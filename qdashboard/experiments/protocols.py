"""
Experiment and protocol management utilities.
"""

import inspect
import importlib
import pkgutil
import signal
import subprocess
import sys
import os
import json
import threading
import traceback
from functools import lru_cache
from qdashboard.utils.logger import get_logger


# Global cache for protocols to avoid repeated discovery
_protocol_cache = None
_cache_lock = threading.Lock()

logger = get_logger(__name__)


def get_qibocal_protocols():
    """
    Dynamically discover all available qibocal protocols by finding Routine objects.
    Returns a dictionary categorized by protocol type.
    Uses caching and fallback methods to handle signal issues.
    """
    global _protocol_cache
    
    # Check if we have cached results
    with _cache_lock:
        if _protocol_cache is not None:
            return _protocol_cache
    
    # Try multiple approaches to get protocols
    try:
        # Approach 1: Try direct import with signal handling
        protocols = _get_protocols_direct()
        with _cache_lock:
            _protocol_cache = protocols
        return protocols
    except Exception as e:
        if "signal only works in main thread" in str(e):
            try:
                # Approach 2: Try subprocess method
                protocols = _get_protocols_subprocess()
                with _cache_lock:
                    _protocol_cache = protocols
                return protocols
            except Exception as e2:
                # Approach 3: Return fallback protocols
                logger.warning(f"Error discovering qibocal protocols: {e}")
                logger.debug(f"Primary error traceback:\n{traceback.format_exc()}")
                logger.warning(f"Subprocess approach also failed: {e2}")
                logger.debug(f"Subprocess error traceback:\n{traceback.format_exc()}")
                protocols = _get_fallback_protocols()
                with _cache_lock:
                    _protocol_cache = protocols
                return protocols
        else:
            logger.warning(f"Error discovering qibocal protocols: {e}")
            logger.debug(f"Full traceback:\n{traceback.format_exc()}")
            protocols = _get_fallback_protocols()
            with _cache_lock:
                _protocol_cache = protocols
            return protocols


def _get_protocols_direct():
    """
    Direct approach to get protocols - try to handle signals properly.
    """
    try:
        import qibocal.protocols as protocols_module
        
        # Use a context manager approach to disable signals more safely
        class SignalDisabler:
            def __enter__(self):
                self.old_signal = signal.signal
                signal.signal = lambda sig, handler: None
                return self
            
            def __exit__(self, exc_type, exc_val, exc_tb):
                signal.signal = self.old_signal
        
        routine_protocols = []
        
        with SignalDisabler():
            # First, get all DIRECT Routine objects from the protocols module
            for name, obj in inspect.getmembers(protocols_module):
                if (not name.startswith('_') and name != 'Enum' and
                    hasattr(obj, '__class__') and
                    str(obj.__class__) == "<class 'qibocal.auto.operation.Routine'>"):
                    
                    routine_protocols.append({
                        'id': name.lower(),
                        'name': name.replace('_', ' ').title(),
                        'class_name': name,
                        'module_name': 'protocols',  # These are direct imports
                        'module_path': f'qibocal.protocols.{name}',
                        'routine_obj': obj
                    })
            
            # Then, get all protocol modules and their Routine objects (like rabi submodule)
            for name, obj in inspect.getmembers(protocols_module):
                if not name.startswith('_') and name != 'Enum':
                    try:
                        # Check if it's a module (has __path__ or __file__)
                        if hasattr(obj, '__path__') or (hasattr(obj, '__file__') and obj.__file__):
                            module_path = f'qibocal.protocols.{name}'
                            
                            # Try to import the module and look for Routine objects
                            try:
                                imported_module = importlib.import_module(module_path)
                                
                                # Look for Routine objects in the module
                                for attr_name, attr_obj in inspect.getmembers(imported_module):
                                    if (not attr_name.startswith('_') and 
                                        hasattr(attr_obj, '__class__') and
                                        str(attr_obj.__class__) == "<class 'qibocal.auto.operation.Routine'>"):
                                        if not any(p['class_name'] == attr_name for p in routine_protocols):
                                            routine_protocols.append({
                                                'id': attr_name.lower(),
                                                'name': attr_name.replace('_', ' ').title(),
                                                'class_name': attr_name,
                                                'module_name': name,
                                                'module_path': module_path,
                                                'routine_obj': attr_obj
                                            })
                                            
                            except Exception as import_error:
                                # If we can't import the module, skip it but don't fail completely
                                logger.warning(f"Could not import {module_path}: {import_error}")
                                continue
                                    
                    except Exception:
                        # Skip attributes that can't be accessed
                        continue
        
        return _categorize_protocols(routine_protocols)
        
    except ImportError as e:
        logger.warning(f"Could not import qibocal.protocols: {e}")
        logger.debug(f"Full traceback:\n{traceback.format_exc()}")
        return _get_fallback_protocols()


def _get_protocols_subprocess():
    """
    Subprocess approach to get protocols - run protocol discovery in a separate process.
    """
    try:
        # Create a script to run protocol discovery in a subprocess
        script_content = '''
import sys
import json
import inspect
import importlib

def discover_protocols():
    try:
        import qibocal.protocols as protocols_module
        
        routine_protocols = []
        
        # Get all DIRECT Routine objects from the protocols module
        for name, obj in inspect.getmembers(protocols_module):
            if (not name.startswith('_') and name != 'Enum' and
                hasattr(obj, '__class__') and
                str(obj.__class__) == "<class 'qibocal.auto.operation.Routine'>"):
                
                routine_protocols.append({
                    'id': name.lower(),
                    'name': name.replace('_', ' ').title(),
                    'class_name': name,
                    'module_name': 'protocols',
                    'module_path': f'qibocal.protocols.{name}'
                })
        
        # Get protocol modules
        for name, obj in inspect.getmembers(protocols_module):
            if not name.startswith('_') and name != 'Enum':
                try:
                    if hasattr(obj, '__path__') or (hasattr(obj, '__file__') and obj.__file__):
                        module_path = f'qibocal.protocols.{name}'
                        
                        try:
                            imported_module = importlib.import_module(module_path)
                            
                            for attr_name, attr_obj in inspect.getmembers(imported_module):
                                if (not attr_name.startswith('_') and 
                                    hasattr(attr_obj, '__class__') and
                                    str(attr_obj.__class__) == "<class 'qibocal.auto.operation.Routine'>"):
                                    if not any(p['class_name'] == attr_name for p in routine_protocols):
                                        routine_protocols.append({
                                            'id': attr_name.lower(),
                                            'name': attr_name.replace('_', ' ').title(),
                                            'class_name': attr_name,
                                            'module_name': name,
                                            'module_path': module_path
                                        })
                                        
                        except Exception:
                            continue
                            
                except Exception:
                    continue
        
        return routine_protocols
        
    except Exception as e:
        return []

if __name__ == "__main__":
    protocols = discover_protocols()
    print(json.dumps(protocols))
'''
        
        # Run the script in a subprocess
        result = subprocess.run([sys.executable, '-c', script_content], 
                              capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            protocols_data = json.loads(result.stdout)
            return _categorize_protocols(protocols_data)
        else:
            raise Exception(f"Subprocess failed: {result.stderr}")
            
    except Exception as e:
        logger.warning(f"Subprocess approach failed: {e}")
        logger.debug(f"Full traceback:\n{traceback.format_exc()}")
        return _get_fallback_protocols()


def _get_fallback_protocols():
    """
    Return a hardcoded list of known qibocal protocols as fallback.
    """
    fallback_protocols = [
        {'id': 'rabi', 'name': 'Rabi', 'class_name': 'Rabi', 'module_name': 'characterization', 'module_path': 'qibocal.protocols.characterization.rabi'},
        {'id': 'ramsey', 'name': 'Ramsey', 'class_name': 'Ramsey', 'module_name': 'characterization', 'module_path': 'qibocal.protocols.characterization.ramsey'},
        {'id': 't1', 'name': 'T1', 'class_name': 'T1', 'module_name': 'characterization', 'module_path': 'qibocal.protocols.characterization.t1'},
        {'id': 't2', 'name': 'T2', 'class_name': 'T2', 'module_name': 'characterization', 'module_path': 'qibocal.protocols.characterization.t2'},
        {'id': 'spin_echo', 'name': 'Spin Echo', 'class_name': 'SpinEcho', 'module_name': 'characterization', 'module_path': 'qibocal.protocols.characterization.spin_echo'},
        {'id': 'resonator_spectroscopy', 'name': 'Resonator Spectroscopy', 'class_name': 'ResonatorSpectroscopy', 'module_name': 'spectroscopy', 'module_path': 'qibocal.protocols.spectroscopy.resonator_spectroscopy'},
        {'id': 'qubit_spectroscopy', 'name': 'Qubit Spectroscopy', 'class_name': 'QubitSpectroscopy', 'module_name': 'spectroscopy', 'module_path': 'qibocal.protocols.spectroscopy.qubit_spectroscopy'},
        {'id': 'standard_rb', 'name': 'Standard RB', 'class_name': 'StandardRB', 'module_name': 'verification', 'module_path': 'qibocal.protocols.verification.standard_rb'},
        {'id': 'allxy', 'name': 'AllXY', 'class_name': 'AllXY', 'module_name': 'verification', 'module_path': 'qibocal.protocols.verification.allxy'},
        {'id': 'drag', 'name': 'DRAG', 'class_name': 'DRAG', 'module_name': 'calibration', 'module_path': 'qibocal.protocols.calibration.drag'},
        {'id': 'single_shot_classification', 'name': 'Single Shot Classification', 'class_name': 'SingleShotClassification', 'module_name': 'readout', 'module_path': 'qibocal.protocols.readout.single_shot_classification'},
        {'id': 'chevron', 'name': 'Chevron', 'class_name': 'Chevron', 'module_name': 'two_qubit', 'module_path': 'qibocal.protocols.two_qubit.chevron'},
        {'id': 'cross_resonance', 'name': 'Cross Resonance', 'class_name': 'CrossResonance', 'module_name': 'two_qubit', 'module_path': 'qibocal.protocols.two_qubit.cross_resonance'},
    ]
    
    return _categorize_protocols(fallback_protocols)


def _categorize_protocols(routine_protocols):
    """
    Categorize protocols based on their name patterns.
    """
    # Remove duplicates based on class name
    seen = set()
    unique_protocols = []
    for protocol in routine_protocols:
        key = protocol['class_name']
        if key not in seen:
            seen.add(key)
            unique_protocols.append(protocol)
    
    # Categorize protocols
    categorized = {
        "Characterization": [],
        "Calibration": [],
        "Verification": [],
        "Coherence": [],
        "Spectroscopy": [],
        "Readout": [],
        "Two-Qubit": [],
        "Couplers": [],
        "Other": []
    }
    
    for protocol in unique_protocols:
        name_lower = protocol['name'].lower()
        module_name = protocol['module_name'].lower()
        class_name = protocol['class_name'].lower()
        
        # Categorize based on protocol name patterns
        if any(keyword in class_name or keyword in module_name 
               for keyword in ['spectroscopy', 'resonator_spectroscopy', 'qubit_spectroscopy']):
            categorized["Spectroscopy"].append(protocol)
        elif any(keyword in class_name or keyword in module_name 
                 for keyword in ['readout', 'classification', 'single_shot', 'state_discrimination']):
            categorized["Readout"].append(protocol)
        elif any(keyword in class_name or keyword in module_name 
                 for keyword in ['coherence', 't1', 't2', 'spin_echo', 'ramsey']):
            categorized["Coherence"].append(protocol)
        elif any(keyword in class_name or keyword in module_name 
                 for keyword in ['coupler', 'avoided_crossing']):
            categorized["Couplers"].append(protocol)
        elif any(keyword in class_name or keyword in module_name 
                 for keyword in ['cross_resonance', 'chevron', 'two_qubit', 'chsh', 'mermin', 'tomography']):
            categorized["Two-Qubit"].append(protocol)
        elif any(keyword in class_name or keyword in module_name 
                 for keyword in ['rb', 'randomized_benchmarking', 'allxy', 'standard_rb', 'filtered_rb']):
            categorized["Verification"].append(protocol)
        elif any(keyword in class_name or keyword in module_name 
                 for keyword in ['drag', 'calibration', 'optimization', 'tuning']):
            categorized["Calibration"].append(protocol)
        elif any(keyword in class_name or keyword in module_name 
                 for keyword in ['rabi', 'characterization']):
            categorized["Characterization"].append(protocol)
        else:
            categorized["Other"].append(protocol)
    
    # Remove empty categories
    categorized = {k: v for k, v in categorized.items() if v}
    
    logger.info(f"Discovered {sum(len(v) for v in categorized.values())} qibocal protocols across {len(categorized)} categories")
    
    return categorized
