#!/usr/bin/env python3

"""
Unit tests for codebase_cli.py
Tests CLI argument parsing, output formatting, and tool execution.
"""

import argparse
import json
from unittest.mock import patch

import pytest

from codebase_cli import OutputFormatter, execute_cli, execute_tool_command
from repository_manager import AbstractRepositoryManager


class MockRepositoryManager(AbstractRepositoryManager):
    """Mock repository manager for testing."""

    def __init__(self):
        self._repositories: dict[str, dict] = {}
        self._should_fail_load = False

    @property
    def repositories(self) -> dict[str, dict]:
        return self._repositories

    def get_repository(self, name: str) -> dict | None:
        return self._repositories.get(name)

    def add_repository(self, name: str, config: dict) -> None:
        self._repositories[name] = config

    def load_configuration(self) -> bool:
        if self._should_fail_load:
            raise Exception("Mock configuration load failure")
        return True

    def set_fail_load(self, should_fail: bool) -> None:
        """Set whether load_configuration should fail."""
        self._should_fail_load = should_fail


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
            "workspace": "/path/to/repo",
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
    async def test_execute_codebase_tool_success(self, mock_symbol_storage):
        """Test successful execution of a codebase tool."""
        with patch("codebase_tools.execute_tool") as mock_execute:
            mock_execute.return_value = '{"result": "success", "data": "test"}'

            result = await execute_tool_command(
                "search_symbols",
                {"query": "test"},
                "my-repo",
                "/path/to/repo",
                mock_symbol_storage,
            )

            assert result == {"result": "success", "data": "test"}
            mock_execute.assert_called_once_with(
                "search_symbols",
                repo_name="my-repo",
                repository_workspace="/path/to/repo",
                query="test",
                symbol_storage=mock_symbol_storage,
            )

    @pytest.mark.asyncio
    async def test_execute_github_tool_success(self, mock_symbol_storage):
        """Test successful execution of a github tool."""
        with patch("github_tools.execute_tool") as mock_execute:
            mock_execute.return_value = '{"result": "success", "data": "test"}'

            result = await execute_tool_command(
                "git_get_current_branch",
                {},
                "my-repo",
                "/path/to/repo",
                mock_symbol_storage,
            )

            assert result == {"result": "success", "data": "test"}
            mock_execute.assert_called_once_with(
                "git_get_current_branch",
                repo_name="my-repo",
                repository_workspace="/path/to/repo",
            )

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self, mock_symbol_storage):
        """Test execution of an unknown tool."""
        result = await execute_tool_command(
            "unknown_tool", {}, "my-repo", "/path/to/repo", mock_symbol_storage
        )

        assert "error" in result
        assert "Unknown tool: unknown_tool" in result["error"]
        assert "available_tools" in result

    @pytest.mark.asyncio
    async def test_execute_tool_json_error(self, mock_symbol_storage):
        """Test handling of invalid JSON response."""
        with patch("codebase_tools.execute_tool") as mock_execute:
            mock_execute.return_value = "invalid json"

            result = await execute_tool_command(
                "search_symbols",
                {"query": "test"},
                "my-repo",
                "/path/to/repo",
                mock_symbol_storage,
            )

            assert "error" in result
            assert "Invalid JSON response from tool" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_tool_exception(self, mock_symbol_storage):
        """Test handling of tool execution exception."""
        with patch("codebase_tools.execute_tool") as mock_execute:
            mock_execute.side_effect = Exception("Tool failed")

            result = await execute_tool_command(
                "search_symbols",
                {"query": "test"},
                "my-repo",
                "/path/to/repo",
                mock_symbol_storage,
            )

            assert "error" in result
            assert "Tool execution failed: Tool failed" in result["error"]


