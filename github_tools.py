#!/usr/bin/env python3

"""
GitHub Tools for MCP Server
Contains all GitHub-related tool implementations.
"""

import io
import json
import logging
import os
import re
import subprocess
import zipfile
from collections.abc import Awaitable, Callable
from typing import Any, cast

import requests
from github import Github
from github.Repository import Repository

from repository_manager import (
    AbstractRepositoryManager,
    RepositoryConfig,
    RepositoryManager,
)

logger = logging.getLogger(__name__)

# Global repository manager (set by worker)
repo_manager: RepositoryManager | None = None


def get_tools(repo_name: str, repo_path: str) -> list[dict]:
    """Get GitHub tool definitions for MCP registration

    Args:
        repo_name: Repository name for display purposes
        repo_path: Repository path for tool descriptions

    Returns:
        List of tool definitions in MCP format
    """
    return [
        {
            "name": "git_get_current_commit",
            "description": f"Get current local commit SHA, message, author and timestamp from the Git repository at {repo_path}. Shows the HEAD commit details including hash, commit message, author, and date. Local Git operation, no network required.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
        {
            "name": "git_get_current_branch",
            "description": f"Get the currently checked out Git branch name from the local repository at {repo_path}. Returns the active branch that would be used for new commits. Local Git operation, no network required.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
        {
            "name": "github_find_pr_for_branch",
            "description": f"Find and retrieve the GitHub Pull Request associated with a specific branch in {repo_name}. Searches GitHub API for open PRs that have the specified branch as their head branch. Returns PR details including number, title, URL, status, and merge information. Useful for connecting local branches to GitHub PRs. If branch_name is not provided, uses the currently checked out local branch.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "branch_name": {
                        "type": "string",
                        "description": "Git branch name to search for (e.g., 'feature/new-login', 'main', 'develop'). Optional - if not provided, uses the currently checked out local branch.",
                    }
                },
                "required": [],
            },
        },
        {
            "name": "github_get_pr_comments",
            "description": f"Retrieve all review comments, issue comments, and discussion threads from a GitHub Pull Request in {repo_name}. Uses GitHub API to fetch comments with author, timestamp, content, and reply status. Essential for finding unanswered code review comments that need responses, tracking discussion threads, and understanding PR feedback. If pr_number is not provided, automatically finds the PR for the current branch using github_find_pr_for_branch.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "pr_number": {
                        "type": "integer",
                        "description": "GitHub Pull Request number (e.g., 123 for PR #123). Optional - if not provided, will auto-detect PR for current branch.",
                    }
                },
                "required": [],
            },
        },
        {
            "name": "github_post_pr_reply",
            "description": f"Post a reply to a specific comment in a GitHub Pull Request for {repo_name}. Uses GitHub API to create a threaded response to review comments or general PR discussion comments. Supports GitHub Markdown formatting for rich text responses.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "comment_id": {
                        "type": "integer",
                        "description": "GitHub comment ID to reply to (found in comment URLs or from github_get_pr_comments)",
                    },
                    "message": {
                        "type": "string",
                        "description": "Reply message content (supports GitHub Markdown formatting)",
                    },
                },
                "required": ["comment_id", "message"],
            },
        },
        {
            "name": "github_check_ci_build_and_test_errors_not_local",
            "description": "🚨 CI STATUS & AUTO-FIX TOOL: For ANY mention of build/test status ('check build', 'CI OK?', 'build errors?') - use this tool to check GitHub CI status AND automatically start fixing any issues found. This tool both reports CI status AND initiates the fix workflow when errors exist. When users ask about build status, they expect you to fix problems, not just report them. After calling this tool: if errors found → immediately fix them → run local tests/lint per CLAUDE.md/AGENT.md → commit changes.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "build_id": {
                        "type": "string",
                        "description": "GitHub Actions run ID (optional - defaults to latest CI run)",
                    }
                },
                "required": [],
            },
        },
        {
            "name": "github_check_ci_lint_errors_not_local",
            "description": f"🚨 MANDATORY FOR LINT ISSUES: When user mentions 'lint errors', 'lint failures', 'fix lint errors', 'linting issues' - ALWAYS use this tool FIRST, NOT local commands. Gets live GitHub Actions lint errors for {repo_name} with exact error messages, file locations, and line numbers. NEVER run local lint when investigating CI lint failures - this tool provides the authoritative CI lint error data. Triggers: 'check lint', 'fix lint errors', 'linting is failing', 'lint has errors', 'CI lint issues'.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "build_id": {
                        "type": "string",
                        "description": "Specific GitHub Actions run ID (optional - if not provided, uses the latest run for the current commit)",
                    }
                },
                "required": [],
            },
        },
        {
            "name": "github_get_build_status",
            "description": f"📊 BUILD STATUS CHECKER: Use this tool to check if builds are passing/failing, investigate CI status, or when asked about 'build status'. Gets comprehensive CI/CD build status and check results for commits in {repo_name}. Shows overall build state (success/failure/pending/in_progress), individual check run details, and failure indicators. Essential for: checking if builds are ready, determining which checks failed, monitoring CI pipeline status before making changes. Use this FIRST when investigating build issues to understand what's failing.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "commit_sha": {
                        "type": "string",
                        "description": "Git commit SHA to check build status for (optional - if not provided, uses the current HEAD commit)",
                    }
                },
                "required": [],
            },
        },
    ]


