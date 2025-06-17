# PR Agent HTTP Server

This document describes how to deploy and use the PR Agent as a unified HTTP server managed by systemctl.

## Overview

The system is a single HTTP service that combines:

1. **PR Management Tools** - All original MCP tools accessible via HTTP API
2. **Background Worker** - Automatic processing of queued PR replies in a background thread
3. **Management Interface** - HTTP endpoints to control the worker and monitor status

## Installation

### Prerequisites

- Ubuntu/Debian Linux system with systemd
- Python 3.8+
- Root/sudo access

### Quick Installation

1. Clone/copy all files to your server
2. Install required Python packages:
   ```bash
   pip install -r requirements.txt
   pip install -r requirements-http.txt
   ```
3. Configure environment variables:
   ```bash
   cp config/services.env .env
   # Edit .env with your GitHub token and repo
   ```
4. Run the installation script:
   ```bash
   sudo ./install-services.sh
   ```

## Configuration

Edit `/opt/github-agent/.env` with your settings:

```bash
# Required
GITHUB_TOKEN=ghp_your_token_here
GITHUB_REPO=owner/repository

# Optional
SERVER_PORT=8080
WORKER_PORT=8081
POLL_INTERVAL=30
```

## Service Management

### Starting Services
```bash
sudo systemctl start pr-review-server
sudo systemctl start pr-worker-service
```

### Stopping Services
```bash
sudo systemctl stop pr-review-server
sudo systemctl stop pr-worker-service
```

### Checking Status
```bash
sudo systemctl status pr-review-server
sudo systemctl status pr-worker-service
```

### Viewing Logs
```bash
# Real-time logs
sudo journalctl -u pr-review-server -f
sudo journalctl -u pr-worker-service -f

# Log files
tail -f /var/log/pr_review_server.log
tail -f /var/log/pr_worker_service.log
```

## API Usage

### PR Review Server (Port 8080)

#### Health Check
```bash
curl http://localhost:8080/health
```

#### Execute Tool
```bash
curl -X POST http://localhost:8080/execute \
  -H "Content-Type: application/json" \
  -d '{
    "name": "get_current_branch",
    "arguments": {}
  }'
```

#### Get PR Comments
```bash
curl http://localhost:8080/pr/123/comments
```

#### Get Unhandled Comments
```bash
curl http://localhost:8080/pr/comments/unhandled
```

### Worker Service (Port 8081)

#### Check Worker Status
```bash
curl http://localhost:8081/status
```

#### Control Worker
```bash
# Start worker
curl -X POST http://localhost:8081/control \
  -H "Content-Type: application/json" \
  -d '{"action": "start"}'

# Process queue immediately
curl -X POST http://localhost:8081/control \
  -H "Content-Type: application/json" \
  -d '{"action": "process_now"}'
```

#### Check Queue Status
```bash
curl http://localhost:8081/queue
```

## Integration with VS Code/Amp

To use these HTTP services with VS Code/Amp instead of the stdio MCP server:

1. Configure your VS Code settings to point to the HTTP endpoints
2. Use the `/execute` endpoint with tool names and arguments
3. The API returns JSON responses in the format:
   ```json
   {
     "success": true,
     "data": { ... },
     "error": null
   }
   ```

## Available Tools

All original MCP tools are available via HTTP:

- `get_current_branch` - Get current Git branch and commit info
- `get_current_commit` - Get current commit details
- `find_pr_for_branch` - Find PR associated with a branch
- `get_pr_comments` - Get all comments from a PR
- `post_pr_reply` - Reply directly to a PR comment
- `post_pr_reply_queue` - Queue a reply for background processing
- `list_unhandled_comments` - List comments without replies
- `ack_reply` - Mark a comment as handled
- `get_build_status` - Get CI/CD build status
- `read_swiftlint_logs` - Read SwiftLint violation reports
- `read_build_logs` - Read build logs and extract errors/warnings
- `process_comment_batch` - Process multiple replies in batch

## Queue System

The unified server includes a built-in queue system for handling PR replies:

### How it Works
1. Use `post_pr_reply_queue` to queue replies instead of posting immediately
2. Background worker automatically processes queued replies
3. Monitor queue status via `/queue` endpoint
4. Control worker via `/worker/control` endpoint

### Benefits
- **Reliability** - Retries failed posts automatically
- **Rate Limiting** - Avoids GitHub API rate limits
- **Async Processing** - Don't block main workflow
- **Monitoring** - Full visibility into queue status

### Queue Endpoints
```bash
# Check queue status
curl http://localhost:8080/queue

# Control worker
curl -X POST http://localhost:8080/worker/control \
  -H "Content-Type: application/json" \
  -d '{"action": "process_now"}'

# Check worker status  
curl http://localhost:8080/worker/status
```

## Security Considerations

- Services run as `www-data` user with restricted permissions
- Log files are properly secured
- Configure firewall rules to restrict access to ports 8080/8081
- Use HTTPS in production (add reverse proxy like nginx)
- Store GitHub tokens securely in environment files

## Troubleshooting

### Service Won't Start
1. Check logs: `sudo journalctl -u pr-review-server -n 50`
2. Verify environment variables are set
3. Check file permissions
4. Ensure Python dependencies are installed

### Worker Not Processing Queue
1. Check worker status: `curl http://localhost:8081/status`
2. Manually trigger processing: `curl -X POST http://localhost:8081/control -d '{"action":"process_now"}'`
3. Check GitHub token permissions
4. Review worker logs

### Database Issues
- Database file is created automatically at `/opt/github-agent/pr_replies.db`
- Ensure `www-data` user has write permissions
- Check SQLite installation

## Development

For development, you can run the services directly:

```bash
# Terminal 1 - PR Review Server
python pr_review_http_server.py

# Terminal 2 - Worker Service  
python pr_worker_service.py
```

Set environment variables in your shell or use a `.env` file in the current directory.
