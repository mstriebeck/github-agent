#!/usr/bin/env python3

"""
GitHub PR Agent MCP Server - Multi-Repository Support
Complete GitHub PR management server with MCP support for coding agents.

This server provides tools for:
- Branch and commit information
- PR discovery and comment management  
- SwiftLint and build log analysis from GitHub Actions
- Reply posting with multiple fallback strategies

NEW: Multi-repository support via URL routing:
- http://localhost:8080/mcp/repo-name/ → configured repository
- Backward compatible with single repository mode

Environment variables:
- GITHUB_TOKEN: GitHub personal access token (required)
- LOCAL_REPO_PATH: Local filesystem path to git repository (fallback mode)
- GITHUB_AGENT_REPO_CONFIG: Path to repositories.json config file

Optional:
- SERVER_HOST: Host to bind to (default: 0.0.0.0)
- SERVER_PORT: Port to listen on (default: 8080)
"""

import asyncio
import os
import json
import requests
import subprocess
import re
import zipfile
import io
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import queue
from github import Github
from git import Repo
from dotenv import load_dotenv

# Import our repository manager
from repository_manager import RepositoryManager, extract_repo_name_from_url, RepositoryConfig

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

app = FastAPI(
    title="GitHub PR Agent MCP Server - Multi-Repository",
    description="Complete GitHub PR management server with MCP support and multi-repository routing",
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

# Queue for messages to send via SSE
message_queue = queue.Queue()

# Global repository manager
repo_manager = RepositoryManager()

# GitHub API Context Class
class GitHubAPIContext:
    """Context for GitHub API operations with repository information"""
    
    def __init__(self, repo_config: RepositoryConfig):
        self.repo_config = repo_config
        self.github_token = os.getenv("GITHUB_TOKEN")
        self.github = Github(self.github_token) if self.github_token else None
        
        # Get repo name from git config
        self.repo_name = None
        self.repo = None
        if self.github and self.repo_config.path:
            try:
                # Get repo name from git remote
                output = subprocess.check_output(
                    ["git", "config", "--get", "remote.origin.url"], 
                    cwd=self.repo_config.path
                ).decode().strip()
                
                if output.startswith("git@"):
                    _, path = output.split(":", 1)
                elif output.startswith("https://"):
                    path = output.split("github.com/", 1)[-1]
                else:
                    raise ValueError(f"Unrecognized GitHub remote URL: {output}")
                
                self.repo_name = path.replace(".git", "")
                self.repo = self.github.get_repo(self.repo_name)
                logger.info(f"Initialized GitHub context for {self.repo_name}")
                
            except Exception as e:
                logger.warning(f"Failed to initialize GitHub context: {e}")
    
    def get_current_branch(self) -> str:
        """Get current branch name"""
        return subprocess.check_output(
            ["git", "branch", "--show-current"], 
            cwd=self.repo_config.path
        ).decode().strip()
    
    def get_current_commit(self) -> str:
        """Get current commit hash"""
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], 
            cwd=self.repo_config.path
        ).decode().strip()


def get_github_context(repo_name: str) -> GitHubAPIContext:
    """Get GitHub API context for a specific repository"""
    repo_config = repo_manager.get_repository(repo_name)
    if not repo_config:
        raise ValueError(f"Repository '{repo_name}' not found")
    
    return GitHubAPIContext(repo_config)

# Tool implementations with repository context
async def execute_find_pr_for_branch(repo_name: str, branch_name: str) -> str:
    """Find the PR associated with a branch in the specified repository"""
    try:
        context = get_github_context(repo_name)
        if not context.repo:
            return json.dumps({"error": f"GitHub repository not configured for {repo_name}"})

        pulls = context.repo.get_pulls(state='all')
        
        # Look for matching branch
        for pr in pulls:
            if pr.head.ref == branch_name:
                return json.dumps({
                    "found": True,
                    "pr_number": pr.number,
                    "title": pr.title,
                    "state": pr.state,
                    "url": pr.html_url,
                    "author": pr.user.login,
                    "base_branch": pr.base.ref,
                    "head_branch": pr.head.ref,
                    "repo": context.repo_name,
                    "repo_config": repo_name
                })

        return json.dumps({
            "found": False,
            "branch_name": branch_name,
            "repo": context.repo_name,
            "repo_config": repo_name,
            "message": f"No PR found for branch '{branch_name}' in {context.repo_name}"
        })

    except Exception as e:
        return json.dumps({"error": f"Failed to find PR for branch {branch_name} in {repo_name}: {str(e)}"})


