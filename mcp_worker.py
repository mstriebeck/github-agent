#!/usr/bin/env python3

"""
MCP Worker Process - Single Repository Handler
Worker process that handles MCP protocol for a single repository on a dedicated port.

This worker process:
- Handles a single repository with clean MCP endpoints
- Runs on a dedicated port assigned by the master process
- Provides both GitHub PR tools and codebase tools for the specific repository
- Uses a single worker per repository architecture (no complex URL routing)
"""

import argparse
import asyncio
import json
import logging
import os
import queue
import signal
import sys
import traceback
from datetime import datetime
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

import codebase_tools
import github_tools
from constants import DATA_DIR, LOGS_DIR, Language
from github_tools import (
    GitHubAPIContext,
    execute_find_pr_for_branch,
    execute_get_build_status,
    execute_get_current_branch,
    execute_get_current_commit,
    execute_get_pr_comments,
    execute_github_check_ci_build_and_test_errors_not_local,
    execute_github_check_ci_lint_errors_not_local,
)

# Import shared functionality
from repository_manager import RepositoryConfig, RepositoryManager
from shutdown_simple import SimpleShutdownCoordinator
from symbol_storage import ProductionSymbolStorage, SQLiteSymbolStorage
from system_utils import MicrosecondFormatter, log_system_state

# Tool modules for dynamic dispatch
TOOL_MODULES = [github_tools, codebase_tools]


