# QDashboard Changelog

## Project Evolution from flask-file-server

QDashboard is designed to inetract with the [Qibo](https://github.com/qiboteam/qibo) stack.

QDashboard file browsing uses [flask-file-server](https://github.com/Wildog/flask-file-server) project by [Wildog](https://github.com/Wildog).

## Major Features

### v0.0.1 - Quantum Computing Dashboard

#### New Features Added
- **Quantum Dashboard**: Complete dashboard interface for quantum computing environments
- **QPU Status Monitoring**: "Real-time" monitoring of Quantum Processing Units with SLURM integration
- **Package Version Tracking**: Automatic detection and display of qibo, qibolab, and qibocal versions
- **Enhanced Report Rendering**: HTML report viewer with Plotly support and dark theme compatibility

#### UI/UX
- **Dark Theme**: Complete dark theme inspired by IBM Quantum platform
- **Professional Branding**: Consistent QDashboard branding throughout the interface
- **Responsive Design**: Responsive layout for quantum computing workflows
- **Navigation Enhancement**: Sidebar navigation with quantum-specific sections

#### Technical capabilities
- **Environment Variables**: Updated configuration system (QD_* prefixes)
- **Error Handling**: Robust error handling for missing platforms and dependencies
- **Asset Management**: Dynamic asset serving for external reports
- **Docker Integration**: Updated Docker configuration with Python 3.10 base
- **Startup Scripts**: Professional startup script with dependency checking

#### File Browser (Based on flask)
- **Template Updates**: Enhanced templates with QDashboard branding
- **Link Management**: Fixed URL routing for proper navigation
- **Integration**: Seamless integration with quantum computing workflows

### Original flask-file-server Features Preserved
- ✅ File browsing and directory navigation
- ✅ File upload and download capabilities
- ✅ Hidden file toggle functionality
- ✅ File type icons and metadata display
- ✅ Search functionality
- ✅ Authentication support
- ✅ Range request support for large files

### Breaking Changes from Original
- Port changed from 8000 to 5005
- Environment variables renamed (FS_* → QD_*)
- Main executable renamed (file_server.py → quantum_dashboard.py)
- Project directory renamed (flask-file-server → qdashboard)

### Dependencies Updated
- Flask upgraded to 3.0.0+
- Added PyYAML for configuration parsing
- Updated Python version requirement to 3.10+
- Enhanced requirements.txt with version constraints

## Attribution

This project extends and builds upon the solid foundation provided by:
- **Original Project**: [flask-file-server](https://github.com/Wildog/flask-file-server)
- **Original Author**: [Wildog](https://github.com/Wildog)
- **License**: Maintains compatibility with original project licensing

## Future Roadmap

- [ ] Enhanced QPU topology visualization
- [ ] Real-time calibration data display
- [ ] Advanced job queue analytics
- [ ] Multi-platform QPU management
- [ ] API endpoints for programmatic access
- [ ] Advanced authentication and user management
