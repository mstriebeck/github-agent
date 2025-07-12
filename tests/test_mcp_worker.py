#!/usr/bin/env python3

"""
Tests for the unified MCP worker
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from constants import Language
from mcp_worker import MCPWorker


@pytest.fixture
def temp_repo():
    """Create a temporary repository for testing"""
    with tempfile.TemporaryDirectory() as temp_dir:
        repo_path = Path(temp_dir)

        # Create .git directory and config
        git_dir = repo_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text(
            '[remote "origin"]\n    url = https://github.com/test/test-repo.git\n'
        )

        # Create some Python files
        (repo_path / "main.py").write_text("print('hello')")
        (repo_path / "requirements.txt").write_text("requests>=2.0.0")
        (repo_path / "README.md").write_text("# Test Repository")

        yield str(repo_path)


@pytest.fixture
def mock_github_token():
    """Mock GitHub token environment variable"""
    with patch.dict(os.environ, {"GITHUB_TOKEN": "test_token_123"}):
        yield


@pytest.fixture
def mock_subprocess():
    """Mock subprocess calls for git operations"""
    with patch("subprocess.check_output") as mock_check_output:
        mock_check_output.return_value = b"https://github.com/test/test-repo.git"
        yield mock_check_output


class TestMCPWorker:
    """Test cases for the unified MCP worker"""

    def test_worker_initialization(self, temp_repo, mock_github_token, mock_subprocess):
        """Test that the worker initializes correctly"""
        with patch("github_tools.Github"), patch("mcp_worker.GitHubAPIContext"):
            from repository_manager import RepositoryConfig

            repo_config = RepositoryConfig.create_repository_config(
                name="test-repo",
                workspace=temp_repo,
                description="Test repository",
                language=Language.PYTHON,
                port=8080,
                python_path="/usr/bin/python3",
            )
            worker = MCPWorker(repo_config)

            assert worker.repo_name == "test-repo"
            assert worker.repo_path == temp_repo
            assert worker.port == 8080
            assert worker.description == "Test repository"
            assert worker.language == Language.PYTHON

    def test_worker_invalid_path(self, mock_github_token):
        """Test that worker fails with invalid repository path"""
        with pytest.raises(ValueError, match="Repository path .* does not exist"):
            from repository_manager import RepositoryConfig

            repo_config = RepositoryConfig.create_repository_config(
                name="test-repo",
                workspace="/nonexistent/path",
                description="Test repository",
                language=Language.PYTHON,
                port=8080,
                python_path="/usr/bin/python3",
            )
            MCPWorker(repo_config)

    def test_fastapi_app_creation(self, temp_repo, mock_github_token, mock_subprocess):
        """Test that the FastAPI app is created correctly"""
        with patch("github_tools.Github"), patch("mcp_worker.GitHubAPIContext"):
            from repository_manager import RepositoryConfig

            repo_config = RepositoryConfig.create_repository_config(
                name="test-repo",
                workspace=temp_repo,
                description="Test repository",
                language=Language.PYTHON,
                port=8080,
                python_path="/usr/bin/python3",
            )
            worker = MCPWorker(repo_config)

            assert worker.app is not None
            assert worker.app.title == "MCP Worker - test-repo"

    def test_app_endpoints(self, temp_repo, mock_github_token, mock_subprocess):
        """Test that the app has the correct endpoints"""
        with patch("github_tools.Github"), patch("mcp_worker.GitHubAPIContext"):
            from repository_manager import RepositoryConfig

            repo_config = RepositoryConfig.create_repository_config(
                name="test-repo",
                workspace=temp_repo,
                description="Test repository",
                language=Language.PYTHON,
                port=8080,
                python_path="/usr/bin/python3",
            )
            worker = MCPWorker(repo_config)

            client = TestClient(worker.app)

            # Test root endpoint
            response = client.get("/")
            assert response.status_code == 200
            data = response.json()
            assert data["name"] == "MCP Worker - test-repo"
            assert data["repository"] == "test-repo"
            assert data["port"] == 8080
            assert "github" in data["tool_categories"]
            assert "codebase" in data["tool_categories"]

    def test_health_endpoint(self, temp_repo, mock_github_token, mock_subprocess):
        """Test the health check endpoint"""
        with patch("github_tools.Github"), patch("mcp_worker.GitHubAPIContext"):
            from repository_manager import RepositoryConfig

            repo_config = RepositoryConfig.create_repository_config(
                name="test-repo",
                workspace=temp_repo,
                description="Test repository",
                language=Language.PYTHON,
                port=8080,
                python_path="/usr/bin/python3",
            )
            worker = MCPWorker(repo_config)

            client = TestClient(worker.app)

            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["repository"] == "test-repo"
            assert data["github_configured"] is True
            assert data["repo_path_exists"] is True
            assert "github" in data["tool_categories"]
            assert "codebase" in data["tool_categories"]

    def test_mcp_initialize(self, temp_repo, mock_github_token, mock_subprocess):
        """Test MCP initialize method"""
        with patch("github_tools.Github"), patch("mcp_worker.GitHubAPIContext"):
            from repository_manager import RepositoryConfig

            repo_config = RepositoryConfig.create_repository_config(
                name="test-repo",
                workspace=temp_repo,
                description="Test repository",
                language=Language.PYTHON,
                port=8080,
                python_path="/usr/bin/python3",
            )
            worker = MCPWorker(repo_config)

            client = TestClient(worker.app)

            # Test MCP initialize
            initialize_request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {},
            }

            response = client.post("/mcp/", json=initialize_request)
            assert response.status_code == 200
            assert response.json()["status"] == "queued"

            # Check that response was queued
            assert not worker.message_queue.empty()
            queued_response = worker.message_queue.get()
            assert (
                queued_response["result"]["serverInfo"]["name"] == "mcp-agent-test-repo"
            )

    def test_mcp_tools_list(self, temp_repo, mock_github_token, mock_subprocess):
        """Test MCP tools/list method"""
        with patch("github_tools.Github"), patch("mcp_worker.GitHubAPIContext"):
            from repository_manager import RepositoryConfig

            repo_config = RepositoryConfig.create_repository_config(
                name="test-repo",
                workspace=temp_repo,
                description="Test repository",
                language=Language.PYTHON,
                port=8080,
                python_path="/usr/bin/python3",
            )
            worker = MCPWorker(repo_config)

            client = TestClient(worker.app)

            # Test tools/list
            tools_request = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            }

            response = client.post("/mcp/", json=tools_request)
            assert response.status_code == 200
            assert response.json()["status"] == "queued"

            # Check that response was queued
            assert not worker.message_queue.empty()
            queued_response = worker.message_queue.get()
            tools = queued_response["result"]["tools"]

            # Should have both GitHub and codebase tools
            tool_names = [tool["name"] for tool in tools]

            # Check for GitHub tools
            assert "git_get_current_branch" in tool_names
            assert "git_get_current_commit" in tool_names
            assert "github_find_pr_for_branch" in tool_names
            assert "github_get_pr_comments" in tool_names
            assert "github_post_pr_reply" in tool_names
            assert "github_check_ci_build_and_test_errors_not_local" in tool_names
            assert "github_check_ci_lint_errors_not_local" in tool_names
            assert "github_get_build_status" in tool_names

            # Check for codebase tools
            assert "codebase_health_check" in tool_names

    @pytest.mark.asyncio
    async def test_mcp_tool_call_codebase_health_check(
        self, temp_repo, mock_github_token, mock_subprocess
    ):
        """Test MCP tool call for codebase health check"""
        with patch("github_tools.Github"), patch("mcp_worker.GitHubAPIContext"):
            from repository_manager import RepositoryConfig

            repo_config = RepositoryConfig.create_repository_config(
                name="test-repo",
                workspace=temp_repo,
                description="Test repository",
                language=Language.PYTHON,
                port=8080,
                python_path="/usr/bin/python3",
            )
            worker = MCPWorker(repo_config)

            client = TestClient(worker.app)

            # Test codebase health check tool call
            tool_call_request = {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "codebase_health_check", "arguments": {}},
            }

            response = client.post("/mcp/", json=tool_call_request)
            assert response.status_code == 200
            assert response.json()["status"] == "queued"

            # Check that response was queued
            assert not worker.message_queue.empty()
            queued_response = worker.message_queue.get()
            result_text = queued_response["result"]["content"][0]["text"]
            assert (
                '"status":' in result_text
            )  # Accept any status (healthy, warning, etc.)
            assert '"repo": "test-repo"' in result_text

            # This is now an integration test - the actual health check runs

    def test_mcp_unknown_tool(self, temp_repo, mock_github_token, mock_subprocess):
        """Test MCP tool call for unknown tool"""
        with patch("github_tools.Github"), patch("mcp_worker.GitHubAPIContext"):
            from repository_manager import RepositoryConfig

            repo_config = RepositoryConfig.create_repository_config(
                name="test-repo",
                workspace=temp_repo,
                description="Test repository",
                language=Language.PYTHON,
                port=8080,
                python_path="/usr/bin/python3",
            )
            worker = MCPWorker(repo_config)

            client = TestClient(worker.app)

            # Test unknown tool call
            tool_call_request = {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "unknown_tool", "arguments": {}},
            }

            response = client.post("/mcp/", json=tool_call_request)
            assert response.status_code == 200
            assert response.json()["status"] == "queued"

            # Check that error response was queued
            assert not worker.message_queue.empty()
            queued_response = worker.message_queue.get()
            result_text = queued_response["result"]["content"][0]["text"]
            assert '"error"' in result_text
            assert "not implemented" in result_text

    def test_shutdown_endpoint(self, temp_repo, mock_github_token, mock_subprocess):
        """Test the shutdown endpoint"""
        with patch("github_tools.Github"), patch("mcp_worker.GitHubAPIContext"):
            from repository_manager import RepositoryConfig

            repo_config = RepositoryConfig.create_repository_config(
                name="test-repo",
                workspace=temp_repo,
                description="Test repository",
                language=Language.PYTHON,
                port=8080,
                python_path="/usr/bin/python3",
            )
            worker = MCPWorker(repo_config)

            client = TestClient(worker.app)

            response = client.post("/shutdown")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "shutdown_initiated"

            # Check that shutdown event is set
            assert worker.shutdown_event.is_set()


if __name__ == "__main__":
    pytest.main([__file__])
