#!/usr/bin/env python3

"""
Integration tests for Python repository manager.
"""

import json
import os
import subprocess
import tempfile

from python_repository_manager import (
    PythonRepositoryManager,
    create_python_repository_manager,
)
from repository_manager import RepositoryManager


def create_git_repo(repo_path: str) -> None:
    """Create a git repository at the specified path."""
    os.makedirs(repo_path, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=repo_path, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"], cwd=repo_path, check=True
    )


class TestPythonRepositoryManagerIntegration:
    """Integration tests for repository configuration with real files."""

    def test_integration_with_real_repositories_json(self):
        """Test integration with actual repositories.json file."""
        # Create a temporary repositories.json file
        config_data = {
            "repositories": {
                "python-repo": {
                    "workspace": "/tmp/test-python-repo",
                    "port": 8081,
                    "description": "Test Python repository",
                    "language": "python",
                    "python_path": "/usr/bin/python3",
                },
                "swift-repo": {
                    "workspace": "/tmp/test-swift-repo",
                    "port": 8082,
                    "description": "Test Swift repository",
                    "language": "swift",
                    "python_path": "/usr/bin/python3",
                },
            }
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create config file
            config_path = os.path.join(tmp_dir, "repositories.json")
            with open(config_path, "w") as f:
                json.dump(config_data, f)

            # Create test repository directories with Python files
            python_repo_dir = "/tmp/test-python-repo"
            swift_repo_dir = "/tmp/test-swift-repo"

            create_git_repo(python_repo_dir)
            create_git_repo(swift_repo_dir)

            try:
                # Create Python file in Python repo
                with open(os.path.join(python_repo_dir, "test.py"), "w") as f:
                    f.write("print('test')")

                # Create Swift file in Swift repo (no Python files)
                with open(os.path.join(swift_repo_dir, "test.swift"), "w") as f:
                    f.write('print("test")')

                # Create repository manager
                repo_manager = RepositoryManager(config_path)
                assert repo_manager.load_configuration() is True

                # Create codebase repository config manager
                codebase_manager = PythonRepositoryManager(repo_manager)

                # Get Python repositories
                python_repos = codebase_manager.get_python_repositories()

                # Should find only the Python repository
                assert len(python_repos) == 1
                assert python_repos[0].name == "python-repo"
                assert python_repos[0].workspace == python_repo_dir
                assert python_repos[0].description == "Test Python repository"
                assert python_repos[0].python_path == "/usr/bin/python3"

            finally:
                # Clean up test directories
                import shutil

                if os.path.exists(python_repo_dir):
                    shutil.rmtree(python_repo_dir)
                if os.path.exists(swift_repo_dir):
                    shutil.rmtree(swift_repo_dir)

    def test_integration_with_nested_python_files(self):
        """Test integration with Python files in nested directories."""
        config_data = {
            "repositories": {
                "nested-python-repo": {
                    "workspace": "/tmp/test-nested-python-repo",
                    "port": 8081,
                    "description": "Test nested Python repository",
                    "language": "python",
                    "python_path": "/usr/bin/python3",
                }
            }
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create config file
            config_path = os.path.join(tmp_dir, "repositories.json")
            with open(config_path, "w") as f:
                json.dump(config_data, f)

            # Create test repository directory with nested Python files
            repo_dir = "/tmp/test-nested-python-repo"
            create_git_repo(repo_dir)

            try:
                # Create nested directory structure
                nested_dir = os.path.join(repo_dir, "src", "package")
                os.makedirs(nested_dir, exist_ok=True)

                # Create Python files in nested directories
                with open(os.path.join(nested_dir, "module.py"), "w") as f:
                    f.write("class TestClass: pass")

                with open(os.path.join(repo_dir, "main.py"), "w") as f:
                    f.write("from src.package.module import TestClass")

                # Create repository manager
                repo_manager = RepositoryManager(config_path)
                assert repo_manager.load_configuration() is True

                # Create codebase repository config manager
                codebase_manager = PythonRepositoryManager(repo_manager)

                # Get Python repositories
                python_repos = codebase_manager.get_python_repositories()

                # Should find the repository with nested Python files
                assert len(python_repos) == 1
                assert python_repos[0].name == "nested-python-repo"
                assert python_repos[0].workspace == repo_dir

            finally:
                # Clean up test directory
                import shutil

                if os.path.exists(repo_dir):
                    shutil.rmtree(repo_dir)

    def test_integration_with_pyi_files(self):
        """Test integration with Python stub (.pyi) files."""
        config_data = {
            "repositories": {
                "stub-python-repo": {
                    "workspace": "/tmp/test-stub-python-repo",
                    "port": 8081,
                    "description": "Test Python stub repository",
                    "language": "python",
                    "python_path": "/usr/bin/python3",
                }
            }
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create config file
            config_path = os.path.join(tmp_dir, "repositories.json")
            with open(config_path, "w") as f:
                json.dump(config_data, f)

            # Create test repository directory with stub files
            repo_dir = "/tmp/test-stub-python-repo"
            create_git_repo(repo_dir)

            try:
                # Create Python stub file and regular Python file
                with open(os.path.join(repo_dir, "types.pyi"), "w") as f:
                    f.write("def test_function() -> None: ...")

                # Need at least one .py file for Python repository validation
                with open(os.path.join(repo_dir, "main.py"), "w") as f:
                    f.write("from types import test_function")

                # Create repository manager
                repo_manager = RepositoryManager(config_path)
                assert repo_manager.load_configuration() is True

                # Create codebase repository config manager
                codebase_manager = PythonRepositoryManager(repo_manager)

                # Get Python repositories
                python_repos = codebase_manager.get_python_repositories()

                # Should find the repository with stub files
                assert len(python_repos) == 1
                assert python_repos[0].name == "stub-python-repo"
                assert python_repos[0].workspace == repo_dir

            finally:
                # Clean up test directory
                import shutil

                if os.path.exists(repo_dir):
                    shutil.rmtree(repo_dir)

    def test_integration_repository_validation_failure(self):
        """Test integration when repository validation fails."""
        config_data = {
            "repositories": {
                "empty-python-repo": {
                    "workspace": "/tmp/test-empty-python-repo",
                    "port": 8081,
                    "description": "Test empty Python repository",
                    "language": "python",
                    "python_path": "/usr/bin/python3",
                }
            }
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create config file
            config_path = os.path.join(tmp_dir, "repositories.json")
            with open(config_path, "w") as f:
                json.dump(config_data, f)

            # Create test repository directory without Python files
            repo_dir = "/tmp/test-empty-python-repo"
            create_git_repo(repo_dir)

            try:
                # Create non-Python files
                with open(os.path.join(repo_dir, "README.md"), "w") as f:
                    f.write("# Test Repository")

                with open(os.path.join(repo_dir, "config.json"), "w") as f:
                    f.write("{}")

                # Create repository manager
                repo_manager = RepositoryManager(config_path)
                # Should fail validation due to missing Python files
                assert repo_manager.load_configuration() is False

            finally:
                # Clean up test directory
                import shutil

                if os.path.exists(repo_dir):
                    shutil.rmtree(repo_dir)

    def test_integration_get_repository_by_name(self):
        """Test getting specific repository by name."""
        config_data = {
            "repositories": {
                "repo1": {
                    "workspace": "/tmp/test-repo1",
                    "port": 8081,
                    "description": "Test repository 1",
                    "language": "python",
                    "python_path": "/usr/bin/python3",
                },
                "repo2": {
                    "workspace": "/tmp/test-repo2",
                    "port": 8082,
                    "description": "Test repository 2",
                    "language": "python",
                    "python_path": "/usr/bin/python3",
                },
            }
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create config file
            config_path = os.path.join(tmp_dir, "repositories.json")
            with open(config_path, "w") as f:
                json.dump(config_data, f)

            # Create test repository directories
            repo1_dir = "/tmp/test-repo1"
            repo2_dir = "/tmp/test-repo2"
            create_git_repo(repo1_dir)
            create_git_repo(repo2_dir)

            try:
                # Create Python files in both repositories
                with open(os.path.join(repo1_dir, "test1.py"), "w") as f:
                    f.write("print('repo1')")

                with open(os.path.join(repo2_dir, "test2.py"), "w") as f:
                    f.write("print('repo2')")

                # Create repository manager
                repo_manager = RepositoryManager(config_path)
                assert repo_manager.load_configuration() is True

                # Create codebase repository config manager
                codebase_manager = PythonRepositoryManager(repo_manager)

                # Get specific repository by name
                repo1_config = codebase_manager.get_repository_by_name("repo1")
                repo2_config = codebase_manager.get_repository_by_name("repo2")
                non_existent = codebase_manager.get_repository_by_name("repo3")

                # Check repo1
                assert repo1_config is not None
                assert repo1_config.name == "repo1"
                assert repo1_config.workspace == repo1_dir
                assert repo1_config.description == "Test repository 1"

                # Check repo2
                assert repo2_config is not None
                assert repo2_config.name == "repo2"
                assert repo2_config.workspace == repo2_dir
                assert repo2_config.description == "Test repository 2"

                # Check non-existent
                assert non_existent is None

            finally:
                # Clean up test directories
                import shutil

                if os.path.exists(repo1_dir):
                    shutil.rmtree(repo1_dir)
                if os.path.exists(repo2_dir):
                    shutil.rmtree(repo2_dir)

    def test_integration_configuration_validation(self):
        """Test repository configuration validation."""
        config_data = {
            "repositories": {
                "valid-python-repo": {
                    "workspace": "/tmp/test-valid-python-repo",
                    "port": 8081,
                    "description": "Valid Python repository",
                    "language": "python",
                    "python_path": "/usr/bin/python3",
                },
                "invalid-python-repo": {
                    "workspace": "/tmp/test-invalid-python-repo",
                    "port": 8082,
                    "description": "Invalid Python repository",
                    "language": "python",
                    "python_path": "/usr/bin/python3",
                },
                "swift-repo": {
                    "workspace": "/tmp/test-swift-repo",
                    "port": 8083,
                    "description": "Swift repository",
                    "language": "swift",
                    "python_path": "/usr/bin/python3",
                },
            }
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create config file
            config_path = os.path.join(tmp_dir, "repositories.json")
            with open(config_path, "w") as f:
                json.dump(config_data, f)

            # Create test repository directories
            valid_repo_dir = "/tmp/test-valid-python-repo"
            invalid_repo_dir = "/tmp/test-invalid-python-repo"
            swift_repo_dir = "/tmp/test-swift-repo"

            create_git_repo(valid_repo_dir)
            create_git_repo(invalid_repo_dir)
            create_git_repo(swift_repo_dir)

            try:
                # Create Python file in valid repo
                with open(os.path.join(valid_repo_dir, "test.py"), "w") as f:
                    f.write("print('valid')")

                # Create a Python file in invalid repo too (for this test, make it valid)
                with open(os.path.join(invalid_repo_dir, "test.py"), "w") as f:
                    f.write("print('also valid')")

                # Create Swift file in Swift repo
                with open(os.path.join(swift_repo_dir, "test.swift"), "w") as f:
                    f.write('print("swift")')

                # Create repository manager
                repo_manager = RepositoryManager(config_path)
                assert repo_manager.load_configuration() is True

                # Create codebase repository config manager
                codebase_manager = PythonRepositoryManager(repo_manager)

                # Validate configuration
                is_valid = codebase_manager.validate_repository_configuration()

                # Should be valid because we have at least one valid Python repository
                assert is_valid is True

                # Get Python repositories - should include both valid Python repos
                python_repos = codebase_manager.get_python_repositories()
                assert len(python_repos) == 2
                python_repo_names = [repo.name for repo in python_repos]
                assert "valid-python-repo" in python_repo_names
                assert "invalid-python-repo" in python_repo_names

            finally:
                # Clean up test directories
                import shutil

                if os.path.exists(valid_repo_dir):
                    shutil.rmtree(valid_repo_dir)
                if os.path.exists(invalid_repo_dir):
                    shutil.rmtree(invalid_repo_dir)
                if os.path.exists(swift_repo_dir):
                    shutil.rmtree(swift_repo_dir)

    def test_integration_factory_function(self):
        """Test the factory function for creating manager."""
        config_data = {
            "repositories": {
                "test-repo": {
                    "workspace": "/tmp/test-factory-repo",
                    "port": 8081,
                    "description": "Test factory repository",
                    "language": "python",
                    "python_path": "/usr/bin/python3",
                }
            }
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create config file
            config_path = os.path.join(tmp_dir, "repositories.json")
            with open(config_path, "w") as f:
                json.dump(config_data, f)

            # Create test repository directory
            repo_dir = "/tmp/test-factory-repo"
            create_git_repo(repo_dir)

            try:
                # Create Python file
                with open(os.path.join(repo_dir, "test.py"), "w") as f:
                    f.write("print('factory test')")

                # Create manager using factory function
                manager = create_python_repository_manager(config_path)

                # Test that it works
                assert isinstance(manager, PythonRepositoryManager)

                python_repos = manager.get_python_repositories()
                assert len(python_repos) == 1
                assert python_repos[0].name == "test-repo"

            finally:
                # Clean up test directory
                import shutil

                if os.path.exists(repo_dir):
                    shutil.rmtree(repo_dir)
