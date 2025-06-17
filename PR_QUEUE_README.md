# PR Reply Queue System

This system extends the MCP PR review server with a queueing mechanism for handling PR comment replies asynchronously.

## Architecture

```
Agent/User
  └─> post_pr_reply_queue(comment_id, path, line, body)
      └─> SQLite database (pr_replies.db)

Background Worker (pr_reply_worker.py)
  └─> polls database for queued replies
      └─> posts to GitHub API
          └─> updates status to "sent" or "failed"
```

## Setup

1. Run the setup script:
   ```bash
   ./setup_pr_queue.sh
   ```

2. Set environment variables in `.env`:
   ```
   GITHUB_TOKEN=your_github_token
   GITHUB_REPO=owner/repo
   POLL_INTERVAL=30  # optional, seconds between polls
   ```

## Usage

### MCP Tools Available

1. **`post_pr_reply_queue`** - Queue a reply for later processing
   ```json
   {
     "comment_id": 123456,
     "path": "src/main.swift", 
     "line": 42,
     "body": "Fixed the issue by adding proper error handling"
   }
   ```

2. **`list_unhandled_comments`** - Get comments that need replies
   ```json
   {
     "pr_number": 123  // optional
   }
   ```

3. **`ack_reply`** - Mark a comment as acknowledged
   ```json
   {
     "comment_id": 123456
   }
   ```

### Running the System

1. **For Sourcegraph AMP users:** Point AMP to `python3 pr_review_server.py` in your MCP configuration. AMP will automatically start and manage the server.

2. **For manual usage:** Start the MCP server:
   ```bash
   python3 pr_review_server.py
   ```

3. **Start the background worker:**
   ```bash
   python3 pr_reply_worker.py
   ```

The worker will poll the database every 30 seconds (configurable) and attempt to post any queued replies to GitHub.

### Database Schema

The system uses SQLite with this schema:

```sql
CREATE TABLE prreply (
    id INTEGER PRIMARY KEY,
    comment_id INTEGER NOT NULL,
    repo_name TEXT NOT NULL,  -- format: "owner/repo"
    status TEXT DEFAULT 'queued',  -- 'queued', 'sent', 'failed'  
    attempt_count INTEGER DEFAULT 0,
    last_attempt_at TIMESTAMP,
    sent_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    data TEXT NOT NULL  -- JSON containing path, line, body, etc.
);
```

**Schema Design:** Query-critical fields (comment_id, repo_name, status, timestamps) are columns, while extensible data (path, line, body, etc.) is stored as JSON for easy schema evolution.

### Logging

- MCP server logs: `/tmp/pr_review_server.log`
- Worker logs: `/tmp/pr_reply_worker.log`

## Agent Workflow

The recommended agent workflow is:

1. Use `list_unhandled_comments` to get comments needing attention
2. For each comment:
   - Analyze and make code changes if needed
   - Generate an appropriate reply
   - Call `post_pr_reply_queue` to queue the reply
   - Call `ack_reply` to mark as handled
3. The background worker handles actual GitHub posting

This decouples reply generation from GitHub API calls, making the agent more responsive and resilient to network issues.
