"""
Experiment and protocol management utilities.
"""

import inspect
import importlib
import threading
import traceback

try:
    from qibocal.auto.operation import Parameters, Results, Data, Protocol
    from qibocal.protocols import PROTOCOLS
    QIBOCAL_AVAILABLE = True
    QIBOCAL_IMPORT_ERROR = None
except Exception as _qibocal_exc:
    Parameters = Results = Data = Protocol = None
    PROTOCOLS = {}
    QIBOCAL_AVAILABLE = False
    QIBOCAL_IMPORT_ERROR = _qibocal_exc

from qdashboard.utils.logger import get_logger


# Global cache for protocols to avoid repeated discovery
_protocol_cache = None
_cache_lock = threading.Lock()

logger = get_logger(__name__)

if not QIBOCAL_AVAILABLE:
    logger.warning(
        f"qibocal could not be imported ({QIBOCAL_IMPORT_ERROR}). "
        "Protocol discovery and experiment submission will be unavailable."
    )


def get_qibocal_protocols():
    """
    Discover all available qibocal protocols from qibocal.protocols.PROTOCOLS,
    the registry qibocal itself uses to resolve runcard actions by id.
    Returns a dictionary categorized by protocol type. Results are cached.
    """
    global _protocol_cache

    if not QIBOCAL_AVAILABLE:
        return _get_fallback_protocols()

    with _cache_lock:
        if _protocol_cache is not None:
            return _protocol_cache

    try:
        protocols = _get_protocols_direct()
    except Exception as e:
        logger.warning(f"Error discovering qibocal protocols: {e}")
        logger.debug(f"Full traceback:\n{traceback.format_exc()}")
        protocols = _get_fallback_protocols()

    with _cache_lock:
        _protocol_cache = protocols
    return protocols


def _get_protocols_direct() -> dict:
    """
    Build the protocol list from qibocal's PROTOCOLS registry. The dict key
    (e.g. 'rabi_amplitude') is the same id qibocal expects as the runcard
    action's 'operation' field, so it is used as-is for 'id'/'class_name'.
    """
    routine_protocols = []
    for protocol_id, routine_obj in PROTOCOLS.items():
        module_path = routine_obj.acquisition.__module__
        routine_protocols.append({
            'id': protocol_id,
            'name': protocol_id.replace('_', ' ').title(),
            'class_name': protocol_id,
            'module_name': module_path.rsplit('.', 2)[-2] if '.' in module_path else module_path,
            'module_path': module_path,
            'routine_obj': routine_obj,
        })

    return _categorize_protocols(routine_protocols)


def _get_fallback_protocols() -> dict:
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


def _categorize_protocols(routine_protocols) -> dict:
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
               for keyword in ['spectroscopy', 'resonator_spectroscopy', 'qubit_spectroscopy', 'punchout']):
            categorized["Spectroscopy"].append(protocol)
        elif any(keyword in class_name or keyword in module_name 
                 for keyword in ['readout', 'classification', 'single_shot', 'state_discrimination', ]):
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


def _get_all_annotations(cls) -> dict:
    """
    Collect type annotations from a class and all its base classes,
    so that fields defined on parent classes (e.g. SpinEchoParameters
    for CpmgSpectroscopyParameters) are not lost. Annotations are merged
    in MRO order (base classes first) so subclasses can override field types.

    Specifically design for the protocol Parameters, which often inherit from each other
    """
    annotations = {}
    for klass in reversed(cls.__mro__):
        if klass is Parameters:
            continue  # Skip base class Parameters
        annotations.update(getattr(klass, '__annotations__', {}))
    return annotations


