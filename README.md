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
   sudo ./install-services.sh
   ```

2. **Configure environment:**
   ```bash
   sudo nano /opt/github-agent/.env
   # Set your GITHUB_TOKEN
   ```

3. **Start the service:**
   ```bash
   sudo systemctl start pr-agent
   ```

4. **Check status:**
   ```bash
   curl http://localhost:8080/health
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
* `pr_agent_server.py` - Unified HTTP server (main service)
* `pr_review_server.py` - Core PR management functions
* `pr_reply_worker.py` - Background worker for processing replies

### Configuration & Deployment
* `install-services.sh` - Installation script
* `systemd/pr-agent.service` - Systemd service file
* `config/services.env` - Configuration template
* `requirements.txt` - Python dependencies

### Documentation
* `HTTP_SERVICES_README.md` - HTTP server deployment guide
* `PR-REVIEW-AGENT-SETUP-GUIDE.md` - Detailed setup instructions

---
