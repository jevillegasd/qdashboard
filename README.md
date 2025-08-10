# QDashboard

A professional quantum computing dashboard with file browsing, experiment monitoring, QPU status tracking, and report visualization capabilities.

![screenshot](screenshot.png)

## About

QDashboard is a comprehensive web-based dashboard designed for quantum computing environments. It provides real-time monitoring, file management, and experiment tracking capabilities for quantum computing workflows. 
The file server functionality is based on the [flask-file-server](https://github.com/Wildog/flask-file-server) project by Wildog.

## Features

- **Dashboard**: Real-time QPU health monitoring, job queue status, and package version tracking
- **File Browser**: Elegant file browsing and management interface (based on flask-file-server)
- **Report Viewer**: Advanced rendering of quantum experiment reports with Plotly support and dark theme
- **QPU Status**: Live monitoring of quantum processing unit availability and SLURM queue integration
- **Job Submission**: SLURM job submission and monitoring interface
- **Package Monitoring**: Real-time display of installed qibo, qibolab, and qibocal versions

## Installation

### For Development

1. **Create and activate a virtual environment:**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. **Install in editable mode:**
```bash
pip install -e .
```

3. **Or use the convenience script:**
```bash
source activate_dev.sh
```

### For Production

```bash
pip install qdashboard
```

## Quick Start

### Using the CLI (Recommended)
```bash
# After installation, run:
qdashboard 5005

# Or with custom options:
qdashboard --host 0.0.0.0 --port 8000 --root /data --debug
```

### Development Server (Legacy)
```bash
python quantum_dashboard.py
```

### Using the Startup Script (Legacy)
```bash
./start_qdashboard.sh
```

### Docker Build
```bash
docker build --rm -t qdashboard:latest .
```

### Docker Run
```bash
docker run -p 5005:5005 qdashboard
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

# List available branches
qdashboard-platforms branches

# Switch to a specific branch
qdashboard-platforms switch branch-name

# Create and switch to a new branch
qdashboard-platforms switch new-branch --create
```

### Branch Management
The qibolab platforms repository contains multiple branches with different platform configurations:

- **main**: Latest stable platform configurations
- **0.1**, **0.2**: Version-specific platform definitions
- **Platform-specific branches**: Calibrated configurations for specific QPUs
- **Feature branches**: Experimental or development configurations

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

- **Quantum Package Integration**: Automatic detection and monitoring of qibo ecosystem packages
- **SLURM Integration**: Real-time queue monitoring and job submission capabilities
- **Report Rendering**: Enhanced HTML report rendering with Plotly support and dark theme compatibility
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

- File server functionality based on [flask-file-server](https://github.com/Wildog/flask-file-server) by [Wildog](https://github.com/Wildog)
- Dark theme inspired by IBM Quantum Computing platform
- Built for quantum computing workflows using the qibo ecosystem