class GitHubAPIContext:
    """Context for GitHub API operations with repository information"""

    repo_name: str
    repo: Repository
    github_token: str
    github: Github

    def __init__(self, repo_config: RepositoryConfig):
        logger.debug(
            f"GitHubAPIContext.__init__: Starting initialization for workspace: {repo_config.workspace}"
        )
        self.repo_config = repo_config

        # Check for GitHub token - required
        github_token = os.getenv("GITHUB_TOKEN")
        if not github_token:
            raise RuntimeError("GITHUB_TOKEN environment variable not set")

        self.github_token = github_token
        logger.debug(
            f"GitHubAPIContext.__init__: GITHUB_TOKEN found (length: {len(self.github_token)})"
        )

        self.github = Github(self.github_token)
        logger.debug("GitHubAPIContext.__init__: GitHub client created successfully")

        # Get repo name from git config - must succeed or initialization fails
        if not self.repo_config.workspace:
            raise RuntimeError("No repository workspace provided")

        logger.debug(
            f"GitHubAPIContext.__init__: Getting git remote from workspace: {self.repo_config.workspace}"
        )

        # Get repo name from git remote
        cmd = ["git", "config", "--get", "remote.origin.url"]
        logger.debug(
            f"GitHubAPIContext.__init__: Running command: {' '.join(cmd)} in {self.repo_config.workspace}"
        )

        try:
            output = (
                subprocess.check_output(cmd, cwd=self.repo_config.workspace)
                .decode()
                .strip()
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to get git remote URL: {e}") from e

        logger.debug(f"GitHubAPIContext.__init__: Git remote URL: {output}")

        if output.startswith("git@"):
            _, path = output.split(":", 1)
            logger.debug(f"GitHubAPIContext.__init__: Parsed SSH URL, path: {path}")
        elif output.startswith("https://"):
            path = output.split("github.com/", 1)[-1]
            logger.debug(f"GitHubAPIContext.__init__: Parsed HTTPS URL, path: {path}")
        else:
            raise ValueError(f"Unrecognized GitHub remote URL: {output}")

        self.repo_name = path.replace(".git", "")
        logger.info(f"GitHubAPIContext.__init__: Extracted repo name: {self.repo_name}")

        # Try to get the repository object
        logger.debug(
            f"GitHubAPIContext.__init__: Getting GitHub repo object for {self.repo_name}"
        )
        try:
            self.repo = self.github.get_repo(self.repo_name)
            logger.info(
                f"GitHubAPIContext.__init__: Successfully initialized GitHub context for {self.repo_name}"
            )
        except Exception as e:
            raise RuntimeError(
                f"Failed to access GitHub repository {self.repo_name}: {e}"
            ) from e

    def get_current_branch(self) -> str:
        """Get current branch name"""
        return (
            subprocess.check_output(
                ["git", "branch", "--show-current"], cwd=self.repo_config.workspace
            )
            .decode()
            .strip()
        )

    def get_current_commit(self) -> str:
        """Get current commit hash"""
        return (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=self.repo_config.workspace
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
        f"get_github_context: Found repo config for '{repo_name}', workspace: {repo_config.workspace}"
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
            "Authorization": f"token {(context.github_token or '')[:8]}..."
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


# Linter helper functions
async def get_artifact_id(
    repo_name: str, run_id: str, token: str, name: str = "lint-reports"
) -> str:
    """Get artifact ID for linter reports (supports both SwiftLint and Python linters)"""
    url = f"https://api.github.com/repos/{repo_name}/actions/runs/{run_id}/artifacts"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)
    logging.info(f"{response=}")
    response.raise_for_status()

    artifacts_data = response.json()
    artifacts = artifacts_data.get("artifacts", [])

    # Debug: Log all available artifacts in a readable format
    logger.info(f"=== ARTIFACTS DEBUG FOR RUN {run_id} ===")
    logger.info(f"Total artifacts found: {len(artifacts)}")
    if artifacts:
        logger.info("Available artifacts:")
        for i, artifact in enumerate(artifacts, 1):
            logger.info(f"  {i}. Name: '{artifact['name']}'")
            logger.info(f"     ID: {artifact['id']}")
            logger.info(f"     Size: {artifact.get('size_in_bytes', 'unknown')} bytes")
            logger.info(f"     Created: {artifact.get('created_at', 'unknown')}")
            logger.info(f"     Expired: {artifact.get('expired', 'unknown')}")
    else:
        logger.warning(f"No artifacts found in workflow run {run_id}")
    logger.info("=== END ARTIFACTS DEBUG ===")

    # Look for the requested artifact
    for artifact in artifacts:
        if artifact["name"] == name:
            logger.info(f"✓ Found matching artifact '{name}' with id: {artifact['id']}")
            return artifact["id"]

    # If not found, provide helpful error message
    available_names = [a["name"] for a in artifacts]
    error_msg = f"✗ No artifact named '{name}' found"
    if available_names:
        error_msg += f". Available artifacts: {', '.join(available_names)}"
    else:
        error_msg += ". No artifacts available in this workflow run."

    raise RuntimeError(error_msg)


async def read_lint_output_file(output_dir: str) -> str:
    """Read the lint output file from the extracted artifact directory"""
    import os

    logger.info(f"=== READING LINT OUTPUT FROM {output_dir} ===")

    # Look for common lint output file names
    possible_files = [
        "lint-output.txt",
        "linter-results.txt",
        "ruff-output.txt",
        "mypy-output.txt",
        "lint.txt",
    ]

    logger.info(f"Looking for lint output files: {possible_files}")

    for filename in possible_files:
        file_path = os.path.join(output_dir, filename)
        logger.info(f"Checking: {file_path}")
        if os.path.exists(file_path):
            logger.info(f"✓ Found {filename}!")
            try:
                file_size = os.path.getsize(file_path)
                logger.info(f"File size: {file_size} bytes")
                with open(file_path, encoding="utf-8") as f:
                    content = f.read()
                    logger.info(
                        f"✓ Successfully read {len(content)} characters from {filename}"
                    )
                    # Show preview of content
                    if content:
                        preview = (
                            content[:200] + "..." if len(content) > 200 else content
                        )
                        logger.info(f"Content preview: {preview!r}")
                    return content
            except Exception as e:
                logger.error(f"✗ Error reading {filename}: {e}")
        else:
            logger.info(f"✗ {filename} not found")

    # If no specific file found, try to read all .txt files and combine them
    logger.info("No specific lint output file found, searching for all .txt files...")
    txt_files = []
    txt_files_found = []

    if os.path.exists(output_dir):
        for file in os.listdir(output_dir):
            if file.endswith(".txt"):
                file_path = os.path.join(output_dir, file)
                logger.info(f"Found .txt file: {file}")
                if os.path.isfile(file_path):
                    try:
                        with open(file_path, encoding="utf-8") as f:
                            content = f.read().strip()
                            if content:
                                txt_files.append(content)
                                txt_files_found.append(file)
                                logger.info(
                                    f"✓ Added content from {file} ({len(content)} chars)"
                                )
                            else:
                                logger.info(f"✗ {file} is empty")
                    except Exception as e:
                        logger.error(f"✗ Error reading {file}: {e}")

    combined_content = "\n".join(txt_files) if txt_files else ""
    logger.info("=== COMBINED RESULT ===")
    logger.info(f"Files used: {txt_files_found}")
    logger.info(f"Total content length: {len(combined_content)} characters")
    if combined_content:
        preview = (
            combined_content[:200] + "..."
            if len(combined_content) > 200
            else combined_content
        )
        logger.info(f"Combined content preview: {preview!r}")
    logger.info("=== END LINT OUTPUT READING ===")

    return combined_content


async def download_and_extract_artifact(
    repo_name: str, artifact_id: str, token: str, extract_dir: str | None = None
) -> str:
    """Download and extract SwiftLint artifact"""
    url = (
        f"https://api.github.com/repos/{repo_name}/actions/artifacts/{artifact_id}/zip"
    )
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers)
    response.raise_for_status()

    if extract_dir is None:
        extract_dir = "/tmp/swiftlint_output"

    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        z.extractall(extract_dir)
    return extract_dir


