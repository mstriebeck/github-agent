#!/usr/bin/env python3

"""
Codebase Tools Validation

This module provides validation functions for codebase service prerequisites.
"""

import importlib.util
import logging
import os
import subprocess
from typing import Any

from constants import Language


def validate(logger: logging.Logger, repositories: dict[str, Any]) -> None:
    """
    Validate codebase service prerequisites.

    Args:
        logger: Logger instance for debugging and monitoring
        repositories: Dictionary of repository configurations

    Raises:
        RuntimeError: If codebase prerequisites are not met
    """
    logger.info("Validating codebase service prerequisites...")

    # Validate symbol storage service
    _validate_symbol_storage(logger)

    # Validate language-specific tools for each repository
    for repo_name, repo_config in repositories.items():
        language = getattr(repo_config, "language", None)
        workspace = getattr(repo_config, "workspace", None)

        if not workspace:
            continue

        # Validate workspace accessibility
        _validate_workspace_access(logger, workspace, repo_name)

        # Validate language-specific LSP tools
        if language == Language.PYTHON:
            _validate_python_lsp_tools(logger, repo_name)

    logger.info(
        f"✅ Codebase service validation passed for {len(repositories)} repositories"
    )


def _validate_workspace_access(
    logger: logging.Logger, workspace: str, repo_name: str
) -> None:
    """
    Validate that the workspace is accessible for reading/writing.
    """
    if not os.path.exists(workspace):
        raise RuntimeError(
            f"Repository workspace does not exist: {workspace} (repo: {repo_name})"
        )

    if not os.path.isdir(workspace):
        raise RuntimeError(
            f"Repository workspace is not a directory: {workspace} (repo: {repo_name})"
        )

    if not os.access(workspace, os.R_OK):
        raise RuntimeError(
            f"Repository workspace is not readable: {workspace} (repo: {repo_name})"
        )

    if not os.access(workspace, os.W_OK):
        raise RuntimeError(
            f"Repository workspace is not writable: {workspace} (repo: {repo_name})"
        )

    logger.debug(f"Workspace access validation passed: {workspace} (repo: {repo_name})")


def _validate_symbol_storage(logger: logging.Logger) -> None:
    """
    Validate that symbol storage service is available and configured.
    """
    try:
        # Check if symbol_storage module is available
        if importlib.util.find_spec("symbol_storage") is None:
            raise ImportError("symbol_storage module not found")

        # Try to import the main storage class
        from symbol_storage import SQLiteSymbolStorage

        logger.debug("Symbol storage validation passed: SQLiteSymbolStorage available")
    except ImportError as e:
        raise RuntimeError(
            f"Symbol storage not available: {e}. Required for codebase indexing."
        ) from e


def _validate_python_lsp_tools(logger: logging.Logger, repo_name: str) -> None:
    """
    Validate Python-specific LSP tools for codebase service.
    """
    # Validate pyright is available since that's the main LSP tool for Python
    try:
        result = subprocess.run(
            ["pyright", "--version"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        version = result.stdout.strip()
        logger.debug(
            f"Python LSP tools validation passed for {repo_name}: pyright {version}"
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise RuntimeError(
            f"Python LSP tools not available for repository {repo_name}. "
            "Please add it to requirements.txt"
        ) from e
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"Pyright command timed out for repository {repo_name}"
        ) from None
