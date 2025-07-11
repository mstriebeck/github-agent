#!/usr/bin/env python3

"""
Validation System for Repository Workspaces

Provides a scalable plugin-based validation framework for validating
language-specific and service-specific prerequisites for repositories.
"""

import abc
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar

from constants import Language
from repository_manager import (
    MINIMUM_PYTHON_MAJOR,
    MINIMUM_PYTHON_MINOR,
    MINIMUM_PYTHON_VERSION,
)


class ValidatorType(Enum):
    """Enum for validator types to avoid brittle string comparisons."""

    PYTHON = "python"
    GITHUB = "github"
    CODEBASE = "codebase"


@dataclass
class ValidationContext:
    """Context information for validation operations."""

    workspace: str
    language: Language
    services: list[str]
    repository_config: Any


class ValidationError(Exception):
    """Exception raised when validation fails."""

    def __init__(self, message: str, validator_type: ValidatorType):
        self.validator_type = validator_type
        super().__init__(message)


class AbstractValidator(abc.ABC):
    """Abstract base class for validators."""
    
    def __init__(self, logger: logging.Logger):
        """Initialize validator with self.logger.
        
        Args:
            logger: Logger instance for debugging and monitoring
        """
        self.logger = logger

    @abc.abstractmethod
    def validate(self, context: ValidationContext) -> None:
        """
        Validate the given context.

        Args:
            context: ValidationContext containing workspace, language, services, and config

        Raises:
            ValidationError: If validation fails
        """
        pass

    @property
    @abc.abstractmethod
    def validator_name(self) -> str:
        """Return a human-readable name for this validator."""
        pass

    @property
    @abc.abstractmethod
    def validator_type(self) -> ValidatorType:
        """Return the validator type enum."""
        pass


class ValidationRegistry:
    """Registry for managing validators and performing validation."""

    _language_validators: ClassVar[dict[Language, AbstractValidator]] = {}
    _service_validators: ClassVar[dict[str, AbstractValidator]] = {}

    @classmethod
    def register_language_validator(
        cls, language: Language, validator: AbstractValidator
    ) -> None:
        """Register a validator for a specific language."""
        cls._language_validators[language] = validator

    @classmethod
    def register_service_validator(
        cls, service: str, validator: AbstractValidator
    ) -> None:
        """Register a validator for a specific service."""
        cls._service_validators[service] = validator

    @classmethod
    def get_language_validator(cls, language: Language) -> AbstractValidator | None:
        """Get the validator for a specific language."""
        return cls._language_validators.get(language)

    @classmethod
    def get_service_validator(cls, service: str) -> AbstractValidator | None:
        """Get the validator for a specific service."""
        return cls._service_validators.get(service)

    @classmethod
    def validate_all(cls, context: ValidationContext) -> None:
        """
        Validate all prerequisites for the given context.

        Args:
            context: ValidationContext containing workspace, language, services, and config

        Raises:
            ValidationError: If any validation fails
        """
        # Validate language prerequisites
        if context.language in cls._language_validators:
            validator = cls._language_validators[context.language]
            try:
                validator.validate(context)
            except ValidationError as e:
                # Re-raise with validator type information
                raise ValidationError(
                    f"Language validation failed for {context.language.value}: {e}",
                    validator_type=validator.validator_type,
                ) from e

        # Validate service prerequisites
        for service in context.services:
            if service in cls._service_validators:
                validator = cls._service_validators[service]
                try:
                    validator.validate(context)
                except ValidationError as e:
                    # Re-raise with validator type information
                    raise ValidationError(
                        f"Service validation failed for {service}: {e}",
                        validator_type=validator.validator_type,
                    ) from e

    @classmethod
    def clear_all_validators(cls) -> None:
        """Clear all registered validators. Primarily for testing."""
        cls._language_validators.clear()
        cls._service_validators.clear()

    @classmethod
    def get_registered_languages(cls) -> list[Language]:
        """Get list of languages with registered validators."""
        return list(cls._language_validators.keys())

    @classmethod
    def get_registered_services(cls) -> list[str]:
        """Get list of services with registered validators."""
        return list(cls._service_validators.keys())


class PythonValidator(AbstractValidator):
    """Validator for Python language prerequisites."""

    @property
    def validator_name(self) -> str:
        return "Python Language Validator"

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

        self.logger.debug(f"Running version check for Python executable: {normalized_path}")

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
            self.logger.error(f"❌ Python version check timed out for {normalized_path}")
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


