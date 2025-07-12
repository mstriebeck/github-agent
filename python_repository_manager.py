#!/usr/bin/env python3

"""
Python Repository Manager for MCP Codebase Server

Manages Python repository configurations for codebase indexing by filtering and validating
Python repositories from the main repository configuration.
"""

import glob
import logging
import os

from constants import Language
from repository_manager import (
    RepositoryConfig,
    RepositoryManager,
)

# Dedicated Python repository manager using composition with RepositoryManager


class PythonRepositoryManager:
    """Manages Python repository configurations for codebase indexing."""

    def __init__(self, repository_manager: RepositoryManager):
        """Initialize with existing repository manager.

        Args:
            repository_manager: Existing RepositoryManager instance
        """
        self.repository_manager = repository_manager
        self.logger = logging.getLogger(__name__)

    def get_python_repositories(self) -> list[RepositoryConfig]:
        """Get list of Python repositories configured for indexing.

        Returns:
            List of RepositoryConfig objects for Python repositories
        """
        python_repos = []

        for repo_name, repo_config in self.repository_manager.repositories.items():
            # Filter for Python repositories (language is already a Language enum)
            if repo_config.language == Language.PYTHON:
                self.logger.debug(f"Found Python repository: {repo_name}")

                try:
                    # Validate repository path and Python files
                    self._validate_python_repository(repo_config.workspace)

                    # Use the RepositoryConfig directly (already validated and configured)
                    python_repos.append(repo_config)
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
        # Note: Path existence, directory check, and read permissions are already validated by RepositoryManager

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

    def get_repository_by_name(self, name: str) -> RepositoryConfig | None:
        """Get Python repository configuration by name.

        Args:
            name: Repository name

        Returns:
            RepositoryConfig if found and is Python repository, None otherwise
        """
        repo_config = self.repository_manager.get_repository(name)
        if not repo_config:
            return None

        # Check if it's a Python repository (language is already a Language enum)
        if repo_config.language != Language.PYTHON:
            return None

        try:
            self._validate_python_repository(repo_config.workspace)
            return repo_config
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


def create_python_repository_manager(
    config_path: str | None = None,
) -> PythonRepositoryManager:
    """Create a PythonRepositoryManager instance.

    Args:
        config_path: Optional path to repositories.json file

    Returns:
        PythonRepositoryManager instance
    """
    repository_manager = RepositoryManager(config_path)

    if not repository_manager.load_configuration():
        raise RuntimeError("Failed to load repository configuration")

    return PythonRepositoryManager(repository_manager)
