#!/usr/bin/env python3

"""
Tests for the validation system.
"""

from unittest.mock import Mock

import pytest

from constants import Language
from validation_system import (
    AbstractValidator,
    ValidationContext,
    ValidationError,
    ValidationRegistry,
)


class MockValidator(AbstractValidator):
    """Mock validator for testing."""

    def __init__(
        self,
        name: str,
        should_fail: bool = False,
        error_message: str = "Validation failed",
    ):
        self._name = name
        self._should_fail = should_fail
        self._error_message = error_message
        self.validate_called = False
        self.last_context = None

    def validate(self, context: ValidationContext) -> None:
        self.validate_called = True
        self.last_context = context
        if self._should_fail:
            raise ValidationError(self._error_message)

    @property
    def validator_name(self) -> str:
        return self._name


class TestValidationContext:
    """Tests for ValidationContext dataclass."""

    def test_validation_context_creation(self):
        """Test creating a ValidationContext."""
        config = Mock()
        context = ValidationContext(
            workspace="/path/to/workspace",
            language=Language.PYTHON,
            services=["github", "codebase"],
            repository_config=config,
        )

        assert context.workspace == "/path/to/workspace"
        assert context.language == Language.PYTHON
        assert context.services == ["github", "codebase"]
        assert context.repository_config is config


class TestValidationError:
    """Tests for ValidationError exception."""

    def test_validation_error_basic(self):
        """Test basic ValidationError creation."""
        error = ValidationError("Test error")
        assert str(error) == "Test error"
        assert error.validator_type is None

    def test_validation_error_with_validator_type(self):
        """Test ValidationError with validator type."""
        error = ValidationError("Test error", "language:python")
        assert str(error) == "Test error"
        assert error.validator_type == "language:python"


class TestAbstractValidator:
    """Tests for AbstractValidator base class."""

    def test_abstract_validator_cannot_be_instantiated(self):
        """Test that AbstractValidator cannot be instantiated directly."""
        with pytest.raises(TypeError):
            AbstractValidator()


