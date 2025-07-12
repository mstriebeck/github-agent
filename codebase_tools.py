#!/usr/bin/env python3

"""
Codebase Tools for MCP Server
Contains codebase-related tool implementations for repository analysis and management.
"""

import importlib.util
import json
import logging
import os
import subprocess
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from constants import Language
from symbol_storage import AbstractSymbolStorage

logger = logging.getLogger(__name__)


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
        import symbol_storage  # noqa: F401

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


def get_tools(repo_name: str, repository_workspace: str) -> list[dict]:
    """Get codebase tool definitions for MCP registration

    Args:
        repo_name: Repository name for display purposes
        repository_workspace: Repository path for tool descriptions

    Returns:
        List of tool definitions in MCP format
    """
    return [
        {
            "name": "codebase_health_check",
            "description": f"Perform a basic health check of the repository at {repository_workspace}. Validates that the path exists, is accessible, and is a valid Git repository with readable metadata.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
        {
            "name": "search_symbols",
            "description": f"Search for symbols (functions, classes, variables) in the {repo_name} repository. Supports fuzzy matching by symbol name with optional filtering by symbol kind.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query for symbol names (supports partial matches)",
                    },
                    "symbol_kind": {
                        "type": "string",
                        "description": "Optional filter by symbol kind",
                        "enum": ["function", "class", "variable"],
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 50, max: 100)",
                        "minimum": 1,
                        "maximum": 100,
                        "default": 50,
                    },
                },
                "required": ["query"],
            },
        },
    ]


