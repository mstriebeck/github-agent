#!/usr/bin/env python3

"""
Background worker for processing queued PR replies
Polls the SQLite database for queued replies and posts them to GitHub
"""

import os
import time
import logging
import requests
from datetime import datetime
from sqlmodel import SQLModel, Session, select, create_engine
from dotenv import load_dotenv

# Import the PRReply model from the main server
from pr_review_server import PRReply, DATABASE_URL, engine

# Load environment variables
load_dotenv()

# Immediately check for required token
if not os.getenv("GITHUB_TOKEN"):
    print("ERROR: GITHUB_TOKEN environment variable is required")
    exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/tmp/pr_reply_worker.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

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
            import json
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
    
    def run(self):
        """Main worker loop"""
        logger.info(f"Starting worker loop, polling every {self.poll_interval} seconds")
        
        while True:
            try:
                self.process_queue()
            except Exception as e:
                logger.error(f"Error in worker loop: {str(e)}")
            
            time.sleep(self.poll_interval)

def main():
    """Main entry point"""
    try:
        worker = PRReplyWorker()
        worker.run()
    except KeyboardInterrupt:
        logger.info("Worker stopped by user")
    except Exception as e:
        logger.error(f"Worker failed: {str(e)}")
        raise

if __name__ == "__main__":
    main()
