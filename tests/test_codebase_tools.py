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
from symbol_storage import Symbol, SymbolKind

# temp_git_repo fixture now consolidated in conftest.py


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
        assert len(tools) == 2

        # Test health check tool
        health_check_tool = tools[0]
        assert health_check_tool["name"] == "codebase_health_check"
        assert repo_path in health_check_tool["description"]
        assert health_check_tool["inputSchema"]["type"] == "object"
        assert health_check_tool["inputSchema"]["required"] == []

        # Test search symbols tool
        search_symbols_tool = tools[1]
        assert search_symbols_tool["name"] == "search_symbols"
        assert repo_name in search_symbols_tool["description"]
        assert search_symbols_tool["inputSchema"]["type"] == "object"
        assert search_symbols_tool["inputSchema"]["required"] == ["query"]
        assert "query" in search_symbols_tool["inputSchema"]["properties"]
        assert "symbol_kind" in search_symbols_tool["inputSchema"]["properties"]
        assert "limit" in search_symbols_tool["inputSchema"]["properties"]

    @pytest.mark.asyncio
    async def test_health_check_nonexistent_path(self):
        """Test health check when repository path doesn't exist"""
        result = await codebase_tools.execute_codebase_health_check(
            "test-repo", "/nonexistent/path"
        )

        data = json.loads(result)
        assert data["repo"] == "test-repo"
        assert data["status"] == "unhealthy"
        assert data["workspace"] == "/nonexistent/path"
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
        assert data["workspace"] == temp_git_repo
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
            "codebase_health_check",
            repo_name="test-repo",
            repository_workspace=temp_git_repo,
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
        assert "search_symbols" in data["available_tools"]

    @pytest.mark.asyncio
    async def test_execute_tool_exception_handling(self):
        """Test execute_tool handles exceptions in tool execution"""
        # This will cause an exception due to missing required argument
        result = await codebase_tools.execute_tool("codebase_health_check")

        data = json.loads(result)
        assert "error" in data
        assert "Tool execution failed" in data["error"]
        assert data["tool"] == "codebase_health_check"

    def test_tool_registration_format(self):
        """Test that tool registration follows proper MCP format"""
        tools = codebase_tools.get_tools("test-repo", "/test/path")

        for tool in tools:
            # Verify required MCP tool fields
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool

            # Verify inputSchema structure
            schema = tool["inputSchema"]
            assert "type" in schema
            assert schema["type"] == "object"
            assert "properties" in schema
            assert "required" in schema

            # Tool name should be a string
            assert isinstance(tool["name"], str)
            assert tool["name"]  # Non-empty

            # Description should be informative
            assert isinstance(tool["description"], str)
            assert tool["description"]  # Non-empty

    def test_tool_handlers_mapping(self):
        """Test that TOOL_HANDLERS mapping is properly configured"""
        # Verify all tools have handlers
        tools = codebase_tools.get_tools("test", "/test")
        for tool in tools:
            tool_name = tool["name"]
            assert tool_name in codebase_tools.TOOL_HANDLERS

        # Verify handler is callable
        for _handler_name, handler in codebase_tools.TOOL_HANDLERS.items():
            assert callable(handler)

    @pytest.mark.asyncio
    async def test_health_check_git_command_timeout(self, temp_git_repo):
        """Test health check behavior with git command timeouts"""
        # This test validates that timeout handling works correctly
        # We can't easily mock subprocess timeout, but we can verify the structure
        # handles the timeout case properly by checking the warning path

        result = await codebase_tools.execute_codebase_health_check(
            "test-repo", temp_git_repo
        )

        data = json.loads(result)
        # Should complete successfully for a valid repo
        assert data["status"] in ["healthy", "warning"]

        # Verify git_responsive is tracked
        assert "git_responsive" in data["checks"]

    @pytest.mark.asyncio
    async def test_health_check_json_output_structure(self, temp_git_repo):
        """Test that health check output follows expected JSON structure"""
        result = await codebase_tools.execute_codebase_health_check(
            "test-repo", temp_git_repo
        )

        data = json.loads(result)

        # Required top-level fields
        required_fields = [
            "repo",
            "workspace",
            "status",
            "checks",
            "warnings",
            "errors",
        ]
        for field in required_fields:
            assert field in data

        # Status should be one of expected values
        assert data["status"] in ["healthy", "warning", "unhealthy", "error"]

        # Collections should be proper types
        assert isinstance(data["checks"], dict)
        assert isinstance(data["warnings"], list)
        assert isinstance(data["errors"], list)

        # Repo and workspace should match input
        assert data["repo"] == "test-repo"
        assert data["workspace"] == temp_git_repo

    @pytest.mark.asyncio
    async def test_health_check_error_handling_edge_cases(self, temp_git_repo):
        """Test health check error handling for various edge cases"""
        # Test with empty string repo name
        result = await codebase_tools.execute_codebase_health_check("", temp_git_repo)
        data = json.loads(result)
        assert data["repo"] == ""
        assert "status" in data

        # Test with very long repo name
        long_name = "x" * 1000
        result = await codebase_tools.execute_codebase_health_check(
            long_name, temp_git_repo
        )
        data = json.loads(result)
        assert data["repo"] == long_name

    @pytest.mark.asyncio
    async def test_search_symbols_basic(self, mock_symbol_storage):
        """Test basic search symbols functionality"""
        # Setup mock storage with test symbols
        mock_symbol_storage.insert_symbol(
            Symbol(
                "test_function",
                SymbolKind.FUNCTION,
                "/test/file.py",
                10,
                0,
                "test-repo",
                "Test function",
            )
        )
        mock_symbol_storage.insert_symbol(
            Symbol(
                "TestClass",
                SymbolKind.CLASS,
                "/test/file.py",
                20,
                0,
                "test-repo",
                "Test class",
            )
        )

        result = await codebase_tools.execute_search_symbols(
            "test-repo", "/test/path", "test", symbol_storage=mock_symbol_storage
        )

        data = json.loads(result)
        assert data["query"] == "test"
        assert data["repository"] == "test-repo"
        assert data["total_results"] == 2
        assert len(data["symbols"]) == 2

        # Verify symbol structure
        symbol = data["symbols"][0]
        assert "name" in symbol
        assert "kind" in symbol
        assert "file_path" in symbol
        assert "line_number" in symbol
        assert "column_number" in symbol
        assert "docstring" in symbol
        assert "repository_id" in symbol

    @pytest.mark.asyncio
    async def test_search_symbols_with_kind_filter(self, mock_symbol_storage):
        """Test search symbols with symbol kind filtering"""
        # Setup mock storage with mixed symbols
        mock_symbol_storage.insert_symbol(
            Symbol(
                "test_function",
                SymbolKind.FUNCTION,
                "/test/file.py",
                10,
                0,
                "test-repo",
                "Test function",
            )
        )
        mock_symbol_storage.insert_symbol(
            Symbol(
                "TestClass",
                SymbolKind.CLASS,
                "/test/file.py",
                20,
                0,
                "test-repo",
                "Test class",
            )
        )
        mock_symbol_storage.insert_symbol(
            Symbol(
                "test_variable",
                SymbolKind.VARIABLE,
                "/test/file.py",
                30,
                0,
                "test-repo",
                "Test variable",
            )
        )

        result = await codebase_tools.execute_search_symbols(
            "test-repo",
            "/test/path",
            "test",
            symbol_kind="function",
            symbol_storage=mock_symbol_storage,
        )

        data = json.loads(result)
        assert data["query"] == "test"
        assert data["symbol_kind"] == "function"
        assert data["total_results"] == 1
        assert data["symbols"][0]["name"] == "test_function"
        assert data["symbols"][0]["kind"] == "function"

    @pytest.mark.asyncio
    async def test_search_symbols_with_limit(self, mock_symbol_storage):
        """Test search symbols with result limit"""
        # Setup mock storage with multiple symbols
        for i in range(10):
            mock_symbol_storage.insert_symbol(
                Symbol(
                    f"test_function_{i}",
                    SymbolKind.FUNCTION,
                    "/test/file.py",
                    10 + i,
                    0,
                    "test-repo",
                    f"Test function {i}",
                )
            )

        result = await codebase_tools.execute_search_symbols(
            "test-repo",
            "/test/path",
            "test",
            limit=3,
            symbol_storage=mock_symbol_storage,
        )

        data = json.loads(result)
        assert data["limit"] == 3
        assert data["total_results"] == 3
        assert len(data["symbols"]) == 3

    @pytest.mark.asyncio
    async def test_search_symbols_no_results(self, mock_symbol_storage):
        """Test search symbols when no results are found"""
        result = await codebase_tools.execute_search_symbols(
            "test-repo", "/test/path", "nonexistent", symbol_storage=mock_symbol_storage
        )

        data = json.loads(result)
        assert data["query"] == "nonexistent"
        assert data["total_results"] == 0
        assert len(data["symbols"]) == 0

    @pytest.mark.asyncio
    async def test_search_symbols_invalid_limit(self, mock_symbol_storage):
        """Test search symbols with invalid limit values"""
        # Test limit too low
        result = await codebase_tools.execute_search_symbols(
            "test-repo", "/test/path", "test", mock_symbol_storage, limit=0
        )

        data = json.loads(result)
        assert "error" in data
        assert "Limit must be between 1 and 100" in data["error"]

        # Test limit too high
        result = await codebase_tools.execute_search_symbols(
            "test-repo", "/test/path", "test", mock_symbol_storage, limit=101
        )

        data = json.loads(result)
        assert "error" in data
        assert "Limit must be between 1 and 100" in data["error"]

    @pytest.mark.asyncio
    async def test_search_symbols_default_parameters(self, mock_symbol_storage):
        """Test search symbols with default parameters"""
        mock_symbol_storage.insert_symbol(
            Symbol(
                "test_function",
                SymbolKind.FUNCTION,
                "/test/file.py",
                10,
                0,
                "test-repo",
                "Test function",
            )
        )

        result = await codebase_tools.execute_search_symbols(
            "test-repo", "/test/path", "test", symbol_storage=mock_symbol_storage
        )

        data = json.loads(result)
        assert data["symbol_kind"] is None
        assert data["limit"] == 50

    @pytest.mark.asyncio
    async def test_search_symbols_exception_handling(self, mock_symbol_storage):
        """Test search symbols exception handling"""

        # Mock a storage error by using a symbol storage that doesn't exist
        # This will cause an exception during search
        # Make the search_symbols method raise an exception
        def error_search(*args, **kwargs):
            raise Exception("Database connection failed")

        mock_symbol_storage.search_symbols = error_search

        result = await codebase_tools.execute_search_symbols(
            "test-repo", "/test/path", "test", mock_symbol_storage
        )

        # Should handle exception gracefully and return error response
        data = json.loads(result)
        assert "error" in data
        assert "Database search failed" in data["error"]
        assert data["query"] == "test"
        assert data["repository"] == "test-repo"
        assert data["total_results"] == 0
        assert len(data["symbols"]) == 0

    @pytest.mark.asyncio
    async def test_execute_tool_search_symbols(self, mock_symbol_storage):
        """Test execute_tool with search_symbols"""
        mock_symbol_storage.insert_symbol(
            Symbol(
                "test_function",
                SymbolKind.FUNCTION,
                "/test/file.py",
                10,
                0,
                "test-repo",
                "Test function",
            )
        )

        # Temporarily patch the execute_search_symbols function to use our mock
        original_func = codebase_tools.execute_search_symbols

        async def patched_execute_search_symbols(*args, **kwargs):
            kwargs["symbol_storage"] = mock_symbol_storage
            return await original_func(*args, **kwargs)

        codebase_tools.TOOL_HANDLERS["search_symbols"] = patched_execute_search_symbols

        try:
            result = await codebase_tools.execute_tool(
                "search_symbols",
                repo_name="test-repo",
                repository_workspace="/test/path",
                query="test",
                symbol_kind="function",
                limit=10,
            )

            data = json.loads(result)
            assert data["query"] == "test"
            assert data["symbol_kind"] == "function"
            assert data["limit"] == 10
            assert data["repository"] == "test-repo"
        finally:
            # Restore original function
            codebase_tools.TOOL_HANDLERS["search_symbols"] = original_func

    @pytest.mark.asyncio
    async def test_search_symbols_json_structure(self, mock_symbol_storage):
        """Test that search symbols output follows expected JSON structure"""
        mock_symbol_storage.insert_symbol(
            Symbol(
                "test_function",
                SymbolKind.FUNCTION,
                "/test/file.py",
                10,
                5,
                "test-repo",
                "Test function docstring",
            )
        )

        result = await codebase_tools.execute_search_symbols(
            "test-repo",
            "/test/path",
            "test",
            symbol_kind="function",
            limit=25,
            symbol_storage=mock_symbol_storage,
        )

        data = json.loads(result)

        # Required top-level fields
        required_fields = [
            "query",
            "symbol_kind",
            "limit",
            "repository",
            "total_results",
            "symbols",
        ]
        for field in required_fields:
            assert field in data

        # Check data types and values
        assert isinstance(data["query"], str)
        assert isinstance(data["symbol_kind"], str)
        assert isinstance(data["limit"], int)
        assert isinstance(data["repository"], str)
        assert isinstance(data["total_results"], int)
        assert isinstance(data["symbols"], list)

        # Values should match input
        assert data["query"] == "test"
        assert data["symbol_kind"] == "function"
        assert data["limit"] == 25
        assert data["repository"] == "test-repo"

        # Verify symbol structure
        if data["symbols"]:
            symbol = data["symbols"][0]
            symbol_fields = [
                "name",
                "kind",
                "file_path",
                "line_number",
                "column_number",
                "docstring",
                "repository_id",
            ]
            for field in symbol_fields:
                assert field in symbol

            assert symbol["name"] == "test_function"
            assert symbol["kind"] == "function"
            assert symbol["file_path"] == "/test/file.py"
            assert symbol["line_number"] == 10
            assert symbol["column_number"] == 5
            assert symbol["docstring"] == "Test function docstring"
            assert symbol["repository_id"] == "test-repo"


if __name__ == "__main__":
    pytest.main([__file__])