async def parse_swiftlint_output(
    output_dir: str, expected_filename: str = "swiftlint_all.txt"
) -> list:
    """Parse SwiftLint output to extract only actual violations/errors"""
    violations = []

    # Look for the expected SwiftLint output file
    expected_file_path = os.path.join(output_dir, expected_filename)
    if not os.path.exists(expected_file_path):
        # Try common alternative names
        alternatives = [
            "swiftlint.txt",
            "violations.txt",
            "lint-results.txt",
            "output.txt",
        ]
        found_file = None
        for alt_name in alternatives:
            alt_path = os.path.join(output_dir, alt_name)
            if os.path.exists(alt_path):
                found_file = alt_path
                break

        if not found_file:
            raise FileNotFoundError(
                f"Expected SwiftLint output file '{expected_filename}' not found in {output_dir}. Available files: {os.listdir(output_dir)}"
            )

        expected_file_path = found_file

    # Pattern to match SwiftLint violation lines
    violation_pattern = re.compile(
        r"^/.+\.swift:\d+:\d+:\s+(error|warning):\s+.+\s+\(.+\)$"
    )

    with open(expected_file_path) as f:
        for line in f:
            line = line.strip()
            if line and violation_pattern.match(line):
                violations.append(
                    {
                        "raw_line": line,
                        "file": extract_file_from_violation(line),
                        "line_number": extract_line_number_from_violation(line),
                        "severity": extract_severity_from_violation(line),
                        "message": extract_message_from_violation(line),
                        "rule": extract_rule_from_violation(line),
                    }
                )

    return violations


def extract_file_from_violation(violation_line: str) -> str:
    """Extract file path from violation line"""
    match = re.match(r"^(/[^:]+\.swift):", violation_line)
    return match.group(1) if match else ""


def extract_line_number_from_violation(violation_line: str) -> int:
    """Extract line number from violation line"""
    match = re.match(r"^/[^:]+\.swift:(\d+):", violation_line)
    return int(match.group(1)) if match else 0


def extract_severity_from_violation(violation_line: str) -> str:
    """Extract severity (error/warning) from violation line"""
    match = re.search(r":\s+(error|warning):", violation_line)
    return match.group(1) if match else ""


def extract_message_from_violation(violation_line: str) -> str:
    """Extract violation message from violation line"""
    match = re.search(r":\s+(?:error|warning):\s+(.+)\s+\(.+\)$", violation_line)
    return match.group(1) if match else ""


def extract_rule_from_violation(violation_line: str) -> str:
    """Extract rule name from violation line"""
    match = re.search(r"\(([^)]+)\)$", violation_line)
    return match.group(1) if match else ""


async def find_workflow_run(
    context: GitHubAPIContext, commit_sha: str, token: str
) -> str:
    """Find the most recent workflow run ID for a commit"""
    url = f"https://api.github.com/repos/{context.repo_name}/actions/runs"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"head_sha": commit_sha}

    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()

    runs_data = response.json()
    runs = runs_data.get("workflow_runs", [])

    if not runs:
        raise RuntimeError(f"No workflow runs found for commit {commit_sha}")

    # Return the most recent run
    return str(runs[0]["id"])


