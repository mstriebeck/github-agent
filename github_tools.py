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
import re
import io
import zipfile
import unicodedata
from typing import Optional
from datetime import datetime
from github import Github
from repository_manager import RepositoryConfig, RepositoryManager
from sqlmodel import SQLModel, Field, create_engine, Session, select

logger = logging.getLogger(__name__)

# Global repository manager (set by worker)
repo_manager: Optional[RepositoryManager] = None

# SQLModel schema for PR reply queue
class PRReply(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    comment_id: int
    path: str
    line: Optional[int]
    body: str
    status: str = "queued"  # "queued", "sent", "failed"
    attempt_count: int = 0
    last_attempt_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.now)

# Database setup
DATABASE_URL = "sqlite:///pr_replies.db"
engine = create_engine(DATABASE_URL, echo=False)

def init_db():
    """Initialize the database and create tables"""
    SQLModel.metadata.create_all(engine)
    logger.info("Database initialized")

class GitHubAPIContext:
    """Context for GitHub API operations with repository information"""
    
    def __init__(self, repo_config: RepositoryConfig):
        logger.debug(f"Initializing GitHubAPIContext for repo config: {repo_config}")
        
        self.repo_config = repo_config
        self.github_token = os.getenv("GITHUB_TOKEN")
        logger.debug(f"GitHub token available: {'Yes' if self.github_token else 'No'}")
        logger.debug(f"Repo config path: {repo_config.path}")
        
        self.github = Github(self.github_token) if self.github_token else None
        logger.debug(f"GitHub client initialized: {'Yes' if self.github else 'No'}")
        
        # Get repo name from git config
        self.repo_name = None
        self.repo = None
        
        if not self.github:
            logger.error("GitHub client not initialized - missing GITHUB_TOKEN")
            return
            
        if not self.repo_config.path:
            logger.error("Repository path not provided in config")
            return
            
        try:
            logger.debug(f"Getting git remote URL from path: {self.repo_config.path}")
            # Get repo name from git remote
            output = subprocess.check_output(
                ["git", "config", "--get", "remote.origin.url"], 
                cwd=self.repo_config.path
            ).decode().strip()
            logger.debug(f"Git remote URL: {output}")
            
            if output.startswith("git@"):
                _, path = output.split(":", 1)
                logger.debug(f"Parsed SSH format path: {path}")
            elif output.startswith("https://"):
                path = output.split("github.com/", 1)[-1]
                logger.debug(f"Parsed HTTPS format path: {path}")
            else:
                raise ValueError(f"Unrecognized GitHub remote URL format: {output}")
            
            self.repo_name = path.replace(".git", "")
            logger.info(f"Parsed repository name: {self.repo_name}")
            
            logger.debug(f"Attempting to get GitHub repository: {self.repo_name}")
            self.repo = self.github.get_repo(self.repo_name)
            logger.info(f"Successfully initialized GitHub context for {self.repo_name}")
            logger.debug(f"Repository full name: {self.repo.full_name}")
            logger.debug(f"Repository private: {self.repo.private}")
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to get git remote URL: {e}")
            logger.error(f"Command output: {e.output if hasattr(e, 'output') else 'None'}")
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
    logger.error(f"TEST: execute_get_current_branch called for repo '{repo_name}'")  # Using ERROR level to ensure it shows up
    logger.info(f"Getting current branch for repository '{repo_name}'")
    
    try:
        logger.debug("Getting GitHub context...")
        context = get_github_context(repo_name)
        
        logger.debug("Getting current branch from git...")
        branch = context.get_current_branch()
        
        logger.info(f"Current branch for {repo_name}: {branch}")
        return json.dumps({
            "branch": branch,
            "repo": context.repo_name,
            "repo_config": repo_name
        })
    except Exception as e:
        logger.error(f"Failed to get current branch for {repo_name}: {str(e)}", exc_info=True)
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
    
    try:
        github_token = os.getenv("GITHUB_TOKEN")
        if not github_token:
            return json.dumps({"error": "GITHUB_TOKEN is not set"})

        # For multi-repo mode, we need to determine which repo this is for
        # For now, we'll try to get the first configured repo as a fallback
        if not repo_manager or not repo_manager.repositories:
            return json.dumps({"error": "No repositories configured"})
        
        # Use the first repo for now - in the future this could be parameterized
        repo_name = list(repo_manager.repositories.keys())[0]
        repo_config = repo_manager.repositories[repo_name]
        context = GitHubAPIContext(repo_config)
        
        if not context.repo:
            return json.dumps({"error": "GitHub repository not configured"})

        if build_id is None:
            commit_sha = context.get_current_commit()
            build_id = await find_workflow_run(context.repo, commit_sha, github_token)

        artifact_id = await get_artifact_id(context.repo, build_id, github_token, name="swiftlint-reports")
        output_dir = await download_and_extract_artifact(context.repo, artifact_id, github_token)
        lint_results = await parse_swiftlint_output(output_dir)
        
        return json.dumps({
            "success": True,
            "repo": context.repo_name,
            "run_id": build_id,
            "artifact_id": artifact_id,
            "violations": lint_results,
            "total_violations": len(lint_results)
        }, indent=2, default=str)
        
    except Exception as e:
        logger.error(f"Failed to read SwiftLint logs: {str(e)}")
        return json.dumps({"error": f"Failed to read SwiftLint logs: {str(e)}"})


