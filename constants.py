#!/usr/bin/env python3

"""
Shared constants for the GitHub MCP agent system.

This file contains constants that are used across both Python code and shell scripts.
"""

from enum import Enum
from pathlib import Path

# Python version requirements
MINIMUM_PYTHON_MAJOR = 3
MINIMUM_PYTHON_MINOR = 8
MINIMUM_PYTHON_VERSION = f"{MINIMUM_PYTHON_MAJOR}.{MINIMUM_PYTHON_MINOR}"


# Repository configuration
class Language(Enum):
    """Supported programming languages for repositories."""

    PYTHON = "python"
    SWIFT = "swift"


SUPPORTED_LANGUAGES = set(Language)

# Port ranges for MCP servers
MCP_PORT_RANGE_START = 8080
MCP_PORT_RANGE_END = 8200

# GitHub URL patterns
GITHUB_SSH_PREFIX = "git@github.com:"
GITHUB_HTTPS_PREFIX = "https://github.com/"

# Data storage paths
DATA_DIR = Path.home() / ".local" / "share" / "github-agent"
LOGS_DIR = DATA_DIR / "logs"
SYMBOLS_DB_PATH = DATA_DIR / "symbols.db"
