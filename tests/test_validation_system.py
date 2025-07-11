#!/usr/bin/env python3

"""
Tests for the validation system and validators.
"""

import logging
import os
from unittest.mock import Mock, patch

import pytest

from constants import Language
from github_tools import GitHubValidator
from python_repository_manager import PythonValidator
from repository_indexer import CodebaseValidator
from validation_system import (
    AbstractValidator,
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
        mock_validator.validate.assert_called_once_with(context)

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
        mock_validator.validate.assert_called_once_with(context)

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
        logger = logging.getLogger("test")
        validator = PythonValidator(logger)
        assert validator.validator_name == "Python Language Validator"

    def test_validate_missing_python_path(self):
        """Test validation fails when python_path is missing."""
        logger = logging.getLogger("test")
        validator = PythonValidator(logger)
        mock_config = Mock()
        mock_config.python_path = None

        context = ValidationContext(
            workspace="/test/workspace",
            language=Language.PYTHON,
            services=[],
            repository_config=mock_config,
        )

        with pytest.raises(ValidationError) as exc_info:
            validator.validate(context)

        assert "Python path not configured" in str(exc_info.value)
        assert exc_info.value.validator_type == ValidatorType.PYTHON

    @patch("python_repository_manager.subprocess.run")
    def test_validate_python_path_success(self, mock_run):
        """Test successful Python path validation."""
        logger = logging.getLogger("test")
        validator = PythonValidator(logger)
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
            patch("python_repository_manager.os.path.exists", return_value=True),
            patch("python_repository_manager.os.access", return_value=True),
            patch("python_repository_manager.os.path.abspath", return_value="/usr/bin/python3"),
        ):
            # Should not raise any exception
            validator.validate(context)

            # Verify both Python version and pyright checks were called
            assert mock_run.call_count == 2

    @patch("python_repository_manager.subprocess.run")
    def test_validate_python_path_nonexistent(self, mock_run):
        """Test validation fails for non-existent Python path."""
        logger = logging.getLogger("test")
        validator = PythonValidator(logger)
        mock_config = Mock()
        mock_config.python_path = "/nonexistent/python"

        context = ValidationContext(
            workspace="/test/workspace",
            language=Language.PYTHON,
            services=[],
            repository_config=mock_config,
        )

        with (
            patch("python_repository_manager.os.path.exists", return_value=False),
            patch(
                "python_repository_manager.os.path.abspath", return_value="/nonexistent/python"
            ),
        ):
            with pytest.raises(ValidationError) as exc_info:
                validator.validate(context)

            assert "Python path validation failed" in str(exc_info.value)
            assert exc_info.value.validator_type == ValidatorType.PYTHON

    @patch("python_repository_manager.subprocess.run")
    def test_validate_python_version_too_old(self, mock_run):
        """Test validation fails for old Python version."""
        logger = logging.getLogger("test")
        validator = PythonValidator(logger)
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
            patch("python_repository_manager.os.path.exists", return_value=True),
            patch("python_repository_manager.os.access", return_value=True),
            patch("python_repository_manager.os.path.abspath", return_value="/usr/bin/python3"),
        ):
            with pytest.raises(ValidationError) as exc_info:
                validator.validate(context)

            assert "Python path validation failed" in str(exc_info.value)
            assert exc_info.value.validator_type == ValidatorType.PYTHON

    @patch("python_repository_manager.subprocess.run")
    def test_validate_pyright_not_available(self, mock_run):
        """Test validation fails when pyright is not available."""
        logger = logging.getLogger("test")
        validator = PythonValidator(logger)
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
            patch("python_repository_manager.os.path.exists", return_value=True),
            patch("python_repository_manager.os.access", return_value=True),
            patch("python_repository_manager.os.path.abspath", return_value="/usr/bin/python3"),
        ):
            with pytest.raises(ValidationError) as exc_info:
                validator.validate(context)

            assert "Pyright availability check failed" in str(exc_info.value)
            assert exc_info.value.validator_type == ValidatorType.PYTHON


