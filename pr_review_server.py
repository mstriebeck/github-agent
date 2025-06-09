#!/usr/bin/env python3

# PR Review Agent MCP Server
# This script exposes PR management tools to coding agents via the Model Context Protocol

import asyncio
import os
import json
import re
import unicodedata
from typing import Optional, List, Dict, Any

# Import MCP components
import mcp
import mcp.server.stdio
import mcp.types as types
from github import Github
from git import Repo
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class PRReviewContext:
    def __init__(self):
        self.github_token = os.getenv("GITHUB_TOKEN")
        self.repo_name = os.getenv("GITHUB_REPO")  # format: "owner/repo"
        self.ci_api_key = os.getenv("CI_API_KEY")
        
        # Initialize GitHub client
        self.github = Github(self.github_token) if self.github_token else None
        self.repo = self.github.get_repo(self.repo_name) if self.github and self.repo_name else None
        
        # Initialize Git repo (assumes script runs from repo root)
        try:
            self.git_repo = Repo(".")
        except:
            self.git_repo = None
        
        # Cache for current context
        self._current_branch = None
        self._current_commit = None
        self._current_pr = None

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
    try:
        result = None
        
        if name == "get_current_branch":
            result = await get_current_branch()
        elif name == "get_current_commit":
            result = await get_current_commit()
        elif name == "find_pr_for_branch":
            result = await find_pr_for_branch(arguments.get("branch_name"))
        elif name == "get_pr_comments":
            result = await get_pr_comments(arguments.get("pr_number"))
        elif name == "post_pr_reply":
            result = await post_pr_reply(arguments.get("comment_id"), arguments.get("message"))
        elif name == "get_build_status":
            result = await get_build_status(arguments.get("commit_sha"))
        elif name == "read_swiftlint_logs":
            result = await read_swiftlint_logs(arguments.get("build_id"))
        elif name == "process_comment_batch":
            result = await process_comment_batch(arguments.get("comments_data"))
        else:
            result = {"error": f"Unknown tool: {name}"}
            
        return [types.TextContent(
            type="text",
            text=json.dumps(result, indent=2, default=str)
        )]
        
    except Exception as e:
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
    try:
        if not context.repo:
            return {"error": "GitHub repository not configured"}
            
        if not branch_name:
            if not context.git_repo:
                return {"error": "Not in a Git repository"}
            branch_name = context._current_branch or context.git_repo.active_branch.name
        
        # Search for PRs with this head branch
        pulls = context.repo.get_pulls(state='open', head=f"{context.repo.owner.login}:{branch_name}")
        pr_list = list(pulls)
        
        if pr_list:
            pr = pr_list[0]  # Take the first (most recent) PR
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
        status = commit.get_combined_status()
        
        check_runs = []
        try:
            for run in commit.get_check_runs():
                check_runs.append({
                    "name": run.name,
                    "status": run.status,
                    "conclusion": run.conclusion,
                    "url": run.html_url
                })
        except Exception:
            pass
        
        return {
            "commit_sha": commit_sha,
            "overall_state": status.state,
            "check_runs": check_runs,
            "has_failures": any(
                run.get("conclusion") in ["failure", "timed_out", "cancelled"] for run in check_runs
            )
        }
        
    except Exception as e:
        return {"error": f"Failed to get build status: {str(e)}"}

async def read_swiftlint_logs(build_id: Optional[str] = None) -> Dict[str, Any]:
    """Read SwiftLint logs - CUSTOMIZE based on your CI system"""
    try:
        # Placeholder implementation
        violations = [
            {
                "file": "Sources/MyApp/ViewController.swift",
                "line": 45,
                "column": 20,
                "severity": "warning",
                "rule": "line_length",
                "message": "Line should be 120 characters or less: currently 125 characters"
            }
        ]
        
        return {
            "build_id": build_id,
            "violations": violations,
            "total_violations": len(violations),
            "errors": len([v for v in violations if v["severity"] == "error"]),
            "warnings": len([v for v in violations if v["severity"] == "warning"])
        }
        
    except Exception as e:
        return {"error": f"Failed to read SwiftLint logs: {str(e)}"}

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
    async with mcp.server.stdio.stdio_server() as streams:
        await app.run(streams[0], streams[1], app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
