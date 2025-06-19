# Generic GitHub PR Review Agent with Pluggable Coding Agent Support

## 🧾 Requirements

### Goal

Build an agent that automatically manages communication between GitHub and a local or remote coding agent, such as AMP. It should:

* Monitor PR review comments
* Send structured requests to the coding agent
* Process agent responses
* Reply to GitHub review comments accordingly

---

## 🚀 Current Implementation: HTTP Server

The agent now runs as a unified HTTP server that can be deployed as a systemd service. This provides:

* **PR Management Tools** - All tools accessible via HTTP API
* **Background Worker** - Automatic processing of queued PR replies
* **Management Interface** - HTTP endpoints to control and monitor the system
* **Production Ready** - Proper logging, error handling, and service management

### Quick Start

1. **Install the service:**
   ```bash
   # Linux (requires sudo)
   sudo ./scripts/install-services.sh
   
   # macOS (installs to user space)
   ./scripts/install-services.sh
   ```

2. **Configure environment:**
   ```bash
   # Linux
   sudo nano /opt/github-agent/.env
   
   # macOS  
   nano ~/.local/share/github-agent/.env
   
   # Set your GITHUB_TOKEN (repo is auto-detected)
   ```

3. **Start the service:**
   ```bash
   # Linux
   sudo systemctl start pr-agent
   
   # macOS
   launchctl start com.mstriebeck.github_mcp_server
   # (Service auto-starts on login)
   ```

4. **Check status:**
   ```bash
   curl http://localhost:8080/health
   ```

5. **Stop the service:**
   ```bash
   # Linux
   sudo systemctl stop pr-agent
   
   # macOS (permanently stop - service has KeepAlive enabled)
   launchctl unload ~/Library/LaunchAgents/com.mstriebeck.github_mcp_server.plist
   
   # macOS (temporary stop - will auto-restart)
   launchctl stop com.mstriebeck.github_mcp_server
   ```

### Troubleshooting (macOS)

If the service doesn't start on macOS, try these steps:

1. **Check if service is loaded:**
   ```bash
   launchctl list | grep github_mcp
   ```

2. **Check the logs:**
   ```bash
   tail -f ~/.local/share/github-agent/logs/github_mcp_server.log
   ```

3. **Unload and reload the service:**
   ```bash
   launchctl unload ~/Library/LaunchAgents/com.github.pr-agent.plist
   launchctl load ~/Library/LaunchAgents/com.github.pr-agent.plist
   ```

4. **Run manually for debugging:**
   ```bash
   cd ~/.local/share/github-agent
   source .venv/bin/activate
   python github_mcp_server.py
   ```

### Important: Agent User Setup

**The code must be submitted by a different user (the "agent" user).** GitHub's API has limitations that prevent the PR author from replying to their own review comments.

1. **Create a separate GitHub user** and invite them to your project
2. **Generate a classic GitHub token** (not fine-grained) with `repo` scope  
3. **Checkout the repository as the agent user** (see [HTTP Services Setup](HTTP_SERVICES_README.md) for detailed SSH setup)

**Critical:** The agent user must create the pull request, not the main user!

---

## 📚 Documentation

* **[HTTP Services Setup](HTTP_SERVICES_README.md)** - Complete deployment, API documentation, and troubleshooting guide

---

## 📁 Current Files

### Core Server Components
* `github_mcp_server.py` - Unified HTTP server (both core GitHub management functions and background worker for processing replies)

### Configuration & Deployment
* `install-services.sh` - Installation script
* `systemd/pr-agent.service` - Systemd service file
* `config/services.env` - Configuration template
* `requirements.txt` - Python dependencies

### Documentation
* `HTTP_SERVICES_README.md` - HTTP server deployment guide
* `PR-REVIEW-AGENT-SETUP-GUIDE.md` - Detailed setup instructions

---
