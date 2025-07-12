#!/usr/bin/env python3

"""
Validation Base Classes

This module provides the base classes and types for the validation system.
Separated to avoid circular imports.
"""

import abc
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from constants import Language


class ValidatorType(Enum):
    """Enum for validator types to avoid brittle string comparisons."""

    PYTHON = "Python Language Validator"
    GITHUB = "GitHub Integration Validator"
    CODEBASE = "Codebase Index Validator"


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
    def validator_name(self) -> str:
        """Return a human-readable name for this validator."""
        return self.validator_type.value

    @property
    @abc.abstractmethod
    def validator_type(self) -> ValidatorType:
        """Return the validator type enum."""
        pass