async def execute_codebase_health_check(
    repo_name: str, repository_workspace: str
) -> str:
    """Execute basic health check for the repository

    Args:
        repo_name: Repository name to check
        repository_workspace: Path to the repository

    Returns:
        JSON string with health check results
    """
    logger.info(f"Performing health check for repository: {repo_name}")

    try:
        repository_workspace_obj = Path(repository_workspace)

        health_status: dict[str, Any] = {
            "repo": repo_name,
            "workspace": str(repository_workspace_obj),
            "status": "healthy",
            "checks": {},
            "warnings": [],
            "errors": [],
        }

        # Check 1: Repository exists and is accessible
        if not repository_workspace_obj.exists():
            health_status["status"] = "unhealthy"
            health_status["checks"]["path_exists"] = False
            health_status["errors"].append(
                f"Repository path does not exist: {repository_workspace_obj}"
            )
            return json.dumps(health_status)

        if not repository_workspace_obj.is_dir():
            health_status["status"] = "unhealthy"
            health_status["checks"]["path_exists"] = True
            health_status["checks"]["is_directory"] = False
            health_status["errors"].append(
                f"Repository path is not a directory: {repository_workspace_obj}"
            )
            return json.dumps(health_status)

        health_status["checks"]["path_exists"] = True
        health_status["checks"]["is_directory"] = True

        # Check 2: Git repository validation
        git_dir = repository_workspace_obj / ".git"
        if not git_dir.exists():
            health_status["status"] = "unhealthy"
            health_status["checks"]["is_git_repo"] = False
            health_status["errors"].append(
                "Not a Git repository (no .git directory found)"
            )
            return json.dumps(health_status)

        health_status["checks"]["is_git_repo"] = True

        # Check 3: Basic Git metadata access
        try:
            # Get current branch
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=repository_workspace_obj,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                current_branch = result.stdout.strip()
                health_status["checks"]["current_branch"] = current_branch
            else:
                health_status["warnings"].append(
                    "Could not determine current Git branch"
                )

            # Get remote origin URL
            result = subprocess.run(
                ["git", "config", "--get", "remote.origin.url"],
                cwd=repository_workspace_obj,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                remote_url = result.stdout.strip()
                health_status["checks"]["has_remote"] = bool(remote_url)
                if remote_url:
                    health_status["checks"]["remote_url"] = remote_url
            else:
                health_status["checks"]["has_remote"] = False

            health_status["checks"]["git_responsive"] = True

        except subprocess.TimeoutExpired:
            health_status["warnings"].append("Git commands timed out")
            health_status["checks"]["git_responsive"] = False
        except subprocess.CalledProcessError as e:
            health_status["warnings"].append(f"Could not access Git metadata: {e}")
            health_status["checks"]["git_responsive"] = False

        # Determine overall health
        if health_status["errors"]:
            health_status["status"] = "unhealthy"
        elif health_status["warnings"]:
            health_status["status"] = "warning"
        else:
            health_status["status"] = "healthy"

        return json.dumps(health_status, indent=2)

    except Exception as e:
        logger.exception(f"Error during health check for {repo_name}")
        error_response = {
            "repo": repo_name,
            "workspace": repository_workspace,
            "status": "error",
            "errors": [f"Health check failed: {e!s}"],
            "checks": {},
            "warnings": [],
        }
        return json.dumps(error_response)


async def execute_search_symbols(
    repo_name: str,
    repository_workspace: str,
    query: str,
    symbol_storage: AbstractSymbolStorage,
    symbol_kind: str | None = None,
    limit: int = 50,
) -> str:
    """Execute symbol search for the repository with enhanced error handling

    Args:
        repo_name: Repository name to search
        repository_workspace: Path to the repository
        query: Search query for symbol names
        symbol_storage: Symbol storage instance for search operations
        symbol_kind: Optional filter by symbol kind (function, class, variable)
        limit: Maximum number of results to return

    Returns:
        JSON string with search results
    """
    logger.info(
        f"Searching symbols in repository: {repo_name}, query: '{query}', kind: {symbol_kind}, limit: {limit}"
    )

    try:
        # Validate inputs
        if not query or not query.strip():
            return json.dumps(
                {
                    "error": "Query cannot be empty",
                    "query": query,
                    "repository": repo_name,
                    "symbols": [],
                    "total_results": 0,
                }
            )

        if limit < 1 or limit > 100:
            return json.dumps(
                {
                    "error": "Limit must be between 1 and 100",
                    "query": query,
                    "repository": repo_name,
                    "symbols": [],
                    "total_results": 0,
                }
            )

        # Validate symbol_kind if provided
        valid_kinds = [
            "function",
            "class",
            "variable",
            "method",
            "property",
            "constant",
            "module",
        ]
        if symbol_kind and symbol_kind not in valid_kinds:
            return json.dumps(
                {
                    "error": f"Invalid symbol kind '{symbol_kind}'. Valid kinds: {valid_kinds}",
                    "query": query,
                    "repository": repo_name,
                    "symbols": [],
                    "total_results": 0,
                }
            )

        # Execute symbol search with timeout and error handling
        try:
            symbols = symbol_storage.search_symbols(
                query=query,
                repository_id=repo_name,
                symbol_kind=symbol_kind,
                limit=limit,
            )
        except Exception as search_error:
            logger.error(f"Database search error for {repo_name}: {search_error}")
            return json.dumps(
                {
                    "error": f"Database search failed: {search_error!s}",
                    "query": query,
                    "repository": repo_name,
                    "symbols": [],
                    "total_results": 0,
                    "troubleshooting": {
                        "suggestions": [
                            "Check if the repository has been indexed",
                            "Try a simpler query",
                            "Check database connectivity",
                        ]
                    },
                }
            )

        # Format results for JSON response
        results = []
        for symbol in symbols:
            try:
                results.append(
                    {
                        "name": symbol.name,
                        "kind": symbol.kind.value,
                        "file_path": symbol.file_path,
                        "line_number": symbol.line_number,
                        "column_number": symbol.column_number,
                        "docstring": symbol.docstring,
                        "repository_id": symbol.repository_id,
                    }
                )
            except Exception as format_error:
                logger.warning(f"Error formatting symbol result: {format_error}")
                # Continue with other symbols
                continue

        response = {
            "query": query,
            "symbol_kind": symbol_kind,
            "limit": limit,
            "repository": repo_name,
            "total_results": len(results),
            "symbols": results,
        }

        logger.info(f"Found {len(results)} symbols for query '{query}' in {repo_name}")
        return json.dumps(response, indent=2)

    except Exception as e:
        logger.exception(f"Error during symbol search for {repo_name}")
        error_response = {
            "query": query,
            "repository": repo_name,
            "error": f"Symbol search failed: {e!s}",
            "symbols": [],
            "total_results": 0,
            "troubleshooting": {
                "error_type": type(e).__name__,
                "suggestions": [
                    "Check repository configuration",
                    "Verify database is accessible",
                    "Try re-indexing the repository",
                ],
            },
        }
        return json.dumps(error_response)


# Tool execution mapping
TOOL_HANDLERS: dict[str, Callable[..., Awaitable[str]]] = {
    "codebase_health_check": execute_codebase_health_check,
    "search_symbols": execute_search_symbols,
}


async def execute_tool(tool_name: str, **kwargs) -> str:
    """Execute a codebase tool by name

    Args:
        tool_name: Name of the tool to execute
        **kwargs: Tool-specific arguments (including symbol_storage for search_symbols)

    Returns:
        Tool execution result as JSON string
    """
    if tool_name not in TOOL_HANDLERS:
        return json.dumps(
            {
                "error": f"Unknown tool: {tool_name}",
                "available_tools": list(TOOL_HANDLERS.keys()),
            }
        )

    handler = TOOL_HANDLERS[tool_name]
    try:
        return await handler(**kwargs)
    except Exception as e:
        logger.exception(f"Error executing tool {tool_name}")
        return json.dumps({"error": f"Tool execution failed: {e!s}", "tool": tool_name})