class TestGitHubValidator:
    """Test GitHubValidator class."""

    def test_validator_name(self):
        """Test validator name property."""

        logger = logging.getLogger("test")
        validator = GitHubValidator(logger)
        assert validator.validator_name == "GitHub Integration Validator"

    @patch.dict(os.environ, {"GITHUB_TOKEN": "test_token"})
    @patch("github_tools.subprocess.run")
    def test_validate_success(self, mock_run):
        """Test successful GitHub validation."""
        logger = logging.getLogger("test")
        validator = GitHubValidator(logger)
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

        with patch("github_tools.os.path.exists", return_value=True):
            # Should not raise any exception
            validator.validate(context)

    @patch.dict(os.environ, {}, clear=True)
    def test_validate_missing_github_token(self):
        """Test validation fails when GITHUB_TOKEN is missing."""
        logger = logging.getLogger("test")
        validator = GitHubValidator(logger)
        mock_config = Mock()

        context = ValidationContext(
            workspace="/test/workspace",
            language=Language.PYTHON,
            services=["github"],
            repository_config=mock_config,
        )

        with pytest.raises(ValidationError) as exc_info:
            validator.validate(context)

        assert "GitHub token validation failed" in str(exc_info.value)
        assert exc_info.value.validator_type == ValidatorType.GITHUB

    @patch.dict(os.environ, {"GITHUB_TOKEN": "test_token"})
    def test_validate_nonexistent_workspace(self):
        """Test validation fails for non-existent workspace."""
        logger = logging.getLogger("test")
        validator = GitHubValidator(logger)
        mock_config = Mock()

        context = ValidationContext(
            workspace="/nonexistent/workspace",
            language=Language.PYTHON,
            services=["github"],
            repository_config=mock_config,
        )

        with patch("github_tools.os.path.exists", return_value=False):
            with pytest.raises(ValidationError) as exc_info:
                validator.validate(context)

            assert "Git repository validation failed" in str(exc_info.value)
            assert exc_info.value.validator_type == ValidatorType.GITHUB

    @patch.dict(os.environ, {"GITHUB_TOKEN": "test_token"})
    def test_validate_not_git_repository(self):
        """Test validation fails for non-git workspace."""
        logger = logging.getLogger("test")
        validator = GitHubValidator(logger)
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

        with patch("github_tools.os.path.exists", side_effect=mock_exists):
            with pytest.raises(ValidationError) as exc_info:
                validator.validate(context)

            assert "Git repository validation failed" in str(exc_info.value)
            assert exc_info.value.validator_type == ValidatorType.GITHUB


class TestCodebaseValidator:
    """Test CodebaseValidator class."""

    def test_validator_name(self):
        """Test validator name property."""

        logger = logging.getLogger("test")
        validator = CodebaseValidator(logger)
        assert validator.validator_name == "Codebase Index Validator"

    @patch("repository_indexer.subprocess.run")
    def test_validate_python_success(self, mock_run):
        """Test successful codebase validation for Python."""
        logger = logging.getLogger("test")
        validator = CodebaseValidator(logger)
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
            patch("repository_indexer.os.path.exists", return_value=True),
            patch("repository_indexer.os.path.isdir", return_value=True),
            patch("repository_indexer.os.access", return_value=True),
        ):
            # Should not raise any exception
            validator.validate(context)

    def test_validate_nonexistent_workspace(self):
        """Test validation fails for non-existent workspace."""
        logger = logging.getLogger("test")
        validator = CodebaseValidator(logger)
        mock_config = Mock()

        context = ValidationContext(
            workspace="/nonexistent/workspace",
            language=Language.PYTHON,
            services=["codebase"],
            repository_config=mock_config,
        )

        with patch("repository_indexer.os.path.exists", return_value=False):
            with pytest.raises(ValidationError) as exc_info:
                validator.validate(context)

            assert "Workspace access validation failed" in str(exc_info.value)
            assert exc_info.value.validator_type == ValidatorType.CODEBASE

    def test_validate_workspace_not_directory(self):
        """Test validation fails when workspace is not a directory."""
        logger = logging.getLogger("test")
        validator = CodebaseValidator(logger)
        mock_config = Mock()

        context = ValidationContext(
            workspace="/test/workspace",
            language=Language.PYTHON,
            services=["codebase"],
            repository_config=mock_config,
        )

        with (
            patch("repository_indexer.os.path.exists", return_value=True),
            patch("repository_indexer.os.path.isdir", return_value=False),
        ):
            with pytest.raises(ValidationError) as exc_info:
                validator.validate(context)

            assert "Workspace access validation failed" in str(exc_info.value)
            assert exc_info.value.validator_type == ValidatorType.CODEBASE

    def test_validate_workspace_not_readable(self):
        """Test validation fails when workspace is not readable."""
        logger = logging.getLogger("test")
        validator = CodebaseValidator(logger)
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
            patch("repository_indexer.os.path.exists", return_value=True),
            patch("repository_indexer.os.path.isdir", return_value=True),
            patch("repository_indexer.os.access", side_effect=mock_access),
        ):
            with pytest.raises(ValidationError) as exc_info:
                validator.validate(context)

            assert "Workspace access validation failed" in str(exc_info.value)
            assert exc_info.value.validator_type == ValidatorType.CODEBASE

    @patch("repository_indexer.subprocess.run")
    def test_validate_python_lsp_tools_not_available(self, mock_run):
        """Test validation fails when Python LSP tools are not available."""
        logger = logging.getLogger("test")
        validator = CodebaseValidator(logger)
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
            patch("repository_indexer.os.path.exists", return_value=True),
            patch("repository_indexer.os.path.isdir", return_value=True),
            patch("repository_indexer.os.access", return_value=True),
        ):
            with pytest.raises(ValidationError) as exc_info:
                validator.validate(context)

            assert "Python LSP tools validation failed" in str(exc_info.value)
            assert exc_info.value.validator_type == ValidatorType.CODEBASE


