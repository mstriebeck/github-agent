#!/usr/bin/env python3

"""
Python Repository Manager for MCP Codebase Server

Manages Python repository configurations for codebase indexing by filtering and validating
Python repositories from the main repository configuration.
"""

import glob
import logging
import os
import re
import subprocess

from constants import Language
from repository_manager import (
    MINIMUM_PYTHON_MAJOR,
    MINIMUM_PYTHON_MINOR,
    MINIMUM_PYTHON_VERSION,
    RepositoryConfig,
    RepositoryManager,
)
from validation_system import (
    AbstractValidator,
    ValidationContext,
    ValidationError,
    ValidatorType,
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
                    self._validate_python_repository(repo_config.path)

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
            self._validate_python_repository(repo_config.path)
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


class PythonValidator(AbstractValidator):
    """Validator for Python language prerequisites."""

    @property
    def validator_type(self) -> ValidatorType:
        return ValidatorType.PYTHON

    def validate(self, context: ValidationContext) -> None:
        """
        Validate Python prerequisites.

        Args:
            context: ValidationContext containing workspace, language, services, and config

        Raises:
            ValidationError: If Python path is invalid or pyright is not available
        """
        # Validate Python executable path
        python_path = getattr(context.repository_config, "python_path", None)
        if not python_path:
            raise ValidationError(
                "Python path not configured in repository config",
                validator_type=ValidatorType.PYTHON,
            )

        try:
            validated_path = self._validate_python_path(python_path)
            self.logger.debug(f"Python path validation passed: {validated_path}")
        except Exception as e:
            raise ValidationError(
                f"Python path validation failed: {e}",
                validator_type=ValidatorType.PYTHON,
            ) from e

        # Validate pyright availability
        try:
            version = self._check_pyright_availability()
            self.logger.debug(f"Pyright availability check passed: {version}")
        except Exception as e:
            raise ValidationError(
                f"Pyright availability check failed: {e}",
                validator_type=ValidatorType.PYTHON,
            ) from e

    def _validate_python_path(self, python_path: str) -> str:
        """
        Validate python_path parameter with comprehensive logging.

        Extracted from repository_manager.py
        """
        self.logger.debug(f"Validating Python executable: {python_path}")

        if not isinstance(python_path, str):
            raise ValueError(
                f"python_path must be a string, got {type(python_path).__name__}"
            )

        if not python_path.strip():
            raise ValueError("python_path cannot be empty or whitespace")

        # Expand user home if needed and normalize
        normalized_path = os.path.abspath(os.path.expanduser(python_path.strip()))
        self.logger.debug(f"Normalized Python path: {normalized_path}")

        # Check if path exists
        if not os.path.exists(normalized_path):
            self.logger.error(f"❌ Python executable does not exist: {normalized_path}")
            raise ValueError(f"Python executable does not exist: {normalized_path}")

        # Check if it's executable
        if not os.access(normalized_path, os.X_OK):
            self.logger.error(f"❌ Python path is not executable: {normalized_path}")
            raise ValueError(f"Python path is not executable: {normalized_path}")

        self.logger.debug(
            f"Running version check for Python executable: {normalized_path}"
        )

        # Verify it's actually a Python executable by running --version
        try:
            result = subprocess.run(
                [normalized_path, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                self.logger.error(
                    f"❌ Python version check failed for {normalized_path}: return code {result.returncode}"
                )
                raise ValueError(
                    f"Python executable failed version check: {normalized_path}"
                )

            # Check if output contains "Python"
            version_output = result.stdout.strip() or result.stderr.strip()
            self.logger.debug(f"Python version output: {version_output}")

            if not version_output.startswith("Python"):
                self.logger.error(
                    f"❌ Executable does not appear to be Python: {normalized_path}, output: {version_output}"
                )
                raise ValueError(
                    f"Executable does not appear to be Python (version output: {version_output}): {normalized_path}"
                )

            # Parse and validate Python version
            version_match = re.search(r"Python (\d+)\.(\d+)\.(\d+)", version_output)
            if not version_match:
                self.logger.error(
                    f"❌ Could not parse Python version from output: {version_output}"
                )
                raise ValueError(
                    f"Could not parse Python version from: {version_output}"
                )

            major, minor, patch = map(int, version_match.groups())
            self.logger.debug(f"Detected Python version: {major}.{minor}.{patch}")

            if major < MINIMUM_PYTHON_MAJOR or (
                major == MINIMUM_PYTHON_MAJOR and minor < MINIMUM_PYTHON_MINOR
            ):
                self.logger.error(
                    f"❌ Python version {major}.{minor}.{patch} is below minimum required "
                    f"{MINIMUM_PYTHON_VERSION} for {normalized_path}"
                )
                raise ValueError(
                    f"Python version {major}.{minor}.{patch} is below minimum required "
                    f"{MINIMUM_PYTHON_VERSION}: {normalized_path}"
                )

            self.logger.info(
                f"✅ Python executable validated: {normalized_path} (version {major}.{minor}.{patch})"
            )

        except subprocess.TimeoutExpired:
            self.logger.error(
                f"❌ Python version check timed out for {normalized_path}"
            )
            raise ValueError(
                f"Python executable timed out during version check: {normalized_path}"
            ) from None
        except subprocess.SubprocessError as e:
            self.logger.error(
                f"❌ Failed to run Python version check for {normalized_path}: {e}"
            )
            raise ValueError(f"Failed to verify Python executable: {e}") from e

        return normalized_path

    def _check_pyright_availability(self) -> str:
        """
        Check if pyright is available in the system and return version.

        Extracted from pyright_lsp_manager.py
        """
        try:
            result = subprocess.run(
                ["pyright", "--version"], capture_output=True, text=True, check=True
            )
            version = result.stdout.strip()
            self.logger.info(f"Pyright version: {version}")
            return version
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            raise RuntimeError(
                "Pyright is not available. Please install it with: npm install -g pyright"
            ) from e