class MCPWorker:
    """Worker process for handling a single repository with both GitHub and codebase tools"""

    # Class member type annotations
    repo_name: str
    repo_path: str
    port: int
    description: str
    language: Language
    logger: logging.Logger
    app: FastAPI
    shutdown_coordinator: SimpleShutdownCoordinator
    symbol_storage: SQLiteSymbolStorage | None

    def __init__(self, repository_config: RepositoryConfig, db_path: str | None = None):
        # Store repository configuration
        self.repo_config = repository_config
        self.db_path = db_path

        # Initialize logger first
        self.logger = logging.getLogger(f"worker-{repository_config.name}")
        self.logger.info(
            f"Starting initialization for {repository_config.name} ({repository_config.language})"
        )

        # Load environment variables from .env file first
        dotenv_path = DATA_DIR / ".env"
        if dotenv_path.exists():
            self.logger.info(f"Loading .env from {dotenv_path}")
            load_dotenv(dotenv_path)
            self.logger.info(
                f"GITHUB_TOKEN loaded: {'Yes' if os.getenv('GITHUB_TOKEN') else 'No'}"
            )
        else:
            self.logger.info(f"No .env file found at {dotenv_path}")
            # Try current directory as fallback
            if os.path.exists(".env"):
                self.logger.info("Loading .env from current directory")
                load_dotenv()
                self.logger.info(
                    f"GITHUB_TOKEN loaded: {'Yes' if os.getenv('GITHUB_TOKEN') else 'No'}"
                )

        # Extract fields for easier access
        self.repo_name = repository_config.name
        self.repo_path = repository_config.workspace
        self.port = repository_config.port
        self.description = repository_config.description
        self.language = repository_config.language
        self.python_path = repository_config.python_path

        # Set up enhanced logging for this worker (use system-appropriate location)
        log_dir = LOGS_DIR
        log_dir.mkdir(parents=True, exist_ok=True)

        # Setup enhanced logging with microsecond precision (logger already initialized)
        # Logging level should be set by master, default to INFO if not specified
        self.logger.setLevel(logging.INFO)

        # Clear any existing handlers
        if self.logger.handlers:
            self.logger.handlers.clear()

        # Detailed formatter with microseconds
        detailed_formatter = MicrosecondFormatter(
            "%(asctime)s [%(levelname)8s] %(name)s.%(funcName)s:%(lineno)d - %(message)s"
        )

        # Console formatter with microseconds
        console_formatter = MicrosecondFormatter(
            "%(asctime)s [%(levelname)s] %(message)s"
        )

        # Add console handler for immediate feedback
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(console_formatter)
        console_handler.setLevel(logging.INFO)
        self.logger.addHandler(console_handler)

        # Add file handler
        file_handler = logging.FileHandler(log_dir / f"{self.repo_name}.log")
        file_handler.setFormatter(detailed_formatter)
        file_handler.setLevel(logging.DEBUG)
        self.logger.addHandler(file_handler)

        self.logger.info(
            f"Worker initializing for {self.repo_name} ({self.language.value}) on port {self.port}"
        )
        self.logger.info(f"Repository path: {self.repo_path}")
        self.logger.info(f"Log directory: {log_dir}")

        # Initialize simple shutdown coordination
        self.shutdown_coordinator = SimpleShutdownCoordinator(self.logger)

        # Validate repository path early
        if not os.path.exists(self.repo_path):
            self.logger.error(f"Repository path {self.repo_path} does not exist!")
            raise ValueError(f"Repository path {self.repo_path} does not exist")

        self.logger.debug("Creating GitHub context...")
        try:
            # Create GitHub context
            self.github_context = GitHubAPIContext(self.repo_config)
            self.logger.debug("GitHub context created successfully")
        except Exception as e:
            self.logger.error(f"Failed to create GitHub context: {e}")
            raise

        self.logger.debug("Setting up repository manager...")
        try:
            # Set up temporary repository manager for this worker
            # This allows the shared tool functions to work with this repository
            self._setup_repository_manager()
            self.logger.debug("Repository manager setup complete")
        except Exception as e:
            self.logger.error(f"Failed to setup repository manager: {e}")
            raise

        self.logger.debug("Creating message queue...")
        # Message queue for MCP communication
        self.message_queue: queue.Queue[dict[str, Any]] = queue.Queue()

        # Server instance for shutdown
        self.server: uvicorn.Server | None = None
        self.shutdown_event = asyncio.Event()

        # Initialize symbol storage for Python repositories
        self.symbol_storage = None
        if self.language == Language.PYTHON:
            self.logger.debug("Initializing symbol storage for Python repository...")
            try:
                self._initialize_symbol_storage()
                self.logger.debug("Symbol storage initialized successfully")
            except Exception as e:
                self.logger.error(f"Failed to initialize symbol storage: {e}")
                # Don't raise - continue without symbol storage
                self.symbol_storage = None

        self.logger.debug("Creating FastAPI app...")
        try:
            # Create FastAPI app
            self.app = self.create_app()
            self.logger.debug("FastAPI app created successfully")
        except Exception as e:
            self.logger.error(f"Failed to create FastAPI app: {e}")
            raise

        self.logger.info(
            f"Worker initialization complete for {self.repo_name} on port {self.port}"
        )

    def _initialize_symbol_storage(self) -> None:
        """Initialize symbol storage for codebase tools."""
        try:
            # Use the provided database path or default to production storage
            if self.db_path:
                self.symbol_storage = SQLiteSymbolStorage(self.db_path)
            else:
                self.symbol_storage = ProductionSymbolStorage()
            # Don't create schema here - master already did that

            self.logger.info(
                f"Symbol storage connected to database: {getattr(self.symbol_storage, 'db_path', 'production')}"
            )

        except Exception as e:
            self.logger.error(f"Failed to initialize symbol storage: {e}")
            raise

    def _setup_repository_manager(self) -> None:
        """Set up a temporary repository manager for this worker's repository"""
        self.logger.debug("Setting up github_tools module...")
        try:
            # Configure github_tools with repository configuration
            self.logger.debug("Successfully accessed github_tools")

            # Configure github_tools logger immediately after import
            github_tools_logger = logging.getLogger("github_tools")
            for handler in self.logger.handlers:
                github_tools_logger.addHandler(handler)
            github_tools_logger.setLevel(logging.DEBUG)
            self.logger.info("Configured github_tools logger")

        except Exception as e:
            self.logger.error(f"Failed to import github_tools: {e}")
            raise

        self.logger.debug("Setting up codebase_tools module...")
        try:
            # Configure codebase_tools logger
            codebase_tools_logger = logging.getLogger("codebase_tools")
            for handler in self.logger.handlers:
                codebase_tools_logger.addHandler(handler)
            codebase_tools_logger.setLevel(logging.DEBUG)
            self.logger.info("Configured codebase_tools logger")

        except Exception as e:
            self.logger.error(f"Failed to configure codebase_tools: {e}")
            raise

        self.logger.debug("Creating temporary repository manager...")
        try:
            # Create a minimal repository manager that only knows about this repo
            temp_repo_manager = RepositoryManager()
            temp_repo_manager.add_repository(self.repo_name, self.repo_config)
            self.logger.debug(f"Created repository manager with repo: {self.repo_name}")
        except Exception as e:
            self.logger.error(f"Failed to create repository manager: {e}")
            raise

        self.logger.debug("Setting global repository manager in github_tools...")
        try:
            # Replace the global repository manager in the tools modules
            github_tools.repo_manager = temp_repo_manager
            self.logger.debug("Successfully set global repository manager")
        except Exception as e:
            self.logger.error(f"Failed to set global repository manager: {e}")
            raise

    def create_app(self) -> FastAPI:
        """Create FastAPI application for this worker"""
        app = FastAPI(
            title=f"MCP Worker - {self.repo_name}",
            description=f"GitHub PR management and codebase tools for {self.repo_name}",
            version="2.0.0",
        )

        # Add CORS middleware
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Root endpoint
        @app.get("/")
        async def root() -> dict[str, Any]:
            return {
                "name": f"MCP Worker - {self.repo_name}",
                "repository": self.repo_name,
                "port": self.port,
                "path": self.repo_path,
                "description": self.description,
                "version": "2.0.0",
                "status": "running",
                "endpoints": {"health": "/health", "mcp": "/mcp/"},
                "tool_categories": ["github", "codebase"],
            }

        # Health check endpoint
        @app.get("/health")
        async def health_check() -> dict[str, Any]:
            github_configured = bool(os.getenv("GITHUB_TOKEN"))
            return {
                "status": "healthy",
                "repository": self.repo_name,
                "port": self.port,
                "timestamp": datetime.now().isoformat(),
                "github_configured": github_configured,
                "repo_path_exists": os.path.exists(self.repo_path),
                "tool_categories": ["github", "codebase"],
            }

        # Graceful shutdown endpoint
        @app.post("/shutdown")
        async def graceful_shutdown() -> dict[str, Any]:
            """Handle graceful shutdown request from master"""
            self.logger.info(
                "Received shutdown request, beginning graceful shutdown..."
            )

            # Trigger shutdown sequence
            self.shutdown_event.set()
            return {"status": "shutdown_initiated"}

        # MCP SSE endpoint
        @app.get("/mcp/")
        async def mcp_sse_endpoint(request: Request) -> StreamingResponse:
            """MCP SSE endpoint for server-to-client messages"""
            client_host = request.client.host if request.client else "unknown"
            self.logger.info(f"SSE connection from {client_host}")

            async def generate_sse():
                try:
                    # Send endpoint event with POST URL
                    yield "event: endpoint\n"
                    yield f"data: http://localhost:{self.port}/mcp/\n\n"

                    # Process queued messages and keep connection alive
                    keepalive_counter = 0
                    while True:
                        # Check for queued messages
                        try:
                            while not self.message_queue.empty():
                                message = self.message_queue.get_nowait()
                                yield "event: message\n"
                                yield f"data: {json.dumps(message)}\n\n"
                        except Exception as e:
                            self.logger.warning(
                                f"Failed to process message from queue: {e}"
                            )

                        await asyncio.sleep(0.1)

                        # Send keepalive every 30 seconds
                        keepalive_counter += 1
                        if keepalive_counter >= 300:
                            yield ": keepalive\n\n"
                            keepalive_counter = 0

                except Exception as e:
                    yield "event: error\n"
                    yield f'data: {{"error": "{e!s}"}}\n\n'

            return StreamingResponse(
                generate_sse(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "Access-Control-Allow-Origin": "*",
                },
            )

        # MCP POST endpoint
        @app.post("/mcp/")
        async def mcp_post_endpoint(request: Request) -> dict[str, Any]:
            """Handle POST requests (JSON-RPC MCP protocol)"""
            try:
                body = await request.json()
                self.logger.info(f"Received MCP request: {body.get('method')}")

                if body.get("method") == "initialize":
                    response = {
                        "jsonrpc": "2.0",
                        "id": body.get("id", 1),
                        "result": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {
                                "tools": {"listChanged": False},
                                "prompts": {"listChanged": False},
                                "resources": {"subscribe": False, "listChanged": False},
                                "experimental": {},
                            },
                            "serverInfo": {
                                "name": f"mcp-agent-{self.repo_name}",
                                "version": "2.0.0",
                                "description": f"GitHub Pull Request management, code review, CI/CD build analysis, codebase health checks, and Git repository tools for {self.repo_name}. Provides GitHub API integration, build log parsing, linter analysis, test failure extraction, PR comment management, local Git operations, and repository analysis.",
                            },
                        },
                    }
                    self.message_queue.put(response)
                    return {"status": "queued"}

                elif body.get("method") == "notifications/initialized":
                    self.logger.info("Received initialized notification")
                    return {"status": "ok"}

                elif body.get("method") == "tools/list":
                    # Dynamically collect tools from all registered modules
                    all_tools = []
                    for module in TOOL_MODULES:
                        all_tools.extend(
                            module.get_tools(self.repo_name, self.repo_path)
                        )

                    response = {
                        "jsonrpc": "2.0",
                        "id": body.get("id", 1),
                        "result": {"tools": all_tools},
                    }
                    self.message_queue.put(response)
                    return {"status": "queued"}

                elif body.get("method") == "tools/call":
                    # Handle tool execution for this repository
                    tool_name = body.get("params", {}).get("name")
                    tool_args = body.get("params", {}).get("arguments", {})

                    self.logger.info(f"Tool call '{tool_name}' with args: {tool_args}")

                    result = None

                    # Handle special cases that need custom parameter processing
                    if tool_name == "github_find_pr_for_branch":
                        branch_name = tool_args.get("branch_name")
                        if not branch_name:
                            # Auto-detect current branch
                            current_branch_result = await execute_get_current_branch(
                                self.repo_name
                            )
                            current_branch_data = json.loads(current_branch_result)
                            if current_branch_data.get("error"):
                                result = json.dumps(
                                    {
                                        "error": f"Failed to get current branch: {current_branch_data.get('error')}"
                                    }
                                )
                            else:
                                branch_name = current_branch_data.get("branch")
                                result = await execute_find_pr_for_branch(
                                    self.repo_name, branch_name
                                )
                        else:
                            result = await execute_find_pr_for_branch(
                                self.repo_name, branch_name
                            )

                    elif tool_name == "github_get_pr_comments":
                        pr_number = tool_args.get("pr_number")
                        if not pr_number:
                            # Auto-detect PR for current branch
                            current_branch_result = await execute_get_current_branch(
                                self.repo_name
                            )
                            current_branch_data = json.loads(current_branch_result)
                            if current_branch_data.get("error"):
                                result = json.dumps(
                                    {
                                        "error": f"Failed to get current branch: {current_branch_data.get('error')}"
                                    }
                                )
                            else:
                                branch_name = current_branch_data.get("branch")
                                find_pr_result = await execute_find_pr_for_branch(
                                    self.repo_name, branch_name
                                )
                                find_pr_data = json.loads(find_pr_result)
                                if find_pr_data.get("error"):
                                    result = json.dumps(
                                        {
                                            "error": f"No PR found for current branch '{branch_name}': {find_pr_data.get('error')}"
                                        }
                                    )
                                else:
                                    pr_number = find_pr_data.get("number")
                                    result = await execute_get_pr_comments(
                                        self.repo_name, pr_number
                                    )
                        else:
                            result = await execute_get_pr_comments(
                                self.repo_name, pr_number
                            )

                    elif tool_name == "github_get_build_status":
                        commit_sha = tool_args.get("commit_sha")
                        if not commit_sha:
                            # Auto-detect current commit
                            current_commit_result = await execute_get_current_commit(
                                self.repo_name
                            )
                            current_commit_data = json.loads(current_commit_result)
                            if current_commit_data.get("error"):
                                result = json.dumps(
                                    {
                                        "error": f"Failed to get current commit: {current_commit_data.get('error')}"
                                    }
                                )
                            else:
                                commit_sha = current_commit_data.get("sha")
                                result = await execute_get_build_status(
                                    self.repo_name, commit_sha
                                )
                        else:
                            result = await execute_get_build_status(
                                self.repo_name, commit_sha
                            )

                    elif tool_name == "github_check_ci_lint_errors_not_local":
                        build_id = tool_args.get("build_id")
                        self.logger.info(
                            f"Calling lint errors with language: {self.language.value}"
                        )
                        result = await execute_github_check_ci_lint_errors_not_local(
                            self.repo_name, self.language.value, build_id
                        )

                    elif tool_name == "github_check_ci_build_and_test_errors_not_local":
                        build_id = tool_args.get("build_id")
                        result = await execute_github_check_ci_build_and_test_errors_not_local(
                            self.repo_name, self.language.value, build_id
                        )

                    elif tool_name == "search_symbols":
                        query = tool_args.get("query")
                        symbol_kind = tool_args.get("symbol_kind")
                        limit = tool_args.get("limit", 50)

                        if not query:
                            result = json.dumps(
                                {
                                    "error": "Query parameter is required for symbol search"
                                }
                            )
                        elif not self.symbol_storage:
                            result = json.dumps(
                                {
                                    "error": "Symbol storage not available for this repository"
                                }
                            )
                        else:
                            result = await codebase_tools.execute_tool(
                                tool_name,
                                repo_name=self.repo_name,
                                repo_path=self.repo_path,
                                query=query,
                                symbol_kind=symbol_kind,
                                limit=limit,
                                symbol_storage=self.symbol_storage,
                            )

                    # If no special handling was needed, use module dispatch
                    if result is None:
                        # Try to find the tool in any of the registered modules
                        for module in TOOL_MODULES:
                            if tool_name in module.TOOL_HANDLERS:
                                # Standard tools that just need repo_name and repo_path
                                if tool_name in [
                                    "git_get_current_branch",
                                    "git_get_current_commit",
                                    "codebase_health_check",
                                ]:
                                    result = await module.execute_tool(
                                        tool_name,
                                        repo_name=self.repo_name,
                                        repository_workspace=self.repo_path,
                                        **tool_args,
                                    )
                                elif tool_name == "github_post_pr_reply":
                                    # This tool only needs repo_name, not repo_path
                                    result = await module.execute_tool(
                                        tool_name,
                                        repo_name=self.repo_name,
                                        **tool_args,
                                    )
                                else:
                                    # For other tools, pass all args as-is
                                    result = await module.execute_tool(
                                        tool_name, **tool_args
                                    )
                                break

                        # If tool not found in any module
                        if result is None:
                            result = json.dumps(
                                {"error": f"Tool '{tool_name}' not implemented"}
                            )

                    response = {
                        "jsonrpc": "2.0",
                        "id": body.get("id", 1),
                        "result": {"content": [{"type": "text", "text": result}]},
                    }
                    self.message_queue.put(response)
                    return {"status": "queued"}

                return {
                    "jsonrpc": "2.0",
                    "id": body.get("id", 1),
                    "error": {"code": -32601, "message": "Method not found"},
                }

            except Exception as e:
                self.logger.error(f"Error handling MCP request: {e}")
                return {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "error": {"code": -32603, "message": f"Internal error: {e!s}"},
                }

        return app

    def signal_handler(self, signum: int, frame: Any) -> None:
        """Handle shutdown signals"""
        signal_name = signal.Signals(signum).name
        self.logger.info(
            f"Received signal {signum} ({signal_name}), initiating graceful shutdown..."
        )

        # Use simple shutdown coordinator
        self.shutdown_coordinator.initiate_shutdown(f"signal_{signal_name}")

        if self.server:
            self.logger.info("Stopping uvicorn server...")
            self.server.should_exit = True

        # Set the shutdown event to wake up the main loop
        if hasattr(self, "shutdown_event"):
            self._shutdown_task = asyncio.create_task(self._set_shutdown_event())
            # Store reference to prevent task being garbage collected

    async def _set_shutdown_event(self):
        """Set shutdown event from async context"""
        self.shutdown_event.set()

    async def start(self):
        """Start the worker process"""
        self.logger.debug("Setting up uvicorn...")

        self.logger.info(f"Starting worker for {self.repo_name} on port {self.port}")
        self.logger.info(f"Repository path: {self.repo_path}")
        self.logger.info(f"MCP endpoint: http://localhost:{self.port}/mcp/")

        # Log initial system state
        log_system_state(self.logger, f"WORKER_{self.repo_name.upper()}_STARTING")

        # Note: Port availability is checked by the master process before starting workers

        self.logger.debug("Creating uvicorn config...")
        try:
            # Start the server
            config = uvicorn.Config(
                self.app, host="0.0.0.0", port=self.port, log_level="info"
            )
            self.logger.debug("Uvicorn config created successfully")
        except Exception as e:
            self.logger.error(f"Failed to create uvicorn config: {e}")
            raise

        self.logger.debug("Creating uvicorn server...")
        try:
            self.server = uvicorn.Server(config)
            self.logger.debug("Uvicorn server created successfully")
        except Exception as e:
            self.logger.error(f"Failed to create uvicorn server: {e}")
            raise

        # Set up signal handlers
        self.logger.debug("Setting up signal handlers...")
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)
        self.logger.debug("Signal handlers configured")

        self.logger.info(f"Starting uvicorn server on port {self.port}...")
        try:
            if self.server is not None:
                # Run server in background and wait for shutdown event
                self.logger.info("Creating server and shutdown tasks...")
                server_task = asyncio.create_task(self.server.serve())
                shutdown_task = asyncio.create_task(self.shutdown_event.wait())
                self.logger.debug("Server and shutdown tasks created successfully")

                # Wait for either server to complete or shutdown event
                done, pending = await asyncio.wait(
                    [server_task, shutdown_task], return_when=asyncio.FIRST_COMPLETED
                )

                # Cancel pending tasks
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

                # If shutdown was triggered, execute graceful shutdown
                if shutdown_task in done:
                    await self.shutdown_sequence()

            else:
                self.logger.error("Server is None, cannot serve")
                raise RuntimeError("Server is None")

        except Exception as e:
            self.logger.error(f"Failed to start uvicorn server: {e}")
            raise
        finally:
            # Ensure cleanup happens
            self.logger.info("Performing final cleanup...")
            self.shutdown_coordinator.initiate_shutdown("server_stopped")

    async def shutdown_sequence(self):
        """Worker's graceful shutdown process"""
        self.logger.info("Beginning graceful shutdown...")

        try:
            # 1. Stop accepting new connections
            if self.server:
                self.server.should_exit = True
                self.logger.info("Server marked for shutdown")

            # 2. Wait briefly for ongoing requests
            await asyncio.sleep(2)

            # 3. Force close server
            if self.server:
                # Uvicorn doesn't have a clean shutdown method, so we exit
                self.logger.info("Closing server...")

            # 4. Clean up any resources
            if self.symbol_storage:
                self.logger.info("Closing worker symbol storage connection...")
                self.symbol_storage.close()
                self.symbol_storage = None

            self.logger.info("✓ Graceful shutdown complete")

        except Exception as e:
            self.logger.error(f"Error during shutdown: {e}")
        finally:
            # Always exit cleanly
            sys.exit(0)


