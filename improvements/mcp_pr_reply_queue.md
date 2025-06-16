# MCP PR Reply Queue with SQLite + SQLModel

This document outlines the design and implementation of a lightweight, local-first queuing system for handling GitHub PR review comment replies, as part of an MCP (Modular Command Protocol) agent integration. It allows the agent to queue replies to PR comments and delegates the actual posting to a background worker that uses GitHub's API. The setup prioritizes developer simplicity and agent responsiveness.

---

## Goals

- Avoid manual copy/paste between agent and GitHub.
- Let the agent focus on code + reply generation.
- Ensure robust delivery without requiring heavy infrastructure.
- Enable filtering of already-addressed comments.
- Reuse and encapsulate logic already implemented in `reply_to_github_comments.py`.

---

## Architecture Overview

```text
Agent
  └──> tool: post_pr_reply_queue(comment_id, path, line, body)
        └──> insert into SQLite queue (status = "queued")

Background Worker (daemon or cron)
  └──> reads from queue where status = "queued"
      └──> attempts to post reply to GitHub
          └──> on success: status = "sent", sent_at = now
          └──> on failure: retry with exponential backoff

Tool: list_unhandled_comments(pr_number)
  └──> fetch PR comments
      └──> subtract replied comment_ids from SQLite
```

---

## SQLite + SQLModel Schema

```python
from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class PRReply(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    comment_id: int
    path: str
    line: Optional[int]
    body: str
    status: str = "queued"  # or "sent", "failed"
    attempt_count: int = 0
    last_attempt_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None
```

This table stores each attempted reply and its delivery status.

---

## Tools

### `post_pr_reply`
Adds a reply to the queue for later processing.

```python
@tool("post_pr_reply")
def post_pr_reply(comment_id: int, path: str, line: int, body: str):
    # Insert into SQLite with status='queued'
```

### `ack_reply`
Optional confirmation tool used by agents to indicate they've finished handling a comment. Could be upgraded to validate against the database.

### `list_unhandled_comments`
Used to only return comments the agent has not yet addressed.

---

## Background Worker

A simple Python loop that:
- Polls for `status='queued'`
- Posts to GitHub via REST API using logic from `reply_to_github_comments.py`
- Updates row to `status='sent'` or increments retry count on failure

The worker logic will be adapted from the user’s existing `reply_to_github_comments.py`, which:
- Extracts repo, branch, PR, and comment information
- Uses GitHub’s REST API to post replies
- Handles authentication via `GITHUB_TOKEN`

This script’s logic will be embedded into a reusable function that is invoked by the worker as it processes each row in the queue.

As this runs in the background, we will need extensive logging to understand what's happening and debug issues.

---

## Agent Prompt Structure

```text
INSTRUCTIONS:
- After addressing each comment:
  1. Modify the code
  2. Generate a reply
  3. Call `post_pr_reply` with the reply
  4. Call `ack_reply(comment_id)` to mark completion
- Only handle one comment at a time.
```

Prompting structure includes:
- Instructions on how to handle questions vs actionable items
- A strict output format for tool invocation
- Emphasis on immediate tool calls after each reply

### Example Prompt for Agent

```text
📝 Please address the following PR review comments:

If a comment is a question, do not make code changes right away. Instead, first respond to the question and wait for clarification.

INSTRUCTIONS:
- For each comment:
  1. Modify the code to address the comment (unless it's a question).
  2. Generate a short reply.
  3. Immediately invoke the tool `post_pr_reply` to queue the reply.
     Format:
     {
       "tool": "post_pr_reply",
       "input": {
         "comment_id": <ID>,
         "path": "<file_path>",
         "line": <line_number>,
         "body": "Reply: <your explanation>"
       }
     }
  4. Then call the tool `ack_reply(comment_id)`.

- Only handle one comment at a time.
```

---

## Setup Instructions

We provide an idempotent setup script (under ./setup) that ensures all required dependencies and configurations are installed on a macOS or Linux development machine.

### Script Capabilities:
- Install Python 3 if not available
- Create and activate a virtual environment
- Install required Python packages (`sqlmodel`, `requests`, etc.)
- Create the SQLite database and initialize the schema (using SQLModel)
- Check for required environment variables (e.g., `GITHUB_TOKEN`)
- (Optional) Register and configure MCP tools if part of a larger agent system

### Sample Script Entry Point: `setup_dev_env.sh`

```bash
#!/bin/bash
set -euo pipefail

python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install sqlmodel requests

python3 -c 'from your_module import init_db; init_db()'

echo "✅ Environment is ready."
```

This script can be rerun safely and will not overwrite existing data or environments.

---

## Alternatives Considered

### Redis + RQ
- Too heavy for local/dev use
- Requires extra process + network dependency

### Huey (Redis/SQLite)
- Good periodic scheduling
- Overkill unless needing retry/dead-letter queues

### Direct GitHub Posting from Agent
- Tight coupling between reply generation and posting
- Slower response cycles
- Harder to retry or audit failures

---

## Summary
This system strikes a balance between automation and simplicity. Using SQLite + SQLModel ensures reliable delivery of agent-generated replies with minimal infrastructure, making it well-suited for running on a local development machine. It reuses existing GitHub logic and enables rich interaction with agents using the MCP framework.

