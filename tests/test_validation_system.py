#!/usr/bin/env python3

"""
Tests for the validation system and validators.
"""

import os
from unittest.mock import Mock, patch

import pytest

from constants import Language
from validation_system import (
    AbstractValidator,
    CodebaseValidator,
    GitHubValidator,
    PythonValidator,
    ValidationContext,
    ValidationError,
    ValidationRegistry,
    ValidatorType,
)


@pytest.fixture
def clean_registry():
    """Fixture to ensure ValidationRegistry is clean before and after each test."""
    ValidationRegistry.clear_all_validators()
    yield
    ValidationRegistry.clear_all_validators()


class TestValidationContext:
    """Test ValidationContext dataclass."""

    def test_validation_context_creation(self):
        """Test creating ValidationContext with all required fields."""
        mock_config = Mock()
        context = ValidationContext(
            workspace="/test/workspace",
            language=Language.PYTHON,
            services=["github", "codebase"],
            repository_config=mock_config,
        )

        assert context.workspace == "/test/workspace"
        assert context.language == Language.PYTHON
        assert context.services == ["github", "codebase"]
        assert context.repository_config is mock_config


class TestValidationError:
    """Test ValidationError exception."""

    def test_validation_error_creation(self):
        """Test creating ValidationError with message and validator type."""
        error = ValidationError("Test error", ValidatorType.PYTHON)
        assert str(error) == "Test error"
        assert error.validator_type == ValidatorType.PYTHON


class TestAbstractValidator:
    """Test AbstractValidator base class."""

    def test_abstract_validator_cannot_be_instantiated(self):
        """Test that AbstractValidator cannot be instantiated directly."""
        with pytest.raises(TypeError):
            AbstractValidator()  # type: ignore[abstract]

    def test_concrete_validator_must_implement_methods(self):
        """Test that concrete validators must implement required methods."""

        class IncompleteValidator(AbstractValidator):
            pass

        with pytest.raises(TypeError):
            IncompleteValidator()  # type: ignore[abstract]


class TestValidationRegistry:
    """Test ValidationRegistry class."""

    def test_register_language_validator(self, clean_registry):
        """Test registering a language validator."""
        mock_validator = Mock(spec=AbstractValidator)
        ValidationRegistry.register_language_validator(Language.PYTHON, mock_validator)

        assert (
            ValidationRegistry.get_language_validator(Language.PYTHON) is mock_validator
        )
        assert Language.PYTHON in ValidationRegistry.get_registered_languages()

    def test_register_service_validator(self, clean_registry):
        """Test registering a service validator."""
        mock_validator = Mock(spec=AbstractValidator)
        ValidationRegistry.register_service_validator("github", mock_validator)

        assert ValidationRegistry.get_service_validator("github") is mock_validator
        assert "github" in ValidationRegistry.get_registered_services()

    def test_validate_all_with_language_validator(self, clean_registry):
        """Test validate_all with language validator."""
        mock_validator = Mock(spec=AbstractValidator)
        mock_config = Mock()
        ValidationRegistry.register_language_validator(Language.PYTHON, mock_validator)

        context = ValidationContext(
            workspace="/test/workspace",
            language=Language.PYTHON,
            services=[],
            repository_config=mock_config,
        )

        ValidationRegistry.validate_all(context)
        mock_validator.validate.assert_called_once()
        args, kwargs = mock_validator.validate.call_args
        assert args[0] == context
        assert len(args) == 2  # context and logger

    def test_validate_all_with_service_validator(self, clean_registry):
        """Test validate_all with service validator."""
        mock_validator = Mock(spec=AbstractValidator)
        mock_config = Mock()
        ValidationRegistry.register_service_validator("github", mock_validator)

        context = ValidationContext(
            workspace="/test/workspace",
            language=Language.PYTHON,
            services=["github"],
            repository_config=mock_config,
        )

        ValidationRegistry.validate_all(context)
        mock_validator.validate.assert_called_once()
        args, kwargs = mock_validator.validate.call_args
        assert args[0] == context
        assert len(args) == 2  # context and logger

    def test_validate_all_with_validation_error(self, clean_registry):
        """Test validate_all handles ValidationError correctly."""
        mock_validator = Mock(spec=AbstractValidator)
        mock_validator.validate.side_effect = ValidationError(
            "Test error", ValidatorType.PYTHON
        )
        mock_validator.validator_type = ValidatorType.PYTHON
        mock_config = Mock()
        ValidationRegistry.register_language_validator(Language.PYTHON, mock_validator)

        context = ValidationContext(
            workspace="/test/workspace",
            language=Language.PYTHON,
            services=[],
            repository_config=mock_config,
        )

        with pytest.raises(ValidationError) as exc_info:
            ValidationRegistry.validate_all(context)

        assert "Language validation failed for python" in str(exc_info.value)
        assert exc_info.value.validator_type == ValidatorType.PYTHON

    def test_clear_all_validators(self, clean_registry):
        """Test clearing all validators."""
        mock_validator = Mock(spec=AbstractValidator)
        ValidationRegistry.register_language_validator(Language.PYTHON, mock_validator)
        ValidationRegistry.register_service_validator("github", mock_validator)

        ValidationRegistry.clear_all_validators()

        assert len(ValidationRegistry.get_registered_languages()) == 0
        assert len(ValidationRegistry.get_registered_services()) == 0