async def execute_get_pr_comments(repo_name: str, pr_number: int) -> str:
    """Get all comments from a PR in the specified repository"""
    try:
        context = get_github_context(repo_name)
        if not context.repo:
            return json.dumps({"error": f"GitHub repository not configured for {repo_name}"})
        
        # Use GitHub API directly for better error handling
        headers = {"Authorization": f"token {context.github_token}"}
        
        # Get PR details first
        pr_url = f"https://api.github.com/repos/{context.repo_name}/pulls/{pr_number}"
        pr_response = requests.get(pr_url, headers=headers)
        pr_response.raise_for_status()
        pr_data = pr_response.json()
        
        # Get review comments
        comments_url = pr_data["review_comments_url"]
        comments_resp = requests.get(comments_url, headers=headers)
        comments_resp.raise_for_status()
        review_comments = comments_resp.json()
        
        # Get issue comments
        issue_comments_url = f"https://api.github.com/repos/{context.repo_name}/issues/{pr_number}/comments"
        issue_resp = requests.get(issue_comments_url, headers=headers)
        issue_resp.raise_for_status()
        issue_comments = issue_resp.json()
        
        # Format review comments
        formatted_review_comments = []
        for comment in review_comments:
            formatted_review_comments.append({
                "id": comment["id"],
                "type": "review_comment",
                "author": comment["user"]["login"],
                "body": comment["body"],
                "file": comment.get("path", ""),
                "line": comment.get("line", comment.get("original_line", 0)),
                "created_at": comment["created_at"],
                "url": comment["html_url"]
            })
        
        # Format issue comments
        formatted_issue_comments = []
        for comment in issue_comments:
            formatted_issue_comments.append({
                "id": comment["id"],
                "type": "issue_comment", 
                "author": comment["user"]["login"],
                "body": comment["body"],
                "created_at": comment["created_at"],
                "url": comment["html_url"]
            })
        
        return json.dumps({
            "pr_number": pr_number,
            "title": pr_data["title"],
            "repo": context.repo_name,
            "repo_config": repo_name,
            "review_comments": formatted_review_comments,
            "issue_comments": formatted_issue_comments,
            "total_comments": len(formatted_review_comments) + len(formatted_issue_comments)
        })
        
    except Exception as e:
        return json.dumps({"error": f"Failed to get PR comments from {repo_name}: {str(e)}"})