class TestValidationRegistry:
    """Tests for ValidationRegistry."""

    def setup_method(self):
        """Clear registry before each test."""
        ValidationRegistry.clear_all_validators()

    def teardown_method(self):
        """Clear registry after each test."""
        ValidationRegistry.clear_all_validators()

    def test_register_language_validator(self):
        """Test registering a language validator."""
        validator = MockValidator("python")
        ValidationRegistry.register_language_validator(Language.PYTHON, validator)

        registered = ValidationRegistry.get_language_validator(Language.PYTHON)
        assert registered is validator

    def test_register_service_validator(self):
        """Test registering a service validator."""
        validator = MockValidator("github")
        ValidationRegistry.register_service_validator("github", validator)

        registered = ValidationRegistry.get_service_validator("github")
        assert registered is validator

    def test_get_nonexistent_language_validator(self):
        """Test getting a validator for unregistered language."""
        validator = ValidationRegistry.get_language_validator(Language.SWIFT)
        assert validator is None

    def test_get_nonexistent_service_validator(self):
        """Test getting a validator for unregistered service."""
        validator = ValidationRegistry.get_service_validator("nonexistent")
        assert validator is None

    def test_validate_all_with_language_validator(self):
        """Test validate_all with a language validator."""
        validator = MockValidator("python")
        ValidationRegistry.register_language_validator(Language.PYTHON, validator)

        context = ValidationContext(
            workspace="/test",
            language=Language.PYTHON,
            services=[],
            repository_config=Mock(),
        )

        ValidationRegistry.validate_all(context)

        assert validator.validate_called
        assert validator.last_context is context

    def test_validate_all_with_service_validator(self):
        """Test validate_all with a service validator."""
        validator = MockValidator("github")
        ValidationRegistry.register_service_validator("github", validator)

        context = ValidationContext(
            workspace="/test",
            language=Language.PYTHON,
            services=["github"],
            repository_config=Mock(),
        )

        ValidationRegistry.validate_all(context)

        assert validator.validate_called
        assert validator.last_context is context

    def test_validate_all_with_multiple_services(self):
        """Test validate_all with multiple service validators."""
        github_validator = MockValidator("github")
        codebase_validator = MockValidator("codebase")

        ValidationRegistry.register_service_validator("github", github_validator)
        ValidationRegistry.register_service_validator("codebase", codebase_validator)

        context = ValidationContext(
            workspace="/test",
            language=Language.PYTHON,
            services=["github", "codebase"],
            repository_config=Mock(),
        )

        ValidationRegistry.validate_all(context)

        assert github_validator.validate_called
        assert codebase_validator.validate_called
        assert github_validator.last_context is context
        assert codebase_validator.last_context is context

    def test_validate_all_with_language_and_service_validators(self):
        """Test validate_all with both language and service validators."""
        language_validator = MockValidator("python")
        service_validator = MockValidator("github")

        ValidationRegistry.register_language_validator(
            Language.PYTHON, language_validator
        )
        ValidationRegistry.register_service_validator("github", service_validator)

        context = ValidationContext(
            workspace="/test",
            language=Language.PYTHON,
            services=["github"],
            repository_config=Mock(),
        )

        ValidationRegistry.validate_all(context)

        assert language_validator.validate_called
        assert service_validator.validate_called

    def test_validate_all_with_no_validators(self):
        """Test validate_all with no registered validators."""
        context = ValidationContext(
            workspace="/test",
            language=Language.PYTHON,
            services=["github"],
            repository_config=Mock(),
        )

        # Should not raise any errors
        ValidationRegistry.validate_all(context)

    def test_validate_all_with_failing_language_validator(self):
        """Test validate_all with failing language validator."""
        validator = MockValidator(
            "python", should_fail=True, error_message="Python validation failed"
        )
        ValidationRegistry.register_language_validator(Language.PYTHON, validator)

        context = ValidationContext(
            workspace="/test",
            language=Language.PYTHON,
            services=[],
            repository_config=Mock(),
        )

        with pytest.raises(ValidationError) as exc_info:
            ValidationRegistry.validate_all(context)

        assert "Language validation failed for python" in str(exc_info.value)
        assert "Python validation failed" in str(exc_info.value)
        assert exc_info.value.validator_type == "language:python"

    def test_validate_all_with_failing_service_validator(self):
        """Test validate_all with failing service validator."""
        validator = MockValidator(
            "github", should_fail=True, error_message="GitHub validation failed"
        )
        ValidationRegistry.register_service_validator("github", validator)

        context = ValidationContext(
            workspace="/test",
            language=Language.PYTHON,
            services=["github"],
            repository_config=Mock(),
        )

        with pytest.raises(ValidationError) as exc_info:
            ValidationRegistry.validate_all(context)

        assert "Service validation failed for github" in str(exc_info.value)
        assert "GitHub validation failed" in str(exc_info.value)
        assert exc_info.value.validator_type == "service:github"

    def test_validate_all_stops_on_first_failure(self):
        """Test that validate_all stops on first validation failure."""
        failing_validator = MockValidator("python", should_fail=True)
        success_validator = MockValidator("github")

        ValidationRegistry.register_language_validator(
            Language.PYTHON, failing_validator
        )
        ValidationRegistry.register_service_validator("github", success_validator)

        context = ValidationContext(
            workspace="/test",
            language=Language.PYTHON,
            services=["github"],
            repository_config=Mock(),
        )

        with pytest.raises(ValidationError):
            ValidationRegistry.validate_all(context)

        assert failing_validator.validate_called
        # Service validator should not be called since language validation failed first
        assert not success_validator.validate_called

    def test_clear_all_validators(self):
        """Test clearing all validators."""
        language_validator = MockValidator("python")
        service_validator = MockValidator("github")

        ValidationRegistry.register_language_validator(
            Language.PYTHON, language_validator
        )
        ValidationRegistry.register_service_validator("github", service_validator)

        # Verify validators are registered
        assert (
            ValidationRegistry.get_language_validator(Language.PYTHON)
            is language_validator
        )
        assert ValidationRegistry.get_service_validator("github") is service_validator

        # Clear all validators
        ValidationRegistry.clear_all_validators()

        # Verify validators are cleared
        assert ValidationRegistry.get_language_validator(Language.PYTHON) is None
        assert ValidationRegistry.get_service_validator("github") is None

    def test_get_registered_languages(self):
        """Test getting list of registered languages."""
        python_validator = MockValidator("python")
        swift_validator = MockValidator("swift")

        ValidationRegistry.register_language_validator(
            Language.PYTHON, python_validator
        )
        ValidationRegistry.register_language_validator(Language.SWIFT, swift_validator)

        languages = ValidationRegistry.get_registered_languages()
        assert set(languages) == {Language.PYTHON, Language.SWIFT}

    def test_get_registered_services(self):
        """Test getting list of registered services."""
        github_validator = MockValidator("github")
        codebase_validator = MockValidator("codebase")

        ValidationRegistry.register_service_validator("github", github_validator)
        ValidationRegistry.register_service_validator("codebase", codebase_validator)

        services = ValidationRegistry.get_registered_services()
        assert set(services) == {"github", "codebase"}

    def test_get_registered_languages_empty(self):
        """Test getting registered languages when none are registered."""
        languages = ValidationRegistry.get_registered_languages()
        assert languages == []

    def test_get_registered_services_empty(self):
        """Test getting registered services when none are registered."""
        services = ValidationRegistry.get_registered_services()
        assert services == []


