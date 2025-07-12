#!/usr/bin/env python3

"""
Integration tests for codebase_cli.py
Tests the CLI with actual MCP tools and real data.
"""

import tempfile
from pathlib import Path

import pytest

from codebase_cli import execute_tool_command


class TestCodebaseCLIIntegration:
    """Integration tests for codebase CLI with actual tools."""

    @pytest.mark.asyncio
    async def test_search_symbols_integration(self, in_memory_symbol_storage):
        """Test search_symbols tool execution through CLI interface."""
        # Test that the tool executes without error and returns expected structure
        result = await execute_tool_command(
            "search_symbols",
            {"query": "test", "limit": 10},
            "test-repo",
            "/fake/path",
            in_memory_symbol_storage,
        )

        # Verify results structure
        assert "symbols" in result
        assert "total_results" in result
        assert "query" in result
        assert "repository" in result
        assert result["query"] == "test"
        assert result["repository"] == "test-repo"

        # Symbols list should be present (might be empty due to in-memory DB)
        assert isinstance(result["symbols"], list)

    @pytest.mark.asyncio
    async def test_search_symbols_with_kind_filter(self, in_memory_symbol_storage):
        """Test search_symbols with symbol kind filtering."""
        # Test that symbol kind filtering is properly passed through
        result = await execute_tool_command(
            "search_symbols",
            {"query": "user", "symbol_kind": "function", "limit": 10},
            "test-repo",
            "/fake/path",
            in_memory_symbol_storage,
        )

        # Verify results structure
        assert "symbols" in result
        assert "query" in result
        assert "repository" in result
        assert result["query"] == "user"
        assert result["repository"] == "test-repo"

        # Results list should be present (might be empty)
        assert isinstance(result["symbols"], list)

    @pytest.mark.asyncio
    async def test_search_symbols_limit_validation(self, in_memory_symbol_storage):
        """Test search_symbols with invalid limit."""
        result = await execute_tool_command(
            "search_symbols",
            {"query": "test", "limit": 150},
            "test-repo",
            "/fake/path",
            in_memory_symbol_storage,
        )

        # Should return error for invalid limit
        assert "error" in result
        assert "Limit must be between 1 and 100" in result["error"]

    @pytest.mark.asyncio
    async def test_health_check_integration(self, in_memory_symbol_storage):
        """Test health_check tool integration."""
        # Create a temporary directory with git repo
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_path = Path(temp_dir) / "test-repo"
            repo_path.mkdir()

            # Initialize git repo
            import subprocess

            subprocess.run(["git", "init"], cwd=repo_path, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=repo_path,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"], cwd=repo_path, check=True
            )

            # Create a test file and commit
            test_file = repo_path / "test.py"
            test_file.write_text("print('Hello, World!')")
            subprocess.run(["git", "add", "test.py"], cwd=repo_path, check=True)
            subprocess.run(
                ["git", "commit", "-m", "Initial commit"], cwd=repo_path, check=True
            )

            # Execute health_check tool (requires symbol_storage parameter but doesn't use it)
            result = await execute_tool_command(
                "codebase_health_check",
                {},
                "test-repo",
                str(repo_path),
                in_memory_symbol_storage,
            )

            # Verify results
            assert "status" in result
            assert "checks" in result
            assert result["repo"] == "test-repo"
            assert result["workspace"] == str(repo_path)

            # Verify checks passed
            checks = result["checks"]
            assert checks["path_exists"] is True
            assert checks["is_directory"] is True
            assert checks["is_git_repo"] is True
            assert checks["git_responsive"] is True

            # Should be healthy
            assert result["status"] in ["healthy", "warning"]  # warnings are OK

    @pytest.mark.asyncio
    async def test_health_check_nonexistent_path(self, in_memory_symbol_storage):
        """Test health_check with nonexistent path."""
        result = await execute_tool_command(
            "codebase_health_check",
            {},
            "test-repo",
            "/nonexistent/path",
            in_memory_symbol_storage,
        )

        # Should return unhealthy status
        assert result["status"] == "unhealthy"
        assert result["checks"]["path_exists"] is False
        assert len(result["errors"]) > 0

    # Note: Complex integration tests removed to focus on unit testing with dependency injection.
    # The execute_tool_command function is thoroughly tested above and provides the core functionality.

    @pytest.mark.asyncio
    async def test_tool_error_handling(self, in_memory_symbol_storage):
        """Test error handling in tool execution."""
        # Test with invalid tool
        result = await execute_tool_command(
            "invalid_tool",
            {"param": "value"},
            "test-repo",
            "/fake/path",
            in_memory_symbol_storage,
        )

        assert "error" in result
        assert "Unknown tool: invalid_tool" in result["error"]
        assert "available_tools" in result

        # Verify available tools are listed
        available_tools = result["available_tools"]
        assert "search_symbols" in available_tools
        assert "codebase_health_check" in available_tools
