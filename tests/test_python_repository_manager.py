#!/usr/bin/env python3

"""
Unit tests for Python repository manager.
"""

import os
import tempfile
from unittest.mock import Mock, patch

import pytest

from constants import Language
from python_repository_manager import (
    PythonRepositoryManager,
    create_python_repository_manager,
)
from repository_manager import RepositoryConfig, RepositoryManager

# Note: Now using PythonRepositoryManager with RepositoryConfig directly


class TestPythonRepositoryManager:
    """Test the PythonRepositoryManager class."""

    def test_initialization(self, mock_repository_manager):
        """Test manager initialization."""
        manager = PythonRepositoryManager(mock_repository_manager)

        assert manager.repository_manager == mock_repository_manager
        assert manager.logger is not None

    def test_get_python_repositories_empty(self, mock_repository_manager):
        """Test getting Python repositories when none are configured."""
        # MockRepositoryManager starts empty
        manager = PythonRepositoryManager(mock_repository_manager)
        python_repos = manager.get_python_repositories()

        assert python_repos == []

    def test_get_python_repositories_no_python(self, mock_repository_manager):
        """Test getting Python repositories when no Python repos are configured."""
        # Create RepositoryConfig directly for testing
        swift_repo_config = RepositoryConfig(
            name="swift-repo",
            workspace="/tmp/test-swift-repo",
            description="Test Swift repository",
            language=Language.SWIFT,
            port=8082,
            python_path="/usr/bin/python3",
            github_owner="test",
            github_repo="swift-repo",
        )

        mock_repository_manager.add_repository("swift-repo", swift_repo_config)

        manager = PythonRepositoryManager(mock_repository_manager)
        python_repos = manager.get_python_repositories()

        assert python_repos == []

    @patch(
        "python_repository_manager.PythonRepositoryManager._validate_python_repository"
    )
    def test_get_python_repositories_valid(
        self, mock_validate, mock_repository_manager
    ):
        """Test getting Python repositories with valid configuration."""
        # Create RepositoryConfig directly for testing
        python_repo_config = RepositoryConfig(
            name="python-repo",
            workspace="/tmp/test-repo",
            description="Test Python repository",
            language=Language.PYTHON,
            port=8081,
            python_path="/usr/bin/python3",
            github_owner="test",
            github_repo="python-repo",
        )

        mock_repository_manager.add_repository("python-repo", python_repo_config)

        manager = PythonRepositoryManager(mock_repository_manager)

        python_repos = manager.get_python_repositories()

        assert len(python_repos) == 1
        assert python_repos[0].name == "python-repo"
        assert python_repos[0].workspace == "/tmp/test-repo"
        assert python_repos[0].description == "Test Python repository"
        assert python_repos[0].python_path == "/usr/bin/python3"

    def test_get_python_repositories_validation_failure(self, mock_repository_manager):
        """Test getting Python repositories when validation fails."""
        # Create RepositoryConfig directly for testing
        python_repo_config = RepositoryConfig(
            name="python-repo",
            workspace="/tmp/test-repo",
            description="Test Python repository",
            language=Language.PYTHON,
            port=8081,
            python_path="/usr/bin/python3",
            github_owner="test",
            github_repo="python-repo",
        )

        mock_repository_manager.add_repository("python-repo", python_repo_config)

        manager = PythonRepositoryManager(mock_repository_manager)

        # Mock the validation method to fail using patch context manager
        with patch.object(
            manager,
            "_validate_python_repository",
            side_effect=ValueError("Validation failed"),
        ):
            python_repos = manager.get_python_repositories()

            # Should return empty list when validation fails
            assert python_repos == []

    # Note: Path existence and directory validation are now handled by RepositoryManager
    # These tests are no longer needed as _validate_python_repository only checks for Python files

    def test_validate_python_repository_no_python_files(self, mock_repository_manager):
        """Test validation fails when directory contains no Python files."""
        manager = PythonRepositoryManager(mock_repository_manager)

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create a non-Python file
            with open(os.path.join(tmp_dir, "test.txt"), "w") as f:
                f.write("test")

            with pytest.raises(ValueError, match="Repository contains no Python files"):
                manager._validate_python_repository(tmp_dir)

    def test_validate_python_repository_success(self, mock_repository_manager):
        """Test successful validation with Python files."""
        manager = PythonRepositoryManager(mock_repository_manager)

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create a Python file
            with open(os.path.join(tmp_dir, "test.py"), "w") as f:
                f.write("print('test')")

            # Should not raise an exception
            manager._validate_python_repository(tmp_dir)

    def test_has_python_files_py_extension(self, mock_repository_manager):
        """Test detection of .py files."""
        manager = PythonRepositoryManager(mock_repository_manager)

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create a Python file
            with open(os.path.join(tmp_dir, "test.py"), "w") as f:
                f.write("print('test')")

            assert manager._has_python_files(tmp_dir) is True

    def test_has_python_files_pyi_extension(self, mock_repository_manager):
        """Test detection of .pyi files."""
        manager = PythonRepositoryManager(mock_repository_manager)

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create a Python stub file
            with open(os.path.join(tmp_dir, "test.pyi"), "w") as f:
                f.write("def test() -> None: ...")

            assert manager._has_python_files(tmp_dir) is True

    def test_has_python_files_nested_directory(self, mock_repository_manager):
        """Test detection of Python files in nested directories."""
        manager = PythonRepositoryManager(mock_repository_manager)

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create nested directory structure
            nested_dir = os.path.join(tmp_dir, "src", "package")
            os.makedirs(nested_dir)

            # Create a Python file in nested directory
            with open(os.path.join(nested_dir, "module.py"), "w") as f:
                f.write("class TestClass: pass")

            assert manager._has_python_files(tmp_dir) is True

    def test_has_python_files_no_python_files(self, mock_repository_manager):
        """Test no Python files detected."""
        manager = PythonRepositoryManager(mock_repository_manager)

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create non-Python files
            with open(os.path.join(tmp_dir, "test.txt"), "w") as f:
                f.write("test")
            with open(os.path.join(tmp_dir, "test.js"), "w") as f:
                f.write("console.log('test')")

            assert manager._has_python_files(tmp_dir) is False

    def test_get_repository_by_name_not_found(self, mock_repository_manager):
        """Test getting repository by name when it doesn't exist."""
        # MockRepositoryManager returns None for non-existent repositories
        manager = PythonRepositoryManager(mock_repository_manager)
        result = manager.get_repository_by_name("non-existent")

        assert result is None

    def test_get_repository_by_name_not_python(self, mock_repository_manager):
        """Test getting repository by name when it's not a Python repository."""
        # Create proper RepositoryConfig object for Swift repository
        swift_repo_config = RepositoryConfig(
            name="swift-repo",
            workspace="/tmp/test-swift-repo",
            description="Test Swift repository",
            language=Language.SWIFT,
            port=8082,
            python_path="/usr/bin/python3",
            github_owner="test",
            github_repo="swift-repo",
        )

        mock_repository_manager.add_repository("swift-repo", swift_repo_config)
        manager = PythonRepositoryManager(mock_repository_manager)
        result = manager.get_repository_by_name("swift-repo")

        assert result is None

    def test_get_repository_by_name_validation_failure(self, mock_repository_manager):
        """Test getting repository by name when validation fails."""
        # Create proper RepositoryConfig object for Python repository
        python_repo_config = RepositoryConfig(
            name="python-repo",
            workspace="/tmp/test-repo",
            description="Test repository",
            language=Language.PYTHON,
            port=8081,
            python_path="/usr/bin/python3",
            github_owner="test",
            github_repo="python-repo",
        )

        mock_repository_manager.add_repository("python-repo", python_repo_config)
        manager = PythonRepositoryManager(mock_repository_manager)

        # Mock validation to fail
        with patch.object(
            manager,
            "_validate_python_repository",
            side_effect=ValueError("Validation failed"),
        ):
            result = manager.get_repository_by_name("python-repo")

            assert result is None

    def test_get_repository_by_name_success(self, mock_repository_manager):
        """Test successful repository retrieval by name."""
        # Create proper RepositoryConfig object for Python repository
        python_repo_config = RepositoryConfig(
            name="python-repo",
            workspace="/tmp/test-repo",
            description="Test repository",
            language=Language.PYTHON,
            port=8081,
            python_path="/usr/bin/python3",
            github_owner="test",
            github_repo="python-repo",
        )

        mock_repository_manager.add_repository("python-repo", python_repo_config)
        manager = PythonRepositoryManager(mock_repository_manager)

        # Mock validation to succeed
        with patch.object(manager, "_validate_python_repository"):
            result = manager.get_repository_by_name("python-repo")

            assert result is not None
            assert result.name == "python-repo"
            assert result.workspace == "/tmp/test-repo"
            assert result.description == "Test repository"
            assert result.python_path == "/usr/bin/python3"

    def test_validate_repository_configuration_no_python_repos(
        self, mock_repository_manager
    ):
        """Test configuration validation when no Python repositories exist."""
        manager = PythonRepositoryManager(mock_repository_manager)

        # Mock get_python_repositories to return empty list
        with patch.object(manager, "get_python_repositories", return_value=[]):
            result = manager.validate_repository_configuration()

            assert result is False

    def test_validate_repository_configuration_with_python_repos(
        self, mock_repository_manager
    ):
        """Test successful configuration validation with Python repositories."""
        manager = PythonRepositoryManager(mock_repository_manager)

        # Create proper RepositoryConfig object
        python_repo_config = RepositoryConfig(
            name="test-repo",
            workspace="/tmp/test-repo",
            description="Test repository",
            language=Language.PYTHON,
            port=8081,
            python_path="/usr/bin/python3",
            github_owner="test",
            github_repo="test-repo",
        )
        with patch.object(
            manager, "get_python_repositories", return_value=[python_repo_config]
        ):
            result = manager.validate_repository_configuration()

            assert result is True

    def test_validate_repository_configuration_exception(self, mock_repository_manager):
        """Test configuration validation when an exception occurs."""
        manager = PythonRepositoryManager(mock_repository_manager)

        # Mock get_python_repositories to raise exception
        with patch.object(
            manager, "get_python_repositories", side_effect=Exception("Test error")
        ):
            result = manager.validate_repository_configuration()

            assert result is False