class TestValidationRegistryIntegration:
    """Integration tests for ValidationRegistry with realistic scenarios."""

    def setup_method(self):
        """Clear registry before each test."""
        ValidationRegistry.clear_all_validators()

    def teardown_method(self):
        """Clear registry after each test."""
        ValidationRegistry.clear_all_validators()

    def test_python_codebase_workflow(self):
        """Test a realistic Python + Codebase validation workflow."""
        # Register validators
        python_validator = MockValidator("python")
        codebase_validator = MockValidator("codebase")

        ValidationRegistry.register_language_validator(
            Language.PYTHON, python_validator
        )
        ValidationRegistry.register_service_validator("codebase", codebase_validator)

        # Create context
        mock_config = Mock()
        context = ValidationContext(
            workspace="/home/user/project",
            language=Language.PYTHON,
            services=["codebase"],
            repository_config=mock_config,
        )

        # Validate
        ValidationRegistry.validate_all(context)

        # Verify both validators were called
        assert python_validator.validate_called
        assert codebase_validator.validate_called
        assert python_validator.last_context.workspace == "/home/user/project"
        assert codebase_validator.last_context.workspace == "/home/user/project"

    def test_swift_github_workflow(self):
        """Test a realistic Swift + GitHub validation workflow."""
        # Register validators
        swift_validator = MockValidator("swift")
        github_validator = MockValidator("github")

        ValidationRegistry.register_language_validator(Language.SWIFT, swift_validator)
        ValidationRegistry.register_service_validator("github", github_validator)

        # Create context
        mock_config = Mock()
        context = ValidationContext(
            workspace="/home/user/swift-project",
            language=Language.SWIFT,
            services=["github"],
            repository_config=mock_config,
        )

        # Validate
        ValidationRegistry.validate_all(context)

        # Verify both validators were called
        assert swift_validator.validate_called
        assert github_validator.validate_called

    def test_multiple_services_workflow(self):
        """Test validation with multiple services."""
        # Register validators
        python_validator = MockValidator("python")
        github_validator = MockValidator("github")
        codebase_validator = MockValidator("codebase")
        jira_validator = MockValidator("jira")

        ValidationRegistry.register_language_validator(
            Language.PYTHON, python_validator
        )
        ValidationRegistry.register_service_validator("github", github_validator)
        ValidationRegistry.register_service_validator("codebase", codebase_validator)
        ValidationRegistry.register_service_validator("jira", jira_validator)

        # Create context with multiple services
        mock_config = Mock()
        context = ValidationContext(
            workspace="/home/user/project",
            language=Language.PYTHON,
            services=["github", "codebase", "jira"],
            repository_config=mock_config,
        )

        # Validate
        ValidationRegistry.validate_all(context)

        # Verify all validators were called
        assert python_validator.validate_called
        assert github_validator.validate_called
        assert codebase_validator.validate_called
        assert jira_validator.validate_called
