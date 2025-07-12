#!/usr/bin/env python3

"""
Simple CLI for Tool Testing
A command-line interface for testing MCP tools directly without server deployment.
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

import codebase_tools
import github_tools
from constants import DATA_DIR, SYMBOLS_DB_PATH
from repository_manager import (
    AbstractRepositoryManager,
    RepositoryConfig,
    RepositoryManager,
)
from symbol_storage import AbstractSymbolStorage, SQLiteSymbolStorage


class OutputFormatter:
    """Handles different output formats for CLI tool results."""

    @staticmethod
    def format_json(data: dict[str, Any]) -> str:
        """Format output as pretty JSON."""
        return json.dumps(data, indent=2)

    @staticmethod
    def format_table(data: dict[str, Any]) -> str:
        """Format output as a simple table."""
        lines = []

        # Handle search_symbols output
        if "symbols" in data:
            lines.append(f"Query: {data.get('query', 'N/A')}")
            lines.append(f"Repository: {data.get('repository', 'N/A')}")
            lines.append(f"Total Results: {data.get('total_results', 0)}")
            lines.append("")

            if data.get("symbols"):
                # Table header
                lines.append(
                    "Symbol Name         | Kind     | File Path                    | Line"
                )
                lines.append("-" * 75)

                for symbol in data["symbols"]:
                    name = symbol.get("name", "")[:18]
                    kind = symbol.get("kind", "")[:8]
                    file_path = symbol.get("file_path", "")[:28]
                    line_num = symbol.get("line_number", "")

                    lines.append(
                        f"{name:<18} | {kind:<8} | {file_path:<28} | {line_num}"
                    )
            else:
                lines.append("No symbols found.")

        # Handle health check output
        elif "status" in data and "checks" in data:
            lines.append(f"Repository: {data.get('repo', 'N/A')}")
            lines.append(f"Path: {data.get('path', 'N/A')}")
            lines.append(f"Status: {data.get('status', 'N/A')}")
            lines.append("")

            if data.get("checks"):
                lines.append("Checks:")
                for check_name, check_result in data["checks"].items():
                    status = "✓" if check_result else "✗"
                    lines.append(f"  {status} {check_name}: {check_result}")

            if data.get("warnings"):
                lines.append("\nWarnings:")
                for warning in data["warnings"]:
                    lines.append(f"  ⚠ {warning}")

            if data.get("errors"):
                lines.append("\nErrors:")
                for error in data["errors"]:
                    lines.append(f"  ✗ {error}")

        # Handle error output
        elif "error" in data:
            lines.append(f"Error: {data['error']}")
            if "tool" in data:
                lines.append(f"Tool: {data['tool']}")

        # Generic fallback
        else:
            for key, value in data.items():
                lines.append(f"{key}: {value}")

        return "\n".join(lines)

    @staticmethod
    def format_simple(data: dict[str, Any]) -> str:
        """Format output as simple text."""
        lines = []

        # Handle search_symbols output
        if "symbols" in data:
            lines.append(
                f"Found {data.get('total_results', 0)} symbols for '{data.get('query', '')}'"
            )

            if data.get("symbols"):
                for symbol in data["symbols"]:
                    lines.append(
                        f"{symbol.get('name', '')} ({symbol.get('kind', '')}) - {symbol.get('file_path', '')}:{symbol.get('line_number', '')}"
                    )
            else:
                lines.append("No symbols found.")

        # Handle health check output
        elif "status" in data and "checks" in data:
            lines.append(
                f"Repository {data.get('repo', 'N/A')}: {data.get('status', 'N/A')}"
            )

            if data.get("errors"):
                for error in data["errors"]:
                    lines.append(f"Error: {error}")

            if data.get("warnings"):
                for warning in data["warnings"]:
                    lines.append(f"Warning: {warning}")

        # Handle error output
        elif "error" in data:
            lines.append(f"Error: {data['error']}")

        # Generic fallback
        else:
            lines.append(str(data))

        return "\n".join(lines)


async def execute_tool_command(
    tool_name: str,
    tool_args: dict[str, Any],
    repo_name: str,
    repo_workspace: str,
    symbol_storage: AbstractSymbolStorage,
) -> dict[str, Any]:
    """Execute a tool command and return the results."""
    try:
        # Route to appropriate tool module
        if tool_name in codebase_tools.TOOL_HANDLERS:
            # Add symbol_storage to tool_args for search_symbols
            if tool_name == "search_symbols":
                tool_args["symbol_storage"] = symbol_storage
            result = await codebase_tools.execute_tool(
                tool_name,
                repo_name=repo_name,
                repository_workspace=repo_workspace,
                **tool_args,
            )
        elif tool_name in github_tools.TOOL_HANDLERS:
            result = await github_tools.execute_tool(
                tool_name,
                repo_name=repo_name,
                repository_workspace=repo_workspace,
                **tool_args,
            )
        else:
            return {
                "error": f"Unknown tool: {tool_name}",
                "available_tools": list(codebase_tools.TOOL_HANDLERS.keys())
                + list(github_tools.TOOL_HANDLERS.keys()),
            }

        # Parse JSON result
        return json.loads(result)

    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON response from tool: {e}", "tool": tool_name}
    except Exception as e:
        return {"error": f"Tool execution failed: {e}", "tool": tool_name}


async def execute_cli(
    args: argparse.Namespace,
    repo_manager: AbstractRepositoryManager,
    formatter: OutputFormatter,
    symbol_storage: AbstractSymbolStorage,
) -> None:
    """Execute CLI functionality with dependency injection.

    Args:
        args: Parsed command-line arguments
        repo_manager: Repository manager instance
        formatter: Output formatter instance
        symbol_storage: Symbol storage instance for search operations (required)
    """
    # Load repository configuration
    try:
        repo_manager.load_configuration()
        repo_config = repo_manager.get_repository(args.repo)
        if not repo_config:
            print(
                f"Error: Repository '{args.repo}' not found in configuration",
                file=sys.stderr,
            )
            sys.exit(1)

        # Handle both RepositoryConfig object and dict for testing
        if isinstance(repo_config, RepositoryConfig):
            repo_path = repo_config.workspace
        else:
            repo_path = repo_config["workspace"]

        # Validate repository path
        if not Path(repo_path).exists():
            print(
                f"Error: Repository path does not exist: {repo_path}", file=sys.stderr
            )
            sys.exit(1)

    except Exception as e:
        print(f"Error loading repository configuration: {e}", file=sys.stderr)
        sys.exit(1)

    # Prepare tool arguments
    tool_args: dict[str, Any] = {}

    if args.tool == "search_symbols":
        tool_args["query"] = args.query
        if args.kind:
            tool_args["symbol_kind"] = args.kind
        tool_args["limit"] = args.limit

    # Execute tool
    try:
        result = await execute_tool_command(
            args.tool, tool_args, args.repo, repo_path, symbol_storage
        )

        # Format and display output
        if args.format == "json":
            output = formatter.format_json(result)
        elif args.format == "table":
            output = formatter.format_table(result)
        else:  # simple
            output = formatter.format_simple(result)

        print(output)

        # Exit with error code if there was an error
        if "error" in result:
            sys.exit(1)

    except Exception as e:
        print(f"Error executing tool: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    """Main CLI entry point - handles argument parsing and object creation."""
    parser = argparse.ArgumentParser(
        description="Simple CLI for MCP Tool Testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s search_symbols --query "UserManager" --repo my-repo
  %(prog)s search_symbols --query "get_user" --kind function --limit 10
  %(prog)s codebase_health_check --repo my-repo --format table
  %(prog)s search_symbols --query "Config" --format json
        """,
    )

    parser.add_argument(
        "tool",
        choices=["search_symbols", "codebase_health_check"],
        help="Tool to execute",
    )
    parser.add_argument("--repo", required=True, help="Repository name to operate on")
    parser.add_argument(
        "--format",
        choices=["json", "table", "simple"],
        default="simple",
        help="Output format",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )

    # Tool-specific arguments
    parser.add_argument(
        "--query", help="Search query for symbols (required for search_symbols)"
    )
    parser.add_argument(
        "--kind",
        choices=["function", "class", "variable"],
        help="Filter by symbol kind",
    )
    parser.add_argument(
        "--limit", type=int, default=50, help="Maximum number of results (1-100)"
    )

    args = parser.parse_args()

    # Configure logging
    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    # Validate tool-specific arguments
    if args.tool == "search_symbols":
        if not args.query:
            print("Error: --query is required for search_symbols tool", file=sys.stderr)
            sys.exit(1)

        if args.limit < 1 or args.limit > 100:
            print("Error: --limit must be between 1 and 100", file=sys.stderr)
            sys.exit(1)

    # Create production objects
    repo_manager = RepositoryManager()
    formatter = OutputFormatter()

    # Use persistent database in user data directory
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    symbol_storage = SQLiteSymbolStorage(str(SYMBOLS_DB_PATH))

    # Execute CLI functionality
    asyncio.run(execute_cli(args, repo_manager, formatter, symbol_storage))


if __name__ == "__main__":
    main()