async def execute_post_pr_reply(repo_name: str, comment_id: int, message: str) -> str:
    """Reply to a PR comment in the specified repository"""
    try:
        context = get_github_context(repo_name)
        if not context.repo:
            return json.dumps({"error": f"GitHub repository not configured for {repo_name}"})
        
        headers = {
            "Authorization": f"token {context.github_token}",
            "Accept": "application/vnd.github+json"
        }
        
        # Try to get original comment context
        comment_url = f"https://api.github.com/repos/{context.repo_name}/pulls/comments/{comment_id}"
        comment_resp = requests.get(comment_url, headers=headers)
        
        if comment_resp.status_code == 200:
            original_comment = comment_resp.json()
            pr_url = original_comment.get("pull_request_url", "")
            pr_number = pr_url.split("/")[-1] if pr_url else None
        else:
            # Try as issue comment
            comment_url = f"https://api.github.com/repos/{context.repo_name}/issues/comments/{comment_id}"
            comment_resp = requests.get(comment_url, headers=headers)
            if comment_resp.status_code == 200:
                original_comment = comment_resp.json()
                issue_url = original_comment.get("issue_url", "")
                pr_number = issue_url.split("/")[-1] if issue_url else None
            else:
                return json.dumps({"error": f"Could not find comment with ID {comment_id} in {repo_name}"})
        
        # Strategy 1: Try direct reply to review comment
        try:
            reply_url = f"https://api.github.com/repos/{context.repo_name}/pulls/comments/{comment_id}/replies"
            reply_data = {"body": message}
            reply_resp = requests.post(reply_url, headers=headers, json=reply_data)
            
            if reply_resp.status_code in [200, 201]:
                return json.dumps({
                    "success": True,
                    "method": "direct_reply",
                    "repo": context.repo_name,
                    "repo_config": repo_name,
                    "comment_id": reply_resp.json()["id"],
                    "url": reply_resp.json()["html_url"]
                })
        except Exception:
            pass
        
        # Strategy 2: Post as issue comment (fallback)
        if pr_number:
            try:
                issue_comment_url = f"https://api.github.com/repos/{context.repo_name}/issues/{pr_number}/comments"
                issue_comment_data = {"body": f"@{original_comment['user']['login']} {message}"}
                issue_resp = requests.post(issue_comment_url, headers=headers, json=issue_comment_data)
                
                if issue_resp.status_code in [200, 201]:
                    return json.dumps({
                        "success": True,
                        "method": "issue_comment_fallback",
                        "repo": context.repo_name,
                        "repo_config": repo_name,
                        "comment_id": issue_resp.json()["id"],
                        "url": issue_resp.json()["html_url"]
                    })
            except Exception as e:
                return json.dumps({"error": f"All reply strategies failed for {repo_name}. Final error: {str(e)}"})
        
        return json.dumps({"error": f"All reply strategies failed for {repo_name}"})
        
    except Exception as e:
        return json.dumps({"error": f"Failed to post PR reply in {repo_name}: {str(e)}"})


async def execute_get_current_branch(repo_name: str) -> str:
    """Get current branch for the specified repository"""
    try:
        context = get_github_context(repo_name)
        branch = context.get_current_branch()
        return json.dumps({
            "branch": branch,
            "repo": context.repo_name,
            "repo_config": repo_name
        })
    except Exception as e:
        return json.dumps({"error": f"Failed to get current branch for {repo_name}: {str(e)}"})


async def execute_get_current_commit(repo_name: str) -> str:
    """Get current commit for the specified repository"""
    try:
        context = get_github_context(repo_name)
        commit = context.get_current_commit()
        return json.dumps({
            "commit": commit,
            "repo": context.repo_name,
            "repo_config": repo_name
        })
    except Exception as e:
        return json.dumps({"error": f"Failed to get current commit for {repo_name}: {str(e)}"})


# Build/Lint helper functions
async def get_github_repo():
    """Return the owner and repo name from the configured git repo."""
    repo_path = os.getenv("LOCAL_REPO_PATH")
    if not repo_path:
        raise ValueError("LOCAL_REPO_PATH environment variable not set")
    
    output = subprocess.check_output(["git", "config", "--get", "remote.origin.url"], cwd=repo_path).decode().strip()
    if output.startswith("git@"):
        _, path = output.split(":", 1)
    elif output.startswith("https://"):
        path = output.split("github.com/", 1)[-1]
    else:
        raise ValueError(f"Unrecognized GitHub remote URL: {output}")
    repo_name = path.replace(".git", "")
    return repo_name

async def get_github_commit():
    repo_path = os.getenv("LOCAL_REPO_PATH")
    if not repo_path:
        raise ValueError("LOCAL_REPO_PATH environment variable not set")
    
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_path).decode().strip()
    return commit

async def get_current_branch():
    repo_path = os.getenv("LOCAL_REPO_PATH")
    if not repo_path:
        raise ValueError("LOCAL_REPO_PATH environment variable not set")
    
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=repo_path).decode().strip()
    return branch

