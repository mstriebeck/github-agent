# PR Review Agent Setup Guide

A comprehensive guide for setting up an AI agent to handle PR reviews, CI/CD integration, and code quality feedback using existing coding agents.

## Overview

This guide covers three main components:
1. **MCP Server** - Exposes your PR tools to the coding agent
2. **Agent Configuration** - Sets up Claude Code or SourceGraph Amp
3. **Workflow Documentation** - Defines how the agent should operate

## Prerequisites & Dev Machine Setup

### Required on Development Machine

#### ✅ Python & Libraries
```bash
# Python 3.8+ (MCP SDK requirement)
python --version  # Should be 3.8 or higher

# Required pip libraries
pip install mcp pygithub gitpython requests pydantic python-dotenv
```

#### ✅ Environment Variables
```bash
# Required
export GITHUB_TOKEN="your_personal_access_token"
export GITHUB_REPO="owner/repo-name"

# Optional (for CI integration)
export CI_API_KEY="your_ci_system_api_key"

# Alternative: Create .env file in your project
echo "GITHUB_TOKEN=your_token_here" > .env
echo "GITHUB_REPO=owner/repo-name" >> .env
```

#### ✅ GitHub Token Permissions
Your `GITHUB_TOKEN` needs these scopes:
- `repo` (full repository access)
- `pull_requests:write` (to post comments)
- `statuses:read` (to read CI status)

**To create a GitHub token:**
1. Go to GitHub Settings → Developer settings → Personal access tokens
2. Generate new token (classic)
3. Select the required scopes above
4. Copy the token and set it in your environment

#### ✅ Agent Installation
**For Claude Code:**
```bash
npm install -g @anthropic-ai/claude-code
```

**For SourceGraph Amp:**
```bash
npm install -g @sourcegraph/amp
```

#### ✅ Git Repository Context
- Must run from inside a Git repository
- Repository should have a remote pointing to the GitHub repo specified in `GITHUB_REPO`
- Ensure you have proper Git user configuration:
```bash
git config user.name "Your Name"
git config user.email "your.email@example.com"
```

### Setup Verification

Run these commands to verify your setup:

```bash
# 1. Check Python version
python --version
# Expected: Python 3.8.0 or higher

# 2. Check required libraries
python -c "import mcp, github, git, requests, pydantic; print('All libraries installed successfully')"

# 3. Check Git repository
git remote -v
# Expected: Should show your GitHub repository URL

# 4. Verify GitHub token (should return your username)
curl -H "Authorization: token $GITHUB_TOKEN" https://api.github.com/user | jq '.login'
# Expected: Your GitHub username

# 5. Test GitHub API access to your repo
curl -H "Authorization: token $GITHUB_TOKEN" https://api.github.com/repos/$GITHUB_REPO | jq '.name'
# Expected: Your repository name

# 6. Check agent installation
claude --version  # For Claude Code
# OR
amp --version     # For SourceGraph Amp

# 7. Test current directory is a Git repo with the right remote
git config --get remote.origin.url
# Expected: Should match your GITHUB_REPO setting
```

### Common Setup Issues

**Python version too old:**
```bash
# Install Python 3.8+ using pyenv, conda, or system package manager
pyenv install 3.11.0
pyenv local 3.11.0
```

**GitHub token issues:**
```bash
# Test token permissions
curl -H "Authorization: token $GITHUB_TOKEN" \
     -H "Accept: application/vnd.github.v3+json" \
     https://api.github.com/repos/$GITHUB_REPO/pulls
# Should return PR list, not 401/403 error
```

**Git repository not configured:**
```bash
# Initialize if needed
git init
git remote add origin https://github.com/owner/repo-name.git

# Or fix existing remote
git remote set-url origin https://github.com/owner/repo-name.git
```

### What You DON'T Need

- ❌ No Docker or containers
- ❌ No database setup  
- ❌ No web server deployment
- ❌ No cloud services
- ❌ No additional authentication beyond GitHub token
- ❌ No special IDE or editor requirements

## 1. Python MCP Server Implementation

The Python script **IS** the server itself. No separate deployment needed - it runs as a local process that agents connect to via STDIO.

### Server Structure

