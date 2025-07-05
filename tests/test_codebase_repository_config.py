#!/usr/bin/env python3

"""
Unit tests for codebase repository configuration integration.
"""

import os
import tempfile
from unittest.mock import Mock, patch

import pytest

from codebase_repository_config import (
    CodebaseRepositoryConfig,
    CodebaseRepositoryConfigManager,
    create_codebase_repository_config_manager,
)
from repository_manager import RepositoryConfig, RepositoryManager


class TestCodebaseRepositoryConfig:
    """Test the CodebaseRepositoryConfig dataclass."""

    def test_valid_config_creation(self):
        """Test creating a valid repository configuration."""
        config = CodebaseRepositoryConfig(
            name="test-repo",
            path="/tmp/test-repo",
            description="Test repository",
            python_path="/usr/bin/python3",
        )

        assert config.name == "test-repo"
        assert config.path == "/tmp/test-repo"
        assert config.description == "Test repository"
        assert config.python_path == "/usr/bin/python3"

    def test_path_normalization(self):
        """Test that repository paths are normalized."""
        config = CodebaseRepositoryConfig(
            name="test-repo",
            path="~/test-repo",
            description="Test repository",
            python_path="/usr/bin/python3",
        )

        # Path should be normalized to absolute path
        assert config.path == os.path.abspath(os.path.expanduser("~/test-repo"))

    def test_empty_name_validation(self):
        """Test that empty name raises ValueError."""
        with pytest.raises(ValueError, match="Repository name cannot be empty"):
            CodebaseRepositoryConfig(
                name="",
                path="/tmp/test-repo",
                description="Test repository",
                python_path="/usr/bin/python3",
            )

    def test_empty_path_validation(self):
        """Test that empty path raises ValueError."""
        with pytest.raises(ValueError, match="Repository path cannot be empty"):
            CodebaseRepositoryConfig(
                name="test-repo",
                path="",
                description="Test repository",
                python_path="/usr/bin/python3",
            )

    def test_none_python_path(self):
        """Test that None python_path is allowed."""
        config = CodebaseRepositoryConfig(
            name="test-repo",
            path="/tmp/test-repo",
            description="Test repository",
            python_path=None,
        )

        assert config.python_path is None


