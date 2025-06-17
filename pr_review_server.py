#!/usr/bin/env python3

# PR Review Agent MCP Server
# This script exposes PR management tools to coding agents via the Model Context Protocol

import asyncio
import os
import json
import re
import unicodedata
import zipfile
import io
import logging
import time
from typing import Optional, List, Dict, Any
import subprocess
from datetime import datetime
import sqlite3

# Import MCP components
import mcp
import mcp.server.stdio
import mcp.types as types
from github import Github
from git import Repo
import requests
from dotenv import load_dotenv

# Import SQLModel components
from sqlmodel import SQLModel, Field, create_engine, Session, select

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/tmp/pr_review_server.log'),
        logging.StreamHandler()  # Also log to console
    ]
)
logger = logging.getLogger(__name__)

# SQLModel schema for PR reply queue
class PRReply(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    comment_id: int
    repo_name: str  # Format: "owner/repo"
    status: str = "queued"  # "queued", "sent", "failed"
    attempt_count: int = 0
    last_attempt_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.now)
    # All other data as JSON for flexibility
    data: str  # JSON string containing: path, line, body, etc.

# Database setup
DATABASE_URL = "sqlite:///pr_replies.db"
engine = create_engine(DATABASE_URL, echo=False)

def init_db():
    """Initialize the database and create tables"""
    SQLModel.metadata.create_all(engine)
    logger.info("Database initialized")

class PRReviewContext:
    def __init__(self):
        self.github_token = os.getenv("GITHUB_TOKEN")
        self.ci_api_key = os.getenv("CI_API_KEY")
        
        # Initialize Git repo (assumes script runs from repo root)
        try:
            self.git_repo = Repo(".")
            self.repo_name = self._detect_github_repo()
        except:
            self.git_repo = None
            self.repo_name = None
        
        # Initialize GitHub client
        self.github = Github(self.github_token) if self.github_token else None
        self.repo = self.github.get_repo(self.repo_name) if self.github and self.repo_name else None
        
        # Cache for current context
        self._current_branch = None
        self._current_commit = None
        self._current_pr = None
    
    def _detect_github_repo(self):
        """Detect GitHub repository name from git remote"""
        if not self.git_repo:
            return None
        
        try:
            # Get the origin remote URL
            origin_url = self.git_repo.remotes.origin.url
            logger.debug(f"Git remote URL: {origin_url}")
            
            # Parse different URL formats
            if origin_url.startswith("git@github.com:"):
                # SSH format: git@github.com:owner/repo.git
                repo_path = origin_url.split(":", 1)[1]
            elif origin_url.startswith("https://github.com/"):
                # HTTPS format: https://github.com/owner/repo.git
                repo_path = origin_url.split("github.com/", 1)[1]
            else:
                logger.warning(f"Unrecognized GitHub remote URL format: {origin_url}")
                return None
            
            # Remove .git suffix if present
            repo_name = repo_path.replace(".git", "")
            logger.info(f"Detected GitHub repository: {repo_name}")
            return repo_name
            
        except Exception as e:
            logger.error(f"Failed to detect GitHub repository: {str(e)}")
            return None

# Create the MCP server instance and context
app = mcp.server.Server("pr-review-server")
context = PRReviewContext()

