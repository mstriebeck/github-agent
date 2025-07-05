#!/usr/bin/env python3

"""
Unit tests for codebase_cli.py
Tests CLI argument parsing, output formatting, and tool execution.
"""

import json
from unittest.mock import patch

import pytest

from codebase_cli import OutputFormatter, execute_tool_command, main


class TestOutputFormatter:
    """Test cases for OutputFormatter."""

    def test_format_json(self):
        """Test JSON formatting."""
        data = {"test": "value", "number": 42}
        result = OutputFormatter.format_json(data)

        # Should be valid JSON
        parsed = json.loads(result)
        assert parsed == data

        # Should be pretty-printed
        assert "\n" in result
        assert "  " in result

    def test_format_table_search_symbols(self):
        """Test table formatting for search_symbols results."""
        data = {
            "query": "test_func",
            "repository": "my-repo",
            "total_results": 2,
            "symbols": [
                {
                    "name": "test_function",
                    "kind": "function",
                    "file_path": "src/test.py",
                    "line_number": 10,
                },
                {
                    "name": "TestClass",
                    "kind": "class",
                    "file_path": "src/models.py",
                    "line_number": 25,
                },
            ],
        }

        result = OutputFormatter.format_table(data)

        assert "Query: test_func" in result
        assert "Repository: my-repo" in result
        assert "Total Results: 2" in result
        assert "test_function" in result
        assert "TestClass" in result
        assert "src/test.py" in result
        assert "10" in result

    def test_format_table_search_symbols_empty(self):
        """Test table formatting for empty search results."""
        data = {
            "query": "nonexistent",
            "repository": "my-repo",
            "total_results": 0,
            "symbols": [],
        }

        result = OutputFormatter.format_table(data)

        assert "Query: nonexistent" in result
        assert "No symbols found." in result

    def test_format_table_health_check(self):
        """Test table formatting for health check results."""
        data = {
            "repo": "my-repo",
            "path": "/path/to/repo",
            "status": "healthy",
            "checks": {
                "path_exists": True,
                "is_directory": True,
                "is_git_repo": True,
                "git_responsive": True,
            },
            "warnings": ["Minor warning"],
            "errors": [],
        }

        result = OutputFormatter.format_table(data)

        assert "Repository: my-repo" in result
        assert "Status: healthy" in result
        assert "✓ path_exists: True" in result
        assert "✓ is_git_repo: True" in result
        assert "⚠ Minor warning" in result

    def test_format_table_error(self):
        """Test table formatting for error results."""
        data = {
            "error": "Something went wrong",
            "tool": "search_symbols",
        }

        result = OutputFormatter.format_table(data)

        assert "Error: Something went wrong" in result
        assert "Tool: search_symbols" in result

    def test_format_simple_search_symbols(self):
        """Test simple formatting for search_symbols results."""
        data = {
            "query": "test_func",
            "total_results": 1,
            "symbols": [
                {
                    "name": "test_function",
                    "kind": "function",
                    "file_path": "src/test.py",
                    "line_number": 10,
                },
            ],
        }

        result = OutputFormatter.format_simple(data)

        assert "Found 1 symbols for 'test_func'" in result
        assert "test_function (function) - src/test.py:10" in result

    def test_format_simple_health_check(self):
        """Test simple formatting for health check results."""
        data = {
            "repo": "my-repo",
            "status": "healthy",
            "checks": {"path_exists": True},
            "errors": [],
            "warnings": ["Minor warning"],
        }

        result = OutputFormatter.format_simple(data)

        assert "Repository my-repo: healthy" in result
        assert "Warning: Minor warning" in result

    def test_format_simple_error(self):
        """Test simple formatting for error results."""
        data = {
            "error": "Something went wrong",
        }

        result = OutputFormatter.format_simple(data)

        assert "Error: Something went wrong" in result