async def execute_read_build_logs(build_id: str = None) -> str:
    """Read build logs and extract Swift compiler errors, warnings, and test failures"""
    logger.info(f"Reading build logs (build_id: {build_id})")
    
    try:
        github_token = os.getenv("GITHUB_TOKEN")
        if not github_token:
            return json.dumps({"error": "GITHUB_TOKEN is not set"})

        # For multi-repo mode, we need to determine which repo this is for
        if not repo_manager or not repo_manager.repositories:
            return json.dumps({"error": "No repositories configured"})
        
        # Use the first repo for now - in the future this could be parameterized
        repo_name = list(repo_manager.repositories.keys())[0]
        repo_config = repo_manager.repositories[repo_name]
        context = GitHubAPIContext(repo_config)
        
        if not context.repo:
            return json.dumps({"error": "GitHub repository not configured"})

        if build_id is None:
            commit_sha = context.get_current_commit()
            build_id = await find_workflow_run(context.repo, commit_sha, github_token)

        artifact_id = await get_artifact_id(context.repo, build_id, github_token, name="build-output")
        output_dir = await download_and_extract_artifact(context.repo, artifact_id, github_token, "/tmp/build_output")
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
            "repo": context.repo_name,
            "run_id": build_id,
            "artifact_id": artifact_id,
            "compiler_errors": compiler_errors,
            "compiler_warnings": compiler_warnings,
            "test_failures": test_failures,
            "total_issues": len(build_issues),
            "total_errors": len([i for i in build_issues if i["type"] == "compiler_error"]),
            "total_warnings": len([i for i in build_issues if i["type"] == "compiler_warning"]),
            "total_test_failures": len([i for i in build_issues if i["type"] == "test_failure"])
        }
        
        return json.dumps(result, indent=2, default=str)
        
    except Exception as e:
        logger.error(f"Failed to read build logs: {str(e)}")
        return json.dumps({"error": f"Failed to read build logs: {str(e)}"})