class TestPythonValidator:
    """Test PythonValidator class."""

    def test_validator_name(self):
        """Test validator name property."""
        validator = PythonValidator()
        assert validator.validator_name == "Python Language Validator"

    def test_validate_missing_python_path(self):
        """Test validation fails when python_path is missing."""
        mock_logger = Mock()
        validator = PythonValidator()
        mock_config = Mock()
        mock_config.python_path = None
        mock_logger = Mock()

        context = ValidationContext(
            workspace="/test/workspace",
            language=Language.PYTHON,
            services=[],
            repository_config=mock_config,
        )

        with pytest.raises(ValidationError) as exc_info:
            validator.validate(context, mock_logger)

        assert "Python path not configured" in str(exc_info.value)
        assert exc_info.value.validator_type == ValidatorType.PYTHON

    @patch("validation_system.subprocess.run")
    def test_validate_python_path_success(self, mock_run):
        mock_logger = Mock()
        """Test successful Python path validation."""
        mock_logger = Mock()
        validator = PythonValidator()
        mock_config = Mock()
        mock_config.python_path = "/usr/bin/python3"

        # Mock successful subprocess calls
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "Python 3.9.0"
        mock_run.return_value.stderr = ""

        context = ValidationContext(
            workspace="/test/workspace",
            language=Language.PYTHON,
            services=[],
            repository_config=mock_config,
        )

        with (
            patch("validation_system.os.path.exists", return_value=True),
            patch("validation_system.os.access", return_value=True),
            patch("validation_system.os.path.abspath", return_value="/usr/bin/python3"),
        ):
            # Should not raise any exception
            validator.validate(context, mock_logger)

            # Verify both Python version and pyright checks were called
            assert mock_run.call_count == 2

    @patch("validation_system.subprocess.run")
    def test_validate_python_path_nonexistent(self, mock_run):
        """Test validation fails for non-existent Python path."""
        mock_logger = Mock()
        validator = PythonValidator()
        mock_config = Mock()
        mock_config.python_path = "/nonexistent/python"

        context = ValidationContext(
            workspace="/test/workspace",
            language=Language.PYTHON,
            services=[],
            repository_config=mock_config,
        )

        with (
            patch("validation_system.os.path.exists", return_value=False),
            patch(
                "validation_system.os.path.abspath", return_value="/nonexistent/python"
            ),
        ):
            with pytest.raises(ValidationError) as exc_info:
                validator.validate(context, mock_logger)

            assert "Python path validation failed" in str(exc_info.value)
            assert exc_info.value.validator_type == ValidatorType.PYTHON

    @patch("validation_system.subprocess.run")
    def test_validate_python_version_too_old(self, mock_run):
        mock_logger = Mock()
        """Test validation fails for old Python version."""
        validator = PythonValidator()
        mock_config = Mock()
        mock_config.python_path = "/usr/bin/python3"

        # Mock subprocess to return old Python version
        def mock_subprocess_run(cmd, **kwargs):
            if cmd[0] == "/usr/bin/python3":
                mock_result = Mock()
                mock_result.returncode = 0
                mock_result.stdout = "Python 3.7.0"
                mock_result.stderr = ""
                return mock_result
            elif cmd[0] == "pyright":
                mock_result = Mock()
                mock_result.returncode = 0
                mock_result.stdout = "pyright 1.1.0"
                mock_result.stderr = ""
                return mock_result

        mock_run.side_effect = mock_subprocess_run

        context = ValidationContext(
            workspace="/test/workspace",
            language=Language.PYTHON,
            services=[],
            repository_config=mock_config,
        )

        with (
            patch("validation_system.os.path.exists", return_value=True),
            patch("validation_system.os.access", return_value=True),
            patch("validation_system.os.path.abspath", return_value="/usr/bin/python3"),
        ):
            with pytest.raises(ValidationError) as exc_info:
                validator.validate(context, mock_logger)

            assert "Python path validation failed" in str(exc_info.value)
            assert exc_info.value.validator_type == ValidatorType.PYTHON

    @patch("validation_system.subprocess.run")
    def test_validate_pyright_not_available(self, mock_run):
        mock_logger = Mock()
        """Test validation fails when pyright is not available."""
        validator = PythonValidator()
        mock_config = Mock()
        mock_config.python_path = "/usr/bin/python3"

        # Mock successful Python check but failed pyright check
        def mock_subprocess_run(cmd, **kwargs):
            if cmd[0] == "/usr/bin/python3":
                mock_result = Mock()
                mock_result.returncode = 0
                mock_result.stdout = "Python 3.9.0"
                mock_result.stderr = ""
                return mock_result
            elif cmd[0] == "pyright":
                raise FileNotFoundError("pyright not found")

        mock_run.side_effect = mock_subprocess_run

        context = ValidationContext(
            workspace="/test/workspace",
            language=Language.PYTHON,
            services=[],
            repository_config=mock_config,
        )

        with (
            patch("validation_system.os.path.exists", return_value=True),
            patch("validation_system.os.access", return_value=True),
            patch("validation_system.os.path.abspath", return_value="/usr/bin/python3"),
        ):
            with pytest.raises(ValidationError) as exc_info:
                validator.validate(context, mock_logger)

            assert "Pyright availability check failed" in str(exc_info.value)
            assert exc_info.value.validator_type == ValidatorType.PYTHON