@app.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """Define all available tools"""
    return [
        # Git/Branch Context Tools
        types.Tool(
            name="get_current_branch",
            description="Get the current Git branch name and last commit info",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="get_current_commit",
            description="Get the current commit SHA and details",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="find_pr_for_branch",
            description="Find the PR associated with the current or specified branch",
            inputSchema={
                "type": "object",
                "properties": {
                    "branch_name": {"type": "string", "description": "Branch name (optional, uses current if not specified)"}
                }
            }
        ),
        
        # PR Management Tools
        types.Tool(
            name="get_pr_comments",
            description="Get comments from a PR",
            inputSchema={
                "type": "object",
                "properties": {
                    "pr_number": {"type": "integer", "description": "PR number (optional, uses current branch's PR if not specified)"}
                }
            }
        ),
        types.Tool(
            name="post_pr_reply",
            description="Reply to a specific PR comment",
            inputSchema={
                "type": "object",
                "properties": {
                    "comment_id": {"type": "integer", "description": "Comment ID to reply to"},
                    "message": {"type": "string", "description": "Reply message"}
                },
                "required": ["comment_id", "message"]
            }
        ),
        
        # Queue-based PR Reply Tools
        types.Tool(
            name="post_pr_reply_queue",
            description="Queue a reply to a PR comment for later processing",
            inputSchema={
                "type": "object",
                "properties": {
                    "comment_id": {"type": "integer", "description": "Comment ID to reply to"},
                    "path": {"type": "string", "description": "File path of the comment"},
                    "line": {"type": "integer", "description": "Line number of the comment"},
                    "body": {"type": "string", "description": "Reply message body"}
                },
                "required": ["comment_id", "path", "body"]
            }
        ),
        types.Tool(
            name="list_unhandled_comments",
            description="List PR comments that haven't been replied to yet",
            inputSchema={
                "type": "object",
                "properties": {
                    "pr_number": {"type": "integer", "description": "PR number (optional, uses current branch's PR if not specified)"}
                }
            }
        ),
        types.Tool(
            name="ack_reply",
            description="Mark a comment as handled/acknowledged",
            inputSchema={
                "type": "object", 
                "properties": {
                    "comment_id": {"type": "integer", "description": "Comment ID to acknowledge"}
                },
                "required": ["comment_id"]
            }
        ),
        
        # CI/CD Integration Tools
        types.Tool(
            name="get_build_status",
            description="Get build/CI status for current commit or PR",
            inputSchema={
                "type": "object",
                "properties": {
                    "commit_sha": {"type": "string", "description": "Commit SHA (optional, uses current if not specified)"}
                }
            }
        ),
        types.Tool(
            name="read_swiftlint_logs",
            description="Read SwiftLint violation logs",
            inputSchema={
                "type": "object",
                "properties": {
                    "build_id": {"type": "string", "description": "Build ID (optional, uses latest for current commit if not specified)"}
                }
            }
        ),
        types.Tool(
            name="read_build_logs",
            description="Read build logs for Swift compiler errors, warnings, and test failures",
            inputSchema={
                "type": "object",
                "properties": {
                    "build_id": {"type": "string", "description": "Build ID (optional, uses latest for current commit if not specified)"}
                }
            }
        ),
        
        # Batch Processing Tools
        types.Tool(
            name="process_comment_batch",
            description="Process a batch of formatted comment responses (for bulk reply operations)",
            inputSchema={
                "type": "object",
                "properties": {
                    "comments_data": {
                        "type": "string",
                        "description": "Formatted comment responses in the format: [comment_id: X - path:line - original_comment: \"text\"] Reply: response"
                    }
                },
                "required": ["comments_data"]
            }
        )
    ]

