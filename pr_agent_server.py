#!/usr/bin/env python3

"""
PR Agent Unified Server
Combined HTTP server with PR management tools and background worker
"""

import asyncio
import os
import json
import logging
import signal
import threading
import time
from datetime import datetime
from typing import Optional, Dict, Any
import uvicorn
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlmodel import Session, select
from dotenv import load_dotenv

# Import all the functions from the original modules
from pr_review_server import (
    PRReviewContext, PRReply, init_db, engine,
    get_current_branch, get_current_commit, find_pr_for_branch,
    get_pr_comments, post_pr_reply, post_pr_reply_queue,
    list_unhandled_comments, ack_reply, get_build_status,
    read_swiftlint_logs, read_build_logs, process_comment_batch
)
from pr_reply_worker import PRReplyWorker

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

# Pydantic models
class ToolRequest(BaseModel):
    name: str
    arguments: Dict[str, Any] = {}

class ToolResponse(BaseModel):
    success: bool
    data: Any = None
    error: str = None

class WorkerStatus(BaseModel):
    status: str
    uptime_seconds: int
    processed_replies: int
    failed_replies: int
    queue_size: int
    last_run: str = None

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
            
    def get_status(self) -> WorkerStatus:
        """Get current worker status"""
        uptime = int((datetime.now() - self.start_time).total_seconds()) if self.start_time else 0
        queue_size = self._get_queue_size()
        
        return WorkerStatus(
            status="running" if self.running else "stopped",
            uptime_seconds=uptime,
            processed_replies=self.processed_count,
            failed_replies=self.failed_count,
            queue_size=queue_size,
            last_run=self.last_run
        )
        
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
        "worker": worker_status.dict()
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
@app.get("/worker/status", response_model=WorkerStatus)
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
