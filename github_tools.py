#!/usr/bin/env python3

"""
GitHub Tools for MCP Server
Contains all GitHub-related tool implementations.
"""

import json
import logging
import os
import subprocess
from typing import Optional

import requests
from github import Github

from repository_manager import RepositoryConfig, RepositoryManager

logger = logging.getLogger(__name__)

# Global repository manager (set by worker)
repo_manager: Optional[RepositoryManager] = None


class GitHubAPIContext:
    """Context for GitHub API operations with repository information"""

    def __init__(self, repo_config: RepositoryConfig):
        logger.debug(
            f"GitHubAPIContext.__init__: Starting initialization for path: {repo_config.path}"
        )
        self.repo_config = repo_config

        # Check for GitHub token
        self.github_token = os.getenv("GITHUB_TOKEN")
        if not self.github_token:
            logger.error(
                "GitHubAPIContext.__init__: GITHUB_TOKEN environment variable not set"
            )
        else:
            logger.debug(
                f"GitHubAPIContext.__init__: GITHUB_TOKEN found (length: {len(self.github_token)})"
            )

        self.github = Github(self.github_token) if self.github_token else None
        if not self.github:
            logger.error("GitHubAPIContext.__init__: Failed to create GitHub client")
        else:
            logger.debug(
                "GitHubAPIContext.__init__: GitHub client created successfully"
            )

        # Get repo name from git config
        self.repo_name = None
        self.repo = None

        if not self.github:
            logger.error(
                "GitHubAPIContext.__init__: Cannot proceed without GitHub client"
            )
            return

        if not self.repo_config.path:
            logger.error("GitHubAPIContext.__init__: No repository path provided")
            return

        logger.debug(
            f"GitHubAPIContext.__init__: Getting git remote from path: {self.repo_config.path}"
        )
        try:
            # Get repo name from git remote
            cmd = ["git", "config", "--get", "remote.origin.url"]
            logger.debug(
                f"GitHubAPIContext.__init__: Running command: {' '.join(cmd)} in {self.repo_config.path}"
            )

            output = (
                subprocess.check_output(cmd, cwd=self.repo_config.path).decode().strip()
            )

            logger.debug(f"GitHubAPIContext.__init__: Git remote URL: {output}")

            if output.startswith("git@"):
                _, path = output.split(":", 1)
                logger.debug(f"GitHubAPIContext.__init__: Parsed SSH URL, path: {path}")
            elif output.startswith("https://"):
                path = output.split("github.com/", 1)[-1]
                logger.debug(
                    f"GitHubAPIContext.__init__: Parsed HTTPS URL, path: {path}"
                )
            else:
                raise ValueError(f"Unrecognized GitHub remote URL: {output}")

            self.repo_name = path.replace(".git", "")
            logger.info(
                f"GitHubAPIContext.__init__: Extracted repo name: {self.repo_name}"
            )

            # Try to get the repository object
            logger.debug(
                f"GitHubAPIContext.__init__: Getting GitHub repo object for {self.repo_name}"
            )
            self.repo = self.github.get_repo(self.repo_name)
            logger.info(
                f"GitHubAPIContext.__init__: Successfully initialized GitHub context for {self.repo_name}"
            )

        except subprocess.CalledProcessError as e:
            logger.error(f"GitHubAPIContext.__init__: Git command failed: {e}")
            logger.error(
                f"GitHubAPIContext.__init__: Command output: {e.output if hasattr(e, 'output') else 'No output'}"
            )
        except Exception as e:
            logger.error(
                f"GitHubAPIContext.__init__: Failed to initialize GitHub context: {e}",
                exc_info=True,
            )

    def get_current_branch(self) -> str:
        """Get current branch name"""
        return (
            subprocess.check_output(
                ["git", "branch", "--show-current"], cwd=self.repo_config.path
            )
            .decode()
            .strip()
        )

    def get_current_commit(self) -> str:
        """Get current commit hash"""
        return (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=self.repo_config.path
            )
            .decode()
            .strip()
        )