async def find_workflow_run(repo, commit, token):
    url = f"https://api.github.com/repos/{repo}/actions/runs"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"per_page": 200}
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    
    workflow_data = response.json()
    workflow_runs = workflow_data.get("workflow_runs", [])
    
    # Look for exact match
    for run in workflow_runs:
        if run["head_sha"] == commit:
            return run["id"]
    
    # Look for partial match (first 8 characters)
    short_commit = commit[:8]
    for run in workflow_runs:
        if run["head_sha"].startswith(short_commit):
            return run["id"]
    
    # Offer the most recent workflow run as fallback
    if workflow_runs:
        latest_run = workflow_runs[0]
        return latest_run["id"]
    
    raise RuntimeError(f"No matching workflow run found for commit {commit}")

async def get_artifact_id(repo, run_id, token, name="swiftlint-reports"):
    url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/artifacts"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    
    artifacts_data = response.json()
    artifacts = artifacts_data.get("artifacts", [])
    
    for artifact in artifacts:
        if artifact["name"] == name:
            return artifact["id"]
    
    raise RuntimeError(f"No artifact named '{name}' found")

async def download_and_extract_artifact(repo, artifact_id, token, extract_dir=None):
    url = f"https://api.github.com/repos/{repo}/actions/artifacts/{artifact_id}/zip"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    
    if extract_dir is None:
        extract_dir = "/tmp/swiftlint_output"
    
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        z.extractall(extract_dir)
    return extract_dir

async def parse_swiftlint_output(output_dir, expected_filename="swiftlint_all.txt"):
    """Parse SwiftLint output to extract only actual violations/errors"""
    violations = []
    
    # Look for the expected SwiftLint output file
    expected_file_path = os.path.join(output_dir, expected_filename)
    if not os.path.exists(expected_file_path):
        # Try common alternative names
        alternatives = ["swiftlint.txt", "violations.txt", "lint-results.txt", "output.txt"]
        found_file = None
        for alt_name in alternatives:
            alt_path = os.path.join(output_dir, alt_name)
            if os.path.exists(alt_path):
                found_file = alt_path
                break
        
        if not found_file:
            raise FileNotFoundError(f"Expected SwiftLint output file '{expected_filename}' not found in {output_dir}")
        
        expected_file_path = found_file
    
    # Pattern to match SwiftLint violation lines
    violation_pattern = re.compile(r'^/.+\.swift:\d+:\d+:\s+(error|warning):\s+.+\s+\(.+\)$')
    
    with open(expected_file_path) as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if line and violation_pattern.match(line):
                violations.append({
                    "raw_line": line,
                    "file": extract_file_from_violation(line),
                    "line_number": extract_line_number_from_violation(line),
                    "severity": extract_severity_from_violation(line),
                    "message": extract_message_from_violation(line),
                    "rule": extract_rule_from_violation(line)
                })
    
    return violations

def extract_file_from_violation(violation_line):
    """Extract file path from violation line"""
    match = re.match(r'^(/[^:]+\.swift):', violation_line)
    return match.group(1) if match else ""

def extract_line_number_from_violation(violation_line):
    """Extract line number from violation line"""
    match = re.match(r'^/[^:]+\.swift:(\d+):', violation_line)
    return int(match.group(1)) if match else 0

def extract_severity_from_violation(violation_line):
    """Extract severity (error/warning) from violation line"""
    match = re.search(r':\s+(error|warning):', violation_line)
    return match.group(1) if match else ""

def extract_message_from_violation(violation_line):
    """Extract violation message from violation line"""
    match = re.search(r':\s+(?:error|warning):\s+(.+)\s+\(.+\)$', violation_line)
    return match.group(1) if match else ""

def extract_rule_from_violation(violation_line):
    """Extract rule name from violation line"""
    match = re.search(r'\(([^)]+)\)$', violation_line)
    return match.group(1) if match else ""