# Build/Lint helper functions (simplified - removed legacy single-repo functions)
async def execute_github_check_ci_lint_errors_not_local(
    repo_name: str, language: str, build_id: str | None = None
) -> str:
    """Check CI lint errors and provide actionable fix instructions"""
    logger.info(
        f"🚀 STARTING execute_github_check_ci_lint_errors_not_local for repository '{repo_name}' (build_id: {build_id}, language: {language})"
    )

    try:
        logger.info(f"📋 Step 1: Getting GitHub context for repository '{repo_name}'")
        context = get_github_context(repo_name)
        if not context.repo or not context.repo_name:
            logger.error(f"❌ GitHub repository not configured for {repo_name}")
            return json.dumps(
                {"error": f"GitHub repository not configured for {repo_name}"}
            )
        logger.info(
            f"✅ Step 1 Complete: GitHub context obtained for '{context.repo_name}'"
        )

        logger.info("📋 Step 2: Checking GitHub token availability")
        token = context.github_token
        if not token:
            logger.error("❌ GITHUB_TOKEN is not set")
            return json.dumps({"error": "GITHUB_TOKEN is not set"})
        logger.info(
            f"✅ Step 2 Complete: GitHub token available (length: {len(token)})"
        )

        if build_id is None:
            logger.info("📋 Step 3: Finding workflow run for current commit")
            commit_sha = context.get_current_commit()
            logger.info(f"🔍 Current commit SHA: {commit_sha}")
            build_id = await find_workflow_run(context, commit_sha, token)
            logger.info(
                f"✅ Step 3 Complete: Using workflow run {build_id} for commit {commit_sha}"
            )
        else:
            logger.info(f"📋 Step 3: Using provided build_id: {build_id}")

        # At this point build_id is guaranteed to be a string
        assert build_id is not None
        logger.info(f"📋 Step 4: Confirmed build_id is available: {build_id}")

        # Get artifact name based on repository language
        logger.info("📋 Step 5: Determining repository language configuration")
        if not repo_manager or repo_name not in repo_manager.repositories:
            logger.error(f"❌ Repository {repo_name} not found in repo_manager")
            return json.dumps({"error": f"Repository {repo_name} not found"})

        repo_config = repo_manager.repositories[repo_name]
        logger.info(f"🔍 Repository config found for {repo_name}")

        # Use passed language parameter, fallback to repository config
        original_language = language
        if language is None:
            language = repo_config.language
            logger.info(
                f"🔄 Language fallback: using repo config language '{language}'"
            )
        else:
            logger.info(f"🎯 Language specified: using parameter language '{language}'")

        logger.info(
            f"✅ Step 5 Complete: Using language: {language} (from parameter: {original_language is not None})"
        )

        # Try generic "lint-reports" first, fall back to language-specific names for backward compatibility
        logger.info(
            f"📋 Step 6: Looking for linter artifacts for {language} repository..."
        )
        try:
            logger.info("🔍 Step 6a: Trying generic 'lint-reports' artifact...")
            artifact_id = await get_artifact_id(
                context.repo_name, build_id, token, "lint-reports"
            )
            logger.info("✅ Step 6a Complete: Found 'lint-reports' artifact")
        except RuntimeError as e:
            # Fall back to legacy artifact names for backward compatibility
            fallback_name = (
                "swiftlint-reports" if language == "swift" else "code-check-reports"
            )
            logger.warning(f"⚠️ Step 6a Failed: 'lint-reports' not found: {e}")
            logger.info(f"🔍 Step 6b: Trying fallback '{fallback_name}' artifact...")
            try:
                artifact_id = await get_artifact_id(
                    context.repo_name, build_id, token, fallback_name
                )
                logger.info(f"✅ Step 6b Complete: Found '{fallback_name}' artifact")
            except RuntimeError as e2:
                logger.error(
                    f"❌ Step 6b Failed: '{fallback_name}' also not found: {e2}"
                )
                raise e2

        logger.info(f"📋 Step 7: Downloading and extracting artifact {artifact_id}...")
        output_dir = await download_and_extract_artifact(
            context.repo_name, artifact_id, token
        )
        logger.info(f"✅ Step 7 Complete: Artifact extracted to: {output_dir}")

        # Debug: List contents of extracted directory
        import os

        if os.path.exists(output_dir):
            logger.info("=== EXTRACTED ARTIFACT CONTENTS ===")
            for root, _, files in os.walk(output_dir):
                level = root.replace(output_dir, "").count(os.sep)
                indent = " " * 2 * level
                logger.info(f"{indent}{os.path.basename(root)}/")
                subindent = " " * 2 * (level + 1)
                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        file_size = os.path.getsize(file_path)
                        logger.info(f"{subindent}{file} ({file_size} bytes)")
                    except OSError:
                        logger.info(f"{subindent}{file} (size unknown)")
            logger.info("=== END ARTIFACT CONTENTS ===")
        else:
            logger.error(f"✗ Output directory does not exist: {output_dir}")

        # Parse output based on language
        logger.info(f"📋 Step 8: Parsing linter output for {language} repository...")
        if language == "swift":
            logger.info("🔍 Step 8a: Using Swift/SwiftLint parser...")
            lint_results = await parse_swiftlint_output(output_dir)
            logger.info(
                f"✅ Step 8a Complete: SwiftLint parser found {len(lint_results)} violations"
            )
        else:
            logger.info("🔍 Step 8a: Using Python linter parser...")
            # For Python, read the raw output and parse with get_linter_errors
            logger.info("📄 Step 8b: Reading lint output file...")
            lint_output = await read_lint_output_file(output_dir)
            logger.info(
                f"✅ Step 8b Complete: Read {len(lint_output)} characters from lint output"
            )

            # Debug: Show first part of lint output
            if lint_output:
                preview = (
                    lint_output[:500] + "..." if len(lint_output) > 500 else lint_output
                )
                logger.info(f"📝 Lint output preview: {preview}")
            else:
                logger.warning("⚠️ Lint output is empty!")

            logger.info("🔧 Step 8c: Parsing lint errors...")
            parsed_result = await get_linter_errors(
                repo_name, lint_output, language, repo_manager
            )
            logger.info(
                f"✅ Step 8c Partial: Parser returned: {len(parsed_result)} characters"
            )

            logger.info("🔍 Step 8d: Parsing JSON result...")
            try:
                parsed_data = json.loads(parsed_result)
                logger.info("✅ Step 8d Complete: JSON parsed successfully")
                logger.info(f"📊 Parser result keys: {list(parsed_data.keys())}")
                lint_results = parsed_data.get("errors", [])
                logger.info(
                    f"✅ Extracted {len(lint_results)} errors from parser result"
                )

                # Debug: Show first few errors
                if lint_results:
                    logger.info("📋 First few errors:")
                    for i, error in enumerate(lint_results[:3]):
                        logger.info(f"  Error {i + 1}: {error}")
                else:
                    logger.warning("⚠️ No errors found in parser result")
            except json.JSONDecodeError as e:
                logger.error(f"❌ Step 8d Failed: Failed to parse JSON result: {e}")
                logger.error(f"Raw result: {parsed_result}")
                lint_results = []

        # Categorize violations by severity/type - limit to 10 per category to prevent huge responses
        logger.info(
            f"📋 Step 9: Categorizing {len(lint_results)} violations by severity..."
        )
        lint_errors = [
            v
            for v in lint_results
            if v.get("severity") == "error" or "error" in str(v).lower()
        ][:10]
        lint_warnings = [
            v
            for v in lint_results
            if v.get("severity") == "warning" or "warning" in str(v).lower()
        ][:10]
        logger.info(
            f"✅ Step 9 Complete: Found {len(lint_errors)} errors and {len(lint_warnings)} warnings"
        )

        # Build response based on language
        logger.info("📋 Step 10: Building response structure...")
        result = {
            "success": True,
            "language": language,
            "repo": context.repo_name,
            "repo_config": repo_name,
            "run_id": build_id,
            "artifact_id": artifact_id,
            "total_violations": len(lint_results),
            "next_steps": [
                "1. Fix all lint violations found above",
                "2. Run local autoformat and lint checks (see CLAUDE.md or AGENT.md for commands)",
                "3. Stage and commit all changes with descriptive commit message",
                "4. DO NOT push - leave for manual review",
            ],
            "workflow_instructions": "After fixing CI lint errors: (1) Fix all violations listed above, (2) Check CLAUDE.md or AGENT.md for local lint commands, (3) Run all autoformat + lint locally, (4) Stage and commit changes with summary message, (5) DO NOT push - manual review required",
        }

        if len(lint_results) > 0:
            result.update(
                {
                    "action_required": True,
                    "user_intent_fulfilled": "User asked about lint status - status is FAILED, now fixing automatically",
                    "immediate_actions": [
                        f"✅ Lint Status checked: FAILED ({len(lint_results)} violation(s) found)",
                        "🔧 NOW FIXING: all violations listed below",
                        "⚡ NEXT: Run local autoformat/lint per CLAUDE.md/AGENT.md",
                        "📝 THEN: Commit all fixes (no push)",
                    ],
                }
            )

        # Add language-specific categorized results
        if language == "swift":
            result.update(
                {
                    "lint_errors": lint_errors,
                    "lint_warnings": lint_warnings,
                    "total_errors": len(
                        [
                            v
                            for v in lint_results
                            if v.get("severity") == "error" or "error" in str(v).lower()
                        ]
                    ),
                    "total_warnings": len(
                        [
                            v
                            for v in lint_results
                            if v.get("severity") == "warning"
                            or "warning" in str(v).lower()
                        ]
                    ),
                }
            )
        elif language == "python":
            result.update(
                {
                    "lint_errors": lint_errors,
                    "lint_warnings": lint_warnings,
                    "total_errors": len(
                        [
                            v
                            for v in lint_results
                            if v.get("severity") == "error" or "error" in str(v).lower()
                        ]
                    ),
                    "total_warnings": len(
                        [
                            v
                            for v in lint_results
                            if v.get("severity") == "warning"
                            or "warning" in str(v).lower()
                        ]
                    ),
                }
            )
        else:
            # Default to same format for unknown languages
            result.update(
                {
                    "lint_errors": lint_errors,
                    "lint_warnings": lint_warnings,
                    "total_errors": len(
                        [
                            v
                            for v in lint_results
                            if v.get("severity") == "error" or "error" in str(v).lower()
                        ]
                    ),
                    "total_warnings": len(
                        [
                            v
                            for v in lint_results
                            if v.get("severity") == "warning"
                            or "warning" in str(v).lower()
                        ]
                    ),
                }
            )

        logger.info("✅ Step 10 Complete: Response structure built successfully")
        logger.info(
            "🎉 SUCCESSFULLY COMPLETED execute_github_check_ci_lint_errors_not_local"
        )
        return json.dumps(result)

    except Exception as e:
        logger.error(
            f"💥 FAILED execute_github_check_ci_lint_errors_not_local for {repo_name}: {e!s}",
            exc_info=True,
        )
        return json.dumps(
            {"error": f"Failed to read linter logs for {repo_name}: {e!s}"}
        )