class TestGitHubValidator:
    """Test GitHubValidator class."""

    def test_validator_name(self):
        """Test validator name property."""

        validator = GitHubValidator()
        assert validator.validator_name == "GitHub Service Validator"

    @patch.dict(os.environ, {"GITHUB_TOKEN": "test_token"})
    @patch("validation_system.subprocess.run")
    def test_validate_success(self, mock_run):
        """Test successful GitHub validation."""
        mock_logger = Mock()
        validator = GitHubValidator()
        mock_config = Mock()

        # Mock successful git command
        mock_run.return_value.returncode = 0
        mock_run.return_value.stderr = ""

        context = ValidationContext(
            workspace="/test/workspace",
            language=Language.PYTHON,
            services=["github"],
            repository_config=mock_config,
        )

        with patch("validation_system.os.path.exists", return_value=True):
            # Should not raise any exception
            validator.validate(context, mock_logger)

    @patch.dict(os.environ, {}, clear=True)
    def test_validate_missing_github_token(self):
        """Test validation fails when GITHUB_TOKEN is missing."""
        mock_logger = Mock()
        validator = GitHubValidator()
        mock_config = Mock()

        context = ValidationContext(
            workspace="/test/workspace",
            language=Language.PYTHON,
            services=["github"],
            repository_config=mock_config,
        )

        with pytest.raises(ValidationError) as exc_info:
            validator.validate(context, mock_logger)

        assert "GitHub token validation failed" in str(exc_info.value)
        assert exc_info.value.validator_type == ValidatorType.GITHUB

    @patch.dict(os.environ, {"GITHUB_TOKEN": "test_token"})
    def test_validate_nonexistent_workspace(self):
        """Test validation fails for non-existent workspace."""
        mock_logger = Mock()
        validator = GitHubValidator()
        mock_config = Mock()

        context = ValidationContext(
            workspace="/nonexistent/workspace",
            language=Language.PYTHON,
            services=["github"],
            repository_config=mock_config,
        )

        with patch("validation_system.os.path.exists", return_value=False):
            with pytest.raises(ValidationError) as exc_info:
                validator.validate(context, mock_logger)

            assert "Git repository validation failed" in str(exc_info.value)
            assert exc_info.value.validator_type == ValidatorType.GITHUB

    @patch.dict(os.environ, {"GITHUB_TOKEN": "test_token"})
    def test_validate_not_git_repository(self):
        """Test validation fails for non-git workspace."""
        mock_logger = Mock()
        validator = GitHubValidator()
        mock_config = Mock()

        context = ValidationContext(
            workspace="/test/workspace",
            language=Language.PYTHON,
            services=["github"],
            repository_config=mock_config,
        )

        # Mock workspace exists but .git doesn't
        def mock_exists(path):
            return "/test/workspace" in path and ".git" not in path

        with patch("validation_system.os.path.exists", side_effect=mock_exists):
            with pytest.raises(ValidationError) as exc_info:
                validator.validate(context, mock_logger)

            assert "Git repository validation failed" in str(exc_info.value)
            assert exc_info.value.validator_type == ValidatorType.GITHUB


