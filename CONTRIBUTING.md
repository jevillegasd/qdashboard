# Contributing to QDashboard

Thank you for your interest in contributing to QDashboard! This document provides guidelines for contributing to the project.

## Development Setup

### Prerequisites
- Python >= 3.8
- Git
- Optional: qibo, qibolab, qibocal for full quantum functionality

### Setting up the Development Environment

1. **Fork and Clone**
```bash
git clone https://github.com/your-username/qdashboard.git
cd qdashboard
```

2. **Create Virtual Environment**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install Development Dependencies**
```bash
pip install -e ".[all]"
```

4. **Install Pre-commit Hooks** (Optional but recommended)
```bash
pre-commit install
```

## Code Style and Standards

### Python Code Style
- **Formatter**: Black (line length: 100)
- **Linter**: Flake8
- **Type Hints**: Required for new functions
- **Docstrings**: Required for public functions

### Running Code Quality Checks
```bash
# Format code
black qdashboard/

# Check linting
flake8 qdashboard/

# Type checking
mypy qdashboard/
```

### Configuration Guidelines
- Use `qdashboard.core.config` utilities for configuration access
- Avoid hardcoded values (ports, paths, etc.)
- Use `ensure_directory_exists()` instead of `os.makedirs()`
- Follow the centralized configuration pattern

## Project Structure

```
qdashboard/
├── qdashboard/           # Main package
│   ├── core/             # Core configuration and app setup
│   ├── qpu/              # QPU monitoring and management
│   ├── experiments/      # Experiment and protocol management
│   ├── web/              # Web interface and routes
│   └── utils/            # Utility functions
├── assets/               # Static files (CSS, JS)
├── templates/            # HTML templates
└── tests/                # Test files
```

## Making Changes

### Branching Strategy
- Create feature branches from `main`
- Use descriptive branch names: `feature/experiment-builder`, `fix/config-validation`

### Commit Messages
Use clear, descriptive commit messages:
```
feat: add mixed qubit support to experiment builder
fix: resolve hardcoded path in job submission
docs: update configuration documentation
```

### Testing
- Write tests for new features
- Ensure all existing tests pass
- Test with different Python versions if possible

```bash
# Run tests
pytest

# Run with coverage
pytest --cov=qdashboard
```

## Pull Request Process

1. **Before Creating PR**
   - Ensure all tests pass
   - Run code quality checks
   - Update documentation if needed
   - Test your changes thoroughly

2. **Creating the PR**
   - Use a descriptive title
   - Provide detailed description of changes
   - Reference any related issues
   - Add screenshots for UI changes

3. **PR Template**
```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] Tests pass locally
- [ ] Added new tests for new functionality
- [ ] Manual testing completed

## Screenshots (if applicable)
Add screenshots for UI changes
```

## Specific Contribution Areas

### Frontend Development
- **JavaScript**: Use modern ES6+ syntax
- **CSS**: Follow existing dark theme patterns
- **Templates**: Use Jinja2 template inheritance
- **Qubit Support**: Ensure both numeric and string qubits work

### Backend Development
- **Configuration**: Use centralized config utilities
- **Error Handling**: Provide clear error messages
- **Logging**: Use the centralized logger
- **APIs**: Follow RESTful patterns

### Documentation
- **Code Documentation**: Update docstrings
- **User Documentation**: Update README.md
- **Architecture**: Update ARCHITECTURE.md for structural changes

## Common Tasks

### Adding a New Configuration Option
1. Add default value to `qdashboard/core/config.py`
2. Add CLI argument in `qdashboard/cli.py`
3. Add environment variable support
4. Update documentation

### Adding a New API Endpoint
1. Add route to `qdashboard/web/routes.py`
2. Follow existing patterns for config access
3. Add proper error handling
4. Document the endpoint

### Adding a New QPU Feature
1. Add functionality to appropriate `qdashboard/qpu/` module
2. Use configuration utilities
3. Add proper logging
4. Consider SLURM integration if applicable

## Getting Help

- **Issues**: Check existing issues before creating new ones
- **Discussions**: Use GitHub Discussions for questions
- **Documentation**: Refer to ARCHITECTURE.md for codebase structure

## Code of Conduct

- Be respectful and inclusive
- Focus on constructive feedback
- Help maintain a welcoming environment
- Follow professional communication standards

## Release Process

For maintainers:

1. Update version in `qdashboard/__init__.py`
2. Update CHANGELOG.md
3. Create release tag
4. Update documentation as needed

Thank you for contributing to QDashboard! 
