#!/usr/bin/env python3

"""
Integration tests for codebase_cli.py
Tests the CLI with actual MCP tools and real data.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from codebase_cli import execute_tool_command, main


class TestCodebaseCLIIntegration:
    """Integration tests for codebase CLI with actual tools."""

    @pytest.mark.asyncio
    async def test_search_symbols_integration(self):
        """Test search_symbols tool execution through CLI interface."""
        # Test that the tool executes without error and returns expected structure
        result = await execute_tool_command(
            "search_symbols",
            {"query": "test", "limit": 10},
            "test-repo",
            "/fake/path",
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
    async def test_search_symbols_with_kind_filter(self):
        """Test search_symbols with symbol kind filtering."""
        # Test that symbol kind filtering is properly passed through
        result = await execute_tool_command(
            "search_symbols",
            {"query": "user", "symbol_kind": "function", "limit": 10},
            "test-repo",
            "/fake/path",
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
    async def test_search_symbols_limit_validation(self):
        """Test search_symbols with invalid limit."""
        result = await execute_tool_command(
            "search_symbols",
            {"query": "test", "limit": 150},
            "test-repo",
            "/fake/path",
        )

        # Should return error for invalid limit
        assert "error" in result
        assert "Limit must be between 1 and 100" in result["error"]

    @pytest.mark.asyncio
    async def test_health_check_integration(self):
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

            # Execute health_check tool
            result = await execute_tool_command(
                "codebase_health_check",
                {},
                "test-repo",
                str(repo_path),
            )

            # Verify results
            assert "status" in result
            assert "checks" in result
            assert result["repo"] == "test-repo"
            assert result["path"] == str(repo_path)

            # Verify checks passed
            checks = result["checks"]
            assert checks["path_exists"] is True
            assert checks["is_directory"] is True
            assert checks["is_git_repo"] is True
            assert checks["git_responsive"] is True

            # Should be healthy
            assert result["status"] in ["healthy", "warning"]  # warnings are OK

    @pytest.mark.asyncio
    async def test_health_check_nonexistent_path(self):
        """Test health_check with nonexistent path."""
        result = await execute_tool_command(
            "codebase_health_check",
            {},
            "test-repo",
            "/nonexistent/path",
        )

        # Should return unhealthy status
        assert result["status"] == "unhealthy"
        assert result["checks"]["path_exists"] is False
        assert len(result["errors"]) > 0

    @pytest.mark.asyncio
    async def test_main_integration_search_symbols(self):
        """Test main function integration with search_symbols."""
        # Create test repository configuration
        test_config = {
            "test-repo": {
                "path": "/fake/path",
                "language": "python",
            }
        }

        test_args = [
            "search_symbols",
            "--repo",
            "test-repo",
            "--query",
            "test_func",
            "--format",
            "json",
            "--limit",
            "5",
        ]

        with patch("sys.argv", ["codebase_cli.py", *test_args]):
            with patch("codebase_cli.RepositoryManager") as mock_repo_manager:
                with patch("pathlib.Path.exists", return_value=True):
                    with patch("builtins.print") as mock_print:
                        # Setup repository manager mock
                        mock_repo_manager.return_value.get_repository.return_value = (
                            test_config["test-repo"]
                        )

                        # Execute main - expect SystemExit due to empty database error
                        with pytest.raises(SystemExit):
                            await main()

                        # Verify print was called for the final output
                        assert mock_print.called

                        # Get the last call which should be the JSON output
                        last_call = mock_print.call_args_list[-1]
                        output = last_call[0][0]
                        result = json.loads(output)

                        # Verify result structure
                        assert "query" in result
                        assert "repository" in result
                        assert "symbols" in result
                        assert result["query"] == "test_func"
                        assert result["repository"] == "test-repo"

    @pytest.mark.asyncio
    async def test_main_integration_health_check(self):
        """Test main function integration with health_check."""
        # Create test repository configuration
        test_config = {
            "test-repo": {
                "path": "/fake/path",
                "language": "python",
            }
        }

        test_args = [
            "codebase_health_check",
            "--repo",
            "test-repo",
            "--format",
            "table",
        ]

        with patch("sys.argv", ["codebase_cli.py", *test_args]):
            with patch("codebase_cli.RepositoryManager") as mock_repo_manager:
                with patch("pathlib.Path.exists", return_value=True):
                    with patch("builtins.print") as mock_print:
                        # Setup repository manager mock
                        mock_repo_manager.return_value.get_repository.return_value = (
                            test_config["test-repo"]
                        )

                        # Execute main
                        await main()

                        # Verify print was called
                        mock_print.assert_called_once()

                        # Verify output format
                        output = mock_print.call_args[0][0]

                        # Should contain table-formatted output
                        assert "Repository:" in output
                        assert "Status:" in output
                        assert "test-repo" in output

    @pytest.mark.asyncio
    async def test_tool_error_handling(self):
        """Test error handling in tool execution."""
        # Test with invalid tool
        result = await execute_tool_command(
            "invalid_tool",
            {"param": "value"},
            "test-repo",
            "/fake/path",
        )

        assert "error" in result
        assert "Unknown tool: invalid_tool" in result["error"]
        assert "available_tools" in result

        # Verify available tools are listed
        available_tools = result["available_tools"]
        assert "search_symbols" in available_tools
        assert "codebase_health_check" in available_tools
