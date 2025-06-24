# GitHub Agent Multi-Repository HTTP Server

Complete deployment and API documentation for the GitHub Agent multi-repository HTTP server system.

## Overview

The GitHub Agent runs as a multi-repository HTTP service system that provides:

1. **PR Management Tools** - All MCP tools accessible via HTTP API per repository
2. **Multi-Repository Support** - Each repository gets its own dedicated worker and port
3. **Management Interface** - Master server with health monitoring and worker management

## Installation

### Prerequisites

- **macOS** or **Linux** system 
- **Python 3.8+**
- **Git repository** with GitHub remote
- **GitHub Personal Access Token** with `repo` scope

### Quick Installation

1. **Clone repository:**
   ```bash
   git clone <repository-url>
   cd github-agent
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure repositories:**
   ```bash
   # Edit repositories.json to add your repositories
   # Each repository gets its own port and worker
   ```

4. **Configure GitHub token:**
   ```bash
   cp config/services.env .env
   # Edit .env and set GITHUB_TOKEN=your_token_here
   ```

5. **Install as service (optional):**
   ```bash
   # Linux (requires sudo)
   sudo ./install-services.sh
   
   # macOS (installs to user space)
   ./install-services.sh
   ```

## Configuration

The system uses two configuration files:

### 1. repositories.json
Define which repositories to manage and their ports:
```json
{
  "repositories": {
    "github-agent": {
      "path": "/path/to/github-agent",
      "port": 8081,
      "description": "GitHub Agent repository"
    },
    "my-project": {
      "path": "/path/to/my-project", 
      "port": 8082,
      "description": "My Project repository"
    }
  }
}
```

### 2. Environment (.env)
```bash
# Required
GITHUB_TOKEN=ghp_your_token_here

# Optional
LOG_LEVEL=INFO
```

**Configuration locations:**
- **Development:** `.env` and `repositories.json` in current directory
- **Service (Linux):** `/opt/github-agent/.env` and `/opt/github-agent/repositories.json`
- **Service (macOS):** `~/.local/share/github-agent/.env` and `~/.local/share/github-agent/repositories.json`

## Running the Server

### Development Mode
```bash
python github_mcp_master.py
```

This starts the master server which automatically launches worker processes for each repository defined in `repositories.json`.

### Service Mode

**Linux (systemd):**
```bash
sudo systemctl start github-agent     # Start
sudo systemctl status github-agent    # Check status
sudo systemctl stop github-agent      # Stop
```

**macOS (launchd):**
```bash
launchctl start com.github.agent         # Start
launchctl list | grep github-agent       # Check status  
launchctl stop com.github.agent          # Stop
```

## API Usage

### Master Server Endpoints (Port 8080)

**Master Health Check:**
```bash
curl http://localhost:8080/health
```

**System Status (all workers):**
```bash
curl http://localhost:8080/status
```

### Repository Worker Endpoints

Each repository defined in `repositories.json` gets its own worker with dedicated endpoints:

**Repository Root Info:**
```bash
curl http://localhost:8081/    # For github-agent repository
curl http://localhost:8082/    # For second repository
```

**Repository Health Check:**
```bash
curl http://localhost:8081/health    # For github-agent repository
curl http://localhost:8082/health    # For second repository
```

**MCP Endpoint (tools and communication):**
```bash
# Each repository has its own MCP endpoint
curl http://localhost:8081/mcp/    # For github-agent repository
curl http://localhost:8082/mcp/    # For second repository
```

## VS Code/Amp Integration

### MCP HTTP Transport

Each repository worker provides an **MCP HTTP transport** endpoint. Configure your MCP client to connect to the specific repository you want to work with:

**MCP Server URLs (per repository):**
- `http://localhost:8081/mcp/` (for github-agent repository)
- `http://localhost:8082/mcp/` (for second repository)
- etc.

The MCP endpoint supports both GET (Server-Sent Events) and POST (JSON-RPC) methods as required by the MCP Streamable HTTP transport protocol.

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
- `github_get_lint_errors` - Extract linting errors from CI logs
- `github_get_build_and_test_errors` - Extract build errors, warnings, and test failures
- `process_comment_batch` - Process multiple replies in batch

