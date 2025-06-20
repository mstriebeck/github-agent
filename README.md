# GitHub MCP Server - Multi-Repository Support

## 🧾 Overview

A production-ready GitHub PR management server with MCP (Model Context Protocol) support for coding agents. Features multi-repository support with dedicated ports for better client compatibility and process isolation.

### Key Features

* **Multi-Repository Support** - Manage multiple repositories simultaneously
* **Dedicated Ports** - Each repository gets its own port for better MCP client compatibility
* **Process Isolation** - Repository issues don't affect other repositories
* **Master-Worker Architecture** - Robust process management with automatic restarts
* **Clean MCP Endpoints** - Simple URLs: `http://localhost:8081/mcp/`
* **Production Ready** - Proper logging, error handling, and service management

---

## 🏗️ Architecture

### Multi-Port Architecture (Current)

The system uses a master-worker architecture where each repository runs on its own dedicated port:

* **Master Process** (`github_mcp_master.py`) - Spawns and monitors worker processes
* **Worker Processes** (`github_mcp_worker.py`) - Handle individual repositories
* **Clean URLs** - No complex routing: each repository has its own endpoint
* **Process Isolation** - Issues in one repository don't affect others

### VSCode/Amp Integration

Each repository automatically gets a `.vscode/settings.json` file configured with the correct MCP server endpoint:

```json
{
  "amp.mcpServers": {
    "github-mcp-server": {
      "url": "http://localhost:8081/mcp/"
    }
  }
}
```

This allows Amp (or other MCP clients) to automatically connect to the repository's dedicated GitHub MCP server.

## 🚀 Quick Start

### 1. Install as System Service

```bash
# Clone repository
git clone <your-repo>
cd github-agent

# Install dependencies and setup development environment
./setup/setup_system.sh

# Install as system service
# Linux (requires sudo)
sudo ./scripts/install-services.sh

# macOS (installs to user space)
./scripts/install-services.sh
```

### 2. Configure Service

```bash
# Linux
sudo nano /opt/github-agent/.env

# macOS  
nano ~/.local/share/github-agent/.env

# Set your GITHUB_TOKEN
GITHUB_TOKEN=your_github_token_here
```

### 3. Start Service

```bash
# Linux
sudo systemctl start pr-agent

# macOS
launchctl start com.mstriebeck.github_mcp_server
# (Service auto-starts on login and auto-restarts if it stops)
```

### 4. Manage Repositories

```bash
# Linux
sudo /opt/github-agent/.venv/bin/python /opt/github-agent/repository_cli.py list

# macOS
~/.local/share/github-agent/.venv/bin/python ~/.local/share/github-agent/repository_cli.py list

# Add more repositories
# Linux: sudo /opt/github-agent/.venv/bin/python /opt/github-agent/repository_cli.py add <name> <path>
# macOS: ~/.local/share/github-agent/.venv/bin/python ~/.local/share/github-agent/repository_cli.py add <name> <path>
```

### 5. Check Status

```bash
# Linux
sudo systemctl status pr-agent

# macOS
launchctl list | grep github_mcp
```

### 6. Access Your Repositories

Each repository gets its own endpoint and is automatically configured in VSCode:
- Repository 1: `http://localhost:8081/mcp/` (configured in `.vscode/settings.json`)
- Repository 2: `http://localhost:8082/mcp/` (configured in `.vscode/settings.json`)
- Health checks: `http://localhost:8081/health`

---

## ⚙️ Configuration

### Repository Configuration

The system uses a JSON configuration file (`repositories.json`) to manage multiple repositories:

```json
{
  "repositories": {
    "my-repo": {
      "path": "/path/to/my-repo",
      "port": 8081,
      "description": "My project repository"
    },
    "other-repo": {
      "path": "/path/to/other-repo", 
      "port": 8082,
      "description": "Another project"
    }
  }
}
```

### CLI Management

Use the repository CLI to manage your configuration:

```bash
# List repositories and their status
python3 repository_cli.py list

# Add a new repository  
python3 repository_cli.py add <name> <path> --description="Description"

# Remove a repository
python3 repository_cli.py remove <name>

# Assign ports automatically
python3 repository_cli.py assign-ports --start-port=8081

# Check system status
python3 repository_cli.py status

# Validate configuration
python3 repository_cli.py validate
```

### Environment Variables

```bash
# Required
export GITHUB_TOKEN=your_github_token_here

# Optional
export GITHUB_AGENT_REPO_CONFIG=/path/to/repositories.json  # Custom config location
export SERVER_HOST=0.0.0.0                                  # Host to bind to
export GITHUB_AGENT_DEV_MODE=true                          # Enable hot reload
```

### Log Files

Logs are stored in `~/.local/share/github-agent/logs/`:
- `master.log` - Master process logs
- `<repo-name>.log` - Individual worker logs per repository

---

## 🔧 Available Tools

Each repository provides these MCP tools:

- **`git_get_current_branch`** - Get current Git branch name
- **`git_get_current_commit`** - Get current commit information  
- **`github_find_pr_for_branch`** - Find PR associated with a branch
- **`github_get_pr_comments`** - Get all comments from a PR
- **`github_post_pr_reply`** - Reply to a PR comment
- **`github_get_build_status`** - Get CI/CD build status for commits
- **`github_get_lint_errors`** - Extract linting errors from CI logs
- **`github_get_build_and_test_errors`** - Extract build errors, warnings, and test failures

---

## 🐛 Troubleshooting