# Python linter error parsing functions
def extract_file_from_ruff_error(error_line: str) -> str:
    """Extract file path from ruff error line"""
    import re

    # GitHub Actions format: ::error title=Ruff (UP045),file=/path/to/file.py,line=503,col=49,endLine=503,endColumn=62::message
    match = re.search(r"::error title=Ruff.*?file=([^,]+)", error_line)
    if match:
        return match.group(1)

    # Direct command format: Error: filename.py:line:col: RULE message
    match = re.match(r"^Error: ([^:]+):\d+:\d+:", error_line)
    return match.group(1) if match else ""


def extract_line_number_from_ruff_error(error_line: str) -> int:
    """Extract line number from ruff error line"""
    import re

    # GitHub Actions format
    match = re.search(r"::error title=Ruff.*?line=(\d+)", error_line)
    if match:
        return int(match.group(1))

    # Direct command format: Error: filename.py:line:col: RULE message
    match = re.match(r"^Error: [^:]+:(\d+):\d+:", error_line)
    return int(match.group(1)) if match else 0


def extract_column_from_ruff_error(error_line: str) -> int:
    """Extract column number from ruff error line"""
    import re

    # GitHub Actions format
    match = re.search(r"::error title=Ruff.*?col=(\d+)", error_line)
    if match:
        return int(match.group(1))

    # Direct command format: Error: filename.py:line:col: RULE message
    match = re.match(r"^Error: [^:]+:\d+:(\d+):", error_line)
    return int(match.group(1)) if match else 0


def extract_rule_from_ruff_error(error_line: str) -> str:
    """Extract rule code from ruff error line"""
    import re

    # GitHub Actions format
    match = re.search(r"::error title=Ruff \(([^)]+)\)", error_line)
    if match:
        return match.group(1)

    # Direct command format: Error: filename.py:line:col: RULE message
    match = re.match(r"^Error: [^:]+:\d+:\d+: ([A-Z]+\d+)", error_line)
    return match.group(1) if match else ""


def extract_message_from_ruff_error(error_line: str) -> str:
    """Extract message from ruff error line"""
    import re

    # GitHub Actions format: message is after the last ::
    match = re.search(r"::error title=Ruff.*?::(.+)$", error_line)
    if match:
        return match.group(1)

    # Direct command format: Error: filename.py:line:col: RULE message
    match = re.match(r"^Error: ([^:]+:\d+:\d+: [A-Z]+\d+ .+)$", error_line)
    return match.group(1) if match else ""


def extract_file_from_mypy_error(error_line: str) -> str:
    """Extract file path from mypy error line"""
    import re

    # Mypy format: file.py:line: error: message [error-code]
    # Must have numeric line number and contain "error:"
    match = re.match(r"^([^:]+\.py):(\d+): error:", error_line)
    return match.group(1) if match else ""


def extract_line_number_from_mypy_error(error_line: str) -> int:
    """Extract line number from mypy error line"""
    import re

    # Must contain "error:" to be valid
    match = re.match(r"^[^:]+\.py:(\d+): error:", error_line)
    return int(match.group(1)) if match else 0


def extract_message_from_mypy_error(error_line: str) -> str:
    """Extract message from mypy error line"""
    import re

    # Must be valid mypy error format with numeric line number
    if not re.match(r"^[^:]+\.py:\d+: error:", error_line):
        return ""
    match = re.search(r": error: (.+?)(?:\s+\[[^\]]+\])?$", error_line)
    return match.group(1) if match else ""


def extract_error_code_from_mypy_error(error_line: str) -> str:
    """Extract error code from mypy error line"""
    import re

    # Must be valid mypy error format with numeric line number
    if not re.match(r"^[^:]+\.py:\d+: error:", error_line):
        return ""
    match = re.search(r"\[([^\]]+)\]$", error_line)
    return match.group(1) if match else ""


