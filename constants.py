#!/usr/bin/env python3

"""
Shared constants for the GitHub MCP agent system.

This file contains constants that are used across both Python code and shell scripts.
"""

# Python version requirements
MINIMUM_PYTHON_MAJOR = 3
MINIMUM_PYTHON_MINOR = 8
MINIMUM_PYTHON_VERSION = f"{MINIMUM_PYTHON_MAJOR}.{MINIMUM_PYTHON_MINOR}"

# Repository configuration
SUPPORTED_LANGUAGES = {"python", "swift"}

# Port ranges for MCP servers
MCP_PORT_RANGE_START = 8080
MCP_PORT_RANGE_END = 8200

# GitHub URL patterns
GITHUB_SSH_PREFIX = "git@github.com:"
GITHUB_HTTPS_PREFIX = "https://github.com/"
