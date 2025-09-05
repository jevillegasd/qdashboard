# QDashboard Changelog

## Project Evolution from flask-file-server

QDashboard is designed to interact with the [Qibo](https://github.com/qiboteam/qibo) stack. The app may be run without Qibo installed but its capabilities are dramatically reduced. 

QDashboard file browsing uses [flask-file-server](https://github.com/Wildog/flask-file-server) project by [Wildog](https://github.com/Wildog).

## Version History

### v0.0.3 - Configuration & Mixed Qubit Support (September 2025)

#### Major Features
- **Mixed Qubit Support**: Support for both numeric (0, 1, 2) and string qubits ("control", "target", "ancilla")
- **Centralized parseQubit Function**: Unified frontend parsing for qubit handling
- **YAML Generation**: YAML export with qubit type handling
- **Testing Framework**: Test suite for mixed qubit functionality

#### Configuration Management
- **Configuration Module**: New `qdashboard.core.config` module
- **Default Settings**: Port (5005) and host (127.0.0.1) across CLI and app
- **Configuration Utilities**: Helper functions for config access patterns
- **Validation**: Configuration validation with error messages

#### Code Quality & Housekeeping
- **Hardcoded Value Removal**: Removed hardcoded paths, ports, and directories
- **Code Deduplication**: Replaced multiple `os.makedirs()` instances with `ensure_directory_exists()`
- **Error Handling**: Exception handling and user feedback
- **Type Safety**: Type hints throughout codebase

#### Technical Improvements
- **Directory Management**: Centralized directory creation with `ensure_directory_exists()`
- **Environment Variable Support**: QD_* environment variables
- **Cross-Platform Compatibility**: Home directory detection across operating systems
- **Modular Architecture**: Module organization with separation of concerns

#### Documentation
- **Architecture Documentation**: Updated ARCHITECTURE.md with configuration details
- **Housekeeping Summary**: Documentation of improvements
- **Project Settings**: Updated pyproject.toml, setup.cfg with dependencies

### v0.0.2 - Modular Architecture & Experiment Builder

#### Modular Architecture
- **Code Reorganization**: Broke down monolithic file into focused modules
- **Separation of Concerns**: Module boundaries for core, utils, qpu, experiments, and web
- **Maintainability**: Smaller, focused files

#### Experiment Builder
- **Protocol Selection**: Dynamic protocol discovery and parameter configuration
- **YAML Generation**: Qibocal runcard generation with formatting
- **Parameter Validation**: Input validation with type checking and constraints
- **Multi-Qubit Support**: Qubit selection and parameter configuration

#### QPU Management
- **Platform Repository Management**: Git operations for platform repositories
- **Branch Management**: Switch between platform branches with updates
- **Topology Visualization**: Quantum device topology analysis
- **Connectivity Analysis**: Inference of qubit connectivity from platform data

#### Job Submission
- **SLURM Integration**: SLURM job submission and monitoring
- **Experiment Metadata**: Experiment tracking and metadata storage
- **Job Status Monitoring**: Job status updates and log viewing
- **Repeat Experiments**: Experiment repetition functionality

### v0.0.1 - Quantum Computing Dashboard

#### New Features Added
- **Quantum Dashboard**: Dashboard interface for quantum computing environments
- **QPU Status Monitoring**: Monitoring of Quantum Processing Units with SLURM integration
- **Package Version Tracking**: Detection and display of qibo, qibolab, and qibocal versions
- **Report Rendering**: HTML report viewer with Plotly support and dark theme compatibility

#### UI/UX
- **Dark Theme**: Dark theme based on IBM Quantum platform
- **Branding**: QDashboard branding throughout the interface
- **Responsive Design**: Layout for quantum computing workflows
- **Navigation**: Sidebar navigation with quantum-specific sections

#### Technical capabilities
- **Environment Variables**: Configuration system (QD_* prefixes)
- **Error Handling**: Error handling for missing platforms and dependencies
- **Asset Management**: Asset serving for external reports
- **Docker Integration**: Docker configuration with Python 3.10 base
- **Startup Scripts**: Startup script with dependency checking

#### File Browser (Based on flask)
- **Template Updates**: Templates with QDashboard branding
- **Link Management**: URL routing for navigation
- **Integration**: Integration with quantum computing workflows

### Original flask-file-server Features Preserved
- File browsing and directory navigation
- File upload and download capabilities
- Hidden file toggle functionality
- File type icons and metadata display
- Search functionality
- Authentication support
- Range request support for large files

### Breaking Changes from Original
- Port changed from 8000 to 5005
- Environment variables renamed (FS_* → QD_*)
- Main executable renamed (file_server.py → quantum_dashboard.py)
- Project directory renamed (flask-file-server → qdashboard)

### Dependencies Updated
- Flask upgraded to 3.0.0+
- Added PyYAML for configuration parsing
- Updated Python version requirement to 3.10+
- Updated requirements.txt with version constraints

## Attribution

This project extends and builds upon the foundation provided by:
- **Original Project**: [flask-file-server](https://github.com/Wildog/flask-file-server)
- **Original Author**: [Wildog](https://github.com/Wildog)
- **License**: Maintains compatibility with original project licensing

## Future Roadmap

- QPU topology visualization
- Real-time calibration data display
- Job queue analytics
- Multi-platform QPU management
- API endpoints for programmatic access
- Authentication and user management