async def get_linter_errors(
    repo_name: str,
    error_output: str,
    language: str,
    repo_manager: AbstractRepositoryManager,
) -> str:
    """Parse linter errors based on repository language configuration"""
    logger.info(f"=== PARSING LINTER ERRORS FOR '{repo_name}' ===")
    logger.info(f"Input length: {len(error_output)} characters")

    try:
        if repo_name not in repo_manager.repositories:
            logger.error(f"Repository {repo_name} not found in configuration")
            return json.dumps({"error": f"Repository {repo_name} not found"})

        repo_config = repo_manager.repositories[repo_name]
        # Use passed language parameter, fallback to repository config
        if language is None:
            language = repo_config.language
        logger.info(
            f"Repository language: {language} (from parameter: {language is not None})"
        )

        errors = []
        lines = error_output.strip().split("\n")
        logger.info(f"Split into {len(lines)} lines for processing")

        if language == "python":
            logger.info("Processing Python linter errors (ruff and mypy)...")
            # Parse Python linter errors (ruff and mypy)
            for i, line in enumerate(lines, 1):
                if not line.strip():
                    continue

                logger.debug(f"Line {i}: {line[:100]!r}")  # Show first 100 chars

                # Try to parse as ruff error first
                if "::error title=Ruff" in line:
                    logger.info(f"Line {i}: Found ruff error")
                    error_info = {
                        "type": "ruff",
                        "file": extract_file_from_ruff_error(line),
                        "line": extract_line_number_from_ruff_error(line),
                        "column": extract_column_from_ruff_error(line),
                        "rule": extract_rule_from_ruff_error(line),
                        "message": extract_message_from_ruff_error(line),
                        "severity": "error",
                    }
                    if error_info[
                        "file"
                    ]:  # Only add if we successfully parsed the file
                        errors.append(error_info)
                        logger.info(
                            f"✓ Added ruff error: {error_info['file']}:{error_info['line']} [{error_info['rule']}]"
                        )
                    else:
                        logger.warning(
                            f"✗ Failed to parse ruff error (no file): {line}"
                        )

                # Try to parse as mypy error
                elif ": error:" in line and line.endswith("]"):
                    logger.info(f"Line {i}: Found mypy error")
                    error_info = {
                        "type": "mypy",
                        "file": extract_file_from_mypy_error(line),
                        "line": extract_line_number_from_mypy_error(line),
                        "message": extract_message_from_mypy_error(line),
                        "error_code": extract_error_code_from_mypy_error(line),
                        "severity": "error",
                    }
                    if error_info[
                        "file"
                    ]:  # Only add if we successfully parsed the file
                        errors.append(error_info)
                        logger.info(
                            f"✓ Added mypy error: {error_info['file']}:{error_info['line']} [{error_info['error_code']}]"
                        )
                    else:
                        logger.warning(
                            f"✗ Failed to parse mypy error (no file): {line}"
                        )
                else:
                    logger.debug(f"Line {i}: Not a recognized error format")

        elif language == "swift":
            # Parse Swift linter errors (SwiftLint)
            for line in lines:
                if not line.strip():
                    continue

                # Parse SwiftLint violations
                if ".swift:" in line and ("error:" in line or "warning:" in line):
                    error_info = {
                        "type": "swiftlint",
                        "file": extract_file_from_violation(line),
                        "line": extract_line_number_from_violation(line),
                        "severity": extract_severity_from_violation(line),
                        "message": extract_message_from_violation(line),
                        "rule": extract_rule_from_violation(line),
                    }
                    if error_info[
                        "file"
                    ]:  # Only add if we successfully parsed the file
                        errors.append(error_info)

        else:
            logger.warning(f"Unsupported language: {language}")
            return json.dumps({"error": f"Unsupported language: {language}"})

        logger.info("=== PARSING COMPLETE ===")
        logger.info(f"Total errors found: {len(errors)}")
        if errors:
            logger.info("Error summary:")
            ruff_count = sum(1 for e in errors if e.get("type") == "ruff")
            mypy_count = sum(1 for e in errors if e.get("type") == "mypy")
            logger.info(f"  - Ruff errors: {ruff_count}")
            logger.info(f"  - Mypy errors: {mypy_count}")
        else:
            logger.warning("No errors found during parsing!")

        result = {
            "repository": repo_name,
            "language": language,
            "total_errors": len(errors),
            "errors": errors,
        }

        logger.info(f"✓ Returning result for {repo_name} with {len(errors)} errors")
        return json.dumps(result)

    except Exception as e:
        logger.error(f"Failed to parse linter errors: {e!s}", exc_info=True)
        return json.dumps({"error": f"Failed to parse linter errors: {e!s}"})


