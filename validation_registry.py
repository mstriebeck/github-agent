#!/usr/bin/env python3

"""
Validation Registry

This module provides the ValidationRegistry class for managing validators
and performing validation operations in a dependency-injection friendly way.
"""

import logging
from typing import Any

from constants import Language
from validation_base import (
    AbstractValidator,
    ValidationContext,
    ValidationError,
)


class ValidationRegistry:
    """Registry for managing validators and performing validation."""

    def __init__(self, logger: logging.Logger):
        """Initialize the validation registry.

        Args:
            logger: Logger instance for debugging and monitoring
        """
        self.logger = logger
        self._language_validators: dict[Language, AbstractValidator] = {}
        self._service_validators: dict[str, AbstractValidator] = {}

    def register_language_validator(
        self, language: Language, validator: AbstractValidator
    ) -> None:
        """Register a validator for a specific language."""
        self._language_validators[language] = validator

    def register_service_validator(
        self, service: str, validator: AbstractValidator
    ) -> None:
        """Register a validator for a specific service."""
        self._service_validators[service] = validator

    def get_language_validator(self, language: Language) -> AbstractValidator | None:
        """Get the validator for a specific language."""
        return self._language_validators.get(language)

    def get_service_validator(self, service: str) -> AbstractValidator | None:
        """Get the validator for a specific service."""
        return self._service_validators.get(service)

    def validate_all(self, context: ValidationContext) -> None:
        """
        Validate all prerequisites for the given context.

        Args:
            context: ValidationContext containing workspace, language, services, and config

        Raises:
            ValidationError: If any validation fails
        """
        # Validate language prerequisites
        if context.language in self._language_validators:
            validator = self._language_validators[context.language]
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
            if service in self._service_validators:
                validator = self._service_validators[service]
                try:
                    validator.validate(context)
                except ValidationError as e:
                    # Re-raise with validator type information
                    raise ValidationError(
                        f"Service validation failed for {service}: {e}",
                        validator_type=validator.validator_type,
                    ) from e

    def clear_all_validators(self) -> None:
        """Clear all registered validators. Primarily for testing."""
        self._language_validators.clear()
        self._service_validators.clear()

    def get_registered_languages(self) -> list[Language]:
        """Get list of languages with registered validators."""
        return list(self._language_validators.keys())

    def get_registered_services(self) -> list[str]:
        """Get list of services with registered validators."""
        return list(self._service_validators.keys())

    def initialize_validators(self) -> None:
        """
        Initialize the validation registry with all available validators.

        This method registers all language and service validators that are available
        in the system.
        """
        # Import validator classes here to avoid circular imports
        from github_tools import GitHubValidator
        from python_repository_manager import PythonValidator
        from repository_indexer import CodebaseValidator

        self.logger.info("Initializing validation registry...")

        # Clear any existing validators (primarily for testing)
        self.clear_all_validators()

        # Register language validators
        python_validator = PythonValidator(self.logger)
        self.register_language_validator(Language.PYTHON, python_validator)
        self.logger.debug(
            f"Registered Python validator: {python_validator.validator_name}"
        )

        # Register service validators
        github_validator = GitHubValidator(self.logger)
        self.register_service_validator("github", github_validator)
        self.logger.debug(
            f"Registered GitHub validator: {github_validator.validator_name}"
        )

        codebase_validator = CodebaseValidator(self.logger)
        self.register_service_validator("codebase", codebase_validator)
        self.logger.debug(
            f"Registered Codebase validator: {codebase_validator.validator_name}"
        )

        # Log summary
        registered_languages = self.get_registered_languages()
        registered_services = self.get_registered_services()

        self.logger.info(
            f"Validation registry initialized with {len(registered_languages)} language validators and {len(registered_services)} service validators"
        )
        self.logger.info(
            f"Registered languages: {[lang.value for lang in registered_languages]}"
        )
        self.logger.info(f"Registered services: {registered_services}")

    def get_status(self) -> dict[str, Any]:
        """
        Get the current status of the validation registry.

        Returns:
            Dictionary containing the current state of the validation registry
        """
        registered_languages = self.get_registered_languages()
        registered_services = self.get_registered_services()

        return {
            "languages": [lang.value for lang in registered_languages],
            "services": registered_services,
            "total_validators": len(registered_languages) + len(registered_services),
        }