```python
# requirements.txt
mcp
pygithub
gitpython
requests
pydantic

# pr_review_server.py
import asyncio
import os
import json
import subprocess
from typing import Optional, List, Dict, Any
from datetime import datetime

from mcp import McpServer, types
from github import Github
from git import Repo
import requests

# This class just organizes our GitHub/Git clients and state
class PRReviewContext:
    def __init__(self):
        self.github_token = os.getenv("GITHUB_TOKEN")
        self.repo_name = os.getenv("GITHUB_REPO")  # format: "owner/repo"
        self.ci_api_key = os.getenv("CI_API_KEY")
        
        # Initialize GitHub client
        self.github = Github(self.github_token) if self.github_token else None
        self.repo = self.github.get_repo(self.repo_name) if self.github and self.repo_name else None
        
        # Initialize Git repo (assumes script runs from repo root)
        self.git_repo = Repo(".")
        
        # Cache for current context
        self._current_branch = None
        self._current_commit = None
        self._current_pr = None

# Create the MCP server instance
server = McpServer("pr-review-server")
context = PRReviewContext()

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """Define all available tools"""
    return [
        # Git/Branch Context Tools
        types.Tool(
            name="get_current_branch",
            description="Get the current Git branch name",
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
        )
        # ... add other tools as needed
    ]

@server.call_tool()
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

# Tool Implementation Functions

async def get_current_branch() -> Dict[str, Any]:
    """Get the current Git branch name and related info"""
    try:
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
    """Get all comments from a PR"""
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
        
        pr = context.repo.get_pull(pr_number)
        
        # Get review comments (on specific lines)
        review_comments = []
        for comment in pr.get_review_comments():
            review_comments.append({
                "id": comment.id,
                "type": "review_comment",
                "author": comment.user.login,
                "body": comment.body,
                "file": comment.path,
                "line": comment.line,
                "created_at": comment.created_at.isoformat(),
                "url": comment.html_url
            })
        
        # Get issue comments (general PR comments)
        issue_comments = []
        for comment in pr.get_issue_comments():
            issue_comments.append({
                "id": comment.id,
                "type": "issue_comment", 
                "author": comment.user.login,
                "body": comment.body,
                "created_at": comment.created_at.isoformat(),
                "url": comment.html_url
            })
        
        return {
            "pr_number": pr_number,
            "title": pr.title,
            "review_comments": review_comments,
            "issue_comments": issue_comments,
            "total_comments": len(review_comments) + len(issue_comments)
        }
        
    except Exception as e:
        return {"error": f"Failed to get PR comments: {str(e)}"}

async def post_pr_reply(comment_id: int, message: str) -> Dict[str, Any]:
    """Reply to a PR comment"""
    try:
        if not context.repo:
            return {"error": "GitHub repository not configured"}
        
        # Get the comment to determine which PR it belongs to
        comment = context.repo.get_issue_comment(comment_id)
        
        # Extract PR number from the issue URL
        pr_number = comment.issue_url.split('/')[-1]
        pr = context.repo.get_pull(int(pr_number))
        
        # Create a new comment (GitHub doesn't have threaded replies)
        new_comment = pr.create_issue_comment(f"@{comment.user.login} {message}")
        
        return {
            "success": True,
            "comment_id": new_comment.id,
            "message": message,
            "url": new_comment.html_url
        }
        
    except Exception as e:
        return {"error": f"Failed to post PR reply: {str(e)}"}

async def get_build_status(commit_sha: Optional[str] = None) -> Dict[str, Any]:
    """Get build status for commit"""
    try:
        if not context.repo:
            return {"error": "GitHub repository not configured"}
        
        if not commit_sha:
            commit_sha = context._current_commit or context.git_repo.head.commit.hexsha
        
        commit = context.repo.get_commit(commit_sha)
        
        # Get status from GitHub Status API
        status = commit.get_combined_status()
        
        # Get check runs (GitHub Actions, etc.)
        check_runs = []
        try:
            for run in commit.get_check_runs():
                check_runs.append({
                    "name": run.name,
                    "status": run.status,  # queued, in_progress, completed
                    "conclusion": run.conclusion,  # success, failure, neutral, cancelled, etc.
                    "url": run.html_url
                })
        except Exception:
            pass  # Check runs might not be available
        
        return {
            "commit_sha": commit_sha,
            "overall_state": status.state,  # pending, success, error, failure
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
        # Placeholder implementation - replace with your actual CI API calls
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

# Main server entry point
async def main():
    """Start the MCP server"""
    from mcp.server.stdio import stdio_server
    
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())
```

### How to Run the Server

```bash
# 1. Install dependencies
pip install mcp pygithub gitpython requests pydantic

# 2. Set environment variables
export GITHUB_TOKEN="your_github_token"
export GITHUB_REPO="owner/repo-name"

# 3. Test the server (it should start and wait for input)
cd /path/to/your/project
python pr_review_server.py

# 4. The server is now running and ready to accept MCP connections
```