@app.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """Route tool calls to appropriate functions"""
    start_time = time.time()
    logger.info(f"Tool call received: {name} with arguments: {arguments}")
    try:
        result = None
        
        if name == "get_current_branch":
            logger.debug("Calling get_current_branch")
            result = await get_current_branch()
        elif name == "get_current_commit":
            logger.debug("Calling get_current_commit")
            result = await get_current_commit()
        elif name == "find_pr_for_branch":
            logger.debug("Calling find_pr_for_branch")
            result = await find_pr_for_branch(arguments.get("branch_name"))
        elif name == "get_pr_comments":
            logger.debug("Calling get_pr_comments")
            result = await get_pr_comments(arguments.get("pr_number"))
        elif name == "post_pr_reply":
            logger.debug("Calling post_pr_reply")
            result = await post_pr_reply(arguments.get("comment_id"), arguments.get("message"))
        elif name == "post_pr_reply_queue":
            logger.debug("Calling post_pr_reply_queue")
            result = await post_pr_reply_queue(
                arguments.get("comment_id"), 
                arguments.get("path"), 
                arguments.get("line"), 
                arguments.get("body")
            )
        elif name == "list_unhandled_comments":
            logger.debug("Calling list_unhandled_comments")
            result = await list_unhandled_comments(arguments.get("pr_number"))
        elif name == "ack_reply":
            logger.debug("Calling ack_reply")
            result = await ack_reply(arguments.get("comment_id"))
        elif name == "get_build_status":
            logger.debug("Calling get_build_status")
            result = await get_build_status(arguments.get("commit_sha"))
        elif name == "read_swiftlint_logs":
            logger.debug("Calling read_swiftlint_logs")
            result = await read_swiftlint_logs(arguments.get("build_id"))
        elif name == "read_build_logs":
            logger.debug("Calling read_build_logs")
            full_result = await read_build_logs(arguments.get("build_id"))
            if "error" in full_result:
                result = f"Error: {full_result['error']}"
            else:
                result = f"Build analysis complete for {full_result.get('repo', 'repository')} (run {full_result.get('run_id', 'unknown')}):\n"
                result += f"• {full_result.get('total_errors', 0)} compiler errors\n"
                result += f"• {full_result.get('total_warnings', 0)} compiler warnings\n" 
                result += f"• {full_result.get('total_test_failures', 0)} test failures\n"
                
                # Add actual issues if they exist
                if full_result.get('compiler_errors'):
                    result += "\nCompiler Errors:\n"
                    for error in full_result['compiler_errors'][:5]:  # Limit to 5
                        result += f"  {error['file']}:{error['line_number']} - {error['message']}\n"
                
                if full_result.get('compiler_warnings'):
                    result += "\nCompiler Warnings:\n"  
                    for warning in full_result['compiler_warnings'][:5]:  # Limit to 5
                        result += f"  {warning['file']}:{warning['line_number']} - {warning['message']}\n"
                        
                if full_result.get('test_failures'):
                    result += "\nTest Failures:\n"
                    for failure in full_result['test_failures'][:5]:  # Limit to 5
                        result += f"  {failure['file']}:{failure['line_number']} - {failure['message']}\n"
        elif name == "process_comment_batch":
            logger.debug("Calling process_comment_batch")
            result = await process_comment_batch(arguments.get("comments_data"))
        else:
            logger.warning(f"Unknown tool requested: {name}")
            result = {"error": f"Unknown tool: {name}"}
        
        execution_time = time.time() - start_time
        logger.info(f"Tool {name} completed successfully in {execution_time:.2f} seconds")
        
        # Serialize result and check size
        response_text = json.dumps(result, indent=2, default=str)
        response_size = len(response_text)
        logger.info(f"Response size: {response_size} characters")
        
        # If response is very large, truncate it for debugging
        if response_size > 50000:  # 50KB limit
            logger.warning(f"Response is large ({response_size} chars), truncating for debugging")
            truncated_result = {
                "truncated": True,
                "original_size": response_size,
                "summary": str(result)[:1000] + "..." if len(str(result)) > 1000 else str(result)
            }
            if isinstance(result, dict):
                # Keep important fields but truncate large arrays
                truncated_result.update({k: v for k, v in result.items() if k in ['success', 'error', 'total_issues', 'total_violations']})
                if 'compiler_errors' in result:
                    truncated_result['compiler_errors'] = result['compiler_errors'][:5]  # First 5 only
                if 'compiler_warnings' in result:
                    truncated_result['compiler_warnings'] = result['compiler_warnings'][:5]
                if 'test_failures' in result:
                    truncated_result['test_failures'] = result['test_failures'][:5]
                if 'violations' in result:
                    truncated_result['violations'] = result['violations'][:5]
            response_text = json.dumps(truncated_result, indent=2, default=str)
            logger.info(f"Truncated response size: {len(response_text)} characters")
        
        return [types.TextContent(
            type="text",
            text=response_text
        )]
        
    except Exception as e:
        logger.error(f"Tool {name} failed with error: {str(e)}", exc_info=True)
        return [types.TextContent(
            type="text", 
            text=json.dumps({"error": str(e)}, indent=2)
        )]

# Tool implementation functions
async def get_current_branch() -> Dict[str, Any]:
    """Get the current Git branch name and related info"""
    try:
        if not context.git_repo:
            return {"error": "Not in a Git repository"}
            
        branch = context.git_repo.active_branch
        context._current_branch = branch.name
        
        return {
            "branch_name": branch.name,
            "is_detached": context.git_repo.head.is_detached,
            "last_commit": {
                "sha": branch.commit.hexsha[:8],
                "message": branch.commit.message.strip(),
                "author": str(branch.commit.author),
                "date": branch.commit.committed_datetime.isoformat()
            }
        }
    except Exception as e:
        return {"error": f"Failed to get current branch: {str(e)}"}

async def get_current_commit() -> Dict[str, Any]:
    """Get current commit information"""
    try:
        if not context.git_repo:
            return {"error": "Not in a Git repository"}
            
        commit = context.git_repo.head.commit
        context._current_commit = commit.hexsha
        
        return {
            "sha": commit.hexsha,
            "short_sha": commit.hexsha[:8],
            "message": commit.message.strip(),
            "author": {
                "name": commit.author.name,
                "email": commit.author.email
            },
            "date": commit.committed_datetime.isoformat(),
            "files_changed": len(commit.stats.files)
        }
    except Exception as e:
        return {"error": f"Failed to get current commit: {str(e)}"}

