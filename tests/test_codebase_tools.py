#!/usr/bin/env python3

"""
Tests for codebase_tools module
"""

import json
import tempfile
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest

import codebase_tools
from repository_manager import RepositoryConfig, RepositoryManager


def create_test_repository_config(**kwargs):
    """Helper method to create RepositoryConfig with defaults"""
    defaults = {
        "name": "test-repo",
        "path": "/path/to/repo",
        "description": "Test repository",
        "language": "python",
        "port": 8000,
        "python_path": "/usr/bin/python3",
    }
    defaults.update(kwargs)
    return RepositoryConfig.create_repository_config(
        name=str(defaults["name"]),
        path=str(defaults["path"]),
        description=str(defaults["description"]),
        language=str(defaults["language"]),
        port=cast(int, defaults["port"]),
        python_path=str(defaults["python_path"])
        if defaults.get("python_path")
        else None,
    )


@pytest.fixture
def temp_repo():
    """Create a temporary repository for testing"""
    with tempfile.TemporaryDirectory() as temp_dir:
        repo_path = Path(temp_dir)

        # Create .git directory
        (repo_path / ".git").mkdir()

        # Create some Python files
        (repo_path / "main.py").write_text("print('hello')")
        (repo_path / "requirements.txt").write_text("requests>=2.0.0")
        (repo_path / "README.md").write_text("# Test Repository")

        yield str(repo_path)


@pytest.fixture
def mock_repo_manager():
    """Create a mock repository manager"""
    repo_manager = RepositoryManager()
    return repo_manager