## 2. Connecting Agents to Your Server

### Claude Code Configuration

Create or edit `~/.config/claude-code/settings.json`:

```json
{
  "mcpServers": {
    "pr-review": {
      "command": "python",
      "args": ["/full/path/to/your/pr_review_server.py"],
      "cwd": "/path/to/your/project",
      "env": {
        "GITHUB_TOKEN": "your_github_token",
        "GITHUB_REPO": "owner/repo-name"
      }
    }
  }
}
```

**Key Points:**
- `command`: The executable to run (python)
- `args`: Full path to your server script
- `cwd`: Your project directory (so Git operations work correctly)
- `env`: Environment variables your server needs

### SourceGraph Amp Configuration

Create or edit `~/.config/amp/settings.json`:

```json
{
  "mcpServers": {
    "pr-review": {
      "command": "python",
      "args": ["/full/path/to/your/pr_review_server.py"],
      "cwd": "/path/to/your/project",
      "env": {
        "GITHUB_TOKEN": "your_github_token", 
        "GITHUB_REPO": "owner/repo-name"
      }
    }
  }
}
```

### Testing the Connection

```bash
# Start Claude Code in your project directory
cd /path/to/your/project
claude

# Test if tools are available
claude> "List all available tools"

# Test a specific tool
claude> "What's my current branch?"

# Start Amp (similar process)
cd /path/to/your/project  
amp

# Test tools
amp> "What tools do you have access to?"
```d branch
        pulls = pr_server.repo.get_pulls(state='open', head=f"{pr_server.repo.owner.login}:{branch_name}")
        pr_list = list(pulls)
        
        if not pr_list:
            # Also check closed PRs in case the branch exists but PR is closed/merged
            pulls_closed = pr_server.repo.get_pulls(state='closed', head=f"{pr_server.repo.owner.login}:{branch_name}")
            pr_list = list(pulls_closed)
        
        if pr_list:
            pr = pr_list[0]  # Take the first (most recent) PR
            pr_server._current_pr = pr.number
            
            return {
                "found": True,
                "pr_number": pr.number,
                "title": pr.title,
                "state": pr.state,
                "url": pr.html_url,
                "author": pr.user.login,
                "created_at": pr.created_at.isoformat(),
                "updated_at": pr.updated_at.isoformat(),
                "base_branch": pr.base.ref,
                "head_branch": pr.head.ref,
                "mergeable": pr.mergeable,
                "mergeable_state": pr.mergeable_state
            }
        else:
            return {
                "found": False,
                "branch_name": branch_name,
                "message": f"No PR found for branch '{branch_name}'"
            }
            
    except Exception as e:
        return {"error": f"Failed to find PR for branch {branch_name}: {str(e)}"}

# PR Management Implementation

async def get_pr_comments(pr_number: Optional[int] = None) -> Dict[str, Any]:
    """Get all comments from a PR"""
    try:
        if not pr_server.repo:
            return {"error": "GitHub repository not configured"}
            
        if not pr_number:
            # Try to find PR for current branch
            pr_info = await find_pr_for_branch()
            if pr_info.get("found"):
                pr_number = pr_info["pr_number"]
            else:
                return {"error": "No PR number provided and couldn't find PR for current branch"}
        
        pr = pr_server.repo.get_pull(pr_number)
        
        # Get review comments (on specific lines)
        review_comments = []
        for comment in pr.get_review_comments():
            review_comments.append({
                "id": comment.id,
                "type": "review_comment",
                "author": comment.user.login,
                "body": comment.body,
                "file": comment.path,
                "line": comment.line,
                "original_line": comment.original_line,
                "diff_hunk": comment.diff_hunk,
                "created_at": comment.created_at.isoformat(),
                "updated_at": comment.updated_at.isoformat(),
                "url": comment.html_url,
                "in_reply_to": comment.in_reply_to_id,
                "conversation_id": comment.pull_request_review_id
            })
        
        # Get issue comments (general PR comments)
        issue_comments = []
        for comment in pr.get_issue_comments():
            issue_comments.append({
                "id": comment.id,
                "type": "issue_comment", 
                "author": comment.user.login,
                "body": comment.body,
                "created_at": comment.created_at.isoformat(),
                "updated_at": comment.updated_at.isoformat(),
                "url": comment.html_url
            })
        
        return {
            "pr_number": pr_number,
            "title": pr.title,
            "review_comments": review_comments,
            "issue_comments": issue_comments,
            "total_comments": len(review_comments) + len(issue_comments)
        }
        
    except Exception as e:
        return {"error": f"Failed to get PR comments: {str(e)}"}