async def find_pr_for_branch(branch_name: Optional[str] = None) -> Dict[str, Any]:
    """Find the PR associated with a branch"""
    logger.debug(f"find_pr_for_branch called with branch_name: {branch_name}")
    try:
        if not context.repo:
            return {"error": "GitHub repository not configured"}

        if not branch_name:
            if not context.git_repo:
                return {"error": "Not in a Git repository"}
            branch_name = context._current_branch or context.git_repo.active_branch.name

        # Search all PRs and match by branch name
        #pulls = context.repo.get_pulls(state='open', head=f"{context.repo.owner.login}:{branch_name}")
        pulls = context.repo.get_pulls(state='all')

        # Debug info
        pulls = list(pulls)
        logger.debug(f"GitHub returned {len(pulls)} total PRs")
        for pr in pulls:
            logger.debug(f"PR #{pr.number}: head.ref={pr.head.ref}, head.repo.full_name={pr.head.repo.full_name}, state={pr.state}")

        pr_list = list(pulls)
        logger.debug(f"Found {len(pr_list)} PR(s) matching branch '{branch_name}'")

        if pr_list:
            logger.debug(f"PR #{pr.number}: head.ref={pr.head.ref}, base.ref={pr.base.ref}, state={pr.state}, title={pr.title}")
            pr = pr_list[0]  # Take the first match
            context._current_pr = pr.number

            return {
                "found": True,
                "pr_number": pr.number,
                "title": pr.title,
                "state": pr.state,
                "url": pr.html_url,
                "author": pr.user.login,
                "base_branch": pr.base.ref,
                "head_branch": pr.head.ref
            }
        else:
            return {
                "found": False,
                "branch_name": branch_name,
                "message": f"No PR found for branch '{branch_name}'"
            }

    except Exception as e:
        return {"error": f"Failed to find PR for branch {branch_name}: {str(e)}"}

async def get_pr_comments(pr_number: Optional[int] = None) -> Dict[str, Any]:
    """Get all comments from a PR with robust error handling"""
    try:
        if not context.repo:
            return {"error": "GitHub repository not configured"}
            
        if not pr_number:
            # Try to find PR for current branch
            pr_info = await find_pr_for_branch()
            if pr_info.get("found"):
                pr_number = pr_info["pr_number"]
            else:
                return {"error": "No PR number provided and couldn't find PR for current branch"}
        
        # Use the robust comment fetching logic
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
        
        return {
            "pr_number": pr_number,
            "title": pr_data["title"],
            "review_comments": formatted_review_comments,
            "issue_comments": formatted_issue_comments,
            "total_comments": len(formatted_review_comments) + len(formatted_issue_comments)
        }
        
    except Exception as e:
        return {"error": f"Failed to get PR comments: {str(e)}"}

async def post_pr_reply(comment_id: int, message: str) -> Dict[str, Any]:
    """Reply to a PR comment with multiple fallback strategies"""
    try:
        if not context.repo:
            return {"error": "GitHub repository not configured"}
        
        headers = {
            "Authorization": f"token {context.github_token}",
            "Accept": "application/vnd.github+json"
        }
        
        # Try to get original comment context
        try:
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
                    return {"error": f"Could not find comment with ID {comment_id}"}
        except Exception as e:
            return {"error": f"Failed to fetch original comment: {str(e)}"}
        
        # Strategy 1: Try direct reply to review comment
        try:
            reply_url = f"https://api.github.com/repos/{context.repo_name}/pulls/comments/{comment_id}/replies"
            reply_data = {"body": message}
            reply_resp = requests.post(reply_url, headers=headers, json=reply_data)
            
            if reply_resp.status_code in [200, 201]:
                return {
                    "success": True,
                    "method": "direct_reply",
                    "comment_id": reply_resp.json()["id"],
                    "url": reply_resp.json()["html_url"]
                }
        except Exception:
            pass
        
        # Strategy 2: Post as issue comment (fallback)
        if pr_number:
            try:
                issue_comment_url = f"https://api.github.com/repos/{context.repo_name}/issues/{pr_number}/comments"
                issue_comment_data = {"body": f"@{original_comment['user']['login']} {message}"}
                issue_resp = requests.post(issue_comment_url, headers=headers, json=issue_comment_data)
                
                if issue_resp.status_code in [200, 201]:
                    return {
                        "success": True,
                        "method": "issue_comment_fallback",
                        "comment_id": issue_resp.json()["id"],
                        "url": issue_resp.json()["html_url"]
                    }
            except Exception as e:
                return {"error": f"All reply strategies failed. Final error: {str(e)}"}
        
        return {"error": "All reply strategies failed"}
        
    except Exception as e:
        return {"error": f"Failed to post PR reply: {str(e)}"}

