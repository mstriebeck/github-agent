#!/usr/bin/env python3

"""
Validator Registry Initialization

This module provides functionality to register validators in the ValidationRegistry
during system initialization.
"""

import logging
from typing import Any

from constants import Language
from github_tools import GitHubValidator
from python_repository_manager import PythonValidator
from repository_indexer import CodebaseValidator
from validation_system import ValidationRegistry


def initialize_validation_registry(logger: logging.Logger) -> None:
    """
    Initialize the validation registry with all available validators.
    
    This function registers all language and service validators that are available
    in the system. It should be called during system initialization.
    
    Args:
        logger: Logger instance for debugging and monitoring
    """
    logger.info("Initializing validation registry...")
    
    # Clear any existing validators (primarily for testing)
    ValidationRegistry.clear_all_validators()
    
    # Register language validators
    python_validator = PythonValidator(logger)
    ValidationRegistry.register_language_validator(Language.PYTHON, python_validator)
    logger.debug(f"Registered Python validator: {python_validator.validator_name}")
    
    # Register service validators
    github_validator = GitHubValidator(logger)
    ValidationRegistry.register_service_validator("github", github_validator)
    logger.debug(f"Registered GitHub validator: {github_validator.validator_name}")
    
    codebase_validator = CodebaseValidator(logger)
    ValidationRegistry.register_service_validator("codebase", codebase_validator)
    logger.debug(f"Registered Codebase validator: {codebase_validator.validator_name}")
    
    # Log summary
    registered_languages = ValidationRegistry.get_registered_languages()
    registered_services = ValidationRegistry.get_registered_services()
    
    logger.info(f"Validation registry initialized with {len(registered_languages)} language validators and {len(registered_services)} service validators")
    logger.info(f"Registered languages: {[lang.value for lang in registered_languages]}")
    logger.info(f"Registered services: {registered_services}")


def get_validation_registry_status() -> dict[str, Any]:
    """
    Get the current status of the validation registry.
    
    Returns:
        Dictionary containing the current state of the validation registry
    """
    registered_languages = ValidationRegistry.get_registered_languages()
    registered_services = ValidationRegistry.get_registered_services()
    
    return {
        "languages": [lang.value for lang in registered_languages],
        "services": registered_services,
        "total_validators": len(registered_languages) + len(registered_services)
    }
