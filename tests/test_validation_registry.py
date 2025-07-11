#!/usr/bin/env python3

"""
Tests for Validation Registry Initialization

This module contains comprehensive tests for the validation registry initialization
functionality.
"""

import logging
import tempfile
import unittest
from unittest.mock import Mock, patch

from constants import Language
from github_tools import GitHubValidator
from python_repository_manager import PythonValidator
from repository_indexer import CodebaseValidator
from validation_registry import get_validation_registry_status, initialize_validation_registry
from validation_system import ValidationContext, ValidationRegistry


class TestValidationRegistry(unittest.TestCase):
    """Test cases for validation registry initialization."""

    def setUp(self):
        """Set up test environment."""
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)
        
        # Clear registry before each test
        ValidationRegistry.clear_all_validators()

    def tearDown(self):
        """Clean up after each test."""
        # Clear registry after each test
        ValidationRegistry.clear_all_validators()

    def test_initialize_validation_registry_basic(self):
        """Test basic initialization of validation registry."""
        # Initialize the registry
        initialize_validation_registry(self.logger)
        
        # Check that validators are registered
        registered_languages = ValidationRegistry.get_registered_languages()
        registered_services = ValidationRegistry.get_registered_services()
        
        # Verify language validators
        self.assertEqual(len(registered_languages), 1)
        self.assertIn(Language.PYTHON, registered_languages)
        
        # Verify service validators
        self.assertEqual(len(registered_services), 2)
        self.assertIn("github", registered_services)
        self.assertIn("codebase", registered_services)

    def test_initialize_validation_registry_validator_types(self):
        """Test that correct validator types are registered."""
        initialize_validation_registry(self.logger)
        
        # Check language validators
        python_validator = ValidationRegistry.get_language_validator(Language.PYTHON)
        self.assertIsInstance(python_validator, PythonValidator)
        
        # Check service validators
        github_validator = ValidationRegistry.get_service_validator("github")
        self.assertIsInstance(github_validator, GitHubValidator)
        
        codebase_validator = ValidationRegistry.get_service_validator("codebase")
        self.assertIsInstance(codebase_validator, CodebaseValidator)

    def test_initialize_validation_registry_clears_existing(self):
        """Test that initialization clears existing validators."""
        # Register a mock validator first
        mock_validator = Mock()
        ValidationRegistry.register_language_validator(Language.PYTHON, mock_validator)
        
        # Verify it's registered
        self.assertEqual(len(ValidationRegistry.get_registered_languages()), 1)
        
        # Initialize the registry
        initialize_validation_registry(self.logger)
        
        # Verify the mock validator was replaced
        python_validator = ValidationRegistry.get_language_validator(Language.PYTHON)
        self.assertIsInstance(python_validator, PythonValidator)
        self.assertNotEqual(python_validator, mock_validator)

    def test_get_validation_registry_status_empty(self):
        """Test getting status of empty registry."""
        status = get_validation_registry_status()
        
        expected_status = {
            "languages": [],
            "services": [],
            "total_validators": 0
        }
        
        self.assertEqual(status, expected_status)

    def test_get_validation_registry_status_populated(self):
        """Test getting status of populated registry."""
        initialize_validation_registry(self.logger)
        
        status = get_validation_registry_status()
        
        expected_status = {
            "languages": ["python"],
            "services": ["github", "codebase"],
            "total_validators": 3
        }
        
        self.assertEqual(status, expected_status)

    def test_initialize_validation_registry_with_logger(self):
        """Test that logger is properly passed to validators."""
        # Mock the validator classes to check logger parameter
        with patch('validation_registry.PythonValidator') as mock_python, \
             patch('validation_registry.GitHubValidator') as mock_github, \
             patch('validation_registry.CodebaseValidator') as mock_codebase:
            
            initialize_validation_registry(self.logger)
            
            # Verify logger was passed to each validator
            mock_python.assert_called_once_with(self.logger)
            mock_github.assert_called_once_with(self.logger)
            mock_codebase.assert_called_once_with(self.logger)

    def test_validation_registry_integration_with_context(self):
        """Test integration with ValidationContext."""
        # Initialize registry
        initialize_validation_registry(self.logger)
        
        # Create a temporary directory for testing
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create validation context
            context = ValidationContext(
                workspace=temp_dir,
                language=Language.PYTHON,
                services=["github", "codebase"],
                repository_config=Mock()
            )
            
            # Mock the repository config to avoid actual validation
            context.repository_config.python_path = "/usr/bin/python3"
            
            # This should not raise an exception if validators are properly registered
            # Note: We can't test actual validation without valid environment setup
            # but we can verify the validators are callable
            python_validator = ValidationRegistry.get_language_validator(Language.PYTHON)
            github_validator = ValidationRegistry.get_service_validator("github")
            codebase_validator = ValidationRegistry.get_service_validator("codebase")
            
            self.assertIsNotNone(python_validator)
            self.assertIsNotNone(github_validator)
            self.assertIsNotNone(codebase_validator)
            
            # Verify validators have validate method
            self.assertTrue(hasattr(python_validator, 'validate'))
            self.assertTrue(hasattr(github_validator, 'validate'))
            self.assertTrue(hasattr(codebase_validator, 'validate'))

    def test_registry_state_after_initialization(self):
        """Test that registry state is correct after initialization."""
        # Start with empty registry
        self.assertEqual(len(ValidationRegistry.get_registered_languages()), 0)
        self.assertEqual(len(ValidationRegistry.get_registered_services()), 0)
        
        # Initialize registry
        initialize_validation_registry(self.logger)
        
        # Verify final state
        registered_languages = ValidationRegistry.get_registered_languages()
        registered_services = ValidationRegistry.get_registered_services()
        
        self.assertEqual(len(registered_languages), 1)
        self.assertEqual(len(registered_services), 2)
        
        # Verify specific registrations
        self.assertIn(Language.PYTHON, registered_languages)
        self.assertIn("github", registered_services)
        self.assertIn("codebase", registered_services)

    def test_multiple_initialization_calls(self):
        """Test that multiple initialization calls work correctly."""
        # Initialize multiple times
        initialize_validation_registry(self.logger)
        initialize_validation_registry(self.logger)
        initialize_validation_registry(self.logger)
        
        # Should still have correct state
        registered_languages = ValidationRegistry.get_registered_languages()
        registered_services = ValidationRegistry.get_registered_services()
        
        self.assertEqual(len(registered_languages), 1)
        self.assertEqual(len(registered_services), 2)
        self.assertIn(Language.PYTHON, registered_languages)
        self.assertIn("github", registered_services)
        self.assertIn("codebase", registered_services)


if __name__ == '__main__':
    unittest.main()