async def get_build_status(commit_sha: Optional[str] = None) -> Dict[str, Any]:
    """Get build status for commit"""
    try:
        if not context.repo:
            return {"error": "GitHub repository not configured"}

        if not commit_sha:
            if not context.git_repo:
                return {"error": "Not in a Git repository"}
            commit_sha = context._current_commit or context.git_repo.head.commit.hexsha

        commit = context.repo.get_commit(commit_sha)

        # --- MODIFICATION START ---
        # Initialize overall_state here; it will be updated based on check runs
        overall_state = "pending" # Default to pending if no checks or statuses are found
        has_failures = False
        check_runs_data = []

        try:
            # Prefer check runs for detailed build status
            # This is more robust against the 'Resource not accessible' error for combined_status
            for run in commit.get_check_runs():
                check_run_info = {
                    "name": run.name,
                    "status": run.status,
                    "conclusion": run.conclusion,
                    "url": run.html_url
                }
                check_runs_data.append(check_run_info)

                if run.conclusion in ["failure", "timed_out", "cancelled", "stale"]:
                    has_failures = True
                elif run.status == "completed" and run.conclusion == "success" and overall_state == "pending":
                    overall_state = "success" # Set to success if at least one successful completed run and no failures yet
                elif run.status != "completed": # If any check is still running, overall is in_progress
                    overall_state = "in_progress"

        except Exception as e:
            # Log this if needed, but allow to proceed to combined_status fallback or default
            logger.debug(f"Warning: Failed to get check runs, trying combined status fallback: {e}")
            pass # Continue to try combined_status if check_runs fails

        # Fallback to get_combined_status if check_runs_data is empty or if check_runs failed
        # This part might still throw the 403, but it's a fallback.
        # If check_runs_data is populated, we might skip this
        if not check_runs_data:
            try:
                status = commit.get_combined_status()
                overall_state = status.state
                has_failures = any(
                    s.state in ["failure", "error", "pending"] and s.context != "expected" # Refine logic if needed
                    for s in status.statuses
                )
                # Populate check_runs_data from statuses if check_runs failed
                # This part is redundant if check_runs already populated data
                if not check_runs_data:
                    for s in status.statuses:
                        check_runs_data.append({
                            "name": s.context,
                            "status": s.state,
                            "conclusion": s.state, # Map status state to conclusion for consistency
                            "url": s.target_url
                        })
            except Exception as e:
                logger.debug(f"Error: Failed to get combined status even as fallback: {e}")
                overall_state = "error" # Indicate an error if both fail
                has_failures = True

        # Ensure overall_state reflects failures if any
        if has_failures:
            overall_state = "failure"

        return {
            "commit_sha": commit_sha,
            "overall_state": overall_state,
            "check_runs": check_runs_data,
            "has_failures": has_failures
        }
        # --- MODIFICATION END ---

    except Exception as e:
        return {"error": f"Failed to get build status: {str(e)}"}

async def get_github_repo():
    """Return the owner and repo name from the current git repo."""
    output = subprocess.check_output(["git", "config", "--get", "remote.origin.url"]).decode().strip()
    logger.debug(f"Git remote URL: {output}")
    if output.startswith("git@"):
        _, path = output.split(":", 1)
    elif output.startswith("https://"):
        path = output.split("github.com/", 1)[-1]
    else:
        raise ValueError(f"Unrecognized GitHub remote URL: {output}")
    repo_name = path.replace(".git", "")
    logger.debug(f"Detected repo name: {repo_name}")
    return repo_name

async def get_github_commit():
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    logger.debug(f"Current commit SHA: {commit}")
    return commit