class TestCodebaseValidator:
    """Test CodebaseValidator class."""

    def test_validator_name(self):
        """Test validator name property."""

        validator = CodebaseValidator()
        assert validator.validator_name == "Codebase Service Validator"

    @patch("validation_system.subprocess.run")
    def test_validate_python_success(self, mock_run):
        """Test successful codebase validation for Python."""
        mock_logger = Mock()
        validator = CodebaseValidator()
        mock_config = Mock()

        # Mock successful pyright check
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "pyright 1.1.0"
        mock_run.return_value.stderr = ""

        context = ValidationContext(
            workspace="/test/workspace",
            language=Language.PYTHON,
            services=["codebase"],
            repository_config=mock_config,
        )

        with (
            patch("validation_system.os.path.exists", return_value=True),
            patch("validation_system.os.path.isdir", return_value=True),
            patch("validation_system.os.access", return_value=True),
        ):
            # Should not raise any exception
            validator.validate(context, mock_logger)

    def test_validate_nonexistent_workspace(self):
        """Test validation fails for non-existent workspace."""
        mock_logger = Mock()
        validator = CodebaseValidator()
        mock_config = Mock()

        context = ValidationContext(
            workspace="/nonexistent/workspace",
            language=Language.PYTHON,
            services=["codebase"],
            repository_config=mock_config,
        )

        with patch("validation_system.os.path.exists", return_value=False):
            with pytest.raises(ValidationError) as exc_info:
                validator.validate(context, mock_logger)

            assert "Workspace access validation failed" in str(exc_info.value)
            assert exc_info.value.validator_type == ValidatorType.CODEBASE

    def test_validate_workspace_not_directory(self):
        """Test validation fails when workspace is not a directory."""
        mock_logger = Mock()
        validator = CodebaseValidator()
        mock_config = Mock()

        context = ValidationContext(
            workspace="/test/workspace",
            language=Language.PYTHON,
            services=["codebase"],
            repository_config=mock_config,
        )

        with (
            patch("validation_system.os.path.exists", return_value=True),
            patch("validation_system.os.path.isdir", return_value=False),
        ):
            with pytest.raises(ValidationError) as exc_info:
                validator.validate(context, mock_logger)

            assert "Workspace access validation failed" in str(exc_info.value)
            assert exc_info.value.validator_type == ValidatorType.CODEBASE

    def test_validate_workspace_not_readable(self):
        """Test validation fails when workspace is not readable."""
        mock_logger = Mock()
        validator = CodebaseValidator()
        mock_config = Mock()

        context = ValidationContext(
            workspace="/test/workspace",
            language=Language.PYTHON,
            services=["codebase"],
            repository_config=mock_config,
        )

        def mock_access(path, mode):
            if mode == os.R_OK:
                return False
            return True

        with (
            patch("validation_system.os.path.exists", return_value=True),
            patch("validation_system.os.path.isdir", return_value=True),
            patch("validation_system.os.access", side_effect=mock_access),
        ):
            with pytest.raises(ValidationError) as exc_info:
                validator.validate(context, mock_logger)

            assert "Workspace access validation failed" in str(exc_info.value)
            assert exc_info.value.validator_type == ValidatorType.CODEBASE

    @patch("validation_system.subprocess.run")
    def test_validate_python_lsp_tools_not_available(self, mock_run):
        """Test validation fails when Python LSP tools are not available."""
        mock_logger = Mock()
        validator = CodebaseValidator()
        mock_config = Mock()

        # Mock pyright not available
        mock_run.side_effect = FileNotFoundError("pyright not found")

        context = ValidationContext(
            workspace="/test/workspace",
            language=Language.PYTHON,
            services=["codebase"],
            repository_config=mock_config,
        )

        with (
            patch("validation_system.os.path.exists", return_value=True),
            patch("validation_system.os.path.isdir", return_value=True),
            patch("validation_system.os.access", return_value=True),
        ):
            with pytest.raises(ValidationError) as exc_info:
                validator.validate(context, mock_logger)

            assert "Python LSP tools validation failed" in str(exc_info.value)
            assert exc_info.value.validator_type == ValidatorType.CODEBASE