class TestCodebaseTools:
    """Test cases for codebase tools"""

    def test_get_tools(self):
        """Test that get_tools returns correct tool definitions"""
        repo_name = "test-repo"
        repo_path = "/test/path"

        tools = codebase_tools.get_tools(repo_name, repo_path)

        assert isinstance(tools, list)
        assert len(tools) == 1

        health_check_tool = tools[0]
        assert health_check_tool["name"] == "codebase_health_check"
        assert repo_path in health_check_tool["description"]
        assert health_check_tool["inputSchema"]["type"] == "object"
        assert health_check_tool["inputSchema"]["required"] == []

    @pytest.mark.asyncio
    async def test_health_check_no_repo_manager(self):
        """Test health check when repository manager is not initialized"""
        with patch("github_tools.repo_manager", None):
            result = await codebase_tools.execute_codebase_health_check("test-repo")

            data = json.loads(result)
            assert "error" in data
            assert "Repository manager not initialized" in data["error"]
            assert data["repo"] == "test-repo"

    @pytest.mark.asyncio
    async def test_health_check_repo_not_found(self, mock_repo_manager):
        """Test health check when repository is not found in configuration"""
        with patch("github_tools.repo_manager", mock_repo_manager):
            result = await codebase_tools.execute_codebase_health_check(
                "nonexistent-repo"
            )

            data = json.loads(result)
            assert "error" in data
            assert "not found in configuration" in data["error"]
            assert data["repo"] == "nonexistent-repo"

    @pytest.mark.asyncio
    async def test_health_check_healthy_python_repo(self, temp_repo, mock_repo_manager):
        """Test health check on a healthy Python repository"""
        repo_config = create_test_repository_config(
            name="test-repo",
            path=temp_repo,
            description="Test repository",
            language="python",
        )
        mock_repo_manager.repositories["test-repo"] = repo_config

        with patch("github_tools.repo_manager", mock_repo_manager):
            result = await codebase_tools.execute_codebase_health_check("test-repo")

            data = json.loads(result)
            assert data["repo"] == "test-repo"
            assert data["path"] == temp_repo
            assert data["status"] in [
                "healthy",
                "warning",
            ]  # May have warnings but should not be unhealthy

            # Check specific assertions
            checks = data["checks"]
            assert checks["path_exists"] is True
            assert checks["is_git_repo"] is True
            assert checks["has_requirements_txt"] is True
            assert checks["has_readme"] is True
            assert checks["python_file_count"] >= 1

    @pytest.mark.asyncio
    async def test_health_check_nonexistent_path(self, mock_repo_manager):
        """Test health check on a repository with nonexistent path"""
        repo_config = create_test_repository_config(
            name="test-repo",
            path="/nonexistent/path",
            description="Test repository",
            language="python",
        )
        mock_repo_manager.repositories["test-repo"] = repo_config

        with patch("github_tools.repo_manager", mock_repo_manager):
            result = await codebase_tools.execute_codebase_health_check("test-repo")

            data = json.loads(result)
            assert data["status"] == "unhealthy"
            assert "Repository path does not exist" in data["errors"]
            assert data["checks"]["path_exists"] is False

    @pytest.mark.asyncio
    async def test_health_check_not_git_repo(self, mock_repo_manager):
        """Test health check on a directory that's not a Git repository"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Don't create .git directory
            repo_config = create_test_repository_config(
                name="test-repo",
                path=temp_dir,
                description="Test repository",
                language="python",
            )
            mock_repo_manager.repositories["test-repo"] = repo_config

            with patch("github_tools.repo_manager", mock_repo_manager):
                result = await codebase_tools.execute_codebase_health_check("test-repo")

                data = json.loads(result)
                assert data["status"] == "unhealthy"
                assert "Not a Git repository" in data["errors"][0]
                assert data["checks"]["is_git_repo"] is False

    @pytest.mark.asyncio
    async def test_health_check_swift_repo(self, mock_repo_manager):
        """Test health check on a Swift repository"""
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_path = Path(temp_dir)

            # Create .git directory
            (repo_path / ".git").mkdir()

            # Create Swift-specific files
            (repo_path / "Package.swift").write_text("// swift-tools-version:5.0")
            (repo_path / "main.swift").write_text('print("hello")')
            (repo_path / "README.md").write_text("# Swift Test Repository")

            repo_config = create_test_repository_config(
                name="swift-repo",
                path=str(repo_path),
                description="Swift test repository",
                language="swift",
            )
            mock_repo_manager.repositories["swift-repo"] = repo_config

            with patch("github_tools.repo_manager", mock_repo_manager):
                result = await codebase_tools.execute_codebase_health_check(
                    "swift-repo"
                )

                data = json.loads(result)
                assert data["repo"] == "swift-repo"
                assert data["status"] in ["healthy", "warning"]

                checks = data["checks"]
                assert checks["path_exists"] is True
                assert checks["is_git_repo"] is True
                assert checks["has_Package_swift"] is True
                assert checks["has_readme"] is True
                assert checks["swift_file_count"] >= 1

    @pytest.mark.asyncio
    async def test_health_check_repo_with_uncommitted_changes(
        self, temp_repo, mock_repo_manager
    ):
        """Test health check on a repository with uncommitted changes"""
        repo_config = create_test_repository_config(
            name="test-repo",
            path=temp_repo,
            description="Test repository",
            language="python",
        )
        mock_repo_manager.repositories["test-repo"] = repo_config

        # Mock git status to return uncommitted changes
        with (
            patch("github_tools.repo_manager", mock_repo_manager),
            patch("subprocess.run") as mock_run,
        ):
            # Mock git status output showing uncommitted changes
            mock_run.return_value.stdout = "M main.py\n?? new_file.py\n"
            mock_run.return_value.check = True

            result = await codebase_tools.execute_codebase_health_check("test-repo")

            data = json.loads(result)
            assert "Repository has uncommitted changes" in data["warnings"]
            assert data["checks"]["clean_working_tree"] is False

    @pytest.mark.asyncio
    async def test_health_check_exception_handling(self, mock_repo_manager):
        """Test that health check handles exceptions gracefully"""
        repo_config = create_test_repository_config(
            name="test-repo",
            path="/valid/path",
            description="Test repository",
            language="python",
        )
        mock_repo_manager.repositories["test-repo"] = repo_config

        # Mock an exception during health check
        with (
            patch("github_tools.repo_manager", mock_repo_manager),
            patch("pathlib.Path.exists", side_effect=Exception("Test exception")),
        ):
            result = await codebase_tools.execute_codebase_health_check("test-repo")

            data = json.loads(result)
            assert "error" in data
            assert "Health check failed" in data["error"]
            assert data["status"] == "error"
            assert data["repo"] == "test-repo"


if __name__ == "__main__":
    pytest.main([__file__])