async def find_workflow_run(repo, commit, token):
    url = f"https://api.github.com/repos/{repo}/actions/runs"
    headers = {"Authorization": f"Bearer {token}"}
    # Remove event filter to see all workflow runs, increase page size
    params = {"per_page": 200}
    logger.debug(f"Searching for workflow runs at: {url}")
    logger.debug(f"Looking for commit: {commit}")
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    
    workflow_data = response.json()
    workflow_runs = workflow_data.get("workflow_runs", [])
    logger.debug(f"Found {len(workflow_runs)} workflow runs")
    
    for i, run in enumerate(workflow_runs[:10]):  # Show first 10 for debugging
        logger.debug(f"Run {i+1}: id={run['id']}, head_sha={run['head_sha'][:8]}..., event={run['event']}, status={run['status']}, conclusion={run.get('conclusion', 'N/A')}")
    
    # Look for exact match
    for run in workflow_runs:
        if run["head_sha"] == commit:
            logger.debug(f"Found exact match: run_id={run['id']}")
            return run["id"]
    
    # Look for partial match (first 8 characters)
    short_commit = commit[:8]
    for run in workflow_runs:
        if run["head_sha"].startswith(short_commit):
            logger.debug(f"Found partial match: run_id={run['id']}, head_sha={run['head_sha']}")
            return run["id"]
    
    logger.debug(f"No matching workflow run found for commit {commit}")
    
    # Offer the most recent workflow run as fallback
    if workflow_runs:
        latest_run = workflow_runs[0]  # Runs are sorted by creation date, most recent first
        logger.debug(f"Using most recent workflow run as fallback: {latest_run['id']} (commit: {latest_run['head_sha'][:8]}...)")
        return latest_run["id"]
    
    raise RuntimeError(f"No matching workflow run found for commit {commit}. Local commit may not be pushed to GitHub yet.")

async def get_artifact_id(repo, run_id, token, name="swiftlint-reports"):
    url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/artifacts"
    headers = {"Authorization": f"Bearer {token}"}
    logger.debug(f"Looking for artifacts in run {run_id}")
    logger.debug(f"Artifacts URL: {url}")
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    
    artifacts_data = response.json()
    artifacts = artifacts_data.get("artifacts", [])
    logger.debug(f"Found {len(artifacts)} artifacts")
    
    for i, artifact in enumerate(artifacts):
        logger.debug(f"Artifact {i+1}: name='{artifact['name']}', size={artifact.get('size_in_bytes', 0)} bytes")
    
    for artifact in artifacts:
        if artifact["name"] == name:
            logger.debug(f"Found matching artifact: {artifact['id']}")
            return artifact["id"]
    
    logger.debug(f"No artifact named '{name}' found")
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
    
    # Show what files are available for debugging
    logger.debug(f"Contents of {output_dir}:")
    for root, dirs, files in os.walk(output_dir):
        for file in files:
            file_path = os.path.join(root, file)
            logger.debug(f"Found file: {file_path}")
    
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
                logger.debug(f"Using alternative file: {alt_path}")
                break
        
        if not found_file:
            raise FileNotFoundError(f"Expected SwiftLint output file '{expected_filename}' not found in {output_dir}. Available files: {os.listdir(output_dir)}")
        
        expected_file_path = found_file
    
    logger.debug(f"Parsing SwiftLint file: {expected_file_path}")
    
    # Pattern to match SwiftLint violation lines
    # Format: /path/to/file.swift:line:column: error/warning: description (rule_name)
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
                logger.debug(f"Found violation: {line}")
    
    logger.debug(f"Total violations found: {len(violations)}")
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

async def read_swiftlint_logs(run_id=None):
    try:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            return {"error": "GITHUB_TOKEN is not set"}

        repo = await get_github_repo()

        if run_id is None:
            commit = await get_github_commit()
            run_id = await find_workflow_run(repo, commit, token)

        artifact_id = await get_artifact_id(repo, run_id, token)
        output_dir = await download_and_extract_artifact(repo, artifact_id, token)
        lint_results = await parse_swiftlint_output(output_dir)
        
        return {
            "success": True,
            "repo": repo,
            "run_id": run_id,
            "artifact_id": artifact_id,
            "violations": lint_results,
            "total_violations": len(lint_results)
        }
        
    except Exception as e:
        return {"error": f"Failed to read SwiftLint logs: {str(e)}"}