async def parse_build_output(output_dir, expected_filename="build_and_test_all.txt"):
    """Parse build output to extract compiler errors, warnings, and test failures"""
    issues = []
    
    # Look for the expected build output file
    expected_file_path = os.path.join(output_dir, expected_filename)
    if not os.path.exists(expected_file_path):
        # Try common alternative names
        alternatives = ["build.txt", "output.log", "output.txt", "log.txt"]
        found_file = None
        for alt_name in alternatives:
            alt_path = os.path.join(output_dir, alt_name)
            if os.path.exists(alt_path):
                found_file = alt_path
                break
        
        if not found_file:
            raise FileNotFoundError(f"Expected build output file '{expected_filename}' not found in {output_dir}")
        
        expected_file_path = found_file
    
    # Patterns to match different types of build issues
    compiler_error_pattern = re.compile(r'^(/.*\.swift):(\d+):(\d+): error: (.+)$')
    compiler_warning_pattern = re.compile(r'^(/.*\.swift):(\d+):(\d+): warning: (.+)$')
    test_failure_pattern = re.compile(r'^(/.*\.swift):(\d+): error: (.+) : (.+)$')
    
    with open(expected_file_path) as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            
            # Check for compiler errors
            if match := compiler_error_pattern.match(line):
                file_path, line_no, col_no, message = match.groups()
                issues.append({
                    "type": "compiler_error",
                    "raw_line": line,
                    "file": file_path,
                    "line_number": int(line_no),
                    "column": int(col_no),
                    "message": message,
                    "severity": "error"
                })
            
            # Check for compiler warnings
            elif match := compiler_warning_pattern.match(line):
                file_path, line_no, col_no, message = match.groups()
                issues.append({
                    "type": "compiler_warning",
                    "raw_line": line,
                    "file": file_path,
                    "line_number": int(line_no),
                    "column": int(col_no),
                    "message": message,
                    "severity": "warning"
                })
            
            # Check for test failures
            elif match := test_failure_pattern.match(line):
                file_path, line_no, test_info, failure_message = match.groups()
                issues.append({
                    "type": "test_failure",
                    "raw_line": line,
                    "file": file_path,
                    "line_number": int(line_no),
                    "test_info": test_info.strip(),
                    "message": failure_message.strip(),
                    "severity": "error"
                })
    
    return issues

# Main build/lint tool implementations
async def execute_read_swiftlint_logs(build_id: str = None) -> str:
    """Read SwiftLint violation logs from GitHub Actions artifacts"""
    try:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            return json.dumps({"error": "GITHUB_TOKEN is not set"})

        repo = await get_github_repo()

        if build_id is None:
            commit = await get_github_commit()
            build_id = await find_workflow_run(repo, commit, token)

        artifact_id = await get_artifact_id(repo, build_id, token)
        output_dir = await download_and_extract_artifact(repo, artifact_id, token)
        lint_results = await parse_swiftlint_output(output_dir)
        
        return json.dumps({
            "success": True,
            "repo": repo,
            "run_id": build_id,
            "artifact_id": artifact_id,
            "violations": lint_results,
            "total_violations": len(lint_results)
        })
        
    except Exception as e:
        return json.dumps({"error": f"Failed to read SwiftLint logs: {str(e)}"})

async def execute_read_build_logs(build_id: str = None) -> str:
    """Read build logs and extract Swift compiler errors, warnings, and test failures"""
    try:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            return json.dumps({"error": "GITHUB_TOKEN is not set"})

        repo = await get_github_repo()

        if build_id is None:
            commit = await get_github_commit()
            build_id = await find_workflow_run(repo, commit, token)

        artifact_id = await get_artifact_id(repo, build_id, token, name="build-output")
        output_dir = await download_and_extract_artifact(repo, artifact_id, token, "/tmp/build_output")
        build_issues = await parse_build_output(output_dir)
        
        # Filter and limit results to prevent huge responses
        compiler_errors = [issue for issue in build_issues if issue["type"] == "compiler_error"][:10]
        compiler_warnings = [issue for issue in build_issues if issue["type"] == "compiler_warning"][:10]
        test_failures = [issue for issue in build_issues if issue["type"] == "test_failure"][:10]
        
        return json.dumps({
            "success": True,
            "repo": repo,
            "run_id": build_id,
            "artifact_id": artifact_id,
            "compiler_errors": compiler_errors,
            "compiler_warnings": compiler_warnings,
            "test_failures": test_failures,
            "total_issues": len(build_issues),
            "total_errors": len([i for i in build_issues if i["type"] == "compiler_error"]),
            "total_warnings": len([i for i in build_issues if i["type"] == "compiler_warning"]),
            "total_test_failures": len([i for i in build_issues if i["type"] == "test_failure"])
        })
        
    except Exception as e:
        return json.dumps({"error": f"Failed to read build logs: {str(e)}"})