async def get_pr_info(pr_number: Optional[int] = None) -> Dict[str, Any]:
    """Get detailed PR information"""
    try:
        if not pr_server.repo:
            return {"error": "GitHub repository not configured"}
            
        if not pr_number:
            pr_info = await find_pr_for_branch()
            if pr_info.get("found"):
                pr_number = pr_info["pr_number"]
            else:
                return {"error": "No PR number provided and couldn't find PR for current branch"}
        
        pr = pr_server.repo.get_pull(pr_number)
        
        # Get check runs for the PR
        commit = pr_server.repo.get_commit(pr.head.sha)
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
            pass  # Check runs might not be available
        
        return {
            "number": pr.number,
            "title": pr.title,
            "body": pr.body or "",
            "state": pr.state,
            "author": pr.user.login,
            "assignees": [a.login for a in pr.assignees],
            "reviewers": [r.login for r in pr.requested_reviewers],
            "labels": [l.name for l in pr.labels],
            "milestone": pr.milestone.title if pr.milestone else None,
            "created_at": pr.created_at.isoformat(),
            "updated_at": pr.updated_at.isoformat(),
            "merged_at": pr.merged_at.isoformat() if pr.merged_at else None,
            "base_branch": pr.base.ref,
            "head_branch": pr.head.ref,
            "head_sha": pr.head.sha,
            "mergeable": pr.mergeable,
            "mergeable_state": pr.mergeable_state,
            "files_changed": pr.changed_files,
            "additions": pr.additions,
            "deletions": pr.deletions,
            "commits": pr.commits,
            "url": pr.html_url,
            "check_runs": check_runs
        }
        
    except Exception as e:
        return {"error": f"Failed to get PR info: {str(e)}"}

async def get_file_changes(pr_number: Optional[int] = None, base_branch: Optional[str] = None) -> Dict[str, Any]:
    """Get files changed in PR or current branch"""
    try:
        if pr_number:
            # Get changes from PR
            if not pr_server.repo:
                return {"error": "GitHub repository not configured"}
                
            pr = pr_server.repo.get_pull(pr_number)
            files = []
            
            for file in pr.get_files():
                files.append({
                    "filename": file.filename,
                    "status": file.status,  # added, removed, modified, renamed
                    "additions": file.additions,
                    "deletions": file.deletions,
                    "changes": file.changes,
                    "patch": file.patch if hasattr(file, 'patch') else None,
                    "previous_filename": file.previous_filename if hasattr(file, 'previous_filename') else None
                })
            
            return {
                "source": "pr",
                "pr_number": pr_number,
                "files": files,
                "total_files": len(files)
            }
        else:
            # Get changes from current branch vs base
            if not base_branch:
                base_branch = "main"  # Default to main
                # Try to find actual default branch
                for branch_name in ["main", "master", "develop"]:
                    if branch_name in [b.name for b in pr_server.git_repo.heads]:
                        base_branch = branch_name
                        break
            
            current_branch = pr_server._current_branch or pr_server.git_repo.active_branch.name
            
            # Get diff between branches
            try:
                base_commit = pr_server.git_repo.heads[base_branch].commit
                current_commit = pr_server.git_repo.active_branch.commit
                
                diff = base_commit.diff(current_commit)
                files = []
                
                for diff_item in diff:
                    change_type = "modified"
                    if diff_item.new_file:
                        change_type = "added"
                    elif diff_item.deleted_file:
                        change_type = "removed"
                    elif diff_item.renamed_file:
                        change_type = "renamed"
                    
                    files.append({
                        "filename": diff_item.b_path or diff_item.a_path,
                        "status": change_type,
                        "previous_filename": diff_item.a_path if diff_item.renamed_file else None
                    })
                
                return {
                    "source": "branch_diff",
                    "base_branch": base_branch,
                    "current_branch": current_branch,
                    "files": files,
                    "total_files": len(files)
                }
                
            except Exception as e:
                return {"error": f"Failed to get branch diff: {str(e)}"}
            
    except Exception as e:
        return {"error": f"Failed to get file changes: {str(e)}"}

# CI/CD Implementation (customize these based on your CI system)

