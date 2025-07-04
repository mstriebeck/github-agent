#!/usr/bin/env python3

"""
Tests for codebase_tools module
"""

import json
import subprocess
import tempfile
from pathlib import Path

import pytest

import codebase_tools


@pytest.fixture
def temp_git_repo():
    """Create a temporary git repository for testing"""
    with tempfile.TemporaryDirectory() as temp_dir:
        repo_path = Path(temp_dir)

        # Initialize as a real git repository
        subprocess.run(["git", "init"], cwd=repo_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo_path,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=repo_path,
            capture_output=True,
        )

        # Create a test file and initial commit
        (repo_path / "test.txt").write_text("test content")
        subprocess.run(["git", "add", "."], cwd=repo_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=repo_path,
            capture_output=True,
        )

        yield str(repo_path)


@pytest.fixture
def temp_dir_not_git():
    """Create a temporary directory that's not a git repository"""
    with tempfile.TemporaryDirectory() as temp_dir:
        repo_path = Path(temp_dir)
        (repo_path / "some_file.txt").write_text("content")
        yield str(repo_path)


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
    async def test_health_check_nonexistent_path(self):
        """Test health check when repository path doesn't exist"""
        result = await codebase_tools.execute_codebase_health_check(
            "test-repo", "/nonexistent/path"
        )

        data = json.loads(result)
        assert data["repo"] == "test-repo"
        assert data["status"] == "unhealthy"
        assert data["path"] == "/nonexistent/path"
        assert len(data["errors"]) > 0
        assert "does not exist" in data["errors"][0]
        assert data["checks"]["path_exists"] is False

    @pytest.mark.asyncio
    async def test_health_check_file_not_directory(self):
        """Test health check when path points to a file, not directory"""
        with tempfile.NamedTemporaryFile() as temp_file:
            result = await codebase_tools.execute_codebase_health_check(
                "test-repo", temp_file.name
            )

            data = json.loads(result)
            assert data["status"] == "unhealthy"
            assert "not a directory" in data["errors"][0]

    @pytest.mark.asyncio
    async def test_health_check_not_git_repo(self, temp_dir_not_git):
        """Test health check when directory is not a git repository"""
        result = await codebase_tools.execute_codebase_health_check(
            "test-repo", temp_dir_not_git
        )

        data = json.loads(result)
        assert data["status"] == "unhealthy"
        assert data["checks"]["path_exists"] is True
        assert data["checks"]["is_directory"] is True
        assert "Not a Git repository" in data["errors"][0]

    @pytest.mark.asyncio
    async def test_health_check_valid_git_repo(self, temp_git_repo):
        """Test health check with a valid git repository"""
        result = await codebase_tools.execute_codebase_health_check(
            "test-repo", temp_git_repo
        )

        data = json.loads(result)
        assert data["repo"] == "test-repo"
        assert data["path"] == temp_git_repo
        assert data["status"] in [
            "healthy",
            "warning",
        ]  # Could have warnings but still be healthy
        assert len(data["errors"]) == 0

        # Check basic validations passed
        assert data["checks"]["path_exists"] is True
        assert data["checks"]["is_directory"] is True
        assert data["checks"]["is_git_repo"] is True
        assert data["checks"]["git_responsive"] is True

        # Should have current branch info
        assert "current_branch" in data["checks"]

        # Remote check (may or may not have remote)
        assert "has_remote" in data["checks"]

    @pytest.mark.asyncio
    async def test_health_check_git_repo_with_remote(self, temp_git_repo):
        """Test health check with a git repository that has a remote"""
        # Add a remote to the test repo
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/test/repo.git"],
            cwd=temp_git_repo,
            capture_output=True,
        )

        result = await codebase_tools.execute_codebase_health_check(
            "test-repo", temp_git_repo
        )

        data = json.loads(result)
        assert data["checks"]["has_remote"] is True
        assert "remote_url" in data["checks"]
        assert "github.com/test/repo.git" in data["checks"]["remote_url"]

    @pytest.mark.asyncio
    async def test_health_check_exception_handling(self):
        """Test health check handles unexpected exceptions gracefully"""
        # Pass an invalid type (bypassing type checking) to trigger an exception
        result = await codebase_tools.execute_codebase_health_check("test-repo", None)  # type: ignore

        data = json.loads(result)
        assert data["status"] == "error"
        assert "Health check failed" in data["errors"][0]
        assert data["repo"] == "test-repo"

    @pytest.mark.asyncio
    async def test_execute_tool_valid_tool(self, temp_git_repo):
        """Test execute_tool with a valid tool name"""
        result = await codebase_tools.execute_tool(
            "codebase_health_check", repo_name="test-repo", repo_path=temp_git_repo
        )

        data = json.loads(result)
        assert data["repo"] == "test-repo"
        assert "status" in data

    @pytest.mark.asyncio
    async def test_execute_tool_invalid_tool(self):
        """Test execute_tool with an invalid tool name"""
        result = await codebase_tools.execute_tool("invalid_tool", repo_name="test")

        data = json.loads(result)
        assert "error" in data
        assert "Unknown tool: invalid_tool" in data["error"]
        assert "available_tools" in data
        assert "codebase_health_check" in data["available_tools"]

    @pytest.mark.asyncio
    async def test_execute_tool_exception_handling(self):
        """Test execute_tool handles exceptions in tool execution"""
        # This will cause an exception due to missing required argument
        result = await codebase_tools.execute_tool("codebase_health_check")

        data = json.loads(result)
        assert "error" in data
        assert "Tool execution failed" in data["error"]
        assert data["tool"] == "codebase_health_check"


if __name__ == "__main__":
    pytest.main([__file__])