class TestCodebaseRepositoryConfigManager:
    """Test the CodebaseRepositoryConfigManager class."""

    def test_initialization(self):
        """Test manager initialization."""
        mock_repo_manager = Mock(spec=RepositoryManager)
        manager = CodebaseRepositoryConfigManager(mock_repo_manager)

        assert manager.repository_manager == mock_repo_manager
        assert manager.logger is not None

    def test_get_python_repositories_empty(self):
        """Test getting Python repositories when none are configured."""
        mock_repo_manager = Mock(spec=RepositoryManager)
        mock_repo_manager.repositories = {}

        manager = CodebaseRepositoryConfigManager(mock_repo_manager)
        python_repos = manager.get_python_repositories()

        assert python_repos == []

    def test_get_python_repositories_no_python(self):
        """Test getting Python repositories when no Python repos are configured."""
        mock_repo_config = Mock(spec=RepositoryConfig)
        mock_repo_config.language = "swift"

        mock_repo_manager = Mock(spec=RepositoryManager)
        mock_repo_manager.repositories = {"swift-repo": mock_repo_config}

        manager = CodebaseRepositoryConfigManager(mock_repo_manager)
        python_repos = manager.get_python_repositories()

        assert python_repos == []

    @patch(
        "codebase_repository_config.CodebaseRepositoryConfigManager._validate_python_repository"
    )
    def test_get_python_repositories_valid(self, mock_validate):
        """Test getting Python repositories with valid configuration."""
        mock_repo_config = Mock(spec=RepositoryConfig)
        mock_repo_config.language = "python"
        mock_repo_config.path = "/tmp/test-repo"
        mock_repo_config.description = "Test Python repository"
        mock_repo_config.python_path = "/usr/bin/python3"

        mock_repo_manager = Mock(spec=RepositoryManager)
        mock_repo_manager.repositories = {"python-repo": mock_repo_config}

        manager = CodebaseRepositoryConfigManager(mock_repo_manager)

        python_repos = manager.get_python_repositories()

        assert len(python_repos) == 1
        assert python_repos[0].name == "python-repo"
        assert python_repos[0].path == "/tmp/test-repo"
        assert python_repos[0].description == "Test Python repository"
        assert python_repos[0].python_path == "/usr/bin/python3"

    def test_get_python_repositories_validation_failure(self):
        """Test getting Python repositories when validation fails."""
        mock_repo_config = Mock(spec=RepositoryConfig)
        mock_repo_config.language = "python"
        mock_repo_config.path = "/tmp/test-repo"
        mock_repo_config.description = "Test Python repository"
        mock_repo_config.python_path = "/usr/bin/python3"

        mock_repo_manager = Mock(spec=RepositoryManager)
        mock_repo_manager.repositories = {"python-repo": mock_repo_config}

        manager = CodebaseRepositoryConfigManager(mock_repo_manager)

        # Mock the validation method to fail using patch context manager
        with patch.object(
            manager,
            "_validate_python_repository",
            side_effect=ValueError("Validation failed"),
        ):
            python_repos = manager.get_python_repositories()

            # Should return empty list when validation fails
            assert python_repos == []

    def test_validate_python_repository_non_existent_path(self):
        """Test validation fails for non-existent path."""
        mock_repo_manager = Mock(spec=RepositoryManager)
        manager = CodebaseRepositoryConfigManager(mock_repo_manager)

        with pytest.raises(ValueError, match="Repository path does not exist"):
            manager._validate_python_repository("/non/existent/path")

    def test_validate_python_repository_file_not_directory(self):
        """Test validation fails when path is a file, not directory."""
        mock_repo_manager = Mock(spec=RepositoryManager)
        manager = CodebaseRepositoryConfigManager(mock_repo_manager)

        with tempfile.NamedTemporaryFile() as tmp_file:
            with pytest.raises(ValueError, match="Repository path is not a directory"):
                manager._validate_python_repository(tmp_file.name)

    def test_validate_python_repository_no_python_files(self):
        """Test validation fails when directory contains no Python files."""
        mock_repo_manager = Mock(spec=RepositoryManager)
        manager = CodebaseRepositoryConfigManager(mock_repo_manager)

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create a non-Python file
            with open(os.path.join(tmp_dir, "test.txt"), "w") as f:
                f.write("test")

            with pytest.raises(ValueError, match="Repository contains no Python files"):
                manager._validate_python_repository(tmp_dir)

    def test_validate_python_repository_success(self):
        """Test successful validation with Python files."""
        mock_repo_manager = Mock(spec=RepositoryManager)
        manager = CodebaseRepositoryConfigManager(mock_repo_manager)

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create a Python file
            with open(os.path.join(tmp_dir, "test.py"), "w") as f:
                f.write("print('test')")

            # Should not raise an exception
            manager._validate_python_repository(tmp_dir)

    def test_has_python_files_py_extension(self):
        """Test detection of .py files."""
        mock_repo_manager = Mock(spec=RepositoryManager)
        manager = CodebaseRepositoryConfigManager(mock_repo_manager)

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create a Python file
            with open(os.path.join(tmp_dir, "test.py"), "w") as f:
                f.write("print('test')")

            assert manager._has_python_files(tmp_dir) is True

    def test_has_python_files_pyi_extension(self):
        """Test detection of .pyi files."""
        mock_repo_manager = Mock(spec=RepositoryManager)
        manager = CodebaseRepositoryConfigManager(mock_repo_manager)

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create a Python stub file
            with open(os.path.join(tmp_dir, "test.pyi"), "w") as f:
                f.write("def test() -> None: ...")

            assert manager._has_python_files(tmp_dir) is True

    def test_has_python_files_nested_directory(self):
        """Test detection of Python files in nested directories."""
        mock_repo_manager = Mock(spec=RepositoryManager)
        manager = CodebaseRepositoryConfigManager(mock_repo_manager)

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create nested directory structure
            nested_dir = os.path.join(tmp_dir, "src", "package")
            os.makedirs(nested_dir)

            # Create a Python file in nested directory
            with open(os.path.join(nested_dir, "module.py"), "w") as f:
                f.write("class TestClass: pass")

            assert manager._has_python_files(tmp_dir) is True

    def test_has_python_files_no_python_files(self):
        """Test no Python files detected."""
        mock_repo_manager = Mock(spec=RepositoryManager)
        manager = CodebaseRepositoryConfigManager(mock_repo_manager)

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create non-Python files
            with open(os.path.join(tmp_dir, "test.txt"), "w") as f:
                f.write("test")
            with open(os.path.join(tmp_dir, "test.js"), "w") as f:
                f.write("console.log('test')")

            assert manager._has_python_files(tmp_dir) is False

    def test_get_repository_by_name_not_found(self):
        """Test getting repository by name when it doesn't exist."""
        mock_repo_manager = Mock(spec=RepositoryManager)
        mock_repo_manager.get_repository.return_value = None

        manager = CodebaseRepositoryConfigManager(mock_repo_manager)
        result = manager.get_repository_by_name("non-existent")

        assert result is None

    def test_get_repository_by_name_not_python(self):
        """Test getting repository by name when it's not a Python repository."""
        mock_repo_config = Mock(spec=RepositoryConfig)
        mock_repo_config.language = "swift"

        mock_repo_manager = Mock(spec=RepositoryManager)
        mock_repo_manager.get_repository.return_value = mock_repo_config

        manager = CodebaseRepositoryConfigManager(mock_repo_manager)
        result = manager.get_repository_by_name("swift-repo")

        assert result is None

    def test_get_repository_by_name_validation_failure(self):
        """Test getting repository by name when validation fails."""
        mock_repo_config = Mock(spec=RepositoryConfig)
        mock_repo_config.language = "python"
        mock_repo_config.path = "/tmp/test-repo"
        mock_repo_config.description = "Test repository"
        mock_repo_config.python_path = "/usr/bin/python3"

        mock_repo_manager = Mock(spec=RepositoryManager)
        mock_repo_manager.get_repository.return_value = mock_repo_config

        manager = CodebaseRepositoryConfigManager(mock_repo_manager)

        # Mock validation to fail
        with patch.object(
            manager,
            "_validate_python_repository",
            side_effect=ValueError("Validation failed"),
        ):
            result = manager.get_repository_by_name("python-repo")

            assert result is None

    def test_get_repository_by_name_success(self):
        """Test successful repository retrieval by name."""
        mock_repo_config = Mock(spec=RepositoryConfig)
        mock_repo_config.language = "python"
        mock_repo_config.path = "/tmp/test-repo"
        mock_repo_config.description = "Test repository"
        mock_repo_config.python_path = "/usr/bin/python3"

        mock_repo_manager = Mock(spec=RepositoryManager)
        mock_repo_manager.get_repository.return_value = mock_repo_config

        manager = CodebaseRepositoryConfigManager(mock_repo_manager)

        # Mock validation to succeed
        with patch.object(manager, "_validate_python_repository"):
            result = manager.get_repository_by_name("python-repo")

            assert result is not None
            assert result.name == "python-repo"
            assert result.path == "/tmp/test-repo"
            assert result.description == "Test repository"
            assert result.python_path == "/usr/bin/python3"

    def test_validate_repository_configuration_no_python_repos(self):
        """Test configuration validation when no Python repositories exist."""
        mock_repo_manager = Mock(spec=RepositoryManager)
        manager = CodebaseRepositoryConfigManager(mock_repo_manager)

        # Mock get_python_repositories to return empty list
        with patch.object(manager, "get_python_repositories", return_value=[]):
            result = manager.validate_repository_configuration()

            assert result is False

    def test_validate_repository_configuration_with_python_repos(self):
        """Test successful configuration validation with Python repositories."""
        mock_repo_manager = Mock(spec=RepositoryManager)
        manager = CodebaseRepositoryConfigManager(mock_repo_manager)

        # Mock get_python_repositories to return repositories
        mock_config = Mock(spec=CodebaseRepositoryConfig)
        with patch.object(
            manager, "get_python_repositories", return_value=[mock_config]
        ):
            result = manager.validate_repository_configuration()

            assert result is True

    def test_validate_repository_configuration_exception(self):
        """Test configuration validation when an exception occurs."""
        mock_repo_manager = Mock(spec=RepositoryManager)
        manager = CodebaseRepositoryConfigManager(mock_repo_manager)

        # Mock get_python_repositories to raise exception
        with patch.object(
            manager, "get_python_repositories", side_effect=Exception("Test error")
        ):
            result = manager.validate_repository_configuration()

            assert result is False


