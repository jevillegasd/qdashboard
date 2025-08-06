# QDashboard Modular Architecture

This document describes the modular organization of the QDashboard codebase.

## Directory Structure

```
qdashboard/
├── app.py                 # Main application entry point
├── qdashboard/           # Main package directory
│   ├── __init__.py       # Package initialization
│   ├── core/             # Core application configuration
│   │   ├── __init__.py
│   │   └── app.py        # Flask app creation and configuration
│   ├── utils/            # Utility functions
│   │   ├── __init__.py
│   │   └── formatters.py # File formatting and template filters
│   ├── qpu/              # QPU monitoring and management
│   │   ├── __init__.py
│   │   ├── monitoring.py # QPU health and status monitoring
│   │   ├── slurm.py      # SLURM queue management
│   │   └── topology.py   # Topology analysis and visualization
│   ├── experiments/      # Experiment and protocol management
│   │   ├── __init__.py
│   │   └── protocols.py  # Qibocal protocol discovery and management
│   └── web/              # Web interface components
│       ├── __init__.py
│       ├── routes.py     # Main application routes
│       ├── file_browser.py # File browser functionality
│       └── reports.py    # Report viewing utilities
├── assets/               # Static assets (CSS, JS, images)
├── templates/            # Jinja2 templates
└── quantum_dashboard.py.backup # Backup of original monolithic file
```

## Module Descriptions

### Core (`qdashboard/core/`)
- **app.py**: Flask application factory, template filter registration, configuration management

### Utilities (`qdashboard/utils/`)
- **formatters.py**: File size formatting, time formatting, icon mapping, data type detection, JSON/YAML utilities

### QPU Management (`qdashboard/qpu/`)
- **monitoring.py**: QPU health checks, qibo package version tracking, platform discovery
- **slurm.py**: SLURM queue status monitoring, job management, log parsing
- **topology.py**: Quantum device topology analysis, connectivity inference, visualization generation

### Experiments (`qdashboard/experiments/`)
- **protocols.py**: Qibocal protocol discovery, categorization, parameter management

### Web Interface (`qdashboard/web/`)
- **routes.py**: Flask route definitions, API endpoints
- **file_browser.py**: File browser functionality (PathView class)
- **reports.py**: Report viewing and asset handling

## Benefits of Modular Architecture

1. **Separation of Concerns**: Each module has a single, well-defined responsibility
2. **Maintainability**: Easier to locate and modify specific functionality
3. **Testability**: Individual modules can be tested in isolation
4. **Reusability**: Components can be imported and reused across the application
5. **Scalability**: New features can be added without modifying existing modules
6. **Readability**: Smaller, focused files are easier to understand

## Migration from Monolithic Structure

The original `quantum_dashboard.py` (1,500+ lines) has been broken down into:
- **Core app setup**: ~30 lines
- **Utility functions**: ~150 lines  
- **QPU monitoring**: ~200 lines
- **SLURM management**: ~100 lines
- **Topology analysis**: ~400 lines
- **Protocol discovery**: ~200 lines
- **Web routes**: ~150 lines
- **File browser**: ~200 lines
- **Report handling**: ~50 lines

This modular approach makes the codebase much more maintainable and allows for easier collaboration between developers working on different aspects of the dashboard.

## Usage

The application maintains the same external interface - start with:

```bash
python3 app.py
# or
./start_qdashboard.sh
```

All existing functionality remains unchanged from the user perspective.