class TestCreatePythonRepositoryManager:
    """Test the factory function for creating PythonRepositoryManager."""

    @patch("python_repository_manager.RepositoryManager")
    def test_create_manager_success(self, mock_repo_manager_class):
        """Test successful manager creation."""
        mock_repo_manager = Mock(spec=RepositoryManager)
        mock_repo_manager.load_configuration.return_value = True
        mock_repo_manager_class.return_value = mock_repo_manager

        manager = create_python_repository_manager("/tmp/config.json")

        assert isinstance(manager, PythonRepositoryManager)
        assert manager.repository_manager == mock_repo_manager
        mock_repo_manager_class.assert_called_once_with("/tmp/config.json")
        mock_repo_manager.load_configuration.assert_called_once()

    @patch("python_repository_manager.RepositoryManager")
    def test_create_manager_load_failure(self, mock_repo_manager_class):
        """Test manager creation when configuration load fails."""
        mock_repo_manager = Mock(spec=RepositoryManager)
        mock_repo_manager.load_configuration.return_value = False
        mock_repo_manager_class.return_value = mock_repo_manager

        with pytest.raises(
            RuntimeError, match="Failed to load repository configuration"
        ):
            create_python_repository_manager("/tmp/config.json")

    @patch("python_repository_manager.RepositoryManager")
    def test_create_manager_default_config_path(self, mock_repo_manager_class):
        """Test manager creation with default config path."""
        mock_repo_manager = Mock(spec=RepositoryManager)
        mock_repo_manager.load_configuration.return_value = True
        mock_repo_manager_class.return_value = mock_repo_manager

        manager = create_python_repository_manager()

        assert isinstance(manager, PythonRepositoryManager)
        mock_repo_manager_class.assert_called_once_with(None)