class TestExecuteToolCommand:
    """Test cases for execute_tool_command."""

    @pytest.mark.asyncio
    async def test_execute_codebase_tool_success(self):
        """Test successful execution of a codebase tool."""
        with patch("codebase_tools.execute_tool") as mock_execute:
            mock_execute.return_value = '{"result": "success", "data": "test"}'

            result = await execute_tool_command(
                "search_symbols", {"query": "test"}, "my-repo", "/path/to/repo"
            )

            assert result == {"result": "success", "data": "test"}
            mock_execute.assert_called_once_with(
                "search_symbols",
                repo_name="my-repo",
                repo_path="/path/to/repo",
                query="test",
            )

    @pytest.mark.asyncio
    async def test_execute_github_tool_success(self):
        """Test successful execution of a github tool."""
        with patch("github_tools.execute_tool") as mock_execute:
            mock_execute.return_value = '{"result": "success", "data": "test"}'

            result = await execute_tool_command(
                "git_get_current_branch", {}, "my-repo", "/path/to/repo"
            )

            assert result == {"result": "success", "data": "test"}
            mock_execute.assert_called_once_with(
                "git_get_current_branch", repo_name="my-repo", repo_path="/path/to/repo"
            )

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self):
        """Test execution of an unknown tool."""
        result = await execute_tool_command(
            "unknown_tool", {}, "my-repo", "/path/to/repo"
        )

        assert "error" in result
        assert "Unknown tool: unknown_tool" in result["error"]
        assert "available_tools" in result

    @pytest.mark.asyncio
    async def test_execute_tool_json_error(self):
        """Test handling of invalid JSON response."""
        with patch("codebase_tools.execute_tool") as mock_execute:
            mock_execute.return_value = "invalid json"

            result = await execute_tool_command(
                "search_symbols", {"query": "test"}, "my-repo", "/path/to/repo"
            )

            assert "error" in result
            assert "Invalid JSON response from tool" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_tool_exception(self):
        """Test handling of tool execution exception."""
        with patch("codebase_tools.execute_tool") as mock_execute:
            mock_execute.side_effect = Exception("Tool failed")

            result = await execute_tool_command(
                "search_symbols", {"query": "test"}, "my-repo", "/path/to/repo"
            )

            assert "error" in result
            assert "Tool execution failed: Tool failed" in result["error"]