async def execute_get_build_status(repo_name: str, commit_sha: Optional[str] = None) -> str:
    """Get build status for commit"""
    logger.info(f"Getting build status for repository '{repo_name}'" + (f" commit {commit_sha}" if commit_sha else " (current commit)"))
    
    try:
        # Enhanced repo manager debugging
        logger.debug(f"Checking repo manager: exists={repo_manager is not None}")
        if repo_manager:
            logger.debug(f"Available repositories: {list(repo_manager.repositories.keys())}")
        
        if not repo_manager or repo_name not in repo_manager.repositories:
            logger.error(f"Repository {repo_name} not found in configuration")
            if repo_manager:
                logger.error(f"Available repos: {list(repo_manager.repositories.keys())}")
            return json.dumps({"error": f"Repository {repo_name} not found"})
        
        logger.debug("Creating GitHub context...")
        repo_config = repo_manager.repositories[repo_name]
        logger.debug(f"Repository config: name={repo_config.name}, path={repo_config.path}")
        
        context = GitHubAPIContext(repo_config)
        
        if not context.repo:
            logger.error("GitHub repository not configured after context creation")
            logger.error(f"Context details: repo_name={context.repo_name}, github_token_available={'Yes' if context.github_token else 'No'}")
            return json.dumps({"error": "GitHub repository not configured"})

        logger.info(f"Successfully connected to GitHub repo: {context.repo.full_name}")
        
        if not commit_sha:
            logger.debug("No commit SHA provided, getting current commit...")
            commit_sha = context.get_current_commit()
            logger.info(f"Using current commit SHA: {commit_sha}")

        logger.info(f"API Call: GET /repos/{context.repo.full_name}/commits/{commit_sha}")
        commit = context.repo.get_commit(commit_sha)
        logger.debug(f"Commit details: author={commit.author.login if commit.author else 'N/A'}, message='{commit.commit.message[:50]}...'")

        # Initialize overall_state here; it will be updated based on check runs
        overall_state = "pending"  # Default to pending if no checks or statuses are found
        has_failures = False
        check_runs_data = []

        logger.info("API Call: GET check runs for commit...")
        try:
            # Prefer check runs for detailed build status
            # This is more robust against the 'Resource not accessible' error for combined_status
            logger.info(f"API Call: GET /repos/{context.repo.full_name}/commits/{commit_sha}/check-runs")
            check_runs = list(commit.get_check_runs())
            logger.info(f"API Response: Found {len(check_runs)} check runs")
            
            for run in check_runs:
                check_run_info = {
                    "name": run.name,
                    "status": run.status,
                    "conclusion": run.conclusion,
                    "url": run.html_url
                }
                check_runs_data.append(check_run_info)
                logger.info(f"Check run: {run.name} - status: {run.status}, conclusion: {run.conclusion}, url: {run.html_url}")

                if run.conclusion in ["failure", "timed_out", "cancelled", "stale"]:
                    has_failures = True
                    logger.warning(f"Found failure in check run: {run.name} (conclusion: {run.conclusion})")
                elif run.status == "completed" and run.conclusion == "success" and overall_state == "pending":
                    overall_state = "success"  # Set to success if at least one successful completed run and no failures yet
                    logger.info("Setting overall state to success based on completed run")
                elif run.status != "completed":  # If any check is still running, overall is in_progress
                    overall_state = "in_progress"
                    logger.info(f"Found in-progress check run: {run.name} (status: {run.status})")

        except Exception as e:
            # Log this if needed, but allow to proceed to combined_status fallback or default
            logger.error(f"API Error: Failed to get check runs: {e}")
            logger.error(f"Exception type: {type(e).__name__}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")

        # Fallback to get_combined_status if check_runs_data is empty or if check_runs failed
        if not check_runs_data:
            logger.info("No check runs found, trying combined status fallback...")
            try:
                logger.info(f"API Call: GET /repos/{context.repo.full_name}/commits/{commit_sha}/status")
                status = commit.get_combined_status()
                overall_state = status.state
                logger.info(f"API Response: Combined status state: {status.state}")
                
                has_failures = any(
                    s.state in ["failure", "error", "pending"] and s.context != "expected"  # Refine logic if needed
                    for s in status.statuses
                )
                
                # Populate check_runs_data from statuses if check_runs failed
                logger.info(f"API Response: Found {len(status.statuses)} status checks")
                for s in status.statuses:
                    check_runs_data.append({
                        "name": s.context,
                        "status": s.state,
                        "conclusion": s.state,  # Map status state to conclusion for consistency
                        "url": s.target_url
                    })
                    logger.info(f"Status check: {s.context} - state: {s.state}, url: {s.target_url}")
                    
            except Exception as e:
                logger.error(f"API Error: Failed to get combined status even as fallback: {e}")
                logger.error(f"Exception type: {type(e).__name__}")
                import traceback
                logger.error(f"Full traceback: {traceback.format_exc()}")
                overall_state = "error"  # Indicate an error if both fail
                has_failures = True

        # Ensure overall_state reflects failures if any
        if has_failures:
            overall_state = "failure"
            logger.info("Overall state set to failure due to detected failures")

        logger.info(f"Build status summary: overall_state={overall_state}, has_failures={has_failures}, checks={len(check_runs_data)}")

        result = {
            "commit_sha": commit_sha,
            "overall_state": overall_state,
            "check_runs": check_runs_data,
            "has_failures": has_failures
        }
        
        return json.dumps(result)

    except Exception as e:
        logger.error(f"Failed to get build status: {str(e)}", exc_info=True)
        return json.dumps({"error": f"Failed to get build status: {str(e)}"})