class GitHubValidator(AbstractValidator):
    """Validator for GitHub service prerequisites."""

    @property
    def validator_name(self) -> str:
        return "GitHub Service Validator"

    @property
    def validator_type(self) -> ValidatorType:
        return ValidatorType.GITHUB

    def validate(self, context: ValidationContext) -> None:
        """
        Validate GitHub service prerequisites.

        Args:
            context: ValidationContext containing workspace, language, services, and config

        Raises:
            ValidationError: If GitHub token is not available or git repository is invalid
        """
        # Validate GitHub token
        try:
            self._validate_github_token()
        except Exception as e:
            raise ValidationError(
                f"GitHub token validation failed: {e}",
                validator_type=ValidatorType.GITHUB,
            ) from e

        # Validate git repository
        try:
            self._validate_git_repository(context.workspace)
        except Exception as e:
            raise ValidationError(
                f"Git repository validation failed: {e}",
                validator_type=ValidatorType.GITHUB,
            ) from e

    def _validate_github_token(self) -> str:
        """
        Validate GitHub token environment variable.

        Extracted from github_tools.py
        """
        github_token = os.getenv("GITHUB_TOKEN")
        if not github_token:
            raise RuntimeError("GITHUB_TOKEN environment variable not set")

        if not github_token.strip():
            raise RuntimeError("GITHUB_TOKEN environment variable is empty")

        self.logger.debug(f"GitHub token found (length: {len(github_token)})")
        return github_token

    def _validate_git_repository(self, workspace: str) -> None:
        """
        Validate that the workspace is a valid git repository.
        """
        if not os.path.exists(workspace):
            raise RuntimeError(f"Workspace directory does not exist: {workspace}")

        git_dir = os.path.join(workspace, ".git")
        if not os.path.exists(git_dir):
            raise RuntimeError(f"Workspace is not a git repository: {workspace}")

        # Check if git is functional in this directory
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"Git command failed in workspace {workspace}: {result.stderr}"
                )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"Git command timed out in workspace: {workspace}"
            ) from None
        except subprocess.SubprocessError as e:
            raise RuntimeError(
                f"Failed to run git command in workspace {workspace}: {e}"
            ) from e

        self.logger.debug(f"Git repository validation passed: {workspace}")


class CodebaseValidator(AbstractValidator):
    """Validator for codebase service prerequisites."""

    @property
    def validator_name(self) -> str:
        return "Codebase Service Validator"

    @property
    def validator_type(self) -> ValidatorType:
        return ValidatorType.CODEBASE

    def validate(self, context: ValidationContext) -> None:
        """
        Validate codebase service prerequisites.

        Args:
            context: ValidationContext containing workspace, language, services, and config

        Raises:
            ValidationError: If codebase prerequisites are not met
        """
        # Validate workspace accessibility
        try:
            self._validate_workspace_access(context.workspace)
        except Exception as e:
            raise ValidationError(
                f"Workspace access validation failed: {e}",
                validator_type=ValidatorType.CODEBASE,
            ) from e

        # Validate symbol storage service
        try:
            self._validate_symbol_storage()
        except Exception as e:
            raise ValidationError(
                f"Symbol storage validation failed: {e}",
                validator_type=ValidatorType.CODEBASE,
            ) from e

        # Validate language-specific LSP tools if applicable
        if context.language == Language.PYTHON:
            try:
                self._validate_python_lsp_tools()
            except Exception as e:
                raise ValidationError(
                    f"Python LSP tools validation failed: {e}",
                    validator_type=ValidatorType.CODEBASE,
                ) from e

    def _validate_workspace_access(self, workspace: str) -> None:
        """
        Validate that the workspace is accessible for reading/writing.
        """
        if not os.path.exists(workspace):
            raise RuntimeError(f"Workspace directory does not exist: {workspace}")

        if not os.path.isdir(workspace):
            raise RuntimeError(f"Workspace path is not a directory: {workspace}")

        if not os.access(workspace, os.R_OK):
            raise RuntimeError(f"Workspace directory is not readable: {workspace}")

        if not os.access(workspace, os.W_OK):
            raise RuntimeError(f"Workspace directory is not writable: {workspace}")

        self.logger.debug(f"Workspace access validation passed: {workspace}")

    def _validate_symbol_storage(self) -> None:
        """
        Validate that symbol storage service is available and configured.
        """
        try:
            # Check if symbol_storage module is available
            import importlib.util

            if importlib.util.find_spec("symbol_storage") is None:
                raise ImportError("symbol_storage module not found")

            # Test basic symbol storage functionality
            # This is a basic check - in production, you might want to test database connectivity
            if importlib.util.find_spec("symbol_storage") is None:
                raise ImportError("SQLiteSymbolStorage not found")

            self.logger.debug(
                "Symbol storage validation passed: SQLiteSymbolStorage available"
            )
        except ImportError as e:
            raise RuntimeError(
                f"Symbol storage not available: {e}. Required for codebase indexing."
            ) from e

    def _validate_python_lsp_tools(self) -> None:
        """
        Validate Python-specific LSP tools for codebase service.
        """
        # Validate pyright is available since that's the main LSP tool for Python
        try:
            result = subprocess.run(
                ["pyright", "--version"], capture_output=True, text=True, check=True
            )
            version = result.stdout.strip()
            self.logger.debug(f"Python LSP tools validation passed: pyright {version}")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            raise RuntimeError(
                "Python LSP tools not available. Please install with: npm install -g pyright"
            ) from e