def get_github_context(repo_name: str) -> GitHubAPIContext:
    """Get GitHub API context for a specific repository"""
    logger.debug(f"get_github_context: Getting context for repo '{repo_name}'")

    if not repo_manager:
        logger.error("get_github_context: Repository manager not initialized")
        raise ValueError("Repository manager not initialized")

    logger.debug(
        f"get_github_context: Repository manager available, looking for repo '{repo_name}'"
    )
    repo_config = repo_manager.get_repository(repo_name)
    if not repo_config:
        logger.error(
            f"get_github_context: Repository '{repo_name}' not found in configuration"
        )
        available_repos = (
            list(repo_manager.repositories.keys())
            if hasattr(repo_manager, "repositories")
            else []
        )
        logger.error(f"get_github_context: Available repositories: {available_repos}")
        raise ValueError(f"Repository '{repo_name}' not found")

    logger.debug(
        f"get_github_context: Found repo config for '{repo_name}', path: {repo_config.path}"
    )
    context = GitHubAPIContext(repo_config)
    logger.debug(
        f"get_github_context: Created GitHubAPIContext, repo_name: {context.repo_name}"
    )
    return context


# Tool implementations with repository context
async def execute_find_pr_for_branch(repo_name: str, branch_name: str) -> str:
    """Find the PR associated with a branch in the specified repository"""
    try:
        context = get_github_context(repo_name)
        if not context.repo:
            return json.dumps(
                {"error": f"GitHub repository not configured for {repo_name}"}
            )

        pulls = context.repo.get_pulls(state="all")

        # Look for matching branch
        for pr in pulls:
            if pr.head.ref == branch_name:
                return json.dumps(
                    {
                        "found": True,
                        "pr_number": pr.number,
                        "title": pr.title,
                        "state": pr.state,
                        "url": pr.html_url,
                        "author": pr.user.login,
                        "base_branch": pr.base.ref,
                        "head_branch": pr.head.ref,
                        "repo": context.repo_name,
                        "repo_config": repo_name,
                    }
                )

        return json.dumps(
            {
                "found": False,
                "branch_name": branch_name,
                "repo": context.repo_name,
                "repo_config": repo_name,
                "message": f"No PR found for branch '{branch_name}' in {context.repo_name}",
            }
        )

    except Exception as e:
        return json.dumps(
            {
                "error": f"Failed to find PR for branch {branch_name} in {repo_name}: {e!s}"
            }
        )


