# QDashboard Modular Architecture

This document describes the modular organization of the QDashboard codebase.

## Directory Structure

```
qdashboard/
├── app.py                 # Main application entry point
├── qdashboard/           # Main package directory
│   ├── __init__.py       # Package initialization
│   ├── cli.py            # Command-line interface
│   ├── platforms_cli.py  # Platform management CLI
│   ├── core/             # Core application configuration
│   │   ├── __init__.py
│   │   ├── app.py        # Flask app creation and configuration
│   │   └── config.py     # Centralized configuration management
│   ├── utils/            # Utility functions
│   │   ├── __init__.py
│   │   ├── formatters.py # File formatting and template filters
│   │   └── logger.py     # Logging configuration
│   ├── qpu/              # QPU monitoring and management
│   │   ├── __init__.py
│   │   ├── monitoring.py # QPU health and status monitoring
│   │   ├── platforms.py  # Platform repository management
│   │   ├── slurm.py      # SLURM queue management
│   │   ├── topology.py   # Topology analysis and visualization
│   │   └── utils.py      # QPU utility functions
│   ├── experiments/      # Experiment and protocol management
│   │   ├── __init__.py
│   │   ├── job_submission.py # SLURM job submission and management
│   │   └── protocols.py  # Qibocal protocol discovery and management
│   └── web/              # Web interface components
|   │   ├── __init__.py
|   │   ├── routes.py     # Main application routes
|   │   ├── file_browser.py # File browser functionality
|   │   └── reports.py    # Report viewing utilities
|   ├── assets/           # Static assets (CSS, JS, images)
|   └── templates/        # Jinja2 templates
|
└── quantum_dashboard.py.backup # Backup of original monolithic file
```

## Module Descriptions

### Core (`qdashboard/core/`)
- **app.py**: FastAPI application factory, static file mounting, Jinja2 template setup, filter registration
- **config.py**: Centralized configuration management, environment variable handling, validation utilities

### Command Line Interface (`qdashboard/`)
- **cli.py**: Main command-line interface for starting QDashboard server
- **platforms_cli.py**: Platform repository management and Git operations

### Utilities (`qdashboard/utils/`)
- **formatters.py**: File size formatting, time formatting, icon mapping, data type detection, JSON/YAML utilities
- **logger.py**: Centralized logging configuration and utilities

### QPU Management (`qdashboard/qpu/`)
- **monitoring.py**: QPU health checks, qibo package version tracking, platform discovery
- **platforms.py**: Platform repository management, Git operations, branch switching
- **slurm.py**: SLURM queue status monitoring, job management, log parsing
- **topology.py**: Quantum device topology analysis, connectivity inference, visualization generation
- **utils.py**: QPU-related utility functions and helpers

### Experiments (`qdashboard/experiments/`)
- **protocols.py**: Qibocal protocol discovery, categorization, parameter management
- **job_submission.py**: SLURM job submission, experiment management, metadata handling

### Web Interface (`qdashboard/web/`)
- **routes.py**: FastAPI `APIRouter` route definitions, async API endpoints, SSE streaming
- **file_browser.py**: File browser via `make_file_router()` factory returning an `APIRouter`
- **reports.py**: Report viewing and asset handling

## Benefits of Modular Architecture

1. **Separation of Concerns**: Each module has a single, well-defined responsibility
2. **Maintainability**: Easier to locate and modify specific functionality
3. **Testability**: Individual modules can be tested in isolation
4. **Reusability**: Components can be imported and reused across the application
5. **Scalability**: New features can be added without modifying existing modules
6. **Readability**: Smaller, focused files are easier to understand
7. **Configuration Management**: Centralized configuration with consistent access patterns
8. **Code Quality**: Reduced duplication and standardized patterns

## Configuration Architecture

QDashboard uses a centralized configuration system:

### Configuration Sources (in order of precedence)
1. **Command-line arguments** (`--port`, `--host`, etc.)
2. **Environment variables** (`QD_PORT`, `QD_BIND`, `QD_PATH`, etc.)
3. **Default values** (defined in `core/config.py`)

### Configuration Access
```python
# Recommended approach — works outside request context
from qdashboard.core.config import get_config, get_temp_dir

config = get_config()
temp_dir = get_temp_dir()

# Inside a route handler
def _get_config(request):
    return request.app.state.config
```
```

### Key Configuration Functions
- `get_app_config()`: Get full configuration dictionary
- `get_temp_dir()`: Get temporary directory path
- `get_data_dir()`: Get data storage directory
- `get_logs_dir()`: Get logs directory
- `ensure_directory_exists()`: Create directories safely

## Tech Stack

- **ASGI server**: FastAPI ≥ 0.111, Uvicorn ≥ 0.29 (replaces Flask/Werkzeug WSGI)
- **Templates**: Jinja2 ≥ 3.1 (server-side rendering, unchanged)
- **File uploads**: python-multipart ≥ 0.0.9, aiofiles ≥ 23.0
- **Python**: 3.10+

The original `quantum_dashboard.py` (1,500+ lines) has been broken down into:
- **Core app setup**: ~40 lines (+ 100 lines configuration management)
- **CLI interface**: ~200 lines  
- **Utility functions**: ~200 lines  
- **QPU monitoring**: ~300 lines
- **Platform management**: ~150 lines
- **SLURM management**: ~150 lines
- **Topology analysis**: ~400 lines
- **Protocol discovery**: ~200 lines
- **Job submission**: ~500 lines
- **Web routes**: ~800 lines
- **File browser**: ~200 lines
- **Report handling**: ~100 lines

### Key Improvements
- **Eliminated hardcoded values**: Centralized configuration
- **Standardized patterns**: Consistent directory creation, config access
- **Error handling**: Validation and error messages
- **Code deduplication**: Shared utilities and common patterns
- **Type safety**: Added type hints throughout codebase

This modular approach makes the codebase much more maintainable and allows for easier collaboration between developers working on different aspects of the dashboard.

## Usage

The application can be started in multiple ways:

### Recommended: CLI Interface
```bash
# Install and run
pip install -e .
qdashboard

# With custom options
qdashboard --port 8080 --host 0.0.0.0 --debug

# Platform management
qdashboard-platforms status
qdashboard-platforms setup --root /custom/path
```

### Development Mode
```bash
# Direct Python execution
python app.py

# Development script
./qdashboard.sh
```

### Environment Configuration
```bash
# Set environment variables
export QD_PORT=8080
export QD_BIND=0.0.0.0
export QD_PATH=/custom/qdashboard/root

# Run with environment
qdashboard
```

All existing functionality remains unchanged from the user perspective, with improved reliability and configuration flexibility.