def main() -> None:
    """Main entry point for worker process"""
    # Set up basic logging immediately
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()],
    )

    logger = logging.getLogger(__name__)
    logger.info("Starting worker process...")

    parser = argparse.ArgumentParser(description="MCP Worker Process")
    parser.add_argument("--repo-name", required=True, help="Repository name")
    parser.add_argument("--repo-path", required=True, help="Repository filesystem path")
    parser.add_argument("--port", type=int, required=True, help="Port to listen on")
    parser.add_argument("--description", default="", help="Repository description")
    parser.add_argument(
        "--language",
        required=True,
        choices=["python", "swift"],
        help="Repository language",
    )
    parser.add_argument(
        "--python-path", required=True, help="Path to Python executable"
    )

    logger.info("Parsing arguments...")
    args = parser.parse_args()
    logger.info(
        f"Arguments: repo_name={args.repo_name}, repo_path={args.repo_path}, port={args.port}, language={args.language}"
    )

    # Validate arguments
    logger.info(f"Validating repository path: {args.repo_path}")
    if not os.path.exists(args.repo_path):
        logger.error(f"Repository path {args.repo_path} does not exist")
        sys.exit(1)
    logger.info("Repository path validation passed")

    # Create repository config from arguments and start worker
    logger.info("Creating repository config from arguments...")
    try:
        repository_config = RepositoryConfig.from_args(args)
        logger.info("Creating worker instance...")
        worker = MCPWorker(repository_config)
        worker.logger.info("Worker instance created successfully")
    except Exception as e:
        logger.error(f"Failed to create worker: {e}")
        traceback.print_exc()
        sys.exit(1)

    worker.logger.info("Starting worker async loop...")
    try:
        asyncio.run(worker.start())

        # Get final exit code from shutdown coordinator
        exit_code = worker.shutdown_coordinator.get_exit_code()
        worker.logger.info(f"Worker shutting down with exit code: {exit_code}")
        sys.exit(exit_code)

    except KeyboardInterrupt:
        worker.logger.info("Worker stopped by user")
        exit_code = worker.shutdown_coordinator.get_exit_code()
        sys.exit(exit_code)
    except Exception as e:
        worker.logger.error(f"Worker failed: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