async def execute_get_pr_comments(repo_name: str, pr_number: int) -> str:
    """Get all comments from a PR in the specified repository"""
    logger.info(f"Getting PR comments for repository '{repo_name}', PR #{pr_number}")

    try:
        logger.debug(f"Getting GitHub context for repository '{repo_name}'")
        context = get_github_context(repo_name)
        if not context.repo:
            logger.error(f"GitHub repository not configured for {repo_name}")
            return json.dumps(
                {"error": f"GitHub repository not configured for {repo_name}"}
            )

        logger.info(
            f"GitHub context initialized for repo '{context.repo_name}' (config: {repo_name})"
        )

        # Use GitHub API directly for better error handling
        headers = {
            "Authorization": f"token {context.github_token[:8]}..."
        }  # Log only first 8 chars for security
        logger.debug(f"Using GitHub API headers: {headers}")

        # Get PR details first
        pr_url = f"https://api.github.com/repos/{context.repo_name}/pulls/{pr_number}"
        logger.info(f"Making GitHub API call to get PR details: {pr_url}")

        pr_response = requests.get(
            pr_url, headers={"Authorization": f"token {context.github_token}"}
        )
        logger.info(
            f"PR details API response: status={pr_response.status_code}, headers={dict(pr_response.headers)}"
        )

        if pr_response.status_code != 200:
            logger.error(
                f"Failed to get PR details. Status: {pr_response.status_code}, Response: {pr_response.text}"
            )
            pr_response.raise_for_status()

        pr_data = pr_response.json()
        logger.info(
            f"Successfully got PR details. Title: '{pr_data['title']}', State: {pr_data['state']}"
        )

        # Get review comments
        comments_url = pr_data["review_comments_url"]
        logger.info(f"Making GitHub API call to get review comments: {comments_url}")

        comments_resp = requests.get(
            comments_url, headers={"Authorization": f"token {context.github_token}"}
        )
        logger.info(
            f"Review comments API response: status={comments_resp.status_code}, headers={dict(comments_resp.headers)}"
        )

        if comments_resp.status_code != 200:
            logger.error(
                f"Failed to get review comments. Status: {comments_resp.status_code}, Response: {comments_resp.text}"
            )
            comments_resp.raise_for_status()

        review_comments = comments_resp.json()
        logger.info(f"Successfully got {len(review_comments)} review comments")

        # Get issue comments
        issue_comments_url = f"https://api.github.com/repos/{context.repo_name}/issues/{pr_number}/comments"
        logger.info(
            f"Making GitHub API call to get issue comments: {issue_comments_url}"
        )

        issue_resp = requests.get(
            issue_comments_url,
            headers={"Authorization": f"token {context.github_token}"},
        )
        logger.info(
            f"Issue comments API response: status={issue_resp.status_code}, headers={dict(issue_resp.headers)}"
        )

        if issue_resp.status_code != 200:
            logger.error(
                f"Failed to get issue comments. Status: {issue_resp.status_code}, Response: {issue_resp.text}"
            )
            issue_resp.raise_for_status()

        issue_comments = issue_resp.json()
        logger.info(f"Successfully got {len(issue_comments)} issue comments")

        # Format review comments
        formatted_review_comments = []
        for comment in review_comments:
            formatted_review_comments.append(
                {
                    "id": comment["id"],
                    "type": "review_comment",
                    "author": comment["user"]["login"],
                    "body": comment["body"],
                    "file": comment.get("path", ""),
                    "line": comment.get("line", comment.get("original_line", 0)),
                    "created_at": comment["created_at"],
                    "url": comment["html_url"],
                }
            )

        # Format issue comments
        formatted_issue_comments = []
        for comment in issue_comments:
            formatted_issue_comments.append(
                {
                    "id": comment["id"],
                    "type": "issue_comment",
                    "author": comment["user"]["login"],
                    "body": comment["body"],
                    "created_at": comment["created_at"],
                    "url": comment["html_url"],
                }
            )

        logger.info(
            f"Formatted {len(formatted_review_comments)} review comments and {len(formatted_issue_comments)} issue comments"
        )

        result = {
            "pr_number": pr_number,
            "title": pr_data["title"],
            "repo": context.repo_name,
            "repo_config": repo_name,
            "review_comments": formatted_review_comments,
            "issue_comments": formatted_issue_comments,
            "total_comments": len(formatted_review_comments)
            + len(formatted_issue_comments),
        }

        logger.info(
            f"Successfully completed get_pr_comments for {repo_name} PR #{pr_number}"
        )
        return json.dumps(result)

    except Exception as e:
        logger.error(
            f"Failed to get PR comments from {repo_name}: {e!s}", exc_info=True
        )
        return json.dumps(
            {"error": f"Failed to get PR comments from {repo_name}: {e!s}"}
        )