async def execute_get_build_status(
    repo_name: str, commit_sha: str | None = None
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


async def parse_build_output(
    output_dir: str,
    language: str,
    expected_filename: str | None = None,
) -> list:
    """Parse build output to extract compiler errors, warnings, and test failures"""
    issues = []

    # Set default filename based on language if not provided
    if expected_filename is None:
        if language == "python":
            expected_filename = "python_test_output.txt"
        else:
            expected_filename = "build_and_test_all.txt"

    logger.info(
        f"parse_build_output: language={language}, expected_filename={expected_filename}"
    )

    # Look for the expected build output file
    expected_file_path = os.path.join(output_dir, expected_filename)
    if not os.path.exists(expected_file_path):
        # Try common alternative names based on language
        if language == "python":
            alternatives = [
                "python_test_output.txt",
                "output.txt",
                "log.txt",
                "test_output.txt",
            ]
        else:
            alternatives = ["build.txt", "output.log", "output.txt", "log.txt"]
        found_file = None
        for alt_name in alternatives:
            alt_path = os.path.join(output_dir, alt_name)
            if os.path.exists(alt_path):
                found_file = alt_path
                break

        if not found_file:
            raise FileNotFoundError(
                f"Expected build output file '{expected_filename}' not found in {output_dir}. Available files: {os.listdir(output_dir)}"
            )

        expected_file_path = found_file

    # Patterns to match different types of build issues based on language
    if language == "swift":
        compiler_error_pattern = re.compile(r"^(/.*\.swift):(\d+):(\d+): error: (.+)$")
        compiler_warning_pattern = re.compile(
            r"^(/.*\.swift):(\d+):(\d+): warning: (.+)$"
        )
        test_failure_pattern = re.compile(r"^(/.*\.swift):(\d+): error: (.+) : (.+)$")
    elif language == "python":
        # Python warnings: /usr/lib/python3.12/unittest/case.py:690: DeprecationWarning: It is deprecated...
        python_warning_pattern = re.compile(r"^(/.*\.py):(\d+): (\w+Warning): (.+)$")
        # Python test failures: assert result is True -> E assert False is True
        python_test_failure_pattern = re.compile(r"^>?\s*(assert .+)$")
        # Python runtime errors: TypeError: is_server_healthy() got an unexpected keyword argument
        python_runtime_error_pattern = re.compile(r"^E\s+(\w+Error): (.+)$")
        # Python file/line pattern: tests/test_utilities.py:274: AssertionError
        python_file_line_pattern = re.compile(
            r"^([^:]+\.py):(\d+): (\w+(?:Error|Warning|Exception))$"
        )
    else:
        # Default to Swift patterns for unknown languages
        compiler_error_pattern = re.compile(r"^(/.*\.swift):(\d+):(\d+): error: (.+)$")
        compiler_warning_pattern = re.compile(
            r"^(/.*\.swift):(\d+):(\d+): warning: (.+)$"
        )
        test_failure_pattern = re.compile(r"^(/.*\.swift):(\d+): error: (.+) : (.+)$")

    with open(expected_file_path) as f:
        lines = f.readlines()

    for line_num, line in enumerate(lines, 1):
        line = line.strip()

        if language == "swift":
            # Check for compiler errors
            if match := compiler_error_pattern.match(line):
                file_path, line_no, col_no, message = match.groups()
                issues.append(
                    {
                        "type": "compiler_error",
                        "raw_line": line,
                        "file": file_path,
                        "line_number": int(line_no),
                        "column": int(col_no),
                        "message": message,
                        "severity": "error",
                    }
                )

            # Check for compiler warnings
            elif match := compiler_warning_pattern.match(line):
                file_path, line_no, col_no, message = match.groups()
                issues.append(
                    {
                        "type": "compiler_warning",
                        "raw_line": line,
                        "file": file_path,
                        "line_number": int(line_no),
                        "column": int(col_no),
                        "message": message,
                        "severity": "warning",
                    }
                )

            # Check for test failures
            elif match := test_failure_pattern.match(line):
                file_path, line_no, test_info, failure_message = match.groups()
                issues.append(
                    {
                        "type": "test_failure",
                        "raw_line": line,
                        "file": file_path,
                        "line_number": int(line_no),
                        "test_info": test_info.strip(),
                        "message": failure_message.strip(),
                        "severity": "error",
                    }
                )

        elif language == "python":
            # Check for Python warnings
            if match := python_warning_pattern.match(line):
                file_path, line_no, warning_type, message = match.groups()
                issues.append(
                    {
                        "type": "python_warning",
                        "raw_line": line,
                        "file": file_path,
                        "line_number": int(line_no),
                        "warning_type": warning_type,
                        "message": message,
                        "severity": "warning",
                    }
                )

            # Check for Python runtime errors
            elif match := python_runtime_error_pattern.match(line):
                error_type, message = match.groups()

                # Look ahead for file/line info
                file_path = None
                line_number = None
                for i in range(line_num, min(line_num + 5, len(lines))):
                    next_line = lines[i].strip()
                    if file_match := python_file_line_pattern.match(next_line):
                        file_path, line_number, _ = file_match.groups()
                        break

                issue_data = {
                    "type": "python_runtime_error",
                    "raw_line": line,
                    "error_type": error_type,
                    "message": message,
                    "severity": "error",
                }

                if file_path and line_number:
                    issue_data.update(
                        {
                            "file": file_path,
                            "line_number": int(line_number),
                        }
                    )

                issues.append(issue_data)

            # Check for Python test failures (assertion lines)
            elif match := python_test_failure_pattern.match(line):
                assertion = match.group(1)
                # Look ahead for the error line
                error_line = ""
                if line_num < len(lines):
                    next_line = lines[line_num].strip()
                    if next_line.startswith("E "):
                        error_line = next_line[2:]  # Remove "E " prefix

                # Look ahead for file/line info
                file_path = None
                line_number = None
                for i in range(line_num, min(line_num + 5, len(lines))):
                    next_line = lines[i].strip()
                    if file_match := python_file_line_pattern.match(next_line):
                        file_path, line_number, _ = file_match.groups()
                        break

                issue_data = {
                    "type": "python_test_failure",
                    "raw_line": line,
                    "assertion": assertion,
                    "error": error_line,
                    "severity": "error",
                }

                if file_path and line_number:
                    issue_data.update(
                        {
                            "file": file_path,
                            "line_number": int(line_number),
                        }
                    )

                issues.append(issue_data)

    return issues


async def execute_github_check_ci_build_and_test_errors_not_local(
    repo_name: str, language: str, build_id: str | None = None
) -> str:
    """Read build logs and extract compiler errors, warnings, and test failures for Swift and Python"""
    logger.info(
        f"Reading build logs for repository '{repo_name}' (build_id: {build_id}, language: {language})"
    )

    try:
        context = get_github_context(repo_name)
        if not context.repo:
            return json.dumps(
                {"error": f"GitHub repository not configured for {repo_name}"}
            )

        # Use passed language parameter, fallback to repository config
        repo_config = None
        if language is None:
            if not repo_manager or repo_name not in repo_manager.repositories:
                logger.error(f"Repository {repo_name} not found in configuration")
                return json.dumps({"error": f"Repository {repo_name} not found"})
            repo_config = repo_manager.repositories[repo_name]
            language = repo_config.language

        logger.info(f"Using language: {language}")
        logger.info(
            f"Repository config language: {repo_config.language if repo_config else 'N/A'}"
        )

        # TEMPORARY DEBUG: Force Python language for github-agent
        if repo_name == "github-agent":
            logger.info(
                f"TEMP DEBUG: Forcing language to 'python' for github-agent (was: {language})"
            )
            language = "python"

        token = context.github_token
        if not token:
            return json.dumps({"error": "GITHUB_TOKEN is not set"})

        if build_id is None:
            commit_sha = context.get_current_commit()
            build_id = await find_workflow_run(context, commit_sha, token)
            logger.info(f"Using workflow run {build_id} for commit {commit_sha}")

        if build_id is None:
            return json.dumps({"error": "Could not determine build ID"})

        # At this point, build_id is guaranteed to be not None
        run_id = cast(str, build_id)
        artifact_id = await get_artifact_id(
            context.repo_name, run_id, token, name="build-output"
        )
        output_dir = await download_and_extract_artifact(
            context.repo_name, artifact_id, token, "/tmp/build_output"
        )
        build_issues = await parse_build_output(output_dir, language=language)

        # Filter and limit results to prevent huge responses based on language
        if language == "swift":
            compiler_errors = [
                issue for issue in build_issues if issue["type"] == "compiler_error"
            ][:10]
            compiler_warnings = [
                issue for issue in build_issues if issue["type"] == "compiler_warning"
            ][:10]
            test_failures = [
                issue for issue in build_issues if issue["type"] == "test_failure"
            ][:10]
        elif language == "python":
            python_warnings = [
                issue for issue in build_issues if issue["type"] == "python_warning"
            ][:10]
            python_runtime_errors = [
                issue
                for issue in build_issues
                if issue["type"] == "python_runtime_error"
            ][:10]
            python_test_failures = [
                issue
                for issue in build_issues
                if issue["type"] == "python_test_failure"
            ][:10]
        else:
            # Default to Swift categorization
            compiler_errors = [
                issue for issue in build_issues if issue["type"] == "compiler_error"
            ][:10]
            compiler_warnings = [
                issue for issue in build_issues if issue["type"] == "compiler_warning"
            ][:10]
            test_failures = [
                issue for issue in build_issues if issue["type"] == "test_failure"
            ][:10]

        # Build response based on language
        result = {
            "success": True,
            "language": language,
            "repo": context.repo_name,
            "repo_config": repo_name,
            "run_id": build_id,
            "artifact_id": artifact_id,
            "total_issues": len(build_issues),
            "next_steps": [
                "1. Fix all errors and warnings found above",
                "2. Run local tests, autoformat, and lint (see CLAUDE.md or AGENT.md for commands)",
                "3. Stage and commit all changes with descriptive commit message",
                "4. DO NOT push - leave for manual review",
            ],
            "workflow_instructions": "After fixing CI errors: (1) Fix all issues listed above, (2) Check CLAUDE.md or AGENT.md for local test/lint commands, (3) Run all tests + autoformat + lint locally, (4) Stage and commit changes with summary message, (5) DO NOT push - manual review required",
        }
        if len(build_issues) > 0:
            result.update(
                {
                    "action_required": True,
                    "user_intent_fulfilled": "User asked about CI status - status is FAILED, now fixing automatically",
                    "immediate_actions": [
                        f"✅ CI Status checked: FAILED ({len(build_issues)} error(s) found)",
                        "🔧 NOW FIXING: all errors listed below",
                        "⚡ NEXT: Run local tests/lint per CLAUDE.md/AGENT.md",
                        "📝 THEN: Commit all fixes (no push)",
                    ],
                }
            )

        if language == "swift":
            result.update(
                {
                    "compiler_errors": compiler_errors,
                    "compiler_warnings": compiler_warnings,
                    "test_failures": test_failures,
                    "total_errors": len(
                        [i for i in build_issues if i["type"] == "compiler_error"]
                    ),
                    "total_warnings": len(
                        [i for i in build_issues if i["type"] == "compiler_warning"]
                    ),
                    "total_test_failures": len(
                        [i for i in build_issues if i["type"] == "test_failure"]
                    ),
                }
            )
        elif language == "python":
            result.update(
                {
                    "python_warnings": python_warnings,
                    "python_runtime_errors": python_runtime_errors,
                    "python_test_failures": python_test_failures,
                    "total_warnings": len(
                        [i for i in build_issues if i["type"] == "python_warning"]
                    ),
                    "total_runtime_errors": len(
                        [i for i in build_issues if i["type"] == "python_runtime_error"]
                    ),
                    "total_test_failures": len(
                        [i for i in build_issues if i["type"] == "python_test_failure"]
                    ),
                }
            )
        else:
            # Default to Swift format for unknown languages
            result.update(
                {
                    "compiler_errors": compiler_errors,
                    "compiler_warnings": compiler_warnings,
                    "test_failures": test_failures,
                    "total_errors": len(
                        [i for i in build_issues if i["type"] == "compiler_error"]
                    ),
                    "total_warnings": len(
                        [i for i in build_issues if i["type"] == "compiler_warning"]
                    ),
                    "total_test_failures": len(
                        [i for i in build_issues if i["type"] == "test_failure"]
                    ),
                }
            )

        return json.dumps(result)

    except Exception as e:
        logger.error(f"Failed to read build logs for {repo_name}: {e!s}", exc_info=True)
        return json.dumps(
            {"error": f"Failed to read build logs for {repo_name}: {e!s}"}
        )


# Tool execution mapping
TOOL_HANDLERS: dict[str, Callable[..., Awaitable[str]]] = {
    "git_get_current_branch": execute_get_current_branch,
    "git_get_current_commit": execute_get_current_commit,
    "github_find_pr_for_branch": execute_find_pr_for_branch,
    "github_get_pr_comments": execute_get_pr_comments,
    "github_post_pr_reply": execute_post_pr_reply,
    "github_get_build_status": execute_get_build_status,
    "github_check_ci_lint_errors_not_local": execute_github_check_ci_lint_errors_not_local,
    "github_check_ci_build_and_test_errors_not_local": execute_github_check_ci_build_and_test_errors_not_local,
}


async def execute_tool(tool_name: str, **kwargs) -> str:
    """Execute a GitHub tool by name

    Args:
        tool_name: Name of the tool to execute
        **kwargs: Tool-specific arguments

    Returns:
        Tool execution result as JSON string
    """
    if tool_name not in TOOL_HANDLERS:
        return json.dumps(
            {
                "error": f"Unknown tool: {tool_name}",
                "available_tools": list(TOOL_HANDLERS.keys()),
            }
        )

    handler = TOOL_HANDLERS[tool_name]
    try:
        return await handler(**kwargs)
    except Exception as e:
        logger.exception(f"Error executing tool {tool_name}")
        return json.dumps({"error": f"Tool execution failed: {e!s}", "tool": tool_name})


def validate(logger: logging.Logger, repositories: dict[str, Any]) -> None:
    """
    Validate GitHub service prerequisites.

    Args:
        logger: Logger instance for debugging and monitoring
        repositories: Dictionary of repository configurations

    Raises:
        RuntimeError: If GitHub prerequisites are not met
    """
    logger.info("Validating GitHub service prerequisites...")

    # Validate GitHub token
    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        raise RuntimeError("GITHUB_TOKEN environment variable not set")

    if not github_token.strip():
        raise RuntimeError("GITHUB_TOKEN environment variable is empty")

    logger.debug(f"GitHub token found (length: {len(github_token)})")

    # Validate git is available
    try:
        result = subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError("Git command is not available or not working")
        logger.debug(f"Git available: {result.stdout.strip()}")
    except (
        subprocess.TimeoutExpired,
        subprocess.SubprocessError,
        FileNotFoundError,
    ) as e:
        raise RuntimeError(f"Git command not available: {e}") from e

    # Validate each repository is a valid git repository
    for repo_name, repo_config in repositories.items():
        workspace = getattr(repo_config, "workspace", None)
        if not workspace:
            continue

        if not os.path.exists(workspace):
            raise RuntimeError(
                f"Repository workspace does not exist: {workspace} (repo: {repo_name})"
            )

        git_dir = os.path.join(workspace, ".git")
        if not os.path.exists(git_dir):
            raise RuntimeError(
                f"Repository is not a git repository: {workspace} (repo: {repo_name})"
            )

        # Check if git is functional in this directory
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"Git command failed in repository {repo_name} at {workspace}: {result.stderr}"
                )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"Git command timed out in repository: {workspace} (repo: {repo_name})"
            ) from None
        except subprocess.SubprocessError as e:
            raise RuntimeError(
                f"Failed to run git command in repository {repo_name} at {workspace}: {e}"
            ) from e

    logger.info(
        f"✅ GitHub service validation passed for {len(repositories)} repositories"
    )