class TestValidationIntegration:
    """Integration tests for the validation system."""

    @patch.dict(os.environ, {"GITHUB_TOKEN": "test_token"})
    @patch("repository_indexer.subprocess.run")
    @patch("github_tools.subprocess.run")
    @patch("python_repository_manager.subprocess.run")
    def test_full_validation_success(self, mock_python_run, mock_github_run, mock_codebase_run, clean_registry):
        """Test full validation workflow with all validators."""
        # Register validators
        ValidationRegistry.register_language_validator(
            Language.PYTHON, PythonValidator(logging.getLogger("test"))
        )
        ValidationRegistry.register_service_validator(
            "github", GitHubValidator(logging.getLogger("test"))
        )
        ValidationRegistry.register_service_validator(
            "codebase", CodebaseValidator(logging.getLogger("test"))
        )

        # Mock repository config
        mock_config = Mock()
        mock_config.python_path = "/usr/bin/python3"

        # Mock successful subprocess calls for Python version check  
        python_result = Mock()
        python_result.returncode = 0
        python_result.stdout = "Python 3.9.0"
        python_result.stderr = ""
        
        pyright_result = Mock()
        pyright_result.returncode = 0
        pyright_result.stdout = "pyright 1.1.0"
        pyright_result.stderr = ""
        
        mock_python_run.side_effect = [python_result, pyright_result]
        
        mock_github_run.return_value.returncode = 0
        mock_github_run.return_value.stdout = ""
        mock_github_run.return_value.stderr = ""
        
        mock_codebase_run.return_value.returncode = 0
        mock_codebase_run.return_value.stdout = "pyright 1.1.0"
        mock_codebase_run.return_value.stderr = ""

        context = ValidationContext(
            workspace="/test/workspace",
            language=Language.PYTHON,
            services=["github", "codebase"],
            repository_config=mock_config,
        )

        with (
            patch("python_repository_manager.os.path.exists", return_value=True),
            patch("python_repository_manager.os.access", return_value=True),
            patch("python_repository_manager.os.path.abspath", return_value="/usr/bin/python3"),
            patch("github_tools.os.path.exists", return_value=True),
            patch("repository_indexer.os.path.exists", return_value=True),
            patch("repository_indexer.os.path.isdir", return_value=True),
            patch("repository_indexer.os.access", return_value=True),
        ):
            # Should not raise any exception
            ValidationRegistry.validate_all(context)

    def test_validation_order_independence(self, clean_registry):
        """Test that validation order doesn't matter."""
        # Register validators in different order
        ValidationRegistry.register_service_validator(
            "codebase", CodebaseValidator(logging.getLogger("test"))
        )
        ValidationRegistry.register_language_validator(
            Language.PYTHON, PythonValidator(logging.getLogger("test"))
        )
        ValidationRegistry.register_service_validator(
            "github", GitHubValidator(logging.getLogger("test"))
        )

        # Test that we can retrieve them
        assert ValidationRegistry.get_language_validator(Language.PYTHON) is not None
        assert ValidationRegistry.get_service_validator("github") is not None
        assert ValidationRegistry.get_service_validator("codebase") is not None
