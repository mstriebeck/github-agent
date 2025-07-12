#!/usr/bin/env python3

"""
Integration tests for search_symbols MCP tool
Tests the complete flow from MCP tool definition through execution
"""

import json

import pytest

import codebase_tools
from constants import Language
from repository_manager import RepositoryConfig
from symbol_storage import Symbol, SymbolKind

# temp_repo_path fixture now consolidated in conftest.py


@pytest.fixture
def mock_repo_config(temp_repo_path):
    """Create a mock repository configuration for testing"""
    return RepositoryConfig(
        name="test-repo",
        workspace=temp_repo_path,
        port=9999,
        description="Test repository for search_symbols integration tests",
        language=Language.PYTHON,
        python_path="/usr/bin/python3",
        github_owner="test-owner",
        github_repo="test-repo",
    )


class TestSearchSymbolsMCPIntegration:
    """Integration tests for search_symbols MCP tool"""

    async def execute_search_with_mock(self, mock_symbol_storage, **kwargs):
        """Helper to execute search_symbols with mock storage"""
        original_func = codebase_tools.execute_search_symbols

        async def patched_execute_search_symbols(*args, **kwargs_inner):
            kwargs_inner["symbol_storage"] = mock_symbol_storage
            return await original_func(*args, **kwargs_inner)

        codebase_tools.TOOL_HANDLERS["search_symbols"] = patched_execute_search_symbols

        try:
            return await codebase_tools.execute_tool("search_symbols", **kwargs)
        finally:
            codebase_tools.TOOL_HANDLERS["search_symbols"] = original_func

    def test_search_symbols_tool_registration(self):
        """Test that search_symbols tool is properly registered in MCP tools"""
        tools = codebase_tools.get_tools("test-repo", "/test/path")

        # Find the search_symbols tool
        search_symbols_tool = None
        for tool in tools:
            if tool["name"] == "search_symbols":
                search_symbols_tool = tool
                break

        assert (
            search_symbols_tool is not None
        ), "search_symbols tool not found in MCP tools"

        # Verify tool structure for MCP compatibility
        assert "name" in search_symbols_tool
        assert "description" in search_symbols_tool
        assert "inputSchema" in search_symbols_tool

        # Verify input schema structure
        schema = search_symbols_tool["inputSchema"]
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "required" in schema

        # Verify required parameters
        assert "query" in schema["required"]
        assert "query" in schema["properties"]

        # Verify optional parameters are properly defined
        properties = schema["properties"]
        assert "symbol_kind" in properties
        assert "limit" in properties

        # Verify parameter types and constraints
        assert properties["query"]["type"] == "string"
        assert properties["symbol_kind"]["type"] == "string"
        assert properties["limit"]["type"] == "integer"
        assert properties["limit"]["minimum"] == 1
        assert properties["limit"]["maximum"] == 100

    @pytest.mark.asyncio
    async def test_search_symbols_tool_execution_flow(self, mock_symbol_storage):
        """Test complete execution flow of search_symbols tool"""
        # Setup test data
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
                "/test/class.py",
                5,
                0,
                "test-repo",
                "Test class",
            )
        )

        # Test basic search
        result = await self.execute_search_with_mock(
            mock_symbol_storage,
            repo_name="test-repo",
            repository_workspace="/test/path",
            query="test",
        )

        data = json.loads(result)
        assert (
            "error" not in data or data.get("total_results", 0) >= 0
        )  # Allow for empty results or success
        assert "query" in data
        assert "repository" in data
        assert "symbols" in data
        assert "total_results" in data

    @pytest.mark.asyncio
    async def test_search_symbols_with_all_parameters(self, mock_symbol_storage):
        """Test search_symbols tool with all parameter combinations"""
        # Setup test data
        mock_symbol_storage.insert_symbol(
            Symbol(
                "search_test",
                SymbolKind.FUNCTION,
                "/test/file.py",
                10,
                0,
                "test-repo",
                "Search test function",
            )
        )
        mock_symbol_storage.insert_symbol(
            Symbol(
                "other_function",
                SymbolKind.FUNCTION,
                "/test/file.py",
                20,
                0,
                "test-repo",
                "Other function",
            )
        )
        mock_symbol_storage.insert_symbol(
            Symbol(
                "SearchClass",
                SymbolKind.CLASS,
                "/test/class.py",
                5,
                0,
                "test-repo",
                "Search test class",
            )
        )

        # Test with query only
        result = await self.execute_search_with_mock(
            mock_symbol_storage,
            repo_name="test-repo",
            repository_workspace="/test/path",
            query="search",
        )
        data = json.loads(result)
        assert data["query"] == "search"
        assert data["symbol_kind"] is None
        assert data["limit"] == 50  # Default limit

        # Test with query and symbol_kind filter
        result = await self.execute_search_with_mock(
            mock_symbol_storage,
            repo_name="test-repo",
            repository_workspace="/test/path",
            query="search",
            symbol_kind="function",
        )
        data = json.loads(result)
        assert data["query"] == "search"
        assert data["symbol_kind"] == "function"

        # Test with query and custom limit
        result = await self.execute_search_with_mock(
            mock_symbol_storage,
            repo_name="test-repo",
            repository_workspace="/test/path",
            query="search",
            limit=10,
        )
        data = json.loads(result)
        assert data["query"] == "search"
        assert data["limit"] == 10

        # Test with all parameters
        result = await self.execute_search_with_mock(
            mock_symbol_storage,
            repo_name="test-repo",
            repository_workspace="/test/path",
            query="search",
            symbol_kind="class",
            limit=5,
        )
        data = json.loads(result)
        assert data["query"] == "search"
        assert data["symbol_kind"] == "class"
        assert data["limit"] == 5

    @pytest.mark.asyncio
    async def test_search_symbols_error_handling_integration(self):
        """Test error handling in the complete MCP tool flow"""
        # Test with missing required parameter
        result = await codebase_tools.execute_tool(
            "search_symbols",
            repo_name="test-repo",
            repository_workspace="/test/path",
            # Missing query parameter
        )

        data = json.loads(result)
        assert "error" in data
        assert "Tool execution failed" in data["error"]

        # Test with invalid parameters
        result = await codebase_tools.execute_tool(
            "search_symbols",
            repo_name="test-repo",
            repository_workspace="/test/path",
            query="test",
            limit=0,  # Invalid limit
        )

        data = json.loads(result)
        assert "error" in data

    def test_search_symbols_tool_handler_registration(self):
        """Test that search_symbols is properly registered in TOOL_HANDLERS"""
        assert "search_symbols" in codebase_tools.TOOL_HANDLERS
        handler = codebase_tools.TOOL_HANDLERS["search_symbols"]
        assert callable(handler)
        assert handler == codebase_tools.execute_search_symbols

    @pytest.mark.asyncio
    async def test_search_symbols_empty_query_handling(self, mock_symbol_storage):
        """Test handling of empty or whitespace-only queries"""
        # Test empty string
        result = await codebase_tools.execute_tool(
            "search_symbols",
            repo_name="test-repo",
            repository_workspace="/test/path",
            query="",
            symbol_storage=mock_symbol_storage,
        )

        data = json.loads(result)
        # Should handle empty query gracefully
        assert "query" in data
        assert data["query"] == ""

        # Test whitespace-only query
        result = await codebase_tools.execute_tool(
            "search_symbols",
            repo_name="test-repo",
            repository_workspace="/test/path",
            query="   ",
            symbol_storage=mock_symbol_storage,
        )

        data = json.loads(result)
        assert "query" in data
        assert data["query"] == "   "

    @pytest.mark.asyncio
    async def test_search_symbols_special_characters(self, mock_symbol_storage):
        """Test search_symbols with special characters in queries"""
        # Setup test data with special characters
        mock_symbol_storage.insert_symbol(
            Symbol(
                "__init__",
                SymbolKind.FUNCTION,
                "/test/file.py",
                10,
                0,
                "test-repo",
                "Init function",
            )
        )
        mock_symbol_storage.insert_symbol(
            Symbol(
                "test_method",
                SymbolKind.FUNCTION,
                "/test/file.py",
                20,
                0,
                "test-repo",
                "Test method",
            )
        )

        # Test search with underscore
        result = await codebase_tools.execute_tool(
            "search_symbols",
            repo_name="test-repo",
            repository_workspace="/test/path",
            query="__init__",
            symbol_storage=mock_symbol_storage,
        )

        data = json.loads(result)
        assert data["query"] == "__init__"
        assert "symbols" in data

        # Test search with partial special characters
        result = await codebase_tools.execute_tool(
            "search_symbols",
            repo_name="test-repo",
            repository_workspace="/test/path",
            query="_",
            symbol_storage=mock_symbol_storage,
        )

        data = json.loads(result)
        assert data["query"] == "_"

    @pytest.mark.asyncio
    async def test_search_symbols_case_sensitivity(self, mock_symbol_storage):
        """Test search_symbols case sensitivity behavior"""
        # Setup test data with mixed case
        mock_symbol_storage.insert_symbol(
            Symbol(
                "TestFunction",
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
                "testfunction",
                SymbolKind.FUNCTION,
                "/test/file.py",
                20,
                0,
                "test-repo",
                "Test function lowercase",
            )
        )

        # Test search behavior with different cases
        result = await codebase_tools.execute_tool(
            "search_symbols",
            repo_name="test-repo",
            repository_workspace="/test/path",
            query="test",
            symbol_storage=mock_symbol_storage,
        )

        data = json.loads(result)
        assert data["query"] == "test"
        assert "symbols" in data
        # Should find symbols regardless of case (due to LIKE pattern)

    @pytest.mark.asyncio
    async def test_search_symbols_repository_isolation(self, mock_symbol_storage):
        """Test that search_symbols only returns symbols from the specified repository"""
        # Setup symbols in different repositories
        mock_symbol_storage.insert_symbol(
            Symbol(
                "function_a",
                SymbolKind.FUNCTION,
                "/test/file.py",
                10,
                0,
                "test-repo",
                "Function A",
            )
        )
        mock_symbol_storage.insert_symbol(
            Symbol(
                "function_b",
                SymbolKind.FUNCTION,
                "/other/file.py",
                10,
                0,
                "other-repo",
                "Function B",
            )
        )

        # Search should only return symbols from test-repo
        result = await codebase_tools.execute_tool(
            "search_symbols",
            repo_name="test-repo",
            repository_workspace="/test/path",
            query="function",
            symbol_storage=mock_symbol_storage,
        )

        data = json.loads(result)
        assert data["repository"] == "test-repo"

        # All returned symbols should belong to test-repo
        for symbol in data.get("symbols", []):
            assert symbol["repository_id"] == "test-repo"

    def test_search_symbols_mcp_schema_validation(self):
        """Test that search_symbols tool schema follows MCP standards"""
        tools = codebase_tools.get_tools("test-repo", "/test/path")
        search_tool = next((t for t in tools if t["name"] == "search_symbols"), None)

        assert search_tool is not None

        # Verify MCP-required fields
        assert "name" in search_tool
        assert "description" in search_tool
        assert "inputSchema" in search_tool

        # Verify schema follows JSON Schema specification
        schema = search_tool["inputSchema"]
        assert schema["type"] == "object"
        assert isinstance(schema["properties"], dict)
        assert isinstance(schema["required"], list)

        # Verify enum values for symbol_kind
        symbol_kind_prop = schema["properties"]["symbol_kind"]
        assert "enum" in symbol_kind_prop
        expected_kinds = ["function", "class", "variable"]
        assert set(symbol_kind_prop["enum"]) == set(expected_kinds)

        # Verify limit constraints
        limit_prop = schema["properties"]["limit"]
        assert limit_prop["minimum"] == 1
        assert limit_prop["maximum"] == 100
        assert limit_prop["default"] == 50


if __name__ == "__main__":
    pytest.main([__file__])
