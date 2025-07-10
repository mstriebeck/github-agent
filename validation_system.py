#!/usr/bin/env python3

"""
Validation System for Repository Workspaces

Provides a scalable plugin-based validation framework for validating
language-specific and service-specific prerequisites for repositories.
"""

import abc
from dataclasses import dataclass
from typing import Any, ClassVar

from constants import Language


@dataclass
class ValidationContext:
    """Context information for validation operations."""

    workspace: str
    language: Language
    services: list[str]
    repository_config: Any


class ValidationError(Exception):
    """Exception raised when validation fails."""

    def __init__(self, message: str, validator_type: str | None = None):
        self.validator_type = validator_type
        super().__init__(message)


class AbstractValidator(abc.ABC):
    """Abstract base class for validators."""

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
                    validator_type=f"language:{context.language.value}",
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
                        validator_type=f"service:{service}",
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