### Check Service Status
```bash
# Linux
sudo systemctl status pr-agent
sudo journalctl -u pr-agent -f

# macOS
launchctl list | grep github_mcp
tail -f ~/.local/share/github-agent/logs/github_mcp_server.log
```

### View Logs
```bash
# Linux
sudo journalctl -u pr-agent -f
tail -f /var/log/github_mcp_server.log

# macOS
tail -f ~/.local/share/github-agent/logs/master.log
tail -f ~/.local/share/github-agent/logs/<repo-name>.log
```

### Restart Service
```bash
# Linux
sudo systemctl restart pr-agent

# macOS (auto-restarts due to KeepAlive)
launchctl stop com.mstriebeck.github_mcp_server
# Service will automatically restart
```

### Stop Service Permanently
```bash
# Linux
sudo systemctl stop pr-agent
sudo systemctl disable pr-agent

# macOS
launchctl unload ~/Library/LaunchAgents/com.mstriebeck.github_mcp_server.plist
```

### Manual Testing
```bash
# Test individual repository endpoints
curl http://localhost:8081/health
curl http://localhost:8082/health

# Test MCP endpoint
curl http://localhost:8081/
```

### Common Issues

1. **Service won't start**: Check logs and GitHub token in `.env` file
2. **Port conflicts**: Restart service or reassign ports via repository CLI
3. **Repository not found**: Check paths via repository CLI
4. **Permission issues** (Linux): Ensure www-data has access to repository paths

---

## 📋 Migration from Single-Port

To migrate from the old single-port server:

1. **Stop old service**:
   ```bash
   # macOS (permanently stop)
   launchctl unload ~/Library/LaunchAgents/com.mstriebeck.github_mcp_server.plist
   
   # Linux  
   sudo systemctl stop pr-agent
   sudo systemctl disable pr-agent
   ```

2. **Configure repositories**:
   ```bash
   python3 repository_cli.py init --example
   python3 repository_cli.py add <repo-name> <repo-path>
   python3 repository_cli.py assign-ports
   ```

3. **Start multi-port server**:
   ```bash
   python3 github_mcp_master.py
   ```

4. **Update MCP client configurations** to use new dedicated ports instead of URL routing

---

## 🔐 Important: Agent User Setup

**The code must be submitted by a different user (the "agent" user).** GitHub's API has limitations that prevent the PR author from replying to their own review comments.

1. **Create a separate GitHub user** and invite them to your project
2. **Generate a classic GitHub token** (not fine-grained) with `repo` scope  
3. **Checkout the repository as the agent user**
4. **Use the agent user's token** in `GITHUB_TOKEN` environment variable

### Agent User NOT logged in user
Often, the agent user won't be a real user and in particular, you won't be logged in as the agent user. In this case, we need to:

1. **Create SSH keys for the agent user** 
```bash
ssh-keygen -t ed25519 -C "mark.striebeck+agent@gmail.com" -f ~/.ssh/id_mstriebeck_agent
```
2. **Upload the public SSH key of the agent user to GitHub**
3. **Configure SSH for this repository**
```bash
# Edit ~/.ssh/config
Host github-agent
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_agent
    IdentitiesOnly yes
```
4. **Update the repository's remote URL**
```bash
git remote set-url origin git@github-agent:mstriebeck/github-agent.git
```
5. **Set user.name and user.email to the agent user**
6. **You can test the connection with**
```bash
ssh -T git@github-agent
# Should show: Hi mstriebeck-agent! You've successfully authenticated...
```

**Critical:** The agent user must create the pull request, not the main user!

---

## 📚 Documentation

* **[Multi-Repository Setup](MULTI_REPO_README.md)** - Detailed multi-repository configuration guide
* **[HTTP Services Setup](HTTP_SERVICES_README.md)** - Legacy single-port deployment guide

---

## 📁 File Structure

### Multi-Port Architecture (Current)
* **`github_mcp_master.py`** - Master process that spawns and monitors workers
* **`github_mcp_worker.py`** - Worker process for individual repositories
* **`repository_manager.py`** - Repository configuration management
* **`repository_cli.py`** - Command-line interface for configuration management
* **`repositories.json`** - Repository configuration file

### Legacy Single-Port
* **`github_mcp_server.py`** - Original unified server with URL routing

### Configuration & Deployment
* **`requirements.txt`** - Python dependencies
* **`install-services.sh`** - Legacy service installation script
* **`systemd/pr-agent.service`** - Systemd service file
* **`config/services.env`** - Configuration template

### Documentation
* **`README.md`** - This file (multi-port architecture guide)
* **`MULTI_REPO_README.md`** - Detailed multi-repository setup
* **`HTTP_SERVICES_README.md`** - Legacy HTTP server guide
* **`improvements/multi-port-architecture.md`** - Technical architecture specification

---

## 🎯 Benefits of Multi-Port Architecture

### Technical Benefits
- **Better Client Compatibility** - Each repository appears as separate MCP server
- **Process Isolation** - Issues in one repository don't affect others  
- **Cleaner Architecture** - Simplified worker processes, clear separation of concerns
- **Easier Debugging** - Clear process boundaries and dedicated logs

### User Experience Benefits
- **Reliable Connections** - No more timeout issues with MCP handshakes
- **Independent Operation** - Can restart/debug individual repositories
- **Clean URLs** - Simpler endpoint management (`localhost:8081/mcp/`)
- **Better Scalability** - Easy to add new repositories

---