class TestMainFunction:
    """Test cases for main CLI function."""

    @pytest.mark.asyncio
    async def test_main_search_symbols_success(self):
        """Test successful search_symbols command execution."""
        test_args = [
            "search_symbols",
            "--repo",
            "test-repo",
            "--query",
            "test_func",
            "--format",
            "json",
        ]

        mock_repo_config = {"path": "/path/to/repo"}
        mock_result = {"symbols": [], "total_results": 0}

        with patch("sys.argv", ["codebase_cli.py", *test_args]):
            with patch("codebase_cli.RepositoryManager") as mock_repo_manager:
                with patch("codebase_cli.execute_tool_command") as mock_execute:
                    with patch("builtins.print") as mock_print:
                        with patch("pathlib.Path.exists", return_value=True):
                            # Setup mocks
                            mock_repo_manager.return_value.get_repository.return_value = mock_repo_config
                            mock_execute.return_value = mock_result

                            # Execute main
                            await main()

                            # Verify execution
                            mock_execute.assert_called_once_with(
                                "search_symbols",
                                {"query": "test_func", "limit": 50},
                                "test-repo",
                                "/path/to/repo",
                            )

                            # Verify output
                            mock_print.assert_called_once()
                            output = mock_print.call_args[0][0]
                            assert json.loads(output) == mock_result

    @pytest.mark.asyncio
    async def test_main_health_check_success(self):
        """Test successful health_check command execution."""
        test_args = [
            "codebase_health_check",
            "--repo",
            "test-repo",
            "--format",
            "simple",
        ]

        mock_repo_config = {"path": "/path/to/repo"}
        mock_result = {
            "repo": "test-repo",
            "status": "healthy",
            "checks": {"path_exists": True},
        }

        with patch("sys.argv", ["codebase_cli.py", *test_args]):
            with patch("codebase_cli.RepositoryManager") as mock_repo_manager:
                with patch("codebase_cli.execute_tool_command") as mock_execute:
                    with patch("builtins.print") as mock_print:
                        with patch("pathlib.Path.exists", return_value=True):
                            # Setup mocks
                            mock_repo_manager.return_value.get_repository.return_value = mock_repo_config
                            mock_execute.return_value = mock_result

                            # Execute main
                            await main()

                            # Verify execution
                            mock_execute.assert_called_once_with(
                                "codebase_health_check",
                                {},
                                "test-repo",
                                "/path/to/repo",
                            )

                            # Verify output
                            mock_print.assert_called_once()
                            output = mock_print.call_args[0][0]
                            assert "Repository test-repo: healthy" in output

    @pytest.mark.asyncio
    async def test_main_missing_query_error(self):
        """Test error when query is missing for search_symbols."""
        test_args = [
            "search_symbols",
            "--repo",
            "test-repo",
        ]

        with patch("sys.argv", ["codebase_cli.py", *test_args]):
            with patch("sys.exit") as mock_exit:
                with patch("builtins.print") as mock_print:
                    # Mock exit to raise SystemExit instead of continuing
                    mock_exit.side_effect = SystemExit(1)

                    with pytest.raises(SystemExit):
                        await main()

                    # Should exit with error
                    mock_exit.assert_called_with(1)

                    # Should print error message
                    mock_print.assert_called_once()
                    error_msg = mock_print.call_args[0][0]
                    assert "query is required" in error_msg

    @pytest.mark.asyncio
    async def test_main_invalid_limit_error(self):
        """Test error when limit is invalid."""
        test_args = [
            "search_symbols",
            "--repo",
            "test-repo",
            "--query",
            "test",
            "--limit",
            "150",
        ]

        with patch("sys.argv", ["codebase_cli.py", *test_args]):
            with patch("sys.exit") as mock_exit:
                with patch("builtins.print") as mock_print:
                    # Mock exit to raise SystemExit instead of continuing
                    mock_exit.side_effect = SystemExit(1)

                    with pytest.raises(SystemExit):
                        await main()

                    # Should exit with error
                    mock_exit.assert_called_with(1)

                    # Should print error message
                    mock_print.assert_called_once()
                    error_msg = mock_print.call_args[0][0]
                    assert "limit must be between 1 and 100" in error_msg

    @pytest.mark.asyncio
    async def test_main_repo_not_found_error(self):
        """Test error when repository is not found."""
        test_args = [
            "search_symbols",
            "--repo",
            "nonexistent-repo",
            "--query",
            "test",
        ]

        with patch("sys.argv", ["codebase_cli.py", *test_args]):
            with patch("codebase_cli.RepositoryManager") as mock_repo_manager:
                with patch("sys.exit") as mock_exit:
                    with patch("builtins.print") as mock_print:
                        # Setup mock to return None (repo not found)
                        mock_repo_manager.return_value.get_repository.return_value = (
                            None
                        )

                        # Mock exit to raise SystemExit instead of continuing
                        mock_exit.side_effect = SystemExit(1)

                        with pytest.raises(SystemExit):
                            await main()

                        # Should exit with error
                        mock_exit.assert_called_with(1)

                        # Should print error message
                        mock_print.assert_called_once()
                        error_msg = mock_print.call_args[0][0]
                        assert "Repository 'nonexistent-repo' not found" in error_msg

    @pytest.mark.asyncio
    async def test_main_repo_path_not_exists_error(self):
        """Test error when repository path doesn't exist."""
        test_args = [
            "search_symbols",
            "--repo",
            "test-repo",
            "--query",
            "test",
        ]

        mock_repo_config = {"path": "/nonexistent/path"}

        with patch("sys.argv", ["codebase_cli.py", *test_args]):
            with patch("codebase_cli.RepositoryManager") as mock_repo_manager:
                with patch("sys.exit") as mock_exit:
                    with patch("builtins.print") as mock_print:
                        with patch("pathlib.Path.exists", return_value=False):
                            # Setup mock
                            mock_repo_manager.return_value.get_repository.return_value = mock_repo_config

                            # Mock exit to raise SystemExit instead of continuing
                            mock_exit.side_effect = SystemExit(1)

                            with pytest.raises(SystemExit):
                                await main()

                            # Should exit with error
                            mock_exit.assert_called_with(1)

                            # Should print error message
                            mock_print.assert_called_once()
                            error_msg = mock_print.call_args[0][0]
                            assert "Repository path does not exist" in error_msg

    @pytest.mark.asyncio
    async def test_main_tool_error_exit_code(self):
        """Test that tool errors result in exit code 1."""
        test_args = [
            "search_symbols",
            "--repo",
            "test-repo",
            "--query",
            "test",
        ]

        mock_repo_config = {"path": "/path/to/repo"}
        mock_result = {"error": "Tool failed"}

        with patch("sys.argv", ["codebase_cli.py", *test_args]):
            with patch("codebase_cli.RepositoryManager") as mock_repo_manager:
                with patch("codebase_cli.execute_tool_command") as mock_execute:
                    with patch("sys.exit") as mock_exit:
                        with patch("builtins.print") as mock_print:
                            with patch("pathlib.Path.exists", return_value=True):
                                # Setup mocks
                                mock_repo_manager.return_value.get_repository.return_value = mock_repo_config
                                mock_execute.return_value = mock_result

                                await main()

                                # Should exit with error code
                                mock_exit.assert_called_once_with(1)

                                # Should print error output
                                mock_print.assert_called_once()
                                output = mock_print.call_args[0][0]
                                assert "Error: Tool failed" in output
