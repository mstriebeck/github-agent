#!/usr/bin/env python3

"""
PR Agent Unified Server
Complete PR management server with all functionality consolidated
"""

import asyncio
import os
import json
import re
import unicodedata
import zipfile
import io
import logging
import signal
import threading
import time
import subprocess
from datetime import datetime
from typing import Optional, Dict, Any, List
import uvicorn
import requests
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlmodel import SQLModel, Field, Session, select, create_engine
from github import Github
from git import Repo
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/log/pr_agent_server.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Database Models
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

# Core Context Class
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

# Worker Class
class PRReplyWorker:
    def __init__(self):
        self.github_token = os.getenv("GITHUB_TOKEN")
        self.poll_interval = int(os.getenv("POLL_INTERVAL", "30"))  # seconds
        
        if not self.github_token:
            raise ValueError("GITHUB_TOKEN environment variable is required")
        
        logger.info("Worker initialized for multi-repository support")
    
    def process_queue(self):
        """Process all queued replies"""
        with Session(engine) as session:
            # Get all queued replies
            queued_replies = session.exec(
                select(PRReply).where(PRReply.status == "queued")
            ).all()
            
            logger.info(f"Found {len(queued_replies)} queued replies to process")
            
            for reply in queued_replies:
                try:
                    success = self.post_reply_to_github(reply)
                    if success:
                        reply.status = "sent"
                        reply.sent_at = datetime.now()
                        logger.info(f"Successfully posted reply for comment {reply.comment_id}")
                    else:
                        reply.status = "failed"
                        reply.attempt_count += 1
                        reply.last_attempt_at = datetime.now()
                        logger.error(f"Failed to post reply for comment {reply.comment_id}")
                    
                    session.add(reply)
                    session.commit()
                    
                except Exception as e:
                    logger.error(f"Error processing reply {reply.id}: {str(e)}")
                    reply.status = "failed"
                    reply.attempt_count += 1
                    reply.last_attempt_at = datetime.now()
                    session.add(reply)
                    session.commit()
    
    def post_reply_to_github(self, reply: PRReply) -> bool:
        """Post a reply to GitHub using the REST API"""
        headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github+json"
        }
        
        try:
            # Parse the reply data
            reply_data = json.loads(reply.data)
            body = reply_data.get("body", "")
            
            # First, try to get the original comment to determine the PR
            comment_url = f"https://api.github.com/repos/{reply.repo_name}/pulls/comments/{reply.comment_id}"
            comment_resp = requests.get(comment_url, headers=headers)
            
            if comment_resp.status_code == 200:
                # It's a review comment
                original_comment = comment_resp.json()
                pr_url = original_comment.get("pull_request_url", "")
                pr_number = pr_url.split("/")[-1] if pr_url else None
                
                # Try direct reply to review comment first
                reply_url = f"https://api.github.com/repos/{reply.repo_name}/pulls/comments/{reply.comment_id}/replies"
                post_data = {"body": body}
                reply_resp = requests.post(reply_url, headers=headers, json=post_data)
                
                if reply_resp.status_code in [200, 201]:
                    return True
                
                # Fallback to issue comment
                if pr_number:
                    issue_comment_url = f"https://api.github.com/repos/{reply.repo_name}/issues/{pr_number}/comments"
                    issue_comment_data = {"body": body}
                    issue_resp = requests.post(issue_comment_url, headers=headers, json=issue_comment_data)
                    return issue_resp.status_code in [200, 201]
            
            else:
                # Try as issue comment
                comment_url = f"https://api.github.com/repos/{reply.repo_name}/issues/comments/{reply.comment_id}"
                comment_resp = requests.get(comment_url, headers=headers)
                
                if comment_resp.status_code == 200:
                    original_comment = comment_resp.json()
                    issue_url = original_comment.get("issue_url", "")
                    pr_number = issue_url.split("/")[-1] if issue_url else None
                    
                    if pr_number:
                        issue_comment_url = f"https://api.github.com/repos/{reply.repo_name}/issues/{pr_number}/comments"
                        issue_comment_data = {"body": body}
                        issue_resp = requests.post(issue_comment_url, headers=headers, json=issue_comment_data)
                        return issue_resp.status_code in [200, 201]
            
            logger.error(f"Could not find comment {reply.comment_id} or determine how to reply")
            return False
            
        except Exception as e:
            logger.error(f"Exception posting reply to GitHub: {str(e)}")
            return False

