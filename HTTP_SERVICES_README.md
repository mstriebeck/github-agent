# PR Agent HTTP Server

Complete deployment and API documentation for the unified PR Agent HTTP server.

## Overview

The PR Agent runs as a single HTTP service that provides:

1. **PR Management Tools** - All MCP tools accessible via HTTP API
2. **Background Worker** - Automatic processing of queued PR replies
3. **Management Interface** - Control and monitoring endpoints

## Installation

### Prerequisites

- **macOS** or **Linux** system 
- **Python 3.8+**
- **Git repository** with GitHub remote
- **GitHub Personal Access Token** with `repo` scope

### Quick Installation

1. **Clone and enter repository:**
   ```bash
   cd your-github-repo  # Must be a git repo with GitHub remote
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure GitHub token:**
   ```bash
   cp config/services.env .env
   # Edit .env and set GITHUB_TOKEN=your_token_here
   ```

4. **Install as service (optional):**
   ```bash
   # Linux (requires sudo)
   sudo ./install-services.sh
   
   # macOS (installs to user space)
   ./install-services.sh
   ```

## Configuration

The server auto-detects your GitHub repository from `git remote origin`. Only the GitHub token is required:

```bash
# Required
GITHUB_TOKEN=ghp_your_token_here

# Optional
SERVER_PORT=8080
POLL_INTERVAL=30
AUTO_START_WORKER=true
LOG_LEVEL=INFO
```

**Configuration locations:**
- **Development:** `.env` in current directory
- **Service (Linux):** `/opt/github-agent/.env`  
- **Service (macOS):** `~/.local/share/github-agent/.env`

## Running the Server

### Development Mode
```bash
python github_mcp_server.py
```

### Service Mode

**Linux (systemd):**
```bash
sudo systemctl start pr-agent     # Start
sudo systemctl status pr-agent    # Check status
sudo systemctl stop pr-agent      # Stop
```

**macOS (launchd):**
```bash
launchctl start com.github.pr-agent    # Start
launchctl list | grep pr-agent         # Check status  
launchctl stop com.github.pr-agent     # Stop
```

## API Usage

### Core Endpoints

**Health Check:**
```bash
curl http://localhost:8080/health
```

**Execute Any Tool:**
```bash
curl -X POST http://localhost:8080/execute \
  -H "Content-Type: application/json" \
  -d '{
    "name": "git_get_current_branch",
    "arguments": {}
  }'
```

**Server Status:**
```bash
curl http://localhost:8080/status
```

### Queue Management

**Check Queue:**
```bash
curl http://localhost:8080/queue
```

**Control Worker:**
```bash
curl -X POST http://localhost:8080/worker/control \
  -H "Content-Type: application/json" \
  -d '{"action": "process_now"}'
```

**Worker Status:**
```bash
curl http://localhost:8080/worker/status
```

## VS Code/Amp Integration

### MCP HTTP Transport

The server provides an **MCP HTTP transport** in addition to the original stdio transport. Configure your MCP client to use:

**MCP Server URL:** `http://localhost:8080/execute`

**Request Format:**
```json
{
  "name": "tool_name",
  "arguments": { "param": "value" }
}
```

**Response Format:**
```json
{
  "success": true,
  "data": { ... },
  "error": null
}
```

### Available Tools

All original MCP tools work via HTTP:

- `git_get_current_branch` - Get current Git branch and commit info
- `git_get_current_commit` - Get current commit details  
- `github_find_pr_for_branch` - Find PR associated with a branch
- `github_get_pr_comments` - Get all comments from a PR
- `github_post_pr_reply` - Reply directly to a PR comment
- `post_pr_reply_queue` - Queue a reply for background processing
- `list_unhandled_comments` - List comments without replies
- `ack_reply` - Mark a comment as handled
- `github_get_build_status` - Get CI/CD build status
- `github_check_ci_lint_errors_not_local` - Extract linting errors from CI logs
- `github_check_ci_build_and_test_errors_not_local` - Extract build errors, warnings, and test failures
- `process_comment_batch` - Process multiple replies in batch

## Queue System

### How It Works
1. Use `post_pr_reply_queue` to queue replies instead of posting immediately
2. Background worker automatically processes queued replies every 30 seconds
3. Monitor queue status via `/queue` endpoint
4. Control worker via `/worker/control` endpoint

### Benefits
- **Reliability** - Retries failed posts automatically
- **Rate Limiting** - Avoids GitHub API rate limits
- **Async Processing** - Don't block main workflow
- **Monitoring** - Full visibility into queue status

## Logging

