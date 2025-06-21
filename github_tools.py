#!/usr/bin/env python3

"""
GitHub Tools for MCP Server
Contains all GitHub-related tool implementations.
"""

import os
import json
import requests
import subprocess
import logging
from typing import Optional
from github import Github
from repository_manager import RepositoryConfig, RepositoryManager

logger = logging.getLogger(__name__)

# Global repository manager (set by worker)
repo_manager: Optional[RepositoryManager] = None

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
    if not repo_manager:
        raise ValueError("Repository manager not initialized")
    
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


# Build/Lint helper functions (simplified - removed legacy single-repo functions)
async def execute_read_swiftlint_logs(build_id: str = None) -> str:
    """Read SwiftLint violation logs from GitHub Actions artifacts"""
    logger.info(f"Reading SwiftLint logs (build_id: {build_id})")
    logger.warning("SwiftLint logs not implemented in multi-repo mode yet")
    return json.dumps({"error": "SwiftLint logs not implemented in multi-repo mode yet"})


async def execute_read_build_logs(build_id: str = None) -> str:
    """Read build logs and extract Swift compiler errors, warnings, and test failures"""
    return json.dumps({"error": "Build logs not implemented in multi-repo mode yet"})