async def get_build_status(commit_sha: Optional[str] = None, pr_number: Optional[int] = None) -> Dict[str, Any]:
    """Get build status for commit or PR"""
    try:
        if not pr_server.repo:
            return {"error": "GitHub repository not configured"}
        
        if not commit_sha:
            if pr_number:
                pr = pr_server.repo.get_pull(pr_number)
                commit_sha = pr.head.sha
            else:
                commit_sha = pr_server._current_commit or pr_server.git_repo.head.commit.hexsha
        
        commit = pr_server.repo.get_commit(commit_sha)
        
        # Get status from GitHub Status API
        status = commit.get_combined_status()
        
        # Get check runs (GitHub Actions, etc.)
        check_runs = []
        try:
            for run in commit.get_check_runs():
                check_runs.append({
                    "name": run.name,
                    "status": run.status,  # queued, in_progress, completed
                    "conclusion": run.conclusion,  # success, failure, neutral, cancelled, skipped, timed_out, action_required
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                    "url": run.html_url,
                    "details_url": run.details_url
                })
        except Exception as e:
            print(f"Could not get check runs: {e}")
        
        # Get traditional status checks
        statuses = []
        for status_obj in status.statuses:
            statuses.append({
                "context": status_obj.context,
                "state": status_obj.state,  # pending, success, error, failure
                "description": status_obj.description,
                "target_url": status_obj.target_url,
                "created_at": status_obj.created_at.isoformat(),
                "updated_at": status_obj.updated_at.isoformat()
            })
        
        return {
            "commit_sha": commit_sha,
            "overall_state": status.state,  # pending, success, error, failure
            "total_count": status.total_count,
            "check_runs": check_runs,
            "status_checks": statuses,
            "has_failures": any(
                run.get("conclusion") in ["failure", "timed_out", "cancelled"] for run in check_runs
            ) or any(
                s.get("state") in ["error", "failure"] for s in statuses
            )
        }
        
    except Exception as e:
        return {"error": f"Failed to get build status: {str(e)}"}

# Placeholder implementations for your specific CI system
# Customize these based on your actual CI/CD setup