async def read_build_logs(run_id=None):
    """Read build logs and extract Swift compiler errors, warnings, and test failures"""
    logger.info(f"read_build_logs called with run_id: {run_id}")
    try:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            logger.error("GITHUB_TOKEN is not set")
            return {"error": "GITHUB_TOKEN is not set"}

        logger.debug("Getting GitHub repo information")
        repo = await get_github_repo()

        if run_id is None:
            logger.debug("Getting current commit to find workflow run")
            commit = await get_github_commit()
            logger.debug("Finding workflow run for commit")
            run_id = await find_workflow_run(repo, commit, token)

        logger.debug(f"Getting build-output artifact for run {run_id}")
        artifact_id = await get_artifact_id(repo, run_id, token, name="build-output")
        logger.debug(f"Downloading and extracting artifact {artifact_id}")
        output_dir = await download_and_extract_artifact(repo, artifact_id, token, "/tmp/build_output")
        logger.debug("Parsing build output")
        build_issues = await parse_build_output(output_dir)
        
        # Filter and limit results to prevent huge responses
        compiler_errors = [issue for issue in build_issues if issue["type"] == "compiler_error"][:10]
        compiler_warnings = [issue for issue in build_issues if issue["type"] == "compiler_warning"][:10]
        test_failures = [issue for issue in build_issues if issue["type"] == "test_failure"][:10]
        
        logger.info(f"Found {len([i for i in build_issues if i['type'] == 'compiler_error'])} compiler errors (showing first 10)")
        logger.info(f"Found {len([i for i in build_issues if i['type'] == 'compiler_warning'])} compiler warnings (showing first 10)")
        logger.info(f"Found {len([i for i in build_issues if i['type'] == 'test_failure'])} test failures (showing first 10)")
        
        result = {
            "success": True,
            "repo": repo,
            "run_id": run_id,
            "artifact_id": artifact_id,
            "compiler_errors": compiler_errors,
            "compiler_warnings": compiler_warnings,
            "test_failures": test_failures,
            "total_issues": len(build_issues),
            "total_errors": len([i for i in build_issues if i["type"] == "compiler_error"]),
            "total_warnings": len([i for i in build_issues if i["type"] == "compiler_warning"]),
            "total_test_failures": len([i for i in build_issues if i["type"] == "test_failure"])
        }
        
        logger.debug(f"Returning result with {len(result)} keys")
        return result
        
    except Exception as e:
        return {"error": f"Failed to read build logs: {str(e)}"}

async def parse_build_output(output_dir, expected_filename="build_and_test_all.txt"):
    """Parse build output to extract compiler errors, warnings, and test failures"""
    issues = []
    
    # Show what files are available for debugging
    logger.debug(f"Contents of {output_dir}:")
    for root, dirs, files in os.walk(output_dir):
        for file in files:
            file_path = os.path.join(root, file)
            logger.debug(f"Found file: {file_path}")
    
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
                logger.debug(f"Using alternative file: {alt_path}")
                break
        
        if not found_file:
            raise FileNotFoundError(f"Expected build output file '{expected_filename}' not found in {output_dir}. Available files: {os.listdir(output_dir)}")
        
        expected_file_path = found_file
    
    logger.debug(f"Parsing build file: {expected_file_path}")
    
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
                logger.debug(f"Found compiler error: {line}")
            
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
                logger.debug(f"Found compiler warning: {line}")
            
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
                logger.debug(f"Found test failure: {line}")
    
    logger.debug(f"Total build issues found: {len(issues)}")
    return issues

# Queue-based PR reply functions
async def post_pr_reply_queue(comment_id: int, path: str, line: Optional[int], body: str) -> Dict[str, Any]:
    """Queue a reply to a PR comment for later processing"""
    try:
        # Get current repository name
        if not context.repo_name:
            return {"error": "GITHUB_REPO not configured"}
        
        with Session(engine) as session:
            # Check if we already have a queued reply for this comment
            existing = session.exec(
                select(PRReply).where(PRReply.comment_id == comment_id)
            ).first()
            
            if existing:
                return {
                    "success": False,
                    "message": f"Reply for comment {comment_id} already queued with status: {existing.status}"
                }
            
            # Prepare data as JSON
            reply_data = {
                "path": path,
                "line": line,
                "body": body
            }
            
            # Create new queued reply
            reply = PRReply(
                comment_id=comment_id,
                repo_name=context.repo_name,
                status="queued",
                data=json.dumps(reply_data)
            )
            
            session.add(reply)
            session.commit()
            session.refresh(reply)
            
            logger.info(f"Queued reply for comment {comment_id} in repo {context.repo_name}")
            return {
                "success": True,
                "reply_id": reply.id,
                "comment_id": comment_id,
                "repo_name": context.repo_name,
                "status": "queued",
                "message": f"Reply queued successfully for comment {comment_id}"
            }
            
    except Exception as e:
        logger.error(f"Failed to queue reply: {str(e)}")
        return {"error": f"Failed to queue reply: {str(e)}"}

