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
from typing import cast

import requests
from github import Github
from github.Repository import Repository

from repository_manager import RepositoryConfig, RepositoryManager

logger = logging.getLogger(__name__)

# Global repository manager (set by worker)
repo_manager: RepositoryManager | None = None


class GitHubAPIContext:
    """Context for GitHub API operations with repository information"""

    repo_name: str
    repo: Repository
    github_token: str
    github: Github

    def __init__(self, repo_config: RepositoryConfig):
        logger.debug(
            f"GitHubAPIContext.__init__: Starting initialization for path: {repo_config.path}"
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
        logger.debug(
            "GitHubAPIContext.__init__: GitHub client created successfully"
        )

        # Get repo name from git config - must succeed or initialization fails
        if not self.repo_config.path:
            raise RuntimeError("No repository path provided")

        logger.debug(
            f"GitHubAPIContext.__init__: Getting git remote from path: {self.repo_config.path}"
        )

        # Get repo name from git remote
        cmd = ["git", "config", "--get", "remote.origin.url"]
        logger.debug(
            f"GitHubAPIContext.__init__: Running command: {' '.join(cmd)} in {self.repo_config.path}"
        )

        try:
            output = (
                subprocess.check_output(cmd, cwd=self.repo_config.path).decode().strip()
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to get git remote URL: {e}") from e

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
        try:
            self.repo = self.github.get_repo(self.repo_name)
            logger.info(
                f"GitHubAPIContext.__init__: Successfully initialized GitHub context for {self.repo_name}"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to access GitHub repository {self.repo_name}: {e}") from e

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
async def execute_read_swiftlint_logs(
    repo_name: str, build_id: str | None = None, language: str | None = None
) -> str:
    """Read linter violation logs from GitHub Actions artifacts (supports both SwiftLint and Python linters)"""
    logger.info(
        f"Reading linter logs for repository '{repo_name}' (build_id: {build_id})"
    )

    try:
        context = get_github_context(repo_name)
        if not context.repo or not context.repo_name:
            return json.dumps(
                {"error": f"GitHub repository not configured for {repo_name}"}
            )

        token = context.github_token
        if not token:
            return json.dumps({"error": "GITHUB_TOKEN is not set"})

        if build_id is None:
            commit_sha = context.get_current_commit()
            build_id = await find_workflow_run(context, commit_sha, token)
            logger.info(f"Using workflow run {build_id} for commit {commit_sha}")

        # At this point build_id is guaranteed to be a string
        assert build_id is not None

        # Get artifact name based on repository language
        if not repo_manager or repo_name not in repo_manager.repositories:
            return json.dumps({"error": f"Repository {repo_name} not found"})

        repo_config = repo_manager.repositories[repo_name]
        # Use passed language parameter, fallback to repository config
        if language is None:
            language = repo_config.language
        logger.info(
            f"Using language: {language} (from parameter: {language is not None})"
        )

        # Try generic "lint-reports" first, fall back to language-specific names for backward compatibility
        logger.info(f"Looking for linter artifacts for {language} repository...")
        try:
            logger.info("Step 1: Trying generic 'lint-reports' artifact...")
            artifact_id = await get_artifact_id(
                context.repo_name, build_id, token, "lint-reports"
            )
            logger.info("✓ Found 'lint-reports' artifact")
        except RuntimeError as e:
            # Fall back to legacy artifact names for backward compatibility
            fallback_name = (
                "swiftlint-reports" if language == "swift" else "code-check-reports"
            )
            logger.warning(f"✗ 'lint-reports' not found: {e}")
            logger.info(f"Step 2: Trying fallback '{fallback_name}' artifact...")
            try:
                artifact_id = await get_artifact_id(
                    context.repo_name, build_id, token, fallback_name
                )
                logger.info(f"✓ Found '{fallback_name}' artifact")
            except RuntimeError as e2:
                logger.error(f"✗ '{fallback_name}' also not found: {e2}")
                raise e2
        logger.info(f"Downloading and extracting artifact {artifact_id}...")
        output_dir = await download_and_extract_artifact(
            context.repo_name, artifact_id, token
        )
        logger.info(f"✓ Artifact extracted to: {output_dir}")

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
        logger.info(f"Parsing linter output for {language} repository...")
        if language == "swift":
            logger.info("Using Swift/SwiftLint parser...")
            lint_results = await parse_swiftlint_output(output_dir)
            logger.info(f"✓ SwiftLint parser found {len(lint_results)} violations")
        else:
            logger.info("Using Python linter parser...")
            # For Python, read the raw output and parse with get_linter_errors
            logger.info("Step 1: Reading lint output file...")
            lint_output = await read_lint_output_file(output_dir)
            logger.info(f"✓ Read {len(lint_output)} characters from lint output")

            # Debug: Show first part of lint output
            if lint_output:
                preview = (
                    lint_output[:500] + "..." if len(lint_output) > 500 else lint_output
                )
                logger.info(f"Lint output preview: {preview}")
            else:
                logger.warning("⚠️ Lint output is empty!")

            logger.info("Step 2: Parsing lint errors...")
            parsed_result = await get_linter_errors(repo_name, lint_output, language)
            logger.info(f"✓ Parser returned: {len(parsed_result)} characters")

            logger.info("Step 3: Parsing JSON result...")
            try:
                parsed_data = json.loads(parsed_result)
                logger.info("✓ JSON parsed successfully")
                logger.info(f"Parser result keys: {list(parsed_data.keys())}")
                lint_results = parsed_data.get("errors", [])
                logger.info(
                    f"✓ Extracted {len(lint_results)} errors from parser result"
                )

                # Debug: Show first few errors
                if lint_results:
                    logger.info("First few errors:")
                    for i, error in enumerate(lint_results[:3]):
                        logger.info(f"  Error {i+1}: {error}")
                else:
                    logger.warning("⚠️ No errors found in parser result")
            except json.JSONDecodeError as e:
                logger.error(f"✗ Failed to parse JSON result: {e}")
                logger.error(f"Raw result: {parsed_result}")
                lint_results = []

        return json.dumps(
            {
                "success": True,
                "repo": context.repo_name,
                "repo_config": repo_name,
                "language": language,
                "run_id": build_id,
                "artifact_id": artifact_id,
                "violations": lint_results,
                "total_violations": len(lint_results),
            }
        )

    except Exception as e:
        logger.error(
            f"Failed to read linter logs for {repo_name}: {e!s}", exc_info=True
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
    repo_name: str, error_output: str, language: str | None = None
) -> str:
    """Parse linter errors based on repository language configuration"""
    logger.info(f"=== PARSING LINTER ERRORS FOR '{repo_name}' ===")
    logger.info(f"Input length: {len(error_output)} characters")

    try:
        if not repo_manager or repo_name not in repo_manager.repositories:
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
    expected_filename: str | None = None,
    language: str = "swift",
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
                issues.append(
                    {
                        "type": "python_runtime_error",
                        "raw_line": line,
                        "error_type": error_type,
                        "message": message,
                        "severity": "error",
                    }
                )

            # Check for Python test failures (assertion lines)
            elif match := python_test_failure_pattern.match(line):
                assertion = match.group(1)
                # Look ahead for the error line
                error_line = ""
                if line_num < len(lines):
                    next_line = lines[line_num].strip()
                    if next_line.startswith("E "):
                        error_line = next_line[2:]  # Remove "E " prefix

                issues.append(
                    {
                        "type": "python_test_failure",
                        "raw_line": line,
                        "assertion": assertion,
                        "error": error_line,
                        "severity": "error",
                    }
                )

    return issues


async def execute_read_build_logs(
    repo_name: str, build_id: str | None = None, language: str | None = None
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
        build_issues = await parse_build_output(
            output_dir, language=language
        )

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
        }

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