# Unified Worker Service for HTTP Server
class UnifiedWorkerService:
    def __init__(self):
        self.worker = PRReplyWorker()
        self.running = False
        self.thread = None
        self.start_time = None
        self.processed_count = 0
        self.failed_count = 0
        self.last_run = None
        self.shutdown_event = threading.Event()
        
    def start_worker(self):
        """Start the worker thread"""
        if self.running:
            return False
            
        self.running = True
        self.start_time = datetime.now()
        self.shutdown_event.clear()
        self.thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.thread.start()
        logger.info("Background worker started")
        return True
        
    def stop_worker(self):
        """Stop the worker thread"""
        if not self.running:
            return False
            
        self.running = False
        self.shutdown_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=10)
        logger.info("Background worker stopped")
        return True
        
    def restart_worker(self):
        """Restart the worker thread"""
        self.stop_worker()
        time.sleep(1)
        return self.start_worker()
        
    def process_now(self):
        """Process queue immediately (one-time)"""
        try:
            before_count = self._get_queue_size()
            self.worker.process_queue()
            after_count = self._get_queue_size()
            processed = before_count - after_count
            self.processed_count += processed
            self.last_run = datetime.now().isoformat()
            return {"processed": processed, "remaining": after_count}
        except Exception as e:
            logger.error(f"Manual processing failed: {str(e)}")
            self.failed_count += 1
            raise
            
    def get_status(self):
        """Get current worker status"""
        uptime = int((datetime.now() - self.start_time).total_seconds()) if self.start_time else 0
        queue_size = self._get_queue_size()
        
        return {
            "status": "running" if self.running else "stopped",
            "uptime_seconds": uptime,
            "processed_replies": self.processed_count,
            "failed_replies": self.failed_count,
            "queue_size": queue_size,
            "last_run": self.last_run
        }
        
    def _worker_loop(self):
        """Main worker loop"""
        logger.info("Worker loop started")
        
        while self.running and not self.shutdown_event.is_set():
            try:
                before_count = self._get_queue_size()
                if before_count > 0:
                    logger.debug(f"Processing {before_count} queued replies")
                    self.worker.process_queue()
                    after_count = self._get_queue_size()
                    processed = before_count - after_count
                    self.processed_count += processed
                    self.last_run = datetime.now().isoformat()
                    
                    if processed > 0:
                        logger.info(f"Processed {processed} replies, {after_count} remaining")
                        
            except Exception as e:
                logger.error(f"Error in worker loop: {str(e)}")
                self.failed_count += 1
                
            # Wait for next iteration or shutdown signal
            self.shutdown_event.wait(timeout=self.worker.poll_interval)
            
        logger.info("Worker loop ended")
        
    def _get_queue_size(self) -> int:
        """Get current queue size"""
        try:
            with Session(engine) as session:
                count = session.exec(
                    select(PRReply).where(PRReply.status == "queued")
                ).all()
                return len(count)
        except Exception:
            return 0

# Core PR Functions
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

        # Search all PRs and match by branch name
        pulls = context.repo.get_pulls(state='all')
        pr_list = list(pulls)

        # Look for matching branch
        for pr in pr_list:
            if pr.head.ref == branch_name:
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

async def post_pr_reply_queue(comment_id: int, path: str, line: Optional[int], body: str) -> Dict[str, Any]:
    """Queue a reply to a PR comment for later processing"""
    try:
        # Get current repository name
        if not context.repo_name:
            return {"error": "GitHub repository not configured"}
        
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

        # Initialize overall_state here; it will be updated based on check runs
        overall_state = "pending" # Default to pending if no checks or statuses are found
        has_failures = False
        check_runs_data = []

        try:
            # Prefer check runs for detailed build status
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
                    overall_state = "success"
                elif run.status != "completed":
                    overall_state = "in_progress"

        except Exception as e:
            logger.debug(f"Warning: Failed to get check runs, trying combined status fallback: {e}")
            pass

        # Fallback to get_combined_status if check_runs_data is empty
        if not check_runs_data:
            try:
                status = commit.get_combined_status()
                overall_state = status.state
                has_failures = any(
                    s.state in ["failure", "error", "pending"] and s.context != "expected"
                    for s in status.statuses
                )
                for s in status.statuses:
                    check_runs_data.append({
                        "name": s.context,
                        "status": s.state,
                        "conclusion": s.state,
                        "url": s.target_url
                    })
            except Exception as e:
                logger.debug(f"Error: Failed to get combined status even as fallback: {e}")
                overall_state = "error"
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

    except Exception as e:
        return {"error": f"Failed to get build status: {str(e)}"}

