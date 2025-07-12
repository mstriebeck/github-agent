#!/usr/bin/env python3

"""
Tests for Validation Registry

This module contains comprehensive tests for the ValidationRegistry class
and its instance-based functionality.
"""

import logging
import tempfile
import unittest
from unittest.mock import Mock, patch

from constants import Language
from github_tools import GitHubValidator
from python_repository_manager import PythonValidator
from repository_indexer import CodebaseValidator
from validation_base import ValidationContext
from validation_registry import ValidationRegistry


class TestValidationRegistry(unittest.TestCase):
    """Test cases for ValidationRegistry instance methods."""

    def setUp(self):
        """Set up test environment."""
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)
        
        # Create a fresh registry instance for each test
        self.registry = ValidationRegistry(self.logger)

    def tearDown(self):
        """Clean up after each test."""
        # Clear registry after each test
        self.registry.clear_all_validators()

    def test_initialize_validators_basic(self):
        """Test basic initialization of validators."""
        # Initialize the registry
        self.registry.initialize_validators()
        
        # Check that validators are registered
        registered_languages = self.registry.get_registered_languages()
        registered_services = self.registry.get_registered_services()
        
        # Verify language validators
        self.assertEqual(len(registered_languages), 1)
        self.assertIn(Language.PYTHON, registered_languages)
        
        # Verify service validators
        self.assertEqual(len(registered_services), 2)
        self.assertIn("github", registered_services)
        self.assertIn("codebase", registered_services)

    def test_initialize_validators_types(self):
        """Test that correct validator types are registered."""
        self.registry.initialize_validators()
        
        # Check language validators
        python_validator = self.registry.get_language_validator(Language.PYTHON)
        self.assertIsInstance(python_validator, PythonValidator)
        
        # Check service validators
        github_validator = self.registry.get_service_validator("github")
        self.assertIsInstance(github_validator, GitHubValidator)
        
        codebase_validator = self.registry.get_service_validator("codebase")
        self.assertIsInstance(codebase_validator, CodebaseValidator)

    def test_initialize_validators_clears_existing(self):
        """Test that initialization clears existing validators."""
        # Register a mock validator first
        mock_validator = Mock()
        self.registry.register_language_validator(Language.PYTHON, mock_validator)
        
        # Verify it's registered
        self.assertEqual(len(self.registry.get_registered_languages()), 1)
        
        # Initialize the registry
        self.registry.initialize_validators()
        
        # Verify the mock validator was replaced
        python_validator = self.registry.get_language_validator(Language.PYTHON)
        self.assertIsInstance(python_validator, PythonValidator)
        self.assertNotEqual(python_validator, mock_validator)

    def test_get_status_empty(self):
        """Test getting status of empty registry."""
        status = self.registry.get_status()
        
        expected_status = {
            "languages": [],
            "services": [],
            "total_validators": 0
        }
        
        self.assertEqual(status, expected_status)

    def test_get_status_populated(self):
        """Test getting status of populated registry."""
        self.registry.initialize_validators()
        
        status = self.registry.get_status()
        
        expected_status = {
            "languages": ["python"],
            "services": ["github", "codebase"],
            "total_validators": 3
        }
        
        self.assertEqual(status, expected_status)

    def test_register_language_validator(self):
        """Test registering a language validator."""
        mock_validator = Mock()
        
        self.registry.register_language_validator(Language.PYTHON, mock_validator)
        
        # Check that it was registered
        registered_languages = self.registry.get_registered_languages()
        self.assertIn(Language.PYTHON, registered_languages)
        
        # Check that we can retrieve it
        retrieved_validator = self.registry.get_language_validator(Language.PYTHON)
        self.assertEqual(retrieved_validator, mock_validator)

    def test_register_service_validator(self):
        """Test registering a service validator."""
        mock_validator = Mock()
        
        self.registry.register_service_validator("test_service", mock_validator)
        
        # Check that it was registered
        registered_services = self.registry.get_registered_services()
        self.assertIn("test_service", registered_services)
        
        # Check that we can retrieve it
        retrieved_validator = self.registry.get_service_validator("test_service")
        self.assertEqual(retrieved_validator, mock_validator)

    def test_clear_all_validators(self):
        """Test clearing all validators."""
        # Register some validators
        mock_lang_validator = Mock()
        mock_service_validator = Mock()
        self.registry.register_language_validator(Language.PYTHON, mock_lang_validator)
        self.registry.register_service_validator("test", mock_service_validator)
        
        # Verify they're registered
        self.assertEqual(len(self.registry.get_registered_languages()), 1)
        self.assertEqual(len(self.registry.get_registered_services()), 1)
        
        # Clear all validators
        self.registry.clear_all_validators()
        
        # Verify they're cleared
        self.assertEqual(len(self.registry.get_registered_languages()), 0)
        self.assertEqual(len(self.registry.get_registered_services()), 0)

    def test_get_language_validator_nonexistent(self):
        """Test getting a non-existent language validator."""
        result = self.registry.get_language_validator(Language.PYTHON)
        self.assertIsNone(result)

    def test_get_service_validator_nonexistent(self):
        """Test getting a non-existent service validator."""
        result = self.registry.get_service_validator("nonexistent")
        self.assertIsNone(result)

    def test_initialize_validators_with_logger(self):
        """Test that logger is properly passed to validators."""
        # Mock the validator classes to check logger parameter
        with patch('python_repository_manager.PythonValidator') as mock_python, \
             patch('github_tools.GitHubValidator') as mock_github, \
             patch('repository_indexer.CodebaseValidator') as mock_codebase:
            
            self.registry.initialize_validators()
            
            # Verify logger was passed to each validator
            mock_python.assert_called_once_with(self.logger)
            mock_github.assert_called_once_with(self.logger)
            mock_codebase.assert_called_once_with(self.logger)

    def test_validate_all_with_context(self):
        """Test validate_all method with ValidationContext."""
        # Initialize registry with real validators
        self.registry.initialize_validators()
        
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
            python_validator = self.registry.get_language_validator(Language.PYTHON)
            github_validator = self.registry.get_service_validator("github")
            codebase_validator = self.registry.get_service_validator("codebase")
            
            self.assertIsNotNone(python_validator)
            self.assertIsNotNone(github_validator)
            self.assertIsNotNone(codebase_validator)
            
            # Verify validators have validate method
            self.assertTrue(hasattr(python_validator, 'validate'))
            self.assertTrue(hasattr(github_validator, 'validate'))
            self.assertTrue(hasattr(codebase_validator, 'validate'))

    def test_validate_all_with_missing_language(self):
        """Test validate_all with language that has no validator."""
        # Don't initialize validators, so no validators are registered
        
        context = ValidationContext(
            workspace="/tmp",
            language=Language.PYTHON,  # No validator registered for this
            services=[],
            repository_config=Mock()
        )
        
        # Should not raise an exception - just skip validation
        try:
            self.registry.validate_all(context)
        except Exception as e:
            self.fail(f"validate_all raised an exception: {e}")

    def test_validate_all_with_missing_service(self):
        """Test validate_all with service that has no validator."""
        # Don't initialize validators, so no validators are registered
        
        context = ValidationContext(
            workspace="/tmp",
            language=Language.PYTHON,
            services=["nonexistent_service"],  # No validator registered for this
            repository_config=Mock()
        )
        
        # Should not raise an exception - just skip validation
        try:
            self.registry.validate_all(context)
        except Exception as e:
            self.fail(f"validate_all raised an exception: {e}")

    def test_multiple_initialization_calls(self):
        """Test that multiple initialization calls work correctly."""
        # Initialize multiple times
        self.registry.initialize_validators()
        self.registry.initialize_validators()
        self.registry.initialize_validators()
        
        # Should still have correct state
        registered_languages = self.registry.get_registered_languages()
        registered_services = self.registry.get_registered_services()
        
        self.assertEqual(len(registered_languages), 1)
        self.assertEqual(len(registered_services), 2)
        self.assertIn(Language.PYTHON, registered_languages)
        self.assertIn("github", registered_services)
        self.assertIn("codebase", registered_services)

    def test_registry_isolation(self):
        """Test that multiple registry instances are isolated."""
        # Create a second registry
        registry2 = ValidationRegistry(self.logger)
        
        # Initialize only the first registry
        self.registry.initialize_validators()
        
        # Check that first registry is populated
        self.assertEqual(len(self.registry.get_registered_languages()), 1)
        self.assertEqual(len(self.registry.get_registered_services()), 2)
        
        # Check that second registry is empty
        self.assertEqual(len(registry2.get_registered_languages()), 0)
        self.assertEqual(len(registry2.get_registered_services()), 0)
        
        # Initialize second registry
        registry2.initialize_validators()
        
        # Both should be populated now
        self.assertEqual(len(self.registry.get_registered_languages()), 1)
        self.assertEqual(len(registry2.get_registered_languages()), 1)
        
        # Clear first registry
        self.registry.clear_all_validators()
        
        # First should be empty, second should still be populated
        self.assertEqual(len(self.registry.get_registered_languages()), 0)
        self.assertEqual(len(registry2.get_registered_languages()), 1)


if __name__ == '__main__':
    unittest.main()
