#!/usr/bin/env python3

"""
GitHub MCP Worker Process - Single Repository Handler
Worker process that handles MCP protocol for a single repository on a dedicated port.

This worker process:
- Handles a single repository with clean MCP endpoints
- Runs on a dedicated port assigned by the master process
- Provides all GitHub PR tools for the specific repository
- Simplified architecture without URL routing complexity
"""

import asyncio
import os
import json
import logging
import argparse
import sys
import signal
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import queue
from datetime import datetime

# Import shared functionality
from repository_manager import RepositoryConfig, RepositoryManager
from github_tools import (
    GitHubAPIContext,
    execute_find_pr_for_branch, execute_get_pr_comments, execute_post_pr_reply,
    execute_get_current_branch, execute_get_current_commit,
    execute_read_swiftlint_logs, execute_read_build_logs, execute_get_build_status
)

class GitHubMCPWorker:
    """Worker process for handling a single repository"""
    
    def __init__(self, repo_name: str, repo_path: str, port: int, description: str):
        print(f"[WORKER INIT] Starting initialization for {repo_name}")  # Use print for immediate output
        
        self.repo_name = repo_name
        self.repo_path = repo_path
        self.port = port
        self.description = description
        
        # Set up logging for this worker (use system-appropriate location)
        from pathlib import Path
        log_dir = Path.home() / ".local" / "share" / "github-agent" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger = logging.getLogger(f"worker-{repo_name}")
        
        # Add console handler for immediate feedback
        console_handler = logging.StreamHandler()
        console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)
        
        # Add file handler
        file_handler = logging.FileHandler(log_dir / f'{repo_name}.log')
        file_handler.setFormatter(console_formatter)
        self.logger.addHandler(file_handler)
        
        self.logger.setLevel(logging.DEBUG)  # Use DEBUG level for more visibility
        
        self.logger.info(f"Worker initializing for {repo_name} on port {port}")
        self.logger.info(f"Repository path: {repo_path}")
        self.logger.info(f"Log directory: {log_dir}")
        
        # Validate repository path early
        if not os.path.exists(repo_path):
            self.logger.error(f"Repository path {repo_path} does not exist!")
            raise ValueError(f"Repository path {repo_path} does not exist")
        
        self.logger.debug("Creating repository configuration...")
        try:
            # Create repository configuration
            self.logger.debug(f"RepositoryConfig args: name={repo_name}, path={repo_path}, description={description}")
            self.repo_config = RepositoryConfig(
                name=repo_name,
                path=repo_path,
                description=description
            )
            self.logger.debug("Repository configuration created successfully")
        except Exception as e:
            self.logger.error(f"Failed to create repository configuration: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            raise
        
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
        self.message_queue = queue.Queue()
        
        # Server instance for shutdown
        self.server = None
        self.shutdown_event = asyncio.Event()
        
        self.logger.debug("Creating FastAPI app...")
        try:
            # Create FastAPI app
            self.app = self.create_app()
            self.logger.debug("FastAPI app created successfully")
        except Exception as e:
            self.logger.error(f"Failed to create FastAPI app: {e}")
            raise
        
        self.logger.info(f"Worker initialization complete for {repo_name} on port {port}")
        
    def _setup_repository_manager(self):
        """Set up a temporary repository manager for this worker's repository"""
        self.logger.debug("Importing github_tools module...")
        try:
            # Create a temporary in-memory repository manager with just this repository
            import github_tools
            self.logger.debug("Successfully imported github_tools")
            
            # Configure github_tools logger immediately after import
            github_tools_logger = logging.getLogger('github_tools')
            for handler in self.logger.handlers:
                github_tools_logger.addHandler(handler)
            github_tools_logger.setLevel(logging.DEBUG)
            self.logger.info("Configured github_tools logger")
            
        except Exception as e:
            self.logger.error(f"Failed to import github_tools: {e}")
            raise
        
        self.logger.debug("Creating temporary repository manager...")
        try:
            # Create a minimal repository manager that only knows about this repo
            temp_repo_manager = RepositoryManager()
            temp_repo_manager.repositories = {self.repo_name: self.repo_config}
            self.logger.debug(f"Created repository manager with repo: {self.repo_name}")
        except Exception as e:
            self.logger.error(f"Failed to create repository manager: {e}")
            raise
        
        self.logger.debug("Setting global repository manager in github_tools...")
        try:
            # Replace the global repository manager in the tools module
            github_tools.repo_manager = temp_repo_manager
            self.logger.debug("Successfully set global repository manager")
        except Exception as e:
            self.logger.error(f"Failed to set global repository manager: {e}")
            raise
    
    def create_app(self) -> FastAPI:
        """Create FastAPI application for this worker"""
        app = FastAPI(
            title=f"GitHub MCP Worker - {self.repo_name}",
            description=f"GitHub PR management for {self.repo_name}",
            version="2.0.0"
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
        async def root():
            return {
                "name": f"GitHub MCP Worker - {self.repo_name}",
                "repository": self.repo_name,
                "port": self.port,
                "path": self.repo_path,
                "description": self.description,
                "version": "2.0.0",
                "status": "running",
                "endpoints": {
                    "health": "/health",
                    "mcp": "/mcp/"
                }
            }
        
        # Health check endpoint
        @app.get("/health")
        async def health_check():
            github_configured = bool(os.getenv("GITHUB_TOKEN"))
            return {
                "status": "healthy",
                "repository": self.repo_name,
                "port": self.port,
                "timestamp": datetime.now().isoformat(),
                "github_configured": github_configured,
                "repo_path_exists": os.path.exists(self.repo_path)
            }
        
        # MCP SSE endpoint (simplified - no repository routing)
        @app.get("/mcp/")
        async def mcp_sse_endpoint(request: Request):
            """MCP SSE endpoint for server-to-client messages"""
            self.logger.info(f"SSE connection from {request.client.host}")
            
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
                        except:
                            pass
                        
                        await asyncio.sleep(0.1)
                        
                        # Send keepalive every 30 seconds
                        keepalive_counter += 1
                        if keepalive_counter >= 300:
                            yield ": keepalive\n\n"
                            keepalive_counter = 0
                        
                except Exception as e:
                    yield f"event: error\n"
                    yield f"data: {{\"error\": \"{str(e)}\"}}\n\n"
            
            return StreamingResponse(
                generate_sse(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "Access-Control-Allow-Origin": "*",
                }
            )
        
        # MCP POST endpoint (simplified - no repository routing)
        @app.post("/mcp/")
        async def mcp_post_endpoint(request: Request):
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
                                "experimental": {}
                            },
                            "serverInfo": {
                                "name": f"github-pr-agent-{self.repo_name}",
                                "version": "2.0.0",
                                "description": f"GitHub Pull Request management, code review, CI/CD build analysis, and Git repository tools for {self.repo_name}. Provides GitHub API integration, build log parsing, linter analysis, test failure extraction, PR comment management, and local Git operations."
                            }
                        }
                    }
                    self.message_queue.put(response)
                    return {"status": "queued"}
                
                elif body.get("method") == "notifications/initialized":
                    self.logger.info("Received initialized notification")
                    return {"status": "ok"}
                
                elif body.get("method") == "tools/list":
                    # Return GitHub PR tools for this repository
                    response = {
                        "jsonrpc": "2.0",
                        "id": body.get("id", 1),
                        "result": {
                            "tools": [
                                {
                                    "name": "git_get_current_commit",
                                    "description": f"Get current local commit SHA, message, author and timestamp from the Git repository at {self.repo_path}. Shows the HEAD commit details including hash, commit message, author, and date. Local Git operation, no network required.",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {},
                                        "required": []
                                    }
                                },
                                {
                                    "name": "git_get_current_branch",
                                    "description": f"Get the currently checked out Git branch name from the local repository at {self.repo_path}. Returns the active branch that would be used for new commits. Local Git operation, no network required.",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {},
                                        "required": []
                                    }
                                },
                                {
                                    "name": "github_find_pr_for_branch",
                                    "description": f"Find and retrieve the GitHub Pull Request associated with a specific branch in {self.repo_name}. Searches GitHub API for open PRs that have the specified branch as their head branch. Returns PR details including number, title, URL, status, and merge information. Useful for connecting local branches to GitHub PRs.",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {
                                            "branch_name": {
                                                "type": "string",
                                                "description": "Git branch name to search for (e.g., 'feature/new-login', 'main', 'develop')"
                                            }
                                        },
                                        "required": ["branch_name"]
                                    }
                                },
                                {
                                    "name": "github_get_pr_comments",
                                    "description": f"Retrieve all review comments, issue comments, and discussion threads from a GitHub Pull Request in {self.repo_name}. Uses GitHub API to fetch comments with author, timestamp, content, and reply status. Essential for finding unanswered code review comments that need responses, tracking discussion threads, and understanding PR feedback.",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {
                                            "pr_number": {
                                                "type": "integer",
                                                "description": "GitHub Pull Request number (e.g., 123 for PR #123)"
                                            }
                                        },
                                        "required": ["pr_number"]
                                    }
                                },
                                {
                                    "name": "github_post_pr_reply",
                                    "description": f"Post a reply to a specific comment in a GitHub Pull Request for {self.repo_name}. Uses GitHub API to create a threaded response to review comments or general PR discussion comments. Supports GitHub Markdown formatting for rich text responses.",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {
                                            "comment_id": {
                                                "type": "integer",
                                                "description": "GitHub comment ID to reply to (found in comment URLs or from github_get_pr_comments)"
                                            },
                                            "message": {
                                                "type": "string",
                                                "description": "Reply message content (supports GitHub Markdown formatting)"
                                            }
                                        },
                                        "required": ["comment_id", "message"]
                                    }
                                },
                                {
                                    "name": "github_get_build_and_test_errors",
                                    "description": f"Extract and return build errors, warnings, and test failures from GitHub Actions CI logs for {self.repo_name}. Analyzes CI/CD pipeline results to identify compilation errors, build warnings, failed tests, and other build issues from the latest GitHub Actions run. Essential for debugging failing builds, understanding test failures, and identifying compilation problems across different programming languages.",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {
                                            "build_id": {
                                                "type": "string",
                                                "description": "Specific GitHub Actions run ID (optional - if not provided, uses the latest run for the current commit)"
                                            }
                                        },
                                        "required": []
                                    }
                                },
                                {
                                    "name": "github_get_lint_errors",
                                    "description": f"Extract and return linting errors and code quality violations from GitHub Actions CI logs for {self.repo_name}. Parses GitHub Actions build output to extract linting violations, style issues, and code quality problems from various linters (SwiftLint, ESLint, Pylint, etc.). Helps identify code style inconsistencies, potential bugs, and maintainability issues across different programming languages.",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {
                                            "build_id": {
                                                "type": "string",
                                                "description": "Specific GitHub Actions run ID (optional - if not provided, uses the latest run for the current commit)"
                                            }
                                        },
                                        "required": []
                                    }
                                },
                                {
                                    "name": "github_get_build_status",
                                    "description": f"Get comprehensive CI/CD build status and check results for a commit in {self.repo_name}. Retrieves GitHub Actions workflow status, check runs, and build conclusions from GitHub API. Shows overall build state (success/failure/pending/in_progress), individual check run details, and failure indicators. Essential for monitoring build health, understanding CI pipeline status, and identifying failing checks.",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {
                                            "commit_sha": {
                                                "type": "string",
                                                "description": "Git commit SHA to check build status for (optional - if not provided, uses the current HEAD commit)"
                                            }
                                        },
                                        "required": []
                                    }
                                }
                            ]
                        }
                    }
                    self.message_queue.put(response)
                    return {"status": "queued"}
                
                elif body.get("method") == "tools/call":
                    # Handle tool execution for this repository
                    tool_name = body.get("params", {}).get("name")
                    tool_args = body.get("params", {}).get("arguments", {})
                    
                    self.logger.info(f"Tool call '{tool_name}' with args: {tool_args}")
                    
                    # Execute tools (all calls pass self.repo_name as the repo context)
                    if tool_name == "github_find_pr_for_branch":
                        branch_name = tool_args.get("branch_name")
                        if not branch_name:
                            result = json.dumps({"error": "branch_name is required"})
                        else:
                            result = await execute_find_pr_for_branch(self.repo_name, branch_name)
                            
                    elif tool_name == "github_get_pr_comments":
                        pr_number = tool_args.get("pr_number")
                        if not pr_number:
                            result = json.dumps({"error": "pr_number is required"})
                        else:
                            result = await execute_get_pr_comments(self.repo_name, pr_number)
                            
                    elif tool_name == "github_post_pr_reply":
                        comment_id = tool_args.get("comment_id")
                        message = tool_args.get("message")
                        if not comment_id or not message:
                            result = json.dumps({"error": "Both comment_id and message are required"})
                        else:
                            result = await execute_post_pr_reply(self.repo_name, comment_id, message)
                            
                    elif tool_name == "git_get_current_branch":
                        result = await execute_get_current_branch(self.repo_name)
                        
                    elif tool_name == "git_get_current_commit":
                        result = await execute_get_current_commit(self.repo_name)
                        
                    elif tool_name == "github_get_lint_errors":
                        build_id = tool_args.get("build_id")
                        result = await execute_read_swiftlint_logs(build_id)
                        
                    elif tool_name == "github_get_build_and_test_errors":
                        build_id = tool_args.get("build_id")
                        result = await execute_read_build_logs(build_id)
                        
                    elif tool_name == "github_get_build_status":
                        commit_sha = tool_args.get("commit_sha")
                        result = await execute_get_build_status(self.repo_name, commit_sha)
                        
                    else:
                        result = json.dumps({"error": f"Tool '{tool_name}' not implemented"})
                    
                    response = {
                        "jsonrpc": "2.0",
                        "id": body.get("id", 1),
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": result
                                }
                            ]
                        }
                    }
                    self.message_queue.put(response)
                    return {"status": "queued"}
                
                return {"jsonrpc": "2.0", "id": body.get("id", 1), "error": {"code": -32601, "message": "Method not found"}}
            
            except Exception as e:
                self.logger.error(f"Error handling MCP request: {e}")
                return {"jsonrpc": "2.0", "id": 1, "error": {"code": -32603, "message": f"Internal error: {str(e)}"}}
        
        return app
    
    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        if self.server:
            self.logger.info("Stopping uvicorn server...")
            self.server.should_exit = True
        # Set the shutdown event to wake up the main loop
        if hasattr(self, 'shutdown_event'):
            asyncio.create_task(self._set_shutdown_event())
    
    async def _set_shutdown_event(self):
        """Set shutdown event from async context"""
        self.shutdown_event.set()
    
    async def start(self):
        """Start the worker process"""
        self.logger.debug("Importing uvicorn...")
        try:
            import uvicorn
            self.logger.debug("Successfully imported uvicorn")
        except Exception as e:
            self.logger.error(f"Failed to import uvicorn: {e}")
            raise
        
        self.logger.info(f"Starting worker for {self.repo_name} on port {self.port}")
        self.logger.info(f"Repository path: {self.repo_path}")
        self.logger.info(f"MCP endpoint: http://localhost:{self.port}/mcp/")
        
        # Note: Port availability is checked by the master process before starting workers
        
        self.logger.debug("Creating uvicorn config...")
        try:
            # Start the server
            config = uvicorn.Config(
                self.app,
                host="0.0.0.0",
                port=self.port,
                log_level="info"
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
            await self.server.serve()
        except Exception as e:
            self.logger.error(f"Failed to start uvicorn server: {e}")
            raise

def main():
    """Main entry point for worker process"""
    print("[WORKER MAIN] Starting worker process...")
    
    # Set up basic logging immediately
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]
    )
    
    parser = argparse.ArgumentParser(description="GitHub MCP Worker Process")
    parser.add_argument("--repo-name", required=True, help="Repository name")
    parser.add_argument("--repo-path", required=True, help="Repository filesystem path")
    parser.add_argument("--port", type=int, required=True, help="Port to listen on")
    parser.add_argument("--description", default="", help="Repository description")
    
    print("[WORKER MAIN] Parsing arguments...")
    args = parser.parse_args()
    print(f"[WORKER MAIN] Arguments: repo_name={args.repo_name}, repo_path={args.repo_path}, port={args.port}")
    
    # Validate arguments
    print(f"[WORKER MAIN] Validating repository path: {args.repo_path}")
    if not os.path.exists(args.repo_path):
        print(f"Error: Repository path {args.repo_path} does not exist", file=sys.stderr)
        sys.exit(1)
    print("[WORKER MAIN] Repository path validation passed")
    
    # Create and start worker
    print("[WORKER MAIN] Creating worker instance...")
    try:
        worker = GitHubMCPWorker(
            repo_name=args.repo_name,
            repo_path=args.repo_path,
            port=args.port,
            description=args.description
        )
        print("[WORKER MAIN] Worker instance created successfully")
    except Exception as e:
        print(f"[WORKER MAIN] Failed to create worker: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    print("[WORKER MAIN] Starting worker async loop...")
    try:
        asyncio.run(worker.start())
    except KeyboardInterrupt:
        print("[WORKER MAIN] Worker stopped by user")
        worker.logger.info("Worker stopped by user")
    except Exception as e:
        print(f"[WORKER MAIN] Worker failed: {e}")
        import traceback
        traceback.print_exc()
        if 'worker' in locals():
            worker.logger.error(f"Worker failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