async def read_swiftlint_logs(build_id: Optional[str] = None) -> Dict[str, Any]:
    """Read SwiftLint logs - CUSTOMIZE THIS based on your CI system"""
    try:
        # Example implementation - replace with your actual CI API calls
        
        if not build_id:
            # Get latest build for current commit
            commit_sha = pr_server._current_commit or pr_server.git_repo.head.commit.hexsha
            build_status = await get_build_status(commit_sha)
            
            # Find SwiftLint check run
            swiftlint_run = None
            for run in build_status.get("check_runs", []):
                if "swiftlint" in run["name"].lower() or "lint" in run["name"].lower():
                    swiftlint_run = run
                    break
            
            if not swiftlint_run:
                return {"error": "No SwiftLint check run found"}
        
        # TODO: Replace this with actual API call to your CI system
        # This is a placeholder implementation
        violations = [
            {
                "file": "Sources/MyApp/ViewController.swift",
                "line": 45,
                "column": 20,
                "severity": "warning",
                "rule": "line_length",
                "message": "Line should be 120 characters or less: currently 125 characters"
            },
            {
                "file": "Sources/MyApp/Model.swift", 
                "line": 12,
                "column": 1,
                "severity": "error",
                "rule": "force_cast",
                "message": "Force casts should be avoided"
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

async def read_test_logs(build_id: Optional[str] = None) -> Dict[str, Any]:
    """Read test failure logs - CUSTOMIZE THIS based on your CI system"""
    try:
        # TODO: Replace with actual implementation for your CI system
        
        # Placeholder implementation
        test_failures = [
            {
                "test_case": "UserServiceTests.testUserLogin",
                "class": "UserServiceTests",
                "method": "testUserLogin", 
                "failure_message": "XCTAssertEqual failed: (\"invalid\") is not equal to (\"valid\")",
                "file": "Tests/UserServiceTests.swift",
                "line": 25,
                "duration": 0.003
            },
            {
                "test_case": "NetworkTests.testAPICall",
                "class": "NetworkTests", 
                "method": "testAPICall",
                "failure_message": "XCTAssertNotNil failed",
                "file": "Tests/NetworkTests.swift",
                "line": 40,
                "duration": 1.2
            }
        ]
        
        return {
            "build_id": build_id,
            "test_failures": test_failures,
            "total_failures": len(test_failures),
            "failed_test_count": len(test_failures)
        }
        
    except Exception as e:
        return {"error": f"Failed to read test logs: {str(e)}"}

# Additional utility implementations

async def post_pr_reply(comment_id: int, message: str) -> Dict[str, Any]:
    """Reply to a PR comment"""
    try:
        if not pr_server.repo:
            return {"error": "GitHub repository not configured"}
        
        # This is a simplified implementation
        # In practice, you'd need to determine if it's a review comment or issue comment
        # and use the appropriate API
        
        # For now, assuming it's an issue comment
        comment = pr_server.repo.get_issue_comment(comment_id)
        
        # Post reply (this creates a new comment, GitHub doesn't have threaded replies for all comment types)
        pr_number = comment.issue_url.split('/')[-1]
        pr = pr_server.repo.get_pull(int(pr_number))
        
        new_comment = pr.create_issue_comment(f"@{comment.user.login} {message}")
        
        return {
            "success": True,
            "comment_id": new_comment.id,
            "message": message,
            "url": new_comment.html_url
        }
        
    except Exception as e:
        return {"error": f"Failed to post PR reply: {str(e)}"}

async def mark_comment_resolved(comment_id: int) -> Dict[str, Any]:
    """Mark a comment as resolved"""
    try:
        # GitHub doesn't have a direct "resolve" API for all comment types
        # This would depend on your specific workflow
        
        return {
            "success": True,
            "comment_id": comment_id,
            "message": "Comment marked as resolved (implementation depends on your workflow)"
        }
        
    except Exception as e:
        return {"error": f"Failed to mark comment as resolved: {str(e)}"}

# Main server startup
async def main():
    from mcp.server.stdio import stdio_server
    
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())
```[]> {
  // Your existing get PR comments logic
  // Return standardized comment format
  return comments.map(comment => ({
    id: comment.id,
    author: comment.user.login,
    body: comment.body,
    file: comment.path,
    line: comment.line,
    created_at: comment.created_at,
    conversation_id: comment.conversation_id
  }));
}

async function getBuildStatus(pr_id?: string): Promise<BuildStatus> {
  // Your existing build status logic
  return {
    status: 'failed' | 'passed' | 'pending',
    build_id: 'build-123',
    checks: [
      { name: 'SwiftLint', status: 'failed', log_url: '...' },
      { name: 'Tests', status: 'failed', log_url: '...' }
    ],
    url: 'https://ci-system.com/build/123'
  };
}

async function readSwiftLintLogs(build_id?: string): Promise<LintResult[]> {
  // Your existing SwiftLint log reading logic
  return violations.map(violation => ({
    file: violation.file,
    line: violation.line,
    column: violation.column,
    severity: violation.severity,
    rule: violation.rule,
    message: violation.reason
  }));
}
```

## 2. Agent Configuration

## 3. Architecture Summary

**How it all works:**

1. **Your Python Script = The MCP Server**
   - No separate deployment needed
   - Runs as a local process on your machine
   - Communicates via STDIO (standard input/output)

2. **Agent Connection Process:**
   ```
   Claude Code/Amp → starts → python pr_review_server.py → MCP protocol → your tools
   ```

3. **Configuration Files Tell Agents Where to Find Your Server:**
   ```json
   {
     "mcpServers": {
       "pr-review": {
         "command": "python",
         "args": ["/path/to/pr_review_server.py"],
         "cwd": "/your/project/directory"
       }
     }
   }
   ```

## 4. Complete Working Example

### File Structure
```
your-project/
├── pr_review_server.py          # Your MCP server
├── CLAUDE.md                    # Claude Code instructions
├── AGENT.md                     # Amp instructions  
├── .env                         # Environment variables (optional)
└── requirements.txt             # Python dependencies
```

### Environment Setup
```bash
# Create .env file (optional - you can also export these)
echo "GITHUB_TOKEN=your_token_here" > .env
echo "GITHUB_REPO=owner/repo-name" >> .env

# Install dependencies
pip install mcp pygithub gitpython requests pydantic python-dotenv
```

### Updated Server Script (with .env support)
```python
# Add this to the top of pr_review_server.py
from dotenv import load_dotenv
load_dotenv()  # Load .env file if it exists
```

### Testing Your Setup

**Step 1: Test the server directly**
```bash
cd /path/to/your/project
python pr_review_server.py

# You should see the server start and wait for input
# Press Ctrl+C to stop
```

**Step 2: Configure Claude Code**
```bash
# Edit Claude Code settings
nano ~/.config/claude-code/settings.json

# Add your MCP server configuration (see above)
```

**Step 3: Test with Claude Code**
```bash
cd /path/to/your/project
claude

# Test commands:
claude> "List available tools"
claude> "What's my current branch?"
claude> "Find the PR for this branch"
```

### Troubleshooting

**Server won't start:**
- Check Python path: `which python`
- Check dependencies: `pip list | grep mcp`
- Check environment variables: `echo $GITHUB_TOKEN`

**Agent can't find server:**
- Verify full path to script in settings.json
- Check that `cwd` points to your project directory
- Ensure the script is executable: `chmod +x pr_review_server.py`

**Tools not working:**
- Check GitHub token permissions (repo access)
- Verify you're in a Git repository
- Check that GITHUB_REPO format is "owner/repo-name"

## 5. Key Differences: Claude Code vs Amp

### Claude Code
- **Config file:** `~/.config/claude-code/settings.json`
- **Workflow docs:** `CLAUDE.md` in project root
- **Strengths:** Better Git integration, more mature MCP support
- **Best for:** Local development workflows

### SourceGraph Amp  
- **Config file:** `~/.config/amp/settings.json`
- **Workflow docs:** `AGENT.md` in project root
- **Strengths:** Unconstrained token usage, team collaboration features
- **Best for:** Larger codebases, team environments

Both agents connect to your MCP server the same way - the differences are in their UI and additional features.

## 6. Next Steps

1. **Start Simple:**
   ```bash
   # Create minimal server with just get_current_branch
   # Test the connection works
   # Add one tool at a time
   ```

2. **Customize CI Integration:**
   ```python
   # Replace the placeholder read_swiftlint_logs function
   # Add your actual CI system API calls
   # Test with real build failures
   ```

3. **Add Workflow Documentation:**
   ```markdown
   # Create CLAUDE.md or AGENT.md
   # Document your specific commands
   # Test agent behavior matches expectations
   ```

4. **Iterate and Improve:**
   ```bash
   # Use the agent for real PR work
   # Identify pain points
   # Add more tools as needed
   ```

The beauty of this approach is that your Python script is both the server AND the implementation - no complex deployment needed!

## 7. Example Usage Session

```bash
# Start in your project
cd /path/to/your/ios-project

# Start Claude Code
claude

# Natural workflow
claude> "What branch am I working on?"
# → Calls get_current_branch()

claude> "Is there a PR for this branch?"  
# → Calls find_pr_for_branch()

claude> "What feedback do I need to address?"
# → Calls get_pr_comments() using the found PR

claude> "Fix the build issues"
# → Calls get_build_status(), read_swiftlint_logs(), fixes code

claude> "Reply to John's comment about error handling"
# → Finds the comment, makes changes, calls post_pr_reply()
```

The agent automatically maintains context about your current branch and PR throughout the session!

## 3. Workflow Documentation

### Claude Code: CLAUDE.md

Create `CLAUDE.md` in your project root:

```markdown
# PR Review Agent Instructions

## Project Context
This is a [Swift/iOS/etc.] project with the following key characteristics:
- Main branch: `main`
- CI/CD: [Your CI system]
- Code style: SwiftLint enforced
- Test framework: [XCTest/etc.]

## Available Tools
Use these MCP tools for PR management:

### PR Management Tools
- `get_pr_comments()` - Get all comments on current PR
- `post_pr_reply(comment_id, message)` - Reply to specific comment  
- `get_pr_info()` - Get PR details (title, description, files changed)

### CI/CD Tools
- `get_build_status()` - Check current build status
- `read_swiftlint_logs()` - Get SwiftLint violations
- `read_test_logs()` - Get test failure details

### File Management
- `get_file_changes()` - See what files changed in PR
- `mark_comment_resolved(comment_id)` - Mark conversation as resolved

## Workflow Instructions

### When asked to "Address PR feedback":
1. Call `get_pr_comments()` to see all feedback
2. For each comment:
   - Analyze the requested change
   - Make the necessary code modifications
   - Post a reply explaining what you changed
   - Mark as resolved if appropriate

### When asked to "Fix build issues":
1. Call `get_build_status()` to see what failed
2. If SwiftLint failed: call `read_swiftlint_logs()` and fix violations
3. If tests failed: call `read_test_logs()` and fix failing tests
4. Explain what you fixed and why

### When asked to "Review CI status":
1. Call `get_build_status()` first
2. If any checks failed, read the relevant logs
3. Provide a summary of issues and next steps

## Code Style Guidelines
- Follow SwiftLint rules strictly
- Use descriptive variable names
- Add comments for complex logic
- Ensure all tests pass before considering work complete

## Response Format
Always:
- Explain what you're doing before calling tools
- Summarize the results after calling tools  
- Provide clear next steps or confirmation when done
- Use the PR tools to communicate progress back to reviewers
```

### SourceGraph Amp: AGENT.md

Create `AGENT.md` in your project root:

```markdown
# PR Review Agent Configuration

## Project Setup
This project uses:
- Language: [Swift/TypeScript/etc.]
- Build system: [Xcode/npm/etc.]
- CI/CD: [GitHub Actions/Jenkins/etc.]
- Code quality: SwiftLint

## MCP Tools Available

### PR Management
- `get_pr_comments()` - Retrieve all PR comments
- `post_pr_reply(comment_id, message)` - Respond to comments
- `get_pr_info()` - Get PR metadata

### Build & Quality
- `get_build_status()` - Check CI status  
- `read_swiftlint_logs()` - Get linting issues
- `read_test_logs()` - Get test failures

## Common Commands

### "Address PR feedback"
1. Get all comments using `get_pr_comments()`
2. Address each piece of feedback
3. Reply to comments with explanations
4. Mark resolved when appropriate

### "Fix build failures"  
1. Check status with `get_build_status()`
2. Read relevant logs (SwiftLint/tests)
3. Fix identified issues
4. Verify fixes address the problems

### "Review and summarize PR"
1. Get PR info and comments
2. Check build status
3. Provide overall health summary
4. Suggest next steps

## Code Standards
- Follow existing project conventions
- Ensure SwiftLint compliance
- Maintain test coverage
- Document significant changes

## Communication Style
- Be concise but thorough in PR responses
- Explain reasoning behind changes
- Ask for clarification when feedback is unclear
- Always test changes before marking as complete
```

## 4. Usage Examples

### Basic Commands

```bash
# Address PR feedback
claude "Please address all the PR feedback"
# or
amp "Please address all the PR feedback"

# Fix build issues
claude "Build failed - please check logs and fix issues"
# or  
amp "Build failed - please check logs and fix issues"

# Review status
claude "What's the current status of this PR?"
# or
amp "What's the current status of this PR?"
```

### Advanced Commands

```bash
# Specific issue focus
claude "Focus on the SwiftLint violations and fix them"

# Comment-specific response  
claude "Look at Sarah's comment about the networking code and address her concerns"

# Comprehensive review
claude "Do a full PR review - check build status, address comments, and summarize what's left to do"
```

## 5. Environment Variables

Both agents will need these environment variables (set in MCP server config):

```bash
# GitHub Integration
GITHUB_TOKEN=your_personal_access_token
GITHUB_REPO=owner/repo-name

# CI/CD Integration (examples)
JENKINS_API_KEY=your_jenkins_key
JENKINS_BASE_URL=https://jenkins.company.com
# or
GITHUB_ACTIONS_TOKEN=your_actions_token

# Project-specific
DEFAULT_BRANCH=main
SWIFTLINT_CONFIG_PATH=.swiftlint.yml
```

## 6. Testing Your Setup

### 1. Test MCP Server
```bash
# Test your MCP server directly
node dist/server.js
# Should start without errors
```

### 2. Test Agent Integration
```bash
# Claude Code
claude "List available tools"

# SourceGraph Amp  
amp "What tools do you have access to?"
```

### 3. Test End-to-End Workflow
```bash
# Create a test PR with some comments
# Then run:
claude "Get the current PR comments and show me what needs to be addressed"
```

## 7. Troubleshooting

### Common Issues

**MCP Server not found:**
- Check file paths in settings.json
- Verify MCP server starts independently
- Check environment variables are set

**GitHub API errors:**
- Verify GITHUB_TOKEN has correct permissions
- Check rate limiting
- Ensure repository access

**Agent not using tools:**
- Verify tools are listed when asked
- Check CLAUDE.md/AGENT.md syntax
- Try more explicit commands

### Debug Commands

```bash
# Claude Code debug mode
claude --verbose "test command"

# Check MCP server logs
node dist/server.js --debug

# Test individual tools
claude "Call get_build_status and show me the raw response"
```

## 8. Next Steps

### Phase 1: Basic Setup
- [ ] Implement MCP server with your existing tools
- [ ] Configure chosen agent (Claude Code or Amp)
- [ ] Create workflow documentation
- [ ] Test basic commands

### Phase 2: Workflow Refinement  
- [ ] Test on real PRs
- [ ] Refine instructions based on agent behavior
- [ ] Add error handling and edge cases
- [ ] Document common patterns

### Phase 3: Automation (Future)
- [ ] Add webhook notifications
- [ ] Create trigger scripts
- [ ] Set up monitoring
- [ ] Scale to multiple repositories

## Conclusion

This setup gives you a flexible foundation for PR review automation that works with multiple coding agents. Start with the manual trigger approach to validate your workflow, then gradually add automation as you gain confidence in the system.

The key is to keep the MCP server generic while using agent-specific configuration files (CLAUDE.md vs AGENT.md) to define behavior. This approach lets you switch between agents or even use multiple agents simultaneously if needed.