## Multi-Repository Architecture

### How It Works
1. Master server (port 8080) manages multiple worker processes
2. Each repository gets its own dedicated worker process and port
3. Workers are automatically started/stopped/restarted by the master
4. Each worker provides its own MCP endpoint at `http://localhost:<port>/mcp/`
5. Configure repositories in `repositories.json`

### Benefits
- **Isolation** - Each repository runs independently
- **Scalability** - Add repositories without affecting others
- **Reliability** - If one worker fails, others continue running
- **Clean URLs** - Simple per-repository endpoint management

## Logging

**Log Locations:**
- **Development:** Console output
- **Linux Service:** `/var/log/github_agent_master.log` + systemd journal
- **macOS Service:** `~/.local/share/github-agent/logs/github_agent_master.log`

**View Logs:**
```bash
# Linux
sudo journalctl -u github-agent -f
tail -f /var/log/github_agent_master.log

# macOS  
tail -f ~/.local/share/github-agent/logs/github_agent_master.log

# Development
# Logs appear in terminal
```

## Troubleshooting

### Server Won't Start
1. **Check GitHub token:** Ensure `GITHUB_TOKEN` is set in `.env`
2. **Verify repository:** Must be a git repo with GitHub remote
3. **Check dependencies:** Run `pip install -r requirements.txt`
4. **View logs:** See log locations above

### Worker Not Responding
1. **Check system status:** `curl http://localhost:8080/status`
2. **Check individual worker:** `curl http://localhost:8081/health` (replace with actual port)
3. **GitHub permissions:** Verify token has `repo` scope
4. **Check logs:** Worker errors appear in master and worker logs

### Database Issues
- Database file created automatically at `./pr_replies.db` (or service directory)
- Ensure write permissions in working directory
- SQLite is included with Python

### GitHub API Errors
- **403 Forbidden:** Check token permissions and repository access
- **404 Not Found:** Verify repository paths in `repositories.json`
- **Rate limiting:** GitHub API has rate limits, workers handle retries automatically

## Security Considerations

- **Service Security:** Linux service runs as `www-data` with restricted permissions
- **Token Storage:** GitHub tokens stored in environment files with 600 permissions  
- **Network Access:** Server binds to localhost by default
- **Production:** Use reverse proxy (nginx) for HTTPS in production environments

## Development

Run directly for development:
```bash
export GITHUB_TOKEN=your_token
python github_mcp_master.py
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
sudo systemctl stop github-agent     # Linux
launchctl unload com.github.agent  # macOS

# Remove installation
sudo rm -rf /opt/github-agent    # Linux
rm -rf ~/.local/share/github-agent  # macOS

# Remove service files
sudo rm /etc/systemd/system/github-agent.service  # Linux
rm ~/Library/LaunchAgents/com.github.agent.plist  # macOS

# Kill any remaining processes
pkill -f github_mcp_master
pkill -f github_mcp_worker
```

The master server starts on http://localhost:8080 and manages workers for each configured repository.

## MCP Integration with Amp

The system provides MCP (Model Context Protocol) support for integration with Amp and other MCP clients.

### MCP Endpoints

Each repository gets its own MCP endpoint:
- **Repository 1:** `http://localhost:8081/mcp/` (supports both POST and GET SSE)
- **Repository 2:** `http://localhost:8082/mcp/` (supports both POST and GET SSE)
- etc.

### Configuring Amp

To add a specific repository to Amp, use its dedicated MCP endpoint:

```
http://localhost:8081/mcp/    # For the first repository
http://localhost:8082/mcp/    # For the second repository
```

Each endpoint provides both HTTP POST (for tool calls) and GET SSE (for streaming) as required by the MCP Streamable HTTP transport protocol.

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
- `github_get_lint_errors` - Extract linting errors from CI logs
- `github_get_build_and_test_errors` - Extract build errors, warnings, and test failures

### Usage in Amp

Once configured, you can use the tools in Amp:

```
@github-pr-agent git_get_current_branch
@github-pr-agent github_get_pr_comments {"pr_number": 123}
@github-pr-agent github_post_pr_reply {"comment_id": 456, "message": "Fixed in latest commit"}
```
