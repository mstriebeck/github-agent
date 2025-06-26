# Python CI/CD Setup for GitHub Actions

This document describes the Python-compatible CI/CD setup that extends the existing Swift infrastructure to support both Swift and Python projects.

## Overview

The setup includes:
- **Multi-language Docker image**: Supports both Swift and Python development
- **GitHub Actions workflow**: Runs linting, testing, type checking, security scanning, and coverage reporting for Python
- **Extended setup script**: Installs and configures tools for both languages

## Files Created/Modified

### 1. Multi-Language Setup Script
- **File**: `setup/setup_git_runners_multi_lang.sh`
- **Purpose**: Extended version of the original Swift setup script that supports both Swift and Python
- **Key Features**:
  - Installs Python 3.12 alongside Swift 6.1
  - Includes ruff for linting, pytest for testing, coverage tools
  - Builds a Docker image: `mstriebeck/multi-lang-ci-runner:6.1-python3.12`
  - Creates runners with labels `multi-lang-ci`

### 2. GitHub Actions Workflow
- **File**: `.github/workflows/pr-checks.yml`
- **Purpose**: Python-specific CI/CD pipeline
- **Jobs**:
  - **Setup**: Determines versions and prepares environment
  - **Ruff Linting**: Code style and linting with ruff
  - **Python Tests & Coverage**: Runs pytest with coverage reporting
  - **Type Checking**: Static type checking with mypy
  - **Security Check**: Security scanning with bandit
  - **Upload Coverage**: Uploads coverage data to codecov.io
  - **Cleanup**: Final workspace cleanup

### 3. Configuration Files
- **File**: `pyproject.toml`
- **Purpose**: Python project configuration with tool settings for ruff, pytest, coverage, mypy, and bandit

- **File**: `setup/versions.env`
- **Purpose**: Version management for both Swift and Python tools

- **File**: `tests/test_basic.py`
- **Purpose**: Basic test structure to verify the testing setup

## Docker Image Contents

The multi-language Docker image (`mstriebeck/multi-lang-ci-runner`) includes:

### Swift Tools
- Swift 6.1 compiler
- SwiftLint 0.59.0
- swift-test-codecov for coverage

### Python Tools
- Python 3.12
- ruff 0.1.13 (linting and formatting)
- pytest (testing framework)
- pytest-cov (coverage plugin)
- pytest-xdist (parallel testing)
- coverage (coverage measurement)
- black (code formatting)
- mypy (static type checking)
- bandit (security scanning)

## Usage

### Running the Setup Script

```bash
# Make the script executable
chmod +x setup/setup_git_runners_multi_lang.sh

# Run the setup
./setup/setup_git_runners_multi_lang.sh
```

This will:
1. Build the multi-language Docker image
2. Test both Swift and Python functionality
3. Push the image to Docker Hub
4. Set up GitHub runners with multi-language support

### GitHub Actions Workflow

The workflow automatically runs on:
- Pull requests to `main` branch
- Pushes to `main` branch

Jobs run in parallel where possible and include:
- Code linting with ruff
- Comprehensive testing with pytest
- Coverage reporting (XML, LCOV, HTML formats)
- Type checking with mypy
- Security scanning with bandit
- Automatic upload to codecov.io

### Local Development

You can run the same checks locally using the Docker image:

```bash
# Linting
docker run --rm -v "$PWD:/app" mstriebeck/multi-lang-ci-runner:6.1-python3.12 ruff check .

# Testing with coverage
docker run --rm -v "$PWD:/app" mstriebeck/multi-lang-ci-runner:6.1-python3.12 pytest --cov=.

# Type checking
docker run --rm -v "$PWD:/app" mstriebeck/multi-lang-ci-runner:6.1-python3.12 mypy .

# Security scanning
docker run --rm -v "$PWD:/app" mstriebeck/multi-lang-ci-runner:6.1-python3.12 bandit -r .
```

## Coverage Reporting

The setup generates coverage in multiple formats:
- **XML**: For codecov.io integration
- **LCOV**: For codecov.io and other tools
- **HTML**: For local viewing
- **Terminal**: For immediate feedback

Coverage files are uploaded as GitHub Actions artifacts and automatically sent to codecov.io if the `CODECOV_TOKEN` secret is configured.

## Configuration Options

### Versions
Update `setup/versions.env` to change tool versions:
```env
SWIFT_VERSION=6.1
SWIFTLINT_VERSION=0.59.0
PYTHON_VERSION=3.12
RUFF_VERSION=0.1.13
```

### Tool Configuration
- **ruff**: Configured in `pyproject.toml` under `[tool.ruff]`
- **pytest**: Configured in `pyproject.toml` under `[tool.pytest.ini_options]`
- **coverage**: Configured in `pyproject.toml` under `[tool.coverage]`
- **mypy**: Configured in `pyproject.toml` under `[tool.mypy]`
- **bandit**: Configured in `pyproject.toml` under `[tool.bandit]`

### GitHub Secrets Required

For full functionality, ensure these secrets are configured in your GitHub repository:
- `CODECOV_TOKEN`: For uploading coverage to codecov.io
- `GITHUB_TOKEN`: Automatically provided by GitHub Actions

## Comparison with Swift Setup

| Feature | Swift Setup | Python Setup |
|---------|-------------|--------------|
| Linting | SwiftLint | ruff |
| Testing | swift test | pytest |
| Coverage | swift-test-codecov | pytest-cov |
| Type Checking | Swift compiler | mypy |
| Security | N/A | bandit |
| Formatting | SwiftLint autocorrect | ruff format |

## Migration from Swift-Only Setup

If you have an existing Swift setup, you can:

1. **Run both setups**: Keep the existing Swift setup and add Python support
2. **Migrate to multi-language**: Replace Swift runners with multi-language runners
3. **Hybrid approach**: Use Swift runners for Swift projects and Python runners for Python projects

The multi-language setup is designed to coexist with existing Swift infrastructure while providing comprehensive Python development support.