class TestExecuteCLI:
    """Test cases for execute_cli function using dependency injection."""

    @pytest.mark.asyncio
    async def test_execute_cli_search_symbols_success(self, mock_symbol_storage):
        """Test successful search_symbols command execution."""
        # Setup test arguments
        args = argparse.Namespace(
            tool="search_symbols",
            repo="test-repo",
            query="test_func",
            kind=None,
            limit=50,
            format="json",
        )

        # Setup mock repository manager
        mock_repo_manager = MockRepositoryManager()
        mock_repo_manager.add_repository("test-repo", {"workspace": "/path/to/repo"})

        # Setup formatter and symbol storage
        formatter = OutputFormatter()

        mock_result = {"symbols": [], "total_results": 0}

        with patch("codebase_cli.execute_tool_command") as mock_execute:
            with patch("builtins.print") as mock_print:
                with patch("pathlib.Path.exists", return_value=True):
                    # Setup mocks
                    mock_execute.return_value = mock_result

                    # Execute CLI
                    await execute_cli(
                        args, mock_repo_manager, formatter, mock_symbol_storage
                    )

                    # Verify execution
                    mock_execute.assert_called_once_with(
                        "search_symbols",
                        {"query": "test_func", "limit": 50},
                        "test-repo",
                        "/path/to/repo",
                        mock_symbol_storage,
                    )

                    # Verify output
                    mock_print.assert_called_once()
                    output = mock_print.call_args[0][0]
                    assert json.loads(output) == mock_result

    @pytest.mark.asyncio
    async def test_execute_cli_health_check_success(self, mock_symbol_storage):
        """Test successful health_check command execution."""
        # Setup test arguments
        args = argparse.Namespace(
            tool="codebase_health_check", repo="test-repo", format="simple"
        )

        # Setup mock repository manager
        mock_repo_manager = MockRepositoryManager()
        mock_repo_manager.add_repository("test-repo", {"workspace": "/path/to/repo"})

        # Setup formatter and symbol storage
        formatter = OutputFormatter()

        mock_result = {
            "repo": "test-repo",
            "status": "healthy",
            "checks": {"path_exists": True},
        }

        with patch("codebase_cli.execute_tool_command") as mock_execute:
            with patch("builtins.print") as mock_print:
                with patch("pathlib.Path.exists", return_value=True):
                    # Setup mocks
                    mock_execute.return_value = mock_result

                    # Execute CLI
                    await execute_cli(
                        args, mock_repo_manager, formatter, mock_symbol_storage
                    )

                    # Verify execution
                    mock_execute.assert_called_once_with(
                        "codebase_health_check",
                        {},
                        "test-repo",
                        "/path/to/repo",
                        mock_symbol_storage,
                    )

                    # Verify output
                    mock_print.assert_called_once()
                    output = mock_print.call_args[0][0]
                    assert "Repository test-repo: healthy" in output

    @pytest.mark.asyncio
    async def test_execute_cli_repo_not_found_error(self, mock_symbol_storage):
        """Test error when repository is not found."""
        # Setup test arguments
        args = argparse.Namespace(
            tool="search_symbols",
            repo="nonexistent-repo",
            query="test",
            kind=None,
            limit=50,
            format="simple",
        )

        # Setup empty mock repository manager
        mock_repo_manager = MockRepositoryManager()
        formatter = OutputFormatter()

        with patch("sys.exit") as mock_exit:
            with patch("builtins.print") as mock_print:
                # Mock exit to raise SystemExit instead of continuing
                mock_exit.side_effect = SystemExit(1)

                with pytest.raises(SystemExit):
                    await execute_cli(
                        args, mock_repo_manager, formatter, mock_symbol_storage
                    )

                # Should exit with error
                mock_exit.assert_called_with(1)

                # Should print error message
                mock_print.assert_called_once()
                error_msg = mock_print.call_args[0][0]
                assert "Repository 'nonexistent-repo' not found" in error_msg

    @pytest.mark.asyncio
    async def test_execute_cli_tool_error_exit_code(self, mock_symbol_storage):
        """Test that tool errors result in exit code 1."""
        # Setup test arguments
        args = argparse.Namespace(
            tool="search_symbols",
            repo="test-repo",
            query="test",
            kind=None,
            limit=50,
            format="simple",
        )

        # Setup mock repository manager
        mock_repo_manager = MockRepositoryManager()
        mock_repo_manager.add_repository("test-repo", {"workspace": "/path/to/repo"})
        formatter = OutputFormatter()

        mock_result = {"error": "Tool failed"}

        with patch("codebase_cli.execute_tool_command") as mock_execute:
            with patch("sys.exit") as mock_exit:
                with patch("builtins.print") as mock_print:
                    with patch("pathlib.Path.exists", return_value=True):
                        # Setup mocks
                        mock_execute.return_value = mock_result

                        await execute_cli(
                            args, mock_repo_manager, formatter, mock_symbol_storage
                        )

                        # Should exit with error code
                        mock_exit.assert_called_once_with(1)

                        # Should print error output
                        mock_print.assert_called_once()
                        output = mock_print.call_args[0][0]
                        assert "Error: Tool failed" in output