# Helper functions for SwiftLint and Build logs
async def find_workflow_run(repo, commit_sha, token):
    """Find the latest workflow run for a commit"""
    logger.info(f"Finding workflow run for commit {commit_sha} in repo {repo.full_name}")
    
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    # Get all workflow runs for the repo and find the one matching the commit
    url = f"https://api.github.com/repos/{repo.full_name}/actions/runs"
    params = {"per_page": 100}
    
    logger.info(f"API Call: GET {url}")
    logger.debug(f"Parameters: {params}")
    
    try:
        response = requests.get(url, headers=headers, params=params)
        logger.info(f"API Response: {response.status_code}")
        response.raise_for_status()
        
        runs = response.json()["workflow_runs"]
        logger.info(f"Found {len(runs)} workflow runs in first page")
        
        for run in runs:
            logger.debug(f"Checking run {run['id']}: head_sha={run['head_sha']}")
            if run["head_sha"] == commit_sha:
                logger.info(f"Found matching workflow run {run['id']} for commit {commit_sha}")
                return run["id"]
        
        # If not found in first page, search more specifically
        logger.info("No matching run found in first page, searching by commit SHA...")
        params["head_sha"] = commit_sha
        logger.info(f"API Call: GET {url} (with head_sha filter)")
        logger.debug(f"Parameters: {params}")
        
        response = requests.get(url, headers=headers, params=params)
        logger.info(f"API Response: {response.status_code}")
        response.raise_for_status()
        
        runs = response.json()["workflow_runs"]
        logger.info(f"Found {len(runs)} workflow runs with head_sha filter")
        
        if runs:
            logger.info(f"Found workflow run {runs[0]['id']} for commit {commit_sha}")
            return runs[0]["id"]
            
    except requests.exceptions.RequestException as e:
        logger.error(f"API Error in find_workflow_run: {e}")
        logger.error(f"Response status: {e.response.status_code if e.response else 'N/A'}")
        logger.error(f"Response text: {e.response.text if e.response else 'N/A'}")
        raise
    
    raise Exception(f"No workflow run found for commit {commit_sha}")


async def get_artifact_id(repo, run_id, token, name="swiftlint-reports"):
    """Get artifact ID for a workflow run"""
    logger.info(f"Getting artifact ID for run {run_id}, artifact name: {name} in repo {repo.full_name}")
    
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    url = f"https://api.github.com/repos/{repo.full_name}/actions/runs/{run_id}/artifacts"
    
    try:
        logger.info(f"API Call: GET {url}")
        response = requests.get(url, headers=headers)
        logger.info(f"API Response: {response.status_code}")
        response.raise_for_status()
        
        artifacts = response.json()["artifacts"]
        logger.info(f"Found {len(artifacts)} artifacts for run {run_id}")
        
        for artifact in artifacts:
            logger.debug(f"Artifact: {artifact['name']} (ID: {artifact['id']})")
            if artifact["name"] == name:
                logger.info(f"Found matching artifact {artifact['id']} for {name}")
                return artifact["id"]
        
        # Log all available artifacts if target not found
        logger.warning(f"Artifact '{name}' not found. Available artifacts:")
        for artifact in artifacts:
            logger.warning(f"  - {artifact['name']} (ID: {artifact['id']})")
        
    except requests.exceptions.RequestException as e:
        logger.error(f"API Error in get_artifact_id: {e}")
        logger.error(f"Response status: {e.response.status_code if e.response else 'N/A'}")
        logger.error(f"Response text: {e.response.text if e.response else 'N/A'}")
        raise
    
    raise Exception(f"Artifact '{name}' not found for run {run_id}")


async def download_and_extract_artifact(repo, artifact_id, token, extract_dir=None):
    """Download and extract a GitHub Actions artifact"""
    import zipfile
    import tempfile
    
    if extract_dir is None:
        extract_dir = "/tmp/swiftlint_output"
    
    logger.debug(f"Downloading artifact {artifact_id} to {extract_dir}")
    
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    url = f"https://api.github.com/repos/{repo.full_name}/actions/artifacts/{artifact_id}/zip"
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    
    # Create extraction directory
    os.makedirs(extract_dir, exist_ok=True)
    
    # Extract the zip file
    with zipfile.ZipFile(io.BytesIO(response.content)) as zip_file:
        zip_file.extractall(extract_dir)
    
    logger.debug(f"Extracted artifact to {extract_dir}")
    return extract_dir