def get_protocol_attributes(protocol: dict) -> dict:
    """
    Get attributes of a specific protocol. These are classified as:
        inputs (subclass of type qibocal.auto.operationParameters)
        results (subclass of type qibocal.auto.Results)
        data (subclass of type qibocal.auto.Data)
    """
    if not QIBOCAL_AVAILABLE:
        logger.warning("qibocal is not available; cannot retrieve protocol attributes.")
        return {"inputs": {}, "results": {}, "data": {}, "error": str(QIBOCAL_IMPORT_ERROR)}

    try:
        if isinstance(protocol, dict):
            routine_obj = protocol.get('routine_obj')
        elif isinstance(protocol, str):
            routine_obj = PROTOCOLS.get(protocol)
            if routine_obj is None:
                logger.error(f"Protocol {protocol} not found in qibocal.protocols")
                raise ValueError(f"Protocol {protocol} not found in qibocal.protocols")
            protocol = {
                "name": protocol,
                "module_name": routine_obj.acquisition.__module__,
                "module_path": routine_obj.acquisition.__module__,
                "class_name": protocol
            }
        if routine_obj:
            protocol_class = importlib.import_module(routine_obj.acquisition.__module__)
        else:
            # If not available, dynamically import the protocol class
            module_path = protocol['module_path']
            class_name = protocol['class_name']
            try:
                # The module path might point to the class itself or the containing module
                module = importlib.import_module(module_path)
                protocol_class = getattr(module, class_name)
            except (ModuleNotFoundError, AttributeError):
                # Fallback for cases where module_path is 'qibocal.protocols.ClassName'
                # We need to import 'qibocal.protocols' and get the class from there.
                parts = module_path.rsplit('.', 1)
                if len(parts) == 2:
                    base_module_path, _ = parts
                    module = importlib.import_module(base_module_path)
                    protocol_class = getattr(module, class_name)
                else:
                    raise

        # Get the inner classes for Parameters, Results, and Data
        parameters_class = None
        results_class = None
        data_class = None
        logger.debug(f"Inspecting protocol: {protocol_class.__name__}")
        try:

            # Inspect inner classes of the protocol to find the ones that inherit
            # from Parameters, Results, and Data.
            for _, inner_class in inspect.getmembers(protocol_class, inspect.isclass):
                    logger.debug(f"Found inner class: {inner_class.__name__}")
                #if inner_class.__module__ == protocol_class.__module__: # Ensure it's an inner class
                    if issubclass(inner_class, Parameters) and inner_class is not Parameters:
                        parameters_class = inner_class
                    elif issubclass(inner_class, Results) and inner_class is not Results:
                        results_class = inner_class
                    elif issubclass(inner_class, Data) and inner_class is not Data:
                        data_class = inner_class
        except (ImportError, TypeError):
            # Fallback to getattr for older qibocal versions or different structures
            parameters_class = getattr(protocol_class, 'Parameters', None)
            results_class = getattr(protocol_class, 'Results', None)
            data_class = getattr(protocol_class, 'Data', None)

        attributes = {
            "inputs": {},
            "results": {},
            "data": {}
        }

        # Extract fields from the Parameters class (including inherited ones)
        if parameters_class:
            for name, field_type in _get_all_annotations(parameters_class).items():
                attributes["inputs"][name] = str(field_type)

        # Extract fields from the Results class (including inherited ones)
        if results_class:
            for name, field_type in _get_all_annotations(results_class).items():
                attributes["results"][name] = str(field_type)

        # Extract fields from the Data class (including inherited ones)
        if data_class:
            for name, field_type in _get_all_annotations(data_class).items():
                attributes["data"][name] = str(field_type)

        # Extract parameter-class docstring as a human-readable description
        description = ""
        try:
            if parameters_class and parameters_class.__doc__:
                description = inspect.cleandoc(parameters_class.__doc__)[:500]
        except Exception:
            pass

        attributes["description"] = description
        return attributes

    except (ImportError, AttributeError, KeyError) as e:
        logger.error(f"Could not get attributes for protocol {protocol.get('name', 'N/A')}: {e}")
        logger.debug(f"Full traceback:\n{traceback.format_exc()}")
        return {
            "inputs": {"error": "Could not retrieve attributes."},
            "results": {"error": "Could not retrieve attributes."},
            "data": {"error": "Could not retrieve attributes."},
            "description": "",
        }