async def read_swiftlint_logs(build_id=None):
    """Read SwiftLint logs - placeholder implementation"""
    try:
        # Placeholder implementation - customize based on your CI system
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

async def read_build_logs(build_id=None):
    """Read build logs - placeholder implementation"""
    try:
        # Placeholder implementation - customize based on your CI system
        test_failures = [
            {
                "file": "Tests/MyAppTests.swift",
                "line": 25,
                "type": "test_failure",
                "message": "XCTAssertEqual failed",
                "severity": "error"
            }
        ]
        
        return {
            "build_id": build_id,
            "compiler_errors": [],
            "compiler_warnings": [],
            "test_failures": test_failures,
            "total_issues": len(test_failures),
            "total_errors": 0,
            "total_warnings": 0,
            "total_test_failures": len(test_failures)
        }
        
    except Exception as e:
        return {"error": f"Failed to read build logs: {str(e)}"}

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

# Pydantic models for HTTP API
class ToolRequest(BaseModel):
    name: str
    arguments: Dict[str, Any] = {}

class ToolResponse(BaseModel):
    success: bool
    data: Any = None
    error: str = None

class WorkerCommand(BaseModel):
    action: str  # "start", "stop", "restart", "process_now"

# FastAPI app
app = FastAPI(
    title="PR Agent Server",
    description="Unified HTTP API for PR management tools and background worker",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure based on your needs
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global instances
context = PRReviewContext()
worker_service = UnifiedWorkerService()

@app.on_event("startup")
async def startup_event():
    """Initialize database and start worker on app startup"""
    try:
        init_db()
        logger.info("Database initialized")
        
        # Auto-start worker if configured
        if os.getenv("AUTO_START_WORKER", "true").lower() == "true":
            worker_service.start_worker()
            logger.info("Auto-started background worker")
            
        logger.info("PR Agent Server started successfully")
    except Exception as e:
        logger.error(f"Failed to initialize server: {str(e)}")
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Stop worker on app shutdown"""
    logger.info("PR Agent Server shutting down")
    worker_service.stop_worker()

# Health and status endpoints
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy", 
        "timestamp": datetime.now().isoformat(),
        "worker_running": worker_service.running
    }

@app.get("/status")
async def get_server_status():
    """Get comprehensive server status"""
    worker_status = worker_service.get_status()
    
    return {
        "server": {
            "status": "running",
            "github_configured": bool(context.github_token and context.repo_name),
            "repo": context.repo_name,
            "database_url": "sqlite:///pr_replies.db",
            "timestamp": datetime.now().isoformat()
        },
        "worker": worker_status
    }

# PR Management Tool endpoints
@app.get("/tools")
async def list_tools():
    """List all available PR management tools"""
    return {
        "pr_tools": [
            "get_current_branch", "get_current_commit", "find_pr_for_branch",
            "get_pr_comments", "post_pr_reply", "post_pr_reply_queue",
            "list_unhandled_comments", "ack_reply", "get_build_status",
            "read_swiftlint_logs", "read_build_logs", "process_comment_batch"
        ],
        "worker_actions": ["start", "stop", "restart", "process_now"]
    }

@app.post("/execute", response_model=ToolResponse)
async def execute_tool(request: ToolRequest):
    """Execute a PR management tool"""
    try:
        logger.info(f"Executing tool: {request.name} with args: {request.arguments}")
        
        # Route to appropriate function
        if request.name == "get_current_branch":
            result = await get_current_branch()
        elif request.name == "get_current_commit":
            result = await get_current_commit()
        elif request.name == "find_pr_for_branch":
            result = await find_pr_for_branch(request.arguments.get("branch_name"))
        elif request.name == "get_pr_comments":
            result = await get_pr_comments(request.arguments.get("pr_number"))
        elif request.name == "post_pr_reply":
            result = await post_pr_reply(
                request.arguments.get("comment_id"), 
                request.arguments.get("message")
            )
        elif request.name == "post_pr_reply_queue":
            result = await post_pr_reply_queue(
                request.arguments.get("comment_id"),
                request.arguments.get("path"),
                request.arguments.get("line"),
                request.arguments.get("body")
            )
        elif request.name == "list_unhandled_comments":
            result = await list_unhandled_comments(request.arguments.get("pr_number"))
        elif request.name == "ack_reply":
            result = await ack_reply(request.arguments.get("comment_id"))
        elif request.name == "get_build_status":
            result = await get_build_status(request.arguments.get("commit_sha"))
        elif request.name == "read_swiftlint_logs":
            result = await read_swiftlint_logs(request.arguments.get("build_id"))
        elif request.name == "read_build_logs":
            result = await read_build_logs(request.arguments.get("build_id"))
        elif request.name == "process_comment_batch":
            result = await process_comment_batch(request.arguments.get("comments_data"))
        else:
            raise HTTPException(status_code=400, detail=f"Unknown tool: {request.name}")
        
        # Check if result indicates an error
        if isinstance(result, dict) and "error" in result:
            return ToolResponse(success=False, error=result["error"])
        
        return ToolResponse(success=True, data=result)
        
    except Exception as e:
        logger.error(f"Tool execution failed: {str(e)}", exc_info=True)
        return ToolResponse(success=False, error=str(e))

# Worker management endpoints
@app.get("/worker/status")
async def get_worker_status():
    """Get background worker status"""
    return worker_service.get_status()

@app.post("/worker/control")
async def control_worker(command: WorkerCommand):
    """Control background worker (start/stop/restart/process_now)"""
    try:
        if command.action == "start":
            success = worker_service.start_worker()
            return {"success": success, "message": "Worker started" if success else "Worker already running"}
            
        elif command.action == "stop":
            success = worker_service.stop_worker()
            return {"success": success, "message": "Worker stopped" if success else "Worker not running"}
            
        elif command.action == "restart":
            success = worker_service.restart_worker()
            return {"success": success, "message": "Worker restarted" if success else "Failed to restart worker"}
            
        elif command.action == "process_now":
            result = worker_service.process_now()
            return {"success": True, "message": f"Processed {result['processed']} replies", "data": result}
            
        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: {command.action}")
            
    except Exception as e:
        logger.error(f"Worker control failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/queue")
async def get_queue_info():
    """Get information about the PR reply queue"""
    try:
        with Session(engine) as session:
            queued = session.exec(select(PRReply).where(PRReply.status == "queued")).all()
            sent = session.exec(select(PRReply).where(PRReply.status == "sent")).all()
            failed = session.exec(select(PRReply).where(PRReply.status == "failed")).all()
            
            return {
                "queued": len(queued),
                "sent": len(sent),
                "failed": len(failed),
                "total": len(queued) + len(sent) + len(failed),
                "oldest_queued": min([r.created_at for r in queued], default=None),
                "newest_queued": max([r.created_at for r in queued], default=None)
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Convenience endpoints for common operations
@app.get("/branch")
async def get_branch():
    """Get current branch info"""
    return await get_current_branch()

@app.get("/commit")
async def get_commit():
    """Get current commit info"""
    return await get_current_commit()

@app.get("/pr/{pr_number}/comments")
async def get_pr_comments_endpoint(pr_number: int):
    """Get comments for a specific PR"""
    return await get_pr_comments(pr_number)

@app.get("/pr/comments/unhandled")
async def get_unhandled_comments(pr_number: Optional[int] = None):
    """Get unhandled comments"""
    return await list_unhandled_comments(pr_number)

@app.post("/pr/comments/{comment_id}/reply")
async def reply_to_comment(comment_id: int, message: str):
    """Reply to a specific comment"""
    return await post_pr_reply(comment_id, message)

def handle_signal(signum, frame):
    """Handle shutdown signals"""
    logger.info(f"Received signal {signum}, shutting down...")
    worker_service.stop_worker()
    exit(0)

def main():
    """Main entry point"""
    # Check for required environment variables
    if not os.getenv("GITHUB_TOKEN"):
        logger.error("GITHUB_TOKEN environment variable is required")
        exit(1)
        
    # Set up signal handlers
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    
    # Get configuration from environment
    host = os.getenv("SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("SERVER_PORT", "8080"))
    workers = int(os.getenv("WORKERS", "1"))
    
    logger.info(f"Starting PR Agent Server on {host}:{port}")
    
    # Run with uvicorn
    uvicorn.run(
        "pr_agent_server:app",
        host=host,
        port=port,
        workers=workers,
        log_level="info",
        reload=False
    )

if __name__ == "__main__":
    main()