async def parse_swiftlint_output(output_dir, expected_filename="swiftlint_all.txt"):
    """Parse SwiftLint output to extract only actual violations/errors"""
    logger.debug(f"Parsing SwiftLint output from {output_dir}")
    
    # Look for the expected SwiftLint output file
    file_path = os.path.join(output_dir, expected_filename)
    
    if not os.path.exists(file_path):
        # Try some alternatives
        alternatives = ["swiftlint.txt", "violations.txt", "lint-results.txt", "output.txt"]
        for alt in alternatives:
            alt_path = os.path.join(output_dir, alt)
            if os.path.exists(alt_path):
                file_path = alt_path
                break
        else:
            raise FileNotFoundError(f"Expected SwiftLint output file '{expected_filename}' not found in {output_dir}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Pattern to match SwiftLint violation lines
    # Format: /path/to/file.swift:line:character: warning/error: message (rule_name)
    violation_pattern = r'^([^:]+):(\d+):(\d+):\s+(warning|error):\s+(.+?)\s+\(([^)]+)\)$'
    
    violations = []
    for line in content.split('\n'):
        line = line.strip()
        if not line:
            continue
            
        match = re.match(violation_pattern, line)
        if match:
            file_path, line_num, char_num, severity, message, rule = match.groups()
            violations.append({
                "file": file_path,
                "line": int(line_num),
                "character": int(char_num),
                "severity": severity,
                "message": message.strip(),
                "rule": rule
            })
    
    logger.info(f"Parsed {len(violations)} SwiftLint violations")
    return violations


async def parse_build_output(output_dir, expected_filename="build_and_test_all.txt"):
    """Parse build output to extract Swift compiler errors, warnings, and test failures"""
    logger.debug(f"Parsing build output from {output_dir}")
    
    file_path = os.path.join(output_dir, expected_filename)
    
    if not os.path.exists(file_path):
        # Try some alternatives
        alternatives = ["build.txt", "xcodebuild.txt", "output.txt"]
        for alt in alternatives:
            alt_path = os.path.join(output_dir, alt)
            if os.path.exists(alt_path):
                file_path = alt_path
                break
        else:
            raise FileNotFoundError(f"Expected build output file '{expected_filename}' not found in {output_dir}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    issues = []
    
    # Swift compiler error pattern
    # Format: /path/to/file.swift:line:character: error: message
    error_pattern = r'^([^:]+):(\d+):(\d+):\s+error:\s+(.+)$'
    
    # Swift compiler warning pattern  
    # Format: /path/to/file.swift:line:character: warning: message
    warning_pattern = r'^([^:]+):(\d+):(\d+):\s+warning:\s+(.+)$'
    
    # Test failure pattern (various formats)
    test_failure_patterns = [
        r'Test Case \'([^\']+)\' failed',
        r'❌\s+(.+?)\s+failed',
        r'FAIL:\s+(.+)',
        r'failed - (.+)'
    ]
    
    for line in content.split('\n'):
        line = line.strip()
        if not line:
            continue
        
        # Check for compiler errors
        match = re.match(error_pattern, line)
        if match:
            file_path, line_num, char_num, message = match.groups()
            issues.append({
                "type": "compiler_error",
                "file": file_path,
                "line": int(line_num),
                "character": int(char_num),
                "message": message.strip()
            })
            continue
        
        # Check for compiler warnings
        match = re.match(warning_pattern, line)
        if match:
            file_path, line_num, char_num, message = match.groups()
            issues.append({
                "type": "compiler_warning", 
                "file": file_path,
                "line": int(line_num),
                "character": int(char_num),
                "message": message.strip()
            })
            continue
        
        # Check for test failures
        for pattern in test_failure_patterns:
            match = re.search(pattern, line)
            if match:
                test_name = match.group(1)
                issues.append({
                    "type": "test_failure",
                    "test_name": test_name,
                    "message": line.strip()
                })
                break
    
    logger.info(f"Parsed {len(issues)} build issues")
    return issues


# Queue-related functions
async def execute_post_pr_reply_queue(repo_name: str, comment_id: int, path: str, line: Optional[int], body: str) -> str:
    """Queue a reply to a PR comment for later processing"""
    try:
        # Initialize database if not already done
        init_db()
        
        with Session(engine) as session:
            # Check if we already have a queued reply for this comment
            existing = session.exec(
                select(PRReply).where(PRReply.comment_id == comment_id)
            ).first()
            
            if existing:
                return json.dumps({
                    "success": False,
                    "message": f"Reply for comment {comment_id} already queued with status: {existing.status}"
                })
            
            # Create new queued reply
            reply = PRReply(
                comment_id=comment_id,
                path=path,
                line=line,
                body=body,
                status="queued"
            )
            
            session.add(reply)
            session.commit()
            session.refresh(reply)
            
            logger.info(f"Queued reply for comment {comment_id}")
            return json.dumps({
                "success": True,
                "reply_id": reply.id,
                "comment_id": comment_id,
                "status": "queued",
                "message": f"Reply queued successfully for comment {comment_id}"
            })
            
    except Exception as e:
        logger.error(f"Failed to queue reply: {str(e)}")
        return json.dumps({"error": f"Failed to queue reply: {str(e)}"})


async def execute_list_unhandled_comments(repo_name: str, pr_number: Optional[int] = None) -> str:
    """List PR comments that haven't been replied to yet"""
    try:
        # Initialize database if not already done
        init_db()
        
        # Get PR comments first
        comments_result = await execute_get_pr_comments(repo_name, pr_number)
        comments_data = json.loads(comments_result)
        
        if "error" in comments_data:
            return json.dumps(comments_data)
        
        # Get all queued/sent comment IDs from database
        with Session(engine) as session:
            handled_replies = session.exec(
                select(PRReply.comment_id).where(PRReply.status.in_(["queued", "sent"]))
            ).all()
            handled_comment_ids = set(handled_replies)
        
        # Filter out comments that already have replies queued or sent
        unhandled_review_comments = []
        unhandled_issue_comments = []
        
        for comment in comments_data.get("review_comments", []):
            if comment["id"] not in handled_comment_ids:
                unhandled_review_comments.append(comment)
        
        for comment in comments_data.get("issue_comments", []):
            if comment["id"] not in handled_comment_ids:
                unhandled_issue_comments.append(comment)
        
        result = {
            "pr_number": comments_data["pr_number"],
            "title": comments_data["title"],
            "unhandled_review_comments": unhandled_review_comments,
            "unhandled_issue_comments": unhandled_issue_comments,
            "total_unhandled": len(unhandled_review_comments) + len(unhandled_issue_comments),
            "total_handled": len(handled_comment_ids)
        }
        
        return json.dumps(result, indent=2, default=str)
        
    except Exception as e:
        logger.error(f"Failed to list unhandled comments: {str(e)}")
        return json.dumps({"error": f"Failed to list unhandled comments: {str(e)}"})


async def execute_ack_reply(repo_name: str, comment_id: int) -> str:
    """Mark a comment as handled/acknowledged"""
    try:
        # Initialize database if not already done
        init_db()
        
        with Session(engine) as session:
            reply = session.exec(
                select(PRReply).where(PRReply.comment_id == comment_id)
            ).first()
            
            if not reply:
                return json.dumps({
                    "success": False,
                    "message": f"No queued reply found for comment {comment_id}"
                })
            
            # Update status or just log the acknowledgment
            logger.info(f"Comment {comment_id} acknowledged (current status: {reply.status})")
            return json.dumps({
                "success": True,
                "comment_id": comment_id,
                "current_status": reply.status,
                "message": f"Comment {comment_id} acknowledged"
            })
            
    except Exception as e:
        logger.error(f"Failed to acknowledge comment: {str(e)}")
        return json.dumps({"error": f"Failed to acknowledge comment: {str(e)}"})


async def execute_process_comment_batch(repo_name: str, comments_data: str) -> str:
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
                result = await execute_post_pr_reply(repo_name, int(comment_id), response_data["body"])
                result_data = json.loads(result)
                if result_data.get("success"):
                    successful_posts += 1
                else:
                    failed_posts += 1
                results.append({
                    "comment_id": comment_id,
                    "result": result_data
                })
            except Exception as e:
                failed_posts += 1
                results.append({
                    "comment_id": comment_id,
                    "result": {"error": str(e)}
                })
        
        return json.dumps({
            "parsed_responses": len(responses),
            "successful_posts": successful_posts,
            "failed_posts": failed_posts,
            "results": results
        }, indent=2, default=str)
        
    except Exception as e:
        return json.dumps({"error": f"Failed to process comment batch: {str(e)}"})