class TestValidationIntegration:
    """Integration tests for the validation system."""

    @patch.dict(os.environ, {"GITHUB_TOKEN": "test_token"})
    @patch("validation_system.subprocess.run")
    def test_full_validation_success(self, mock_run, clean_registry):
        """Test full validation workflow with all validators."""
        # Register validators
        ValidationRegistry.register_language_validator(
            Language.PYTHON, PythonValidator()
        )
        ValidationRegistry.register_service_validator("github", GitHubValidator())
        ValidationRegistry.register_service_validator("codebase", CodebaseValidator())

        # Mock repository config
        mock_config = Mock()
        mock_config.python_path = "/usr/bin/python3"

        # Mock successful subprocess calls
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "Python 3.9.0"
        mock_run.return_value.stderr = ""

        context = ValidationContext(
            workspace="/test/workspace",
            language=Language.PYTHON,
            services=["github", "codebase"],
            repository_config=mock_config,
        )

        with (
            patch("validation_system.os.path.exists", return_value=True),
            patch("validation_system.os.access", return_value=True),
            patch("validation_system.os.path.abspath", return_value="/usr/bin/python3"),
            patch("validation_system.os.path.isdir", return_value=True),
        ):
            # Should not raise any exception
            ValidationRegistry.validate_all(context)

    def test_validation_order_independence(self, clean_registry):
        """Test that validation order doesn't matter."""
        # Register validators in different order
        ValidationRegistry.register_service_validator("codebase", CodebaseValidator())
        ValidationRegistry.register_language_validator(
            Language.PYTHON, PythonValidator()
        )
        ValidationRegistry.register_service_validator("github", GitHubValidator())

        # Test that we can retrieve them
        assert ValidationRegistry.get_language_validator(Language.PYTHON) is not None
        assert ValidationRegistry.get_service_validator("github") is not None
        assert ValidationRegistry.get_service_validator("codebase") is not None
