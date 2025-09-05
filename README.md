# QDashboard

A quantum computing dashboard with file browsing, experiment monitoring, QPU status tracking, and report visualization capabilities.

![screenshot](screenshot.png)

## About

# QDashboard

QDashboard is a web-based dashboard for quantum computing workflows. It provides an interface for file management, quantum experiment building, SLURM job monitoring, and quantum hardware platform management. Built on a file server foundation, QDashboard extends file browsing with quantum-specific functionalities. 

The file server functionality is based on the [flask-file-server](https://github.com/Wildog/flask-file-server) project by Wildog.

## Features

### Core Dashboard
- **Real-time QPU Monitoring**: Live status tracking of quantum processing units
- **SLURM Integration**: Job queue monitoring and submission interface
- **Package Tracking**: Automatic detection of qibo, qibolab, and qibocal versions
- **Professional UI**: Dark theme with responsive design

### Experiment Builder
- **Interactive Protocol Selection**: Browse and configure qibocal protocols
- **Mixed Qubit Support**: Handle both numeric (0, 1, 2) and string qubits ("control", "target")
- **YAML Generation**: Automatic runcard generation with proper formatting
- **Parameter Validation**: Type checking and constraint validation
- **One-Click Submission**: Direct SLURM job submission from the interface

### QPU Management
- **Platform Repository Management**: Automated git operations for qibolab platforms
- **Branch Switching**: Live platform branch management with updates
- **Topology Visualization**: Quantum device connectivity analysis
- **Multi-Platform Support**: Handle multiple QPU configurations

### File Management
- **Elegant File Browser**: Beautiful interface for file navigation
- **Report Viewer**: Advanced rendering of quantum experiment reports
- **Upload/Download**: Seamless file operations
- **Search Functionality**: Quick file and directory search

### Configuration
- **Centralized Config**: Consistent configuration management across all modules
- **Environment Variables**: Full QD_* environment variable support
- **CLI Interface**: Comprehensive command-line interface
- **Cross-Platform**: Works on Linux, macOS, and Windows

## Installation

### Prerequisites
- Python >= 3.8
- Optional: qibo, qibolab, qibocal packages for full quantum functionality

### For Production

```bash
pip install qdashboard
```

### For Development

1. **Clone and setup:**
```bash
git clone https://github.com/qiboteam/qdashboard.git
cd qdashboard
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. **Install in editable mode:**
```bash
pip install -e .
```

3. **Install with quantum dependencies:**
```bash
pip install -e ".[quantum]"
```

4. **Install with all development tools:**
```bash
pip install -e ".[all]"
```

## Quick Start

### Using the CLI (Recommended)
```bash
# Basic startup (default: localhost:5005)
qdashboard

# Custom port and host
qdashboard --port 8080 --host 0.0.0.0

# With custom root directory
qdashboard --root /path/to/quantum/data --debug

# Full configuration
qdashboard --host 0.0.0.0 --port 8080 --root /data --auth-key mykey123 --debug
```

### Using Environment Variables
```bash
# Set configuration via environment
export QD_PORT=8080
export QD_BIND=0.0.0.0
export QD_PATH=/custom/qdashboard/root
export QD_KEY=myauthkey

# Run with environment configuration
qdashboard
```

### Development Mode
```bash
# Direct Python execution
python app.py

# Using the startup script
./qdashboard.sh
```

### Docker
```bash
# Build
docker build -t qdashboard .

# Run
docker run -p 5005:5005 -v /your/data:/data qdashboard
```

## QPU Platforms Management

QDashboard automatically manages the qibolab platforms repository for you:

### Automatic Setup
When you start QDashboard, it automatically:
1. Checks if `QIBOLAB_PLATFORMS` environment variable is set
2. If not set, creates a `qibolab_platforms_qrc` directory in your specified root directory
3. Automatically clones the [qibolab_platforms_qrc](https://github.com/qiboteam/qibolab_platforms_qrc) repository
4. Makes all QPU platforms available to the dashboard

### Manual Management
Use the dedicated platforms CLI tool:

```bash
# Check current status
qdashboard-platforms status

# Set up platforms in a specific directory
qdashboard-platforms --root /path/to/directory setup

# Update platforms repository
qdashboard-platforms update
```

## Key Features

### Experiment Builder
The experiment builder allows you to:

1. **Browse Protocols**: Discover available qibocal protocols automatically
2. **Configure Parameters**: Set protocol-specific parameters with validation
3. **Generate YAML**: Create formatted qibocal runcards
4. **Submit Jobs**: SLURM job submission from the web interface

### Platform Management
- **Setup**: Auto-clone qibolab platforms repository
- **Branch Management**: Switch between platform branches
- **Git Integration**: Built-in git operations for platform updates
- **Status Monitoring**: Platform and QPU status

### Configuration Management
- **Config**: All settings in one place with defaults
- **Environment Support**: QD_* environment variable support
- **Validation**: Configuration validation with errors
- **Cross-Platform**: Works across operating systems

# List available branches
qdashboard-platforms branches

# Switch to a specific branch
qdashboard-platforms switch branch-name

# Create and switch to a new branch
qdashboard-platforms switch new-branch --create
```

### Branch Management
The qibolab platforms repository contains branches with platform configurations:

- **main**: Stable platform configurations
- **0.1**, **0.2**: Version-specific platform definitions
- **Platform-specific branches**: Configurations for specific QPUs
- **Feature branches**: Development configurations

Different branches may contain different sets of platforms or different calibration parameters for the same platforms.

### Environment Variable
If you prefer to use your own platforms directory:
```bash
export QIBOLAB_PLATFORMS=/path/to/your/platforms
qdashboard
```

## Configuration

Environment variables:

- `QD_BIND` - Bind address, default 127.0.0.1
- `QD_PORT` - Server port, default 5005  
- `QD_PATH` - Root path to serve, default $HOME
- `QD_KEY` - Authentication key (base64 encoded username:password), default none
- `QIBOLAB_PLATFORMS` - Path to qibolab platforms directory

### Example with custom configuration:
```bash
docker run -p 8000:8000 -e QD_BIND=0.0.0.0 -e QD_PORT=8000 -e QD_PATH=/data -e QD_KEY=dGVzdDp0ZXN0 qdashboard
```

## Dependencies

- Flask >= 3.0.0
- humanize >= 4.0.0
- pathlib2 >= 2.3.0
- werkzeug >= 3.0.0
- PyYAML >= 6.0.0

## Architecture

QDashboard extends the file server capabilities with quantum computing specific features:

- **Quantum Package Integration**: Detection and monitoring of qibo ecosystem packages
- **SLURM Integration**: Queue monitoring and job submission capabilities
- **Report Rendering**: HTML report rendering with Plotly support and dark theme compatibility
- **QPU Management**: Platform configuration parsing and status monitoring

## Installation

### From PyPI (when released)

```bash
pip install qdashboard
```

### From Source

```bash
git clone https://github.com/qiboteam/qdashboard.git
cd qdashboard
pip install .
```

### With Quantum Dependencies

```bash
pip install qdashboard[quantum]
```

### Development Installation

```bash
git clone https://github.com/qiboteam/qdashboard.git
cd qdashboard
pip install -e .[dev]
```

## Usage

### Command Line Interface

After installation, you can start the dashboard using the command line:

```bash
# Start on default port 5005
qdashboard

# Start on custom port
qdashboard 8080

# Start with custom host and root directory
qdashboard --host 0.0.0.0 --root /path/to/quantum/data 8080

# Enable debug mode
qdashboard --debug 5005

# View all options
qdashboard --help
```

### Python API

You can also start the dashboard programmatically:

```python
from qdashboard.cli import main

# Start with default settings
main()

# Start with custom arguments
main(['--host', '0.0.0.0', '--port', '8080'])
```

### Alternative Scripts

The package provides two equivalent commands:
- `qdashboard` - Main command
- `qdashboard-server` - Alternative alias

## Configuration

### Environment Variables

- `QIBOLAB_PLATFORMS`: Path to qibolab platforms directory
- `HOME`: User home directory (default root for file serving)

### Command Line Options

- `--host HOST`: Host address to bind the server (default: 127.0.0.1)
- `--root ROOT`: Root directory for file serving (default: user home)
- `--auth-key KEY`: Authentication key for dashboard access
- `--debug`: Enable Flask debug mode
- `--version`: Show version information

## Requirements

### Core Dependencies
- Python 3.8+
- Flask 3.0+
- Werkzeug 3.0+
- PyYAML 6.0+
- humanize 4.0+

### Optional Dependencies
- qibo: Quantum simulation library
- qibolab: Quantum hardware control
- qibocal: Quantum calibration tools

## Acknowledgments

- File server functionality based on [flask-file-server](https://github.com/Wildog/flask-file-server) by [Wildog](https://github.com/Wildog).
- Dark theme inspired by IBM Quantum Computing platform.
- Built for quantum computing workflows using the qibo ecosystem.
