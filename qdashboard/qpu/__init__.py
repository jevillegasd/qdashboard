"""QPU management and monitoring utilities."""

from .platforms import (
    ensure_platforms_directory, 
    get_platforms_path, 
    update_platforms_repository,
    list_repository_branches,
    switch_repository_branch,
    get_current_branch_info
)
from .monitoring import (
    get_qpu_health, 
    get_available_qpus, 
    get_qibo_versions,  
)

from .utils import (
    detect_and_save_qibolab_version,
    is_qibolab_new_api
)

__all__ = [
    'ensure_platforms_directory',
    'get_platforms_path', 
    'update_platforms_repository',
    'list_repository_branches',
    'switch_repository_branch',
    'get_current_branch_info',
    'get_qpu_health',
    'get_available_qpus',
    'get_qibo_versions',
    'detect_and_save_qibolab_version', 
    'is_qibolab_new_api'
]