**Log Locations:**
- **Development:** Console output
- **Linux Service:** `/var/log/github_mcp_server.log` + systemd journal
- **macOS Service:** `~/.local/share/github-agent/logs/github_mcp_server.log`

**View Logs:**
```bash
# Linux
sudo journalctl -u pr-agent -f
tail -f /var/log/github_mcp_server.log

# macOS  
tail -f ~/.local/share/github-agent/logs/github_mcp_server.log

# Development
# Logs appear in terminal
```

## Troubleshooting

### Server Won't Start
1. **Check GitHub token:** Ensure `GITHUB_TOKEN` is set in `.env`
2. **Verify repository:** Must be a git repo with GitHub remote
3. **Check dependencies:** Run `pip install -r requirements.txt`
4. **View logs:** See log locations above

### Worker Not Processing Queue
1. **Check worker status:** `curl http://localhost:8080/worker/status`
2. **Manual trigger:** `curl -X POST http://localhost:8080/worker/control -d '{"action":"process_now"}'`
3. **GitHub permissions:** Verify token has `repo` scope
4. **Check logs:** Worker errors appear in main log

### Database Issues
- Database file created automatically at `./pr_replies.db` (or service directory)
- Ensure write permissions in working directory
- SQLite is included with Python

### GitHub API Errors
- **Rate limiting:** Use queue system (`post_pr_reply_queue`) 
- **403 Forbidden:** Check token permissions and repository access
- **404 Not Found:** Verify repository name detection with `/status`

## Security Considerations

- **Service Security:** Linux service runs as `www-data` with restricted permissions
- **Token Storage:** GitHub tokens stored in environment files with 600 permissions  
- **Network Access:** Server binds to localhost by default
- **Production:** Use reverse proxy (nginx) for HTTPS in production environments

## Development

Run directly for development:
```bash
export GITHUB_TOKEN=your_token
python github_mcp_server.py
```

## Uninstallation

Use the provided uninstall script to completely remove the GitHub Agent:

```bash
./scripts/uninstall-services.sh
```

The uninstall script will:
- Stop and remove the service (systemd/launchd)
- Remove all installation files and directories
- Clean up log files and databases
- Remove Python cache files
- Verify complete removal
- Handle permission issues automatically

**Features:**
- **Cross-platform**: Works on both Linux and macOS
- **Verification**: Confirms all components are removed
- **Safety**: Asks for confirmation before proceeding
- **Cleanup**: Removes cache files and processes
- **Detailed output**: Shows exactly what's being removed

**Manual Uninstall (if script fails):**
```bash
# Stop the service
sudo systemctl stop pr-agent     # Linux
launchctl unload com.github.pr-agent  # macOS

# Remove installation
sudo rm -rf /opt/github-agent    # Linux
rm -rf ~/.local/share/github-agent  # macOS

# Remove service files
sudo rm /etc/systemd/system/pr-agent.service  # Linux
rm ~/Library/LaunchAgents/com.github.pr-agent.plist  # macOS

# Kill any remaining processes
pkill -f github_mcp_server
```

The server will auto-detect your repository and start on http://localhost:8080

## MCP Integration with Amp

The server provides MCP (Model Context Protocol) support for integration with Amp and other MCP clients.

### MCP Endpoints

- **Streamable HTTP (Recommended):** `http://localhost:8080/mcp` - Supports both POST messages and GET SSE streams

### Configuring Amp

To add the GitHub PR Agent to Amp, enter this URL:

```
http://localhost:8080/mcp
```

This single endpoint provides both HTTP POST (for tool calls) and GET SSE (for streaming) as required by the MCP Streamable HTTP transport protocol.

### Available MCP Tools

Once connected, Amp will have access to these PR management tools:

- `git_get_current_branch` - Get current Git branch information
- `git_get_current_commit` - Get current commit details  
- `github_find_pr_for_branch` - Find PR associated with a branch
- `github_get_pr_comments` - Get all comments from a PR
- `github_post_pr_reply` - Reply to a PR comment immediately
- `post_pr_reply_queue` - Queue a reply for later processing
- `list_unhandled_comments` - List unhandled PR comments
- `github_get_build_status` - Get CI/CD build status for commits
- `github_check_ci_lint_errors_not_local` - Extract linting errors from CI logs
- `github_check_ci_build_and_test_errors_not_local` - Extract build errors, warnings, and test failures

### Usage in Amp

Once configured, you can use the tools in Amp:

```
@github-pr-agent git_get_current_branch
@github-pr-agent github_get_pr_comments {"pr_number": 123}
@github-pr-agent github_post_pr_reply {"comment_id": 456, "message": "Fixed in latest commit"}
```