class TestCreateCodebaseRepositoryConfigManager:
    """Test the factory function for creating CodebaseRepositoryConfigManager."""

    @patch("codebase_repository_config.RepositoryManager")
    def test_create_manager_success(self, mock_repo_manager_class):
        """Test successful manager creation."""
        mock_repo_manager = Mock(spec=RepositoryManager)
        mock_repo_manager.load_configuration.return_value = True
        mock_repo_manager_class.return_value = mock_repo_manager

        manager = create_codebase_repository_config_manager("/tmp/config.json")

        assert isinstance(manager, CodebaseRepositoryConfigManager)
        assert manager.repository_manager == mock_repo_manager
        mock_repo_manager_class.assert_called_once_with("/tmp/config.json")
        mock_repo_manager.load_configuration.assert_called_once()

    @patch("codebase_repository_config.RepositoryManager")
    def test_create_manager_load_failure(self, mock_repo_manager_class):
        """Test manager creation when configuration load fails."""
        mock_repo_manager = Mock(spec=RepositoryManager)
        mock_repo_manager.load_configuration.return_value = False
        mock_repo_manager_class.return_value = mock_repo_manager

        with pytest.raises(
            RuntimeError, match="Failed to load repository configuration"
        ):
            create_codebase_repository_config_manager("/tmp/config.json")

    @patch("codebase_repository_config.RepositoryManager")
    def test_create_manager_default_config_path(self, mock_repo_manager_class):
        """Test manager creation with default config path."""
        mock_repo_manager = Mock(spec=RepositoryManager)
        mock_repo_manager.load_configuration.return_value = True
        mock_repo_manager_class.return_value = mock_repo_manager

        manager = create_codebase_repository_config_manager()

        assert isinstance(manager, CodebaseRepositoryConfigManager)
        mock_repo_manager_class.assert_called_once_with(None)
