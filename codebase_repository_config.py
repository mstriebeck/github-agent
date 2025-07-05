#!/usr/bin/env python3

"""
Repository Configuration Integration for MCP Codebase Server

Integrates with existing repositories.json configuration to identify Python repositories
for indexing and provides validation for repository paths and Python file existence.
"""

import glob
import logging
import os
from dataclasses import dataclass

from repository_manager import RepositoryManager


@dataclass
class CodebaseRepositoryConfig:
    """Configuration for a Python repository to be indexed by the codebase server."""

    name: str
    path: str
    description: str
    python_path: str | None

    def __post_init__(self):
        """Validate repository configuration after initialization."""
        if not self.name:
            raise ValueError("Repository name cannot be empty")
        if not self.path:
            raise ValueError("Repository path cannot be empty")

        # Normalize path
        self.path = os.path.abspath(os.path.expanduser(self.path))


class CodebaseRepositoryConfigManager:
    """Manages repository configuration for codebase indexing."""

    def __init__(self, repository_manager: RepositoryManager):
        """Initialize with existing repository manager.

        Args:
            repository_manager: Existing RepositoryManager instance
        """
        self.repository_manager = repository_manager
        self.logger = logging.getLogger(__name__)

    def get_python_repositories(self) -> list[CodebaseRepositoryConfig]:
        """Get list of Python repositories configured for indexing.

        Returns:
            List of CodebaseRepositoryConfig objects for Python repositories
        """
        python_repos = []

        for repo_name, repo_config in self.repository_manager.repositories.items():
            # Filter for Python repositories
            if repo_config.language == "python":
                self.logger.debug(f"Found Python repository: {repo_name}")

                try:
                    # Validate repository path and Python files
                    self._validate_python_repository(repo_config.path)

                    # Create codebase repository config
                    codebase_config = CodebaseRepositoryConfig(
                        name=repo_name,
                        path=repo_config.path,
                        description=repo_config.description,
                        python_path=repo_config.python_path,
                    )

                    python_repos.append(codebase_config)
                    self.logger.info(
                        f"✅ Added Python repository for indexing: {repo_name}"
                    )

                except Exception as e:
                    self.logger.warning(f"❌ Skipping repository {repo_name}: {e}")
                    continue

        self.logger.info(f"Found {len(python_repos)} Python repositories for indexing")
        return python_repos

    def _validate_python_repository(self, repo_path: str) -> None:
        """Validate that repository path exists and contains Python files.

        Args:
            repo_path: Path to the repository

        Raises:
            ValueError: If repository path is invalid or contains no Python files
        """
        # Check if path exists
        if not os.path.exists(repo_path):
            raise ValueError(f"Repository path does not exist: {repo_path}")

        # Check if it's a directory
        if not os.path.isdir(repo_path):
            raise ValueError(f"Repository path is not a directory: {repo_path}")

        # Check read permissions
        if not os.access(repo_path, os.R_OK):
            raise ValueError(f"No read access to repository: {repo_path}")

        # Check if repository contains Python files
        if not self._has_python_files(repo_path):
            raise ValueError(f"Repository contains no Python files: {repo_path}")

    def _has_python_files(self, repo_path: str) -> bool:
        """Check if repository contains Python files.

        Args:
            repo_path: Path to the repository

        Returns:
            True if repository contains Python files, False otherwise
        """
        try:
            # Look for Python files recursively
            python_patterns = [
                os.path.join(repo_path, "**", "*.py"),
                os.path.join(repo_path, "**", "*.pyi"),
            ]

            for pattern in python_patterns:
                if glob.glob(pattern, recursive=True):
                    return True

            return False

        except Exception as e:
            self.logger.debug(f"Error checking for Python files in {repo_path}: {e}")
            return False

    def get_repository_by_name(self, name: str) -> CodebaseRepositoryConfig | None:
        """Get Python repository configuration by name.

        Args:
            name: Repository name

        Returns:
            CodebaseRepositoryConfig if found and is Python repository, None otherwise
        """
        repo_config = self.repository_manager.get_repository(name)
        if not repo_config:
            return None

        if repo_config.language != "python":
            return None

        try:
            self._validate_python_repository(repo_config.path)
            return CodebaseRepositoryConfig(
                name=name,
                path=repo_config.path,
                description=repo_config.description,
                python_path=repo_config.python_path,
            )
        except Exception as e:
            self.logger.warning(f"Repository {name} validation failed: {e}")
            return None

    def validate_repository_configuration(self) -> bool:
        """Validate repository configuration for codebase indexing.

        Returns:
            True if at least one Python repository is configured, False otherwise
        """
        try:
            python_repos = self.get_python_repositories()

            if not python_repos:
                self.logger.warning("No Python repositories configured for indexing")
                return False

            self.logger.info(
                f"✅ Repository configuration validated: {len(python_repos)} Python repositories"
            )
            return True

        except Exception as e:
            self.logger.error(f"❌ Repository configuration validation failed: {e}")
            return False


def create_codebase_repository_config_manager(
    config_path: str | None = None,
) -> CodebaseRepositoryConfigManager:
    """Create a CodebaseRepositoryConfigManager instance.

    Args:
        config_path: Optional path to repositories.json file

    Returns:
        CodebaseRepositoryConfigManager instance
    """
    repository_manager = RepositoryManager(config_path)

    if not repository_manager.load_configuration():
        raise RuntimeError("Failed to load repository configuration")

    return CodebaseRepositoryConfigManager(repository_manager)