async def execute_post_pr_reply(repo_name: str, comment_id: int, message: str) -> str:
    """Reply to a PR comment in the specified repository"""
    try:
        context = get_github_context(repo_name)
        if not context.repo:
            return json.dumps(
                {"error": f"GitHub repository not configured for {repo_name}"}
            )

        headers = {
            "Authorization": f"token {context.github_token}",
            "Accept": "application/vnd.github+json",
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
                return json.dumps(
                    {
                        "error": f"Could not find comment with ID {comment_id} in {repo_name}"
                    }
                )

        # Strategy 1: Try direct reply to review comment
        try:
            reply_url = f"https://api.github.com/repos/{context.repo_name}/pulls/comments/{comment_id}/replies"
            reply_data = {"body": message}
            reply_resp = requests.post(reply_url, headers=headers, json=reply_data)

            if reply_resp.status_code in [200, 201]:
                return json.dumps(
                    {
                        "success": True,
                        "method": "direct_reply",
                        "repo": context.repo_name,
                        "repo_config": repo_name,
                        "comment_id": reply_resp.json()["id"],
                        "url": reply_resp.json()["html_url"],
                    }
                )
        except Exception:
            pass

        # Strategy 2: Post as issue comment (fallback)
        if pr_number:
            try:
                issue_comment_url = f"https://api.github.com/repos/{context.repo_name}/issues/{pr_number}/comments"
                issue_comment_data = {
                    "body": f"@{original_comment['user']['login']} {message}"
                }
                issue_resp = requests.post(
                    issue_comment_url, headers=headers, json=issue_comment_data
                )

                if issue_resp.status_code in [200, 201]:
                    return json.dumps(
                        {
                            "success": True,
                            "method": "issue_comment_fallback",
                            "repo": context.repo_name,
                            "repo_config": repo_name,
                            "comment_id": issue_resp.json()["id"],
                            "url": issue_resp.json()["html_url"],
                        }
                    )
            except Exception as e:
                return json.dumps(
                    {
                        "error": f"All reply strategies failed for {repo_name}. Final error: {e!s}"
                    }
                )

        return json.dumps({"error": f"All reply strategies failed for {repo_name}"})

    except Exception as e:
        return json.dumps({"error": f"Failed to post PR reply in {repo_name}: {e!s}"})


async def execute_get_current_branch(repo_name: str) -> str:
    """Get current branch for the specified repository"""
    logger.error(
        f"TEST: execute_get_current_branch called for repo '{repo_name}'"
    )  # Using ERROR level to ensure it shows up
    logger.info(f"Getting current branch for repository '{repo_name}'")

    try:
        logger.debug("Getting GitHub context...")
        context = get_github_context(repo_name)

        logger.debug("Getting current branch from git...")
        branch = context.get_current_branch()

        logger.info(f"Current branch for {repo_name}: {branch}")
        return json.dumps(
            {"branch": branch, "repo": context.repo_name, "repo_config": repo_name}
        )
    except Exception as e:
        logger.error(
            f"Failed to get current branch for {repo_name}: {e!s}", exc_info=True
        )
        return json.dumps(
            {"error": f"Failed to get current branch for {repo_name}: {e!s}"}
        )


async def execute_get_current_commit(repo_name: str) -> str:
    """Get current commit for the specified repository"""
    try:
        context = get_github_context(repo_name)
        commit = context.get_current_commit()
        return json.dumps(
            {"commit": commit, "repo": context.repo_name, "repo_config": repo_name}
        )
    except Exception as e:
        return json.dumps(
            {"error": f"Failed to get current commit for {repo_name}: {e!s}"}
        )


# Build/Lint helper functions (simplified - removed legacy single-repo functions)
async def execute_read_swiftlint_logs(build_id: str = None) -> str:
    """Read SwiftLint violation logs from GitHub Actions artifacts"""
    logger.info(f"Reading SwiftLint logs (build_id: {build_id})")
    logger.warning("SwiftLint logs not implemented in multi-repo mode yet")
    return json.dumps(
        {"error": "SwiftLint logs not implemented in multi-repo mode yet"}
    )


async def execute_read_build_logs(build_id: str = None) -> str:
    """Read build logs and extract Swift compiler errors, warnings, and test failures"""
    logger.info(f"Reading build logs (build_id: {build_id})")
    logger.warning("Build logs not implemented in multi-repo mode yet")
    return json.dumps({"error": "Build logs not implemented in multi-repo mode yet"})


async def execute_get_build_status(
    repo_name: str, commit_sha: Optional[str] = None
) -> str:
    """Get build status for commit"""
    logger.info(
        f"Getting build status for repository '{repo_name}'"
        + (f" commit {commit_sha}" if commit_sha else " (current commit)")
    )

    try:
        if not repo_manager or repo_name not in repo_manager.repositories:
            logger.error(f"Repository {repo_name} not found in configuration")
            return json.dumps({"error": f"Repository {repo_name} not found"})

        logger.debug("Creating GitHub context...")
        repo_config = repo_manager.repositories[repo_name]
        context = GitHubAPIContext(repo_config)

        if not context.repo:
            logger.error("GitHub repository not configured")
            return json.dumps({"error": "GitHub repository not configured"})

        if not commit_sha:
            logger.debug("No commit SHA provided, getting current commit...")
            commit_sha = context.get_current_commit()
            logger.debug(f"Using commit SHA: {commit_sha}")

        logger.debug(f"Fetching commit details for {commit_sha}...")
        commit = context.repo.get_commit(commit_sha)

        # Initialize overall_state here; it will be updated based on check runs
        overall_state = (
            "pending"  # Default to pending if no checks or statuses are found
        )
        has_failures = False
        check_runs_data = []

        logger.debug("Attempting to get check runs...")
        try:
            # Prefer check runs for detailed build status
            # This is more robust against the 'Resource not accessible' error for combined_status
            check_runs = list(commit.get_check_runs())
            logger.info(f"Found {len(check_runs)} check runs")

            for run in check_runs:
                check_run_info = {
                    "name": run.name,
                    "status": run.status,
                    "conclusion": run.conclusion,
                    "url": run.html_url,
                }
                check_runs_data.append(check_run_info)
                logger.debug(
                    f"Check run: {run.name} - status: {run.status}, conclusion: {run.conclusion}"
                )

                if run.conclusion in ["failure", "timed_out", "cancelled", "stale"]:
                    has_failures = True
                    logger.debug(f"Found failure in check run: {run.name}")
                elif (
                    run.status == "completed"
                    and run.conclusion == "success"
                    and overall_state == "pending"
                ):
                    overall_state = "success"  # Set to success if at least one successful completed run and no failures yet
                    logger.debug(
                        "Setting overall state to success based on completed run"
                    )
                elif (
                    run.status != "completed"
                ):  # If any check is still running, overall is in_progress
                    overall_state = "in_progress"
                    logger.debug("Found in-progress check run")

        except Exception as e:
            # Log this if needed, but allow to proceed to combined_status fallback or default
            logger.warning(
                f"Failed to get check runs, trying combined status fallback: {e}"
            )

        # Fallback to get_combined_status if check_runs_data is empty or if check_runs failed
        if not check_runs_data:
            logger.debug("No check runs found, trying combined status fallback...")
            try:
                status = commit.get_combined_status()
                overall_state = status.state
                logger.debug(f"Combined status state: {status.state}")

                has_failures = any(
                    s.state in ["failure", "error", "pending"]
                    and s.context != "expected"  # Refine logic if needed
                    for s in status.statuses
                )

                # Populate check_runs_data from statuses if check_runs failed
                logger.info(f"Found {len(status.statuses)} status checks")
                for s in status.statuses:
                    check_runs_data.append(
                        {
                            "name": s.context,
                            "status": s.state,
                            "conclusion": s.state,  # Map status state to conclusion for consistency
                            "url": s.target_url,
                        }
                    )
                    logger.debug(f"Status check: {s.context} - state: {s.state}")

            except Exception as e:
                logger.error(
                    f"Failed to get combined status even as fallback: {e}",
                    exc_info=True,
                )
                overall_state = "error"  # Indicate an error if both fail
                has_failures = True

        # Ensure overall_state reflects failures if any
        if has_failures:
            overall_state = "failure"
            logger.info("Overall state set to failure due to detected failures")

        logger.info(
            f"Build status summary: overall_state={overall_state}, has_failures={has_failures}, checks={len(check_runs_data)}"
        )

        result = {
            "commit_sha": commit_sha,
            "overall_state": overall_state,
            "check_runs": check_runs_data,
            "has_failures": has_failures,
        }

        return json.dumps(result)

    except Exception as e:
        logger.error(f"Failed to get build status: {e!s}", exc_info=True)
        return json.dumps({"error": f"Failed to get build status: {e!s}"})
