#!/usr/bin/env python3

"""
Integration Tests for MCP Master-Worker System (US001-12)

This test suite validates the complete end-to-end workflow from repository
configuration through MCP server startup to tool execution. It uses a hybrid
approach with dynamic port allocation and process mocking to avoid conflicts
with production servers running on the same machine.

Test Architecture:
1. Dynamic port allocation prevents conflicts with production servers
2. Process mocking simulates worker startup without actual subprocess spawning
3. Real tool loading and execution validates the complete integration
4. Temporary git repositories provide realistic test environments

IMPORTANT: This test is designed to work alongside a running production server
by using different ports and mocking process creation. Do not modify the
mocking strategy without ensuring it still avoids production conflicts.
"""

import json
import socket
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import codebase_tools
import github_tools
import mcp_master
from constants import Language
from repository_manager import RepositoryManager


def find_free_port() -> int:
    """
    Dynamically find an available port to avoid conflicts with production servers.

    This is critical because the production MCP server may already be running
    on ports 8081-8082. By using dynamic allocation, we ensure our tests
    never conflict with production instances.

    Returns:
        int: An available port number
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("localhost", 0))  # Bind to any available port
        return s.getsockname()[1]  # Return the allocated port


# temp_git_repo fixture now consolidated in conftest.py


@pytest.fixture
def test_config_with_dynamic_port(temp_git_repo):
    """
    Create a test repository configuration with dynamically allocated port.

    This configuration includes all required fields from the repository
    schema validation (port, path, language, python_path) and uses
    a dynamically allocated port to avoid conflicts.

    Args:
        temp_git_repo: Path to the temporary git repository

    Returns:
        tuple: (config_dict, allocated_port)
    """
    # Get a free port - this is critical to avoid conflicts with production
    test_port = find_free_port()

    # Create a complete repository configuration that matches production format
    # All these fields are required by the master's configuration validation
    config = {
        "repositories": {
            "integration-test-repo": {
                "port": test_port,
                "workspace": temp_git_repo,
                "language": Language.PYTHON.value,  # Required field
                "python_path": "/usr/bin/python3",  # Required field for US001-12
                "description": "Integration test repository",
                "github_owner": "test-owner",  # Optional but realistic
                "github_repo": "integration-test",  # Optional but realistic
            }
        }
    }

    return config, test_port


class TestMCPIntegration:
    """
    Integration tests for the complete MCP Master-Worker system.

    These tests validate US001-12 requirements:
    - End-to-end workflow with repository configuration
    - Health check tool functionality
    - Complete setup-to-server workflow
    - Both GitHub and codebase tools loading
    """

    @pytest.mark.asyncio
    async def test_end_to_end_workflow(
        self, test_config_with_dynamic_port, mcp_master_factory
    ):
        """
        Test the complete end-to-end MCP workflow from configuration to tool execution.

        This test validates:
        1. Repository configuration loading and validation
        2. Worker startup simulation (mocked to avoid process conflicts)
        3. Tool loading from both github_tools and codebase_tools modules
        4. Health check tool execution end-to-end
        5. Proper error handling throughout the workflow

        The test uses mocking strategically to avoid:
        - Port conflicts with production servers
        - Actual subprocess spawning (which could interfere with system)
        - GitHub API calls (which would require authentication)

        While still testing the real integration of:
        - Configuration parsing and validation
        - Tool loading and registration
        - Tool execution logic
        - Repository management
        """
        config, test_port = test_config_with_dynamic_port
        repo_name = "integration-test-repo"
        repo_config = config["repositories"][repo_name]
        repo_path = repo_config["workspace"]

        # ============================================================================
        # PHASE 1: Master Configuration Loading and Validation
        # ============================================================================

        # Create a temporary configuration file - this simulates the real
        # repositories.json file that the master reads on startup
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config, f, indent=2)
            config_file_path = f.name

        try:
            # Test that master can load and validate our configuration
            # This exercises the real configuration validation logic that
            # checks for required fields (port, path, language, python_path)
            master = mcp_master_factory(config_file_path)

            # Verify configuration was loaded and validated successfully
            assert master.repository_manager is not None
            assert len(master.repository_manager.repositories) > 0

            # Test that we can access the loaded repository info through workers dict
            # The master doesn't expose repositories directly, but we can verify the
            # configuration was valid by checking the load succeeded

        finally:
            # Clean up temporary config file
            Path(config_file_path).unlink()

        # ============================================================================
        # PHASE 2: Worker Startup Simulation (Mocked)
        # ============================================================================

        # Mock subprocess.Popen to simulate worker startup without actually
        # spawning processes. This is critical because:
        # 1. We don't want to interfere with production processes
        # 2. Actual worker startup would bind to ports and could conflict
        # 3. We want to test the startup logic, not the actual process management
        mock_process = MagicMock()
        mock_process.poll.return_value = None  # Simulate running process
        mock_process.pid = 12345  # Fake PID for logging
        mock_process.returncode = None  # Still running

        with patch("subprocess.Popen", return_value=mock_process) as mock_popen:
            # Test that master can start a worker with our configuration
            # This validates the worker startup logic without actual process creation

            # Create a minimal repo config object for the start_worker method
            from repository_manager import RepositoryConfig

            test_repo_config = RepositoryConfig(
                name=repo_name,
                workspace=repo_path,
                description="Integration test repo",
                language=Language.PYTHON,
                port=test_port,
                python_path="/usr/bin/python3",
                github_owner="test-owner",
                github_repo="integration-test",
            )

            # Create a WorkerProcess object as expected by start_worker
            from mcp_master import WorkerProcess

            worker = WorkerProcess(repository_config=test_repo_config)

            # Use the same master instance from the first phase
            worker_started = master.start_worker(worker)

            # Verify worker startup was attempted with correct parameters
            assert worker_started is True
            mock_popen.assert_called_once()

            # Verify the command line arguments passed to the worker
            args, kwargs = mock_popen.call_args
            command = args[0]

            # The worker should be started with correct arguments
            assert "mcp_worker.py" in " ".join(command)
            assert str(test_port) in command  # Port should be passed
            assert repo_name in command  # Repository name should be passed

        # ============================================================================
        # PHASE 3: Tool Loading Integration Test
        # ============================================================================

        # Test that worker can load tools from both modules
        # We test this directly rather than through the worker process to avoid
        # the complexity of inter-process communication in tests

        # Test GitHub tools loading
        github_tool_list = github_tools.get_tools(repo_name, repo_path)
        assert isinstance(github_tool_list, list)
        assert len(github_tool_list) > 0

        # Verify GitHub tools have proper MCP format
        for tool in github_tool_list:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool
            assert tool["inputSchema"]["type"] == "object"

        # Test codebase tools loading
        codebase_tool_list = codebase_tools.get_tools(repo_name, repo_path)
        assert isinstance(codebase_tool_list, list)
        assert len(codebase_tool_list) > 0

        # Verify codebase tools have proper MCP format
        for tool in codebase_tool_list:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool
            assert tool["inputSchema"]["type"] == "object"

        # Verify that health check tool is available (US001-12 requirement)
        health_check_tools = [
            t for t in codebase_tool_list if t["name"] == "codebase_health_check"
        ]
        assert len(health_check_tools) == 1
        health_check_tool = health_check_tools[0]
        assert repo_path in health_check_tool["description"]

        # ============================================================================
        # PHASE 4: Health Check Tool Execution (End-to-End)
        # ============================================================================

        # Test the health check tool execution end-to-end
        # This validates the complete workflow from tool registration to execution

        # Execute health check directly (simulating MCP tool call)
        health_result = await codebase_tools.execute_codebase_health_check(
            repo_name, repo_path
        )

        # Parse and validate health check results
        health_data = json.loads(health_result)

        # Verify health check structure and content
        assert health_data["repo"] == repo_name
        assert health_data["workspace"] == repo_path
        assert health_data["status"] in [
            "healthy",
            "warning",
        ]  # Should not be unhealthy/error

        # Verify specific health checks passed (these validate real repository state)
        assert health_data["checks"]["path_exists"] is True
        assert health_data["checks"]["is_directory"] is True
        assert health_data["checks"]["is_git_repo"] is True
        assert health_data["checks"]["git_responsive"] is True

        # Should have branch information from real git repo
        assert "current_branch" in health_data["checks"]

        # ============================================================================
        # PHASE 5: Tool Integration Validation
        # ============================================================================

        # Test that tools can be executed through the unified tool handler
        # This simulates how the MCP worker would route tool calls

        # Test tool execution through codebase_tools.execute_tool
        tool_result = await codebase_tools.execute_tool(
            "codebase_health_check", repo_name=repo_name, repository_workspace=repo_path
        )

        # Verify tool execution succeeded
        tool_data = json.loads(tool_result)
        assert "error" not in tool_data
        assert tool_data["repo"] == repo_name

        # Test error handling for invalid tools
        error_result = await codebase_tools.execute_tool("nonexistent_tool")
        error_data = json.loads(error_result)
        assert "error" in error_data
        assert "Unknown tool" in error_data["error"]
        assert "available_tools" in error_data
        assert "codebase_health_check" in error_data["available_tools"]

    @pytest.mark.asyncio
    async def test_repository_manager_integration(self, test_config_with_dynamic_port):
        """
        Test integration with RepositoryManager for proper repository isolation.

        This test validates that repositories are properly managed and isolated
        when multiple repositories are configured. While we only test one repo
        here, we verify the manager can handle the configuration correctly.
        """
        config, test_port = test_config_with_dynamic_port
        repo_name = "integration-test-repo"
        repo_config = config["repositories"][repo_name]

        # Create a repository manager with our test configuration
        # This simulates how the worker sets up repository management
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config, f, indent=2)
            config_file_path = f.name

        try:
            # Initialize repository manager with test configuration
            repo_manager = RepositoryManager(config_file_path)

            # Load the configuration
            loaded_successfully = repo_manager.load_configuration()
            assert loaded_successfully is True

            # Verify repository was loaded correctly
            assert repo_name in repo_manager.repositories
            loaded_config = repo_manager.repositories[repo_name]

            # Verify all required fields are present
            assert loaded_config.port == test_port
            assert loaded_config.workspace == repo_config["workspace"]
            assert loaded_config.language == Language.PYTHON
            assert loaded_config.python_path == "/usr/bin/python3"

            # Repository loading success indicates validation passed
            # The RepositoryManager validates repos during load_configuration()

        finally:
            Path(config_file_path).unlink()

    def test_port_conflict_avoidance(self):
        """
        Test that our dynamic port allocation successfully avoids conflicts.

        This test validates the core assumption of our integration test strategy:
        that we can reliably find available ports even when production servers
        are running.
        """
        # Get several ports to ensure we're not just getting lucky
        ports = []
        for _ in range(5):
            port = find_free_port()
            ports.append(port)

            # Verify port is actually free using the same logic as the master
            assert mcp_master.is_port_free(port) is True

        # All allocated ports should be different
        assert len(set(ports)) == len(ports)

        # All ports should be in reasonable range (not system ports)
        for port in ports:
            assert port > 1024  # Not system reserved
            assert port < 65536  # Valid port range

    @pytest.mark.asyncio
    async def test_configuration_validation_integration(
        self, temp_git_repo, mcp_master_factory
    ):
        """
        Test that configuration validation works end-to-end with real files.

        This test validates that the master's configuration validation
        properly rejects invalid configurations and accepts valid ones.
        """
        # Test valid configuration (should pass)
        valid_config = {
            "repositories": {
                "valid-repo": {
                    "port": find_free_port(),
                    "workspace": temp_git_repo,
                    "language": Language.PYTHON.value,
                    "python_path": "/usr/bin/python3",
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(valid_config, f, indent=2)
            valid_config_path = f.name

        try:
            # Valid configuration should load successfully
            master = mcp_master_factory(valid_config_path)
            assert master.repository_manager is not None
            assert len(master.repository_manager.repositories) > 0
        finally:
            Path(valid_config_path).unlink()

        # Test invalid configuration (missing required fields)
        invalid_config = {
            "repositories": {
                "invalid-repo": {
                    "port": find_free_port(),
                    "workspace": temp_git_repo,
                    # Missing language and python_path
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(invalid_config, f, indent=2)
            invalid_config_path = f.name

        try:
            # Invalid configuration should fail to load with RepositoryManager
            with pytest.raises(RuntimeError):
                RepositoryManager.create_from_config(invalid_config_path)
        finally:
            Path(invalid_config_path).unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
