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
            "description": f"Perform a comprehensive health check of the repository at {repo_path}. Validates repository structure, checks for required files, verifies Git status, and reports on overall repository health.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    ]


async def execute_codebase_health_check(repo_name: str) -> str:
    """Execute comprehensive health check for the repository

    Args:
        repo_name: Repository name to check

    Returns:
        JSON string with health check results
    """
    logger.info(f"Performing health check for repository: {repo_name}")

    try:
        # Get repository manager (should be set by worker)
        from github_tools import repo_manager

        if not repo_manager:
            return json.dumps(
                {"error": "Repository manager not initialized", "repo": repo_name}
            )

        # Get repository config
        if repo_name not in repo_manager.repositories:
            return json.dumps(
                {
                    "error": f"Repository '{repo_name}' not found in configuration",
                    "repo": repo_name,
                }
            )

        repo_config = repo_manager.repositories[repo_name]
        repo_path = Path(repo_config.path)

        health_status: dict[str, Any] = {
            "repo": repo_name,
            "path": str(repo_path),
            "status": "healthy",
            "checks": {},
            "warnings": [],
            "errors": [],
        }

        # Check 1: Repository path exists
        if not repo_path.exists():
            health_status["errors"].append("Repository path does not exist")
            health_status["status"] = "unhealthy"
            health_status["checks"]["path_exists"] = False
        else:
            health_status["checks"]["path_exists"] = True

        # Check 2: Git repository
        git_dir = repo_path / ".git"
        if not git_dir.exists():
            health_status["errors"].append("Not a Git repository (no .git directory)")
            health_status["status"] = "unhealthy"
            health_status["checks"]["is_git_repo"] = False
        else:
            health_status["checks"]["is_git_repo"] = True

            # Check Git status
            try:
                result = subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    check=True,
                )

                if result.stdout.strip():
                    health_status["warnings"].append(
                        "Repository has uncommitted changes"
                    )
                    health_status["checks"]["clean_working_tree"] = False
                else:
                    health_status["checks"]["clean_working_tree"] = True

            except subprocess.CalledProcessError as e:
                health_status["warnings"].append(f"Could not check Git status: {e}")
                health_status["checks"]["clean_working_tree"] = None

        # Check 3: Language-specific files
        language = repo_config.language.lower()

        if language == "python":
            # Check for Python-specific files
            python_files = [
                ("requirements.txt", "Python dependencies file"),
                ("pyproject.toml", "Python project configuration"),
                ("setup.py", "Python setup script"),
            ]

            python_found = False
            for filename, _description in python_files:
                if (repo_path / filename).exists():
                    health_status["checks"][f"has_{filename.replace('.', '_')}"] = True
                    python_found = True
                else:
                    health_status["checks"][f"has_{filename.replace('.', '_')}"] = False

            if not python_found:
                health_status["warnings"].append(
                    "No Python dependency files found (requirements.txt, pyproject.toml, or setup.py)"
                )

            # Check for Python files
            python_file_count = len(list(repo_path.rglob("*.py")))
            health_status["checks"]["python_file_count"] = python_file_count

            if python_file_count == 0:
                health_status["warnings"].append("No Python files found in repository")

        elif language == "swift":
            # Check for Swift-specific files
            swift_files = [
                ("Package.swift", "Swift package file"),
                ("*.xcodeproj", "Xcode project"),
                ("*.xcworkspace", "Xcode workspace"),
            ]

            swift_found = False
            for pattern, _description in swift_files:
                if pattern.startswith("*"):
                    matches = list(repo_path.glob(pattern))
                    if matches:
                        health_status["checks"][
                            f"has_{pattern.replace('*', 'any').replace('.', '_')}"
                        ] = True
                        swift_found = True
                    else:
                        health_status["checks"][
                            f"has_{pattern.replace('*', 'any').replace('.', '_')}"
                        ] = False
                else:
                    if (repo_path / pattern).exists():
                        health_status["checks"][f"has_{pattern.replace('.', '_')}"] = (
                            True
                        )
                        swift_found = True
                    else:
                        health_status["checks"][f"has_{pattern.replace('.', '_')}"] = (
                            False
                        )

            if not swift_found:
                health_status["warnings"].append("No Swift project files found")

            # Check for Swift files
            swift_file_count = len(list(repo_path.rglob("*.swift")))
            health_status["checks"]["swift_file_count"] = swift_file_count

            if swift_file_count == 0:
                health_status["warnings"].append("No Swift files found in repository")

        # Check 4: README file
        readme_files = ["README.md", "README.rst", "README.txt", "README"]
        readme_found = False
        for readme in readme_files:
            if (repo_path / readme).exists():
                health_status["checks"]["has_readme"] = True
                readme_found = True
                break

        if not readme_found:
            health_status["checks"]["has_readme"] = False
            health_status["warnings"].append("No README file found")

        # Check 5: GitHub configuration
        try:
            # Validate GitHub access
            github_owner = repo_config.github_owner
            github_repo = repo_config.github_repo

            if github_owner and github_repo:
                health_status["checks"]["has_github_info"] = True
                health_status["checks"]["github_owner"] = github_owner
                health_status["checks"]["github_repo"] = github_repo
            else:
                health_status["checks"]["has_github_info"] = False
                health_status["warnings"].append(
                    "GitHub repository information not available"
                )

        except Exception as e:
            health_status["warnings"].append(
                f"Could not validate GitHub configuration: {e}"
            )
            health_status["checks"]["has_github_info"] = False

        # Determine overall status
        if health_status["errors"]:
            health_status["status"] = "unhealthy"
        elif health_status["warnings"]:
            health_status["status"] = "warning"
        else:
            health_status["status"] = "healthy"

        logger.info(
            f"Health check completed for {repo_name}: {health_status['status']}"
        )
        return json.dumps(health_status, indent=2)

    except Exception as e:
        logger.error(f"Health check failed for {repo_name}: {e}")
        return json.dumps(
            {"error": f"Health check failed: {e}", "repo": repo_name, "status": "error"}
        )
