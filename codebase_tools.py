#!/usr/bin/env python3

"""
Codebase Tools for MCP Server
Contains codebase-related tool implementations for repository analysis and management.
"""

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def get_tools(repo_name: str, repo_path: str) -> list[dict]:
    """Get codebase tool definitions for MCP registration

    Args:
        repo_name: Repository name for display purposes
        repo_path: Repository path for tool descriptions

    Returns:
        List of tool definitions in MCP format
    """
    return [
        {
            "name": "codebase_health_check",
            "description": f"Perform a basic health check of the repository at {repo_path}. Validates that the path exists, is accessible, and is a valid Git repository with readable metadata.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    ]


async def execute_codebase_health_check(repo_name: str, repo_path: str) -> str:
    """Execute basic health check for the repository

    Args:
        repo_name: Repository name to check
        repo_path: Path to the repository

    Returns:
        JSON string with health check results
    """
    logger.info(f"Performing health check for repository: {repo_name}")

    try:
        repo_path_obj = Path(repo_path)

        health_status: dict[str, Any] = {
            "repo": repo_name,
            "path": str(repo_path_obj),
            "status": "healthy",
            "checks": {},
            "warnings": [],
            "errors": [],
        }

        # Check 1: Repository exists and is accessible
        if not repo_path_obj.exists():
            health_status["status"] = "unhealthy"
            health_status["checks"]["path_exists"] = False
            health_status["errors"].append(
                f"Repository path does not exist: {repo_path_obj}"
            )
            return json.dumps(health_status)

        if not repo_path_obj.is_dir():
            health_status["status"] = "unhealthy"
            health_status["checks"]["path_exists"] = True
            health_status["checks"]["is_directory"] = False
            health_status["errors"].append(
                f"Repository path is not a directory: {repo_path_obj}"
            )
            return json.dumps(health_status)

        health_status["checks"]["path_exists"] = True
        health_status["checks"]["is_directory"] = True

        # Check 2: Git repository validation
        git_dir = repo_path_obj / ".git"
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
                cwd=repo_path_obj,
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
                cwd=repo_path_obj,
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
            "path": repo_path,
            "status": "error",
            "errors": [f"Health check failed: {e!s}"],
            "checks": {},
            "warnings": [],
        }
        return json.dumps(error_response)


# Tool execution mapping
TOOL_HANDLERS = {
    "codebase_health_check": execute_codebase_health_check,
}


async def execute_tool(tool_name: str, **kwargs) -> str:
    """Execute a codebase tool by name

    Args:
        tool_name: Name of the tool to execute
        **kwargs: Tool-specific arguments

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
