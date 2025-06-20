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
from typing import Optional
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import queue
from datetime import datetime

# Import shared functionality
from repository_manager import RepositoryConfig, RepositoryManager
from github_tools import (
    GitHubAPIContext,
    execute_find_pr_for_branch, execute_get_pr_comments, execute_post_pr_reply,
    execute_get_current_branch, execute_get_current_commit,
    execute_read_swiftlint_logs, execute_read_build_logs
)

class GitHubMCPWorker:
    """Worker process for handling a single repository"""
    
    def __init__(self, repo_name: str, repo_path: str, port: int, description: str):
        self.repo_name = repo_name
        self.repo_path = repo_path
        self.port = port
        self.description = description
        
        # Set up logging for this worker (use system-appropriate location)
        from pathlib import Path
        log_dir = Path.home() / ".local" / "share" / "github-agent" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger = logging.getLogger(f"worker-{repo_name}")
        handler = logging.FileHandler(log_dir / f'{repo_name}.log')
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)
        
        # Create repository configuration
        self.repo_config = RepositoryConfig(
            name=repo_name,
            path=repo_path,
            description=description
        )
        
        # Create GitHub context
        self.github_context = GitHubAPIContext(self.repo_config)
        
        # Set up temporary repository manager for this worker
        # This allows the shared tool functions to work with this repository
        self._setup_repository_manager()
        
        # Message queue for MCP communication
        self.message_queue = queue.Queue()
        
        # Create FastAPI app
        self.app = self.create_app()
        
        self.logger.info(f"Worker initialized for {repo_name} on port {port}")
        
    def _setup_repository_manager(self):
        """Set up a temporary repository manager for this worker's repository"""
        # Create a temporary in-memory repository manager with just this repository
        import github_tools
        
        # Create a minimal repository manager that only knows about this repo
        temp_repo_manager = RepositoryManager()
        temp_repo_manager.repositories = {self.repo_name: self.repo_config}
        
        # Replace the global repository manager in the tools module
        github_tools.repo_manager = temp_repo_manager
    
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
                                "version": "2.0.0"
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
                                    "name": "get_current_commit",
                                    "description": f"Get current commit information for {self.repo_name}",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {},
                                        "required": []
                                    }
                                },
                                {
                                    "name": "get_current_branch",
                                    "description": f"Get current Git branch name for {self.repo_name}",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {},
                                        "required": []
                                    }
                                },
                                {
                                    "name": "find_pr_for_branch",
                                    "description": f"Find the PR associated with a branch in {self.repo_name}",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {
                                            "branch_name": {
                                                "type": "string",
                                                "description": "Branch name to search for"
                                            }
                                        },
                                        "required": ["branch_name"]
                                    }
                                },
                                {
                                    "name": "get_pr_comments",
                                    "description": f"Get all comments from a PR in {self.repo_name}",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {
                                            "pr_number": {
                                                "type": "integer",
                                                "description": "PR number"
                                            }
                                        },
                                        "required": ["pr_number"]
                                    }
                                },
                                {
                                    "name": "post_pr_reply",
                                    "description": f"Reply to a PR comment in {self.repo_name}",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {
                                            "comment_id": {
                                                "type": "integer",
                                                "description": "ID of the comment to reply to"
                                            },
                                            "message": {
                                                "type": "string",
                                                "description": "Reply message content"
                                            }
                                        },
                                        "required": ["comment_id", "message"]
                                    }
                                },
                                {
                                    "name": "read_build_logs",
                                    "description": "Read build logs for Swift compiler errors, warnings, and test failures",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {
                                            "build_id": {
                                                "type": "string",
                                                "description": "Build ID (optional, uses latest for current commit if not specified)"
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
                    if tool_name == "find_pr_for_branch":
                        branch_name = tool_args.get("branch_name")
                        if not branch_name:
                            result = json.dumps({"error": "branch_name is required"})
                        else:
                            result = await execute_find_pr_for_branch(self.repo_name, branch_name)
                            
                    elif tool_name == "get_pr_comments":
                        pr_number = tool_args.get("pr_number")
                        if not pr_number:
                            result = json.dumps({"error": "pr_number is required"})
                        else:
                            result = await execute_get_pr_comments(self.repo_name, pr_number)
                            
                    elif tool_name == "post_pr_reply":
                        comment_id = tool_args.get("comment_id")
                        message = tool_args.get("message")
                        if not comment_id or not message:
                            result = json.dumps({"error": "Both comment_id and message are required"})
                        else:
                            result = await execute_post_pr_reply(self.repo_name, comment_id, message)
                            
                    elif tool_name == "get_current_branch":
                        result = await execute_get_current_branch(self.repo_name)
                        
                    elif tool_name == "get_current_commit":
                        result = await execute_get_current_commit(self.repo_name)
                        
                    elif tool_name == "read_swiftlint_logs":
                        build_id = tool_args.get("build_id")
                        result = await execute_read_swiftlint_logs(build_id)
                        
                    elif tool_name == "read_build_logs":
                        build_id = tool_args.get("build_id")
                        result = await execute_read_build_logs(build_id)
                        
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
    
    async def start(self):
        """Start the worker process"""
        import uvicorn
        
        self.logger.info(f"Starting worker for {self.repo_name} on port {self.port}")
        self.logger.info(f"Repository path: {self.repo_path}")
        self.logger.info(f"MCP endpoint: http://localhost:{self.port}/mcp/")
        
        # Start the server
        config = uvicorn.Config(
            self.app,
            host="0.0.0.0",
            port=self.port,
            log_level="info"
        )
        server = uvicorn.Server(config)
        await server.serve()

def main():
    """Main entry point for worker process"""
    parser = argparse.ArgumentParser(description="GitHub MCP Worker Process")
    parser.add_argument("--repo-name", required=True, help="Repository name")
    parser.add_argument("--repo-path", required=True, help="Repository filesystem path")
    parser.add_argument("--port", type=int, required=True, help="Port to listen on")
    parser.add_argument("--description", default="", help="Repository description")
    
    args = parser.parse_args()
    
    # Validate arguments
    if not os.path.exists(args.repo_path):
        print(f"Error: Repository path {args.repo_path} does not exist", file=sys.stderr)
        sys.exit(1)
    
    # Create and start worker
    worker = GitHubMCPWorker(
        repo_name=args.repo_name,
        repo_path=args.repo_path,
        port=args.port,
        description=args.description
    )
    
    try:
        asyncio.run(worker.start())
    except KeyboardInterrupt:
        worker.logger.info("Worker stopped by user")
    except Exception as e:
        worker.logger.error(f"Worker failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