# HTTP API Endpoints
@app.get("/")
async def root():
    """Root endpoint with basic server information"""
    repositories = repo_manager.list_repositories()
    return {
        "name": "GitHub PR Agent MCP Server - Multi-Repository",
        "version": "2.0.0",
        "status": "running",
        "multi_repo_mode": repo_manager.is_multi_repo_mode(),
        "repositories": repositories,
        "endpoints": {
            "health": "/health",
            "status": "/status", 
            "mcp": "/mcp/{repo-name}/",
            "docs": "/docs"
        }
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    repositories = repo_manager.list_repositories()
    github_configured = bool(os.getenv("GITHUB_TOKEN"))
    
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "github_configured": github_configured,
        "multi_repo_mode": repo_manager.is_multi_repo_mode(),
        "repositories_count": len(repositories),
        "repositories": repositories
    }


@app.get("/status") 
async def get_server_status():
    """Get comprehensive server status"""
    repositories = repo_manager.list_repositories()
    repo_details = {}
    
    for repo_name in repositories:
        repo_info = repo_manager.get_repository_info(repo_name)
        if repo_info:
            repo_details[repo_name] = repo_info
    
    return {
        "server": {
            "status": "running",
            "github_configured": bool(os.getenv("GITHUB_TOKEN")),
            "multi_repo_mode": repo_manager.is_multi_repo_mode(),
            "timestamp": datetime.now().isoformat()
        },
        "repositories": repo_details,
        "tools": [
            "get_current_branch", "get_current_commit", "find_pr_for_branch",
            "get_pr_comments", "post_pr_reply", "read_swiftlint_logs", "read_build_logs"
        ]
    }

# MCP Endpoints with URL routing
@app.get("/mcp/{repo_name}/")
async def mcp_sse_endpoint(repo_name: str, request: Request):
    """
    MCP SSE endpoint for server-to-client messages with repository routing
    """
    logger.info(f"SSE connection for repository '{repo_name}' from {request.client.host}")
    
    # Validate repository name
    if not repo_manager.get_repository(repo_name):
        available_repos = repo_manager.list_repositories()
        raise HTTPException(
            status_code=404, 
            detail={
                "error": f"Repository '{repo_name}' not found",
                "available_repositories": available_repos
            }
        )
    
    async def generate_sse():
        try:
            # REQUIRED: Send endpoint event with POST URL  
            yield "event: endpoint\n"
            yield f"data: http://localhost:8080/mcp/{repo_name}/\n\n"
            
            # Process queued messages and keep connection alive
            keepalive_counter = 0
            while True:
                # Check for queued messages
                try:
                    while not message_queue.empty():
                        message = message_queue.get_nowait()
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