async def list_unhandled_comments(pr_number: Optional[int] = None) -> Dict[str, Any]:
    """List PR comments that haven't been replied to yet"""
    try:
        # Get PR comments first
        comments_result = await get_pr_comments(pr_number)
        if "error" in comments_result:
            return comments_result
        
        # Get all queued/sent comment IDs from database
        with Session(engine) as session:
            handled_replies = session.exec(
                select(PRReply.comment_id).where(PRReply.status.in_(["queued", "sent"]))
            ).all()
            handled_comment_ids = set(handled_replies)
        
        # Filter out comments that already have replies queued or sent
        unhandled_review_comments = []
        unhandled_issue_comments = []
        
        for comment in comments_result.get("review_comments", []):
            if comment["id"] not in handled_comment_ids:
                unhandled_review_comments.append(comment)
        
        for comment in comments_result.get("issue_comments", []):
            if comment["id"] not in handled_comment_ids:
                unhandled_issue_comments.append(comment)
        
        return {
            "pr_number": comments_result["pr_number"],
            "title": comments_result["title"],
            "unhandled_review_comments": unhandled_review_comments,
            "unhandled_issue_comments": unhandled_issue_comments,
            "total_unhandled": len(unhandled_review_comments) + len(unhandled_issue_comments),
            "total_handled": len(handled_comment_ids)
        }
        
    except Exception as e:
        logger.error(f"Failed to list unhandled comments: {str(e)}")
        return {"error": f"Failed to list unhandled comments: {str(e)}"}

async def ack_reply(comment_id: int) -> Dict[str, Any]:
    """Mark a comment as handled/acknowledged"""
    try:
        with Session(engine) as session:
            reply = session.exec(
                select(PRReply).where(PRReply.comment_id == comment_id)
            ).first()
            
            if not reply:
                return {
                    "success": False,
                    "message": f"No queued reply found for comment {comment_id}"
                }
            
            # Update status or just log the acknowledgment
            logger.info(f"Comment {comment_id} acknowledged (current status: {reply.status})")
            return {
                "success": True,
                "comment_id": comment_id,
                "current_status": reply.status,
                "message": f"Comment {comment_id} acknowledged"
            }
            
    except Exception as e:
        logger.error(f"Failed to acknowledge comment: {str(e)}")
        return {"error": f"Failed to acknowledge comment: {str(e)}"}

async def process_comment_batch(comments_data: str) -> Dict[str, Any]:
    """Process a batch of formatted comment responses"""
    try:
        # Normalize input
        normalized = unicodedata.normalize("NFKC", comments_data.replace("\u2028", "\n").replace("\u00A0", " "))
        
        # Parse responses
        responses = {}
        pattern = r'\[comment_id:\s*(\d+)\s*-\s*(.+?):(\d+)\s*-\s*original_comment:\s*"(.+?)"\]\s*\n?Reply:\s*(.+?)(?=\n\[comment_id:|$)'
        
        for match in re.finditer(pattern, normalized, re.DOTALL):
            cid, path, line, original_comment, reply = match.groups()
            responses[cid.strip()] = {
                "body": reply.strip(),
                "path": path.strip(),
                "line": int(line.strip()),
                "original_comment": original_comment.strip()
            }
        
        # Process each response
        results = []
        successful_posts = 0
        failed_posts = 0
        
        for comment_id, response_data in responses.items():
            try:
                result = await post_pr_reply(int(comment_id), response_data["body"])
                if result.get("success"):
                    successful_posts += 1
                else:
                    failed_posts += 1
                results.append({
                    "comment_id": comment_id,
                    "result": result
                })
            except Exception as e:
                failed_posts += 1
                results.append({
                    "comment_id": comment_id,
                    "result": {"error": str(e)}
                })
        
        return {
            "parsed_responses": len(responses),
            "successful_posts": successful_posts,
            "failed_posts": failed_posts,
            "results": results
        }
        
    except Exception as e:
        return {"error": f"Failed to process comment batch: {str(e)}"}

# Main entry point
async def main():
    """Start the MCP server"""
    logger.info("Starting PR Review MCP Server")
    
    # Initialize database
    try:
        init_db()
    except Exception as e:
        logger.error(f"Failed to initialize database: {str(e)}")
        raise
    
    try:
        async with mcp.server.stdio.stdio_server() as streams:
            logger.info("MCP server initialized, starting main loop")
            await app.run(streams[0], streams[1], app.create_initialization_options())
    except Exception as e:
        logger.error(f"MCP server failed: {str(e)}", exc_info=True)
        raise

if __name__ == "__main__":
    logger.info("PR Review Server starting...")
    asyncio.run(main())