@app.post("/mcp/{repo_name}/")
async def mcp_post_endpoint(repo_name: str, request: Request):
    """
    Handle POST requests (JSON-RPC MCP protocol) with repository routing
    """
    # Validate repository name
    if not repo_manager.get_repository(repo_name):
        available_repos = repo_manager.list_repositories()
        return JSONResponse(
            status_code=404,
            content={
                "error": f"Repository '{repo_name}' not found",
                "available_repositories": available_repos
            }
        )
    
    try:
        body = await request.json()
        logger.info(f"Received MCP request for '{repo_name}': {body.get('method')}")
        
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
                        "name": f"github-pr-agent-{repo_name}",
                        "version": "2.0.0"
                    }
                }
            }
            message_queue.put(response)
            return {"status": "queued"}
        
        elif body.get("method") == "notifications/initialized":
            logger.info(f"Received initialized notification for {repo_name}")
            return {"status": "ok"}
        
        elif body.get("method") == "tools/list":
            # Return GitHub PR tools
            response = {
                "jsonrpc": "2.0",
                "id": body.get("id", 1),
                "result": {
                    "tools": [
                        {
                            "name": "get_current_commit",
                            "description": f"Get current commit information for {repo_name}",
                            "inputSchema": {
                                "type": "object",
                                "properties": {},
                                "required": []
                            }
                        },
                        {
                            "name": "get_current_branch",
                            "description": f"Get current Git branch name for {repo_name}",
                            "inputSchema": {
                                "type": "object",
                                "properties": {},
                                "required": []
                            }
                        },
                        {
                            "name": "find_pr_for_branch",
                            "description": f"Find the PR associated with a branch in {repo_name}",
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
                            "description": f"Get all comments from a PR in {repo_name}",
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
                            "description": f"Reply to a PR comment in {repo_name}",
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
            message_queue.put(response)
            return {"status": "queued"}
        
        elif body.get("method") == "tools/call":
            # Handle tool execution with repository context
            tool_name = body.get("params", {}).get("name")
            tool_args = body.get("params", {}).get("arguments", {})
            
            logger.info(f"Tool call '{tool_name}' for repo '{repo_name}' with args: {tool_args}")
            
            # Execute tools with repository context
            if tool_name == "find_pr_for_branch":
                branch_name = tool_args.get("branch_name")
                if not branch_name:
                    result = json.dumps({"error": "branch_name is required"})
                else:
                    result = await execute_find_pr_for_branch(repo_name, branch_name)
                    
            elif tool_name == "get_pr_comments":
                pr_number = tool_args.get("pr_number")
                if not pr_number:
                    result = json.dumps({"error": "pr_number is required"})
                else:
                    result = await execute_get_pr_comments(repo_name, pr_number)
                    
            elif tool_name == "post_pr_reply":
                comment_id = tool_args.get("comment_id")
                message = tool_args.get("message")
                if not comment_id or not message:
                    result = json.dumps({"error": "Both comment_id and message are required"})
                else:
                    result = await execute_post_pr_reply(repo_name, comment_id, message)
                    
            elif tool_name == "get_current_branch":
                result = await execute_get_current_branch(repo_name)
                
            elif tool_name == "get_current_commit":
                result = await execute_get_current_commit(repo_name)
                
            else:
                result = json.dumps({"error": f"Tool '{tool_name}' not implemented yet"})
            
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
            message_queue.put(response)
            return {"status": "queued"}
        
        return {"jsonrpc": "2.0", "id": body.get("id", 1), "error": {"code": -32601, "message": "Method not found"}}
    
    except Exception as e:
        logger.error(f"Error handling MCP request for {repo_name}: {e}")
        return {"jsonrpc": "2.0", "id": 1, "error": {"code": -32603, "message": f"Internal error: {str(e)}"}}


@app.on_event("startup")
async def startup_event():
    """Initialize repository manager on startup"""
    logger.info("Starting GitHub MCP Server - Multi-Repository")
    
    # Load repository configuration
    if repo_manager.load_configuration():
        repositories = repo_manager.list_repositories()
        logger.info(f"Successfully loaded {len(repositories)} repositories: {repositories}")
        
        if repo_manager.is_multi_repo_mode():
            logger.info("Running in multi-repository mode")
        else:
            logger.info("Running in single-repository fallback mode")
        
        # Enable hot reload in development mode
        if os.getenv("GITHUB_AGENT_DEV_MODE", "").lower() in ("true", "1", "yes"):
            logger.info("Development mode enabled - starting configuration file watcher")
            repo_manager.start_watching_config(check_interval=2.0)
        else:
            logger.info("Hot reload disabled (set GITHUB_AGENT_DEV_MODE=true to enable)")
    else:
        logger.error("Failed to load repository configuration")
        raise RuntimeError("Could not initialize repository configuration")


if __name__ == "__main__":
    import uvicorn
    
    host = os.getenv("SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("SERVER_PORT", "8080"))
    
    logger.info(f"Starting server on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
