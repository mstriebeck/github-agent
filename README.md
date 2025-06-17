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
   # Set your GITHUB_TOKEN and GITHUB_REPO
   ```

3. **Start the service:**
   ```bash
   sudo systemctl start pr-agent
   ```

4. **Check status:**
   ```bash
   curl http://localhost:8080/health
   ```

### Setup - Agent User

The code must be submitted by a different user (the "agent" user). Otherwise the comment and reply functionality does not work. So, first, create a separate user in GitHub and invite them to your project.

#### 🧪 Github Token

The Github tokens must be created by the "agent user"!!!

The Github Token needs to be a fine-grained token with the following permissions:
* content: read
* pull requests: read & write

Unfortunately, the GitHub API to post comments doesn't work with fine-grained tokens (yet), 
so we need a second classic token with the following permissions:
* repo → full access to private and public repo

#### Checking out under Agent User

As the code needs to be submitted under the Agent User, we need to checkout the code under that user. But for me, this was only a Github user, so I needed to checkout under this user while being logged into my dev computer under my user:

##### Step 1: Generate a new SSH key for agent user
```
ssh-keygen -t ed25519 -C "<agent user>" -f ~/.ssh/id_ed25519_agent
```
When prompted for a passphrase: optional (recommended for security)

This creates:
* ~/.ssh/id_ed25519_agent
* ~/.ssh/id_ed25519_agent.pub

##### Step 2: Add the public key to agent GitHub account
1. Log into github.com as `<agent user>`
2. Go to SSH and GPG Keys
3. Click "New SSH Key"
4. Title: Local Dev Machine
5. Paste the contents of ~/.ssh/id_ed25519_agent.pub

##### Step 3: Add a custom SSH config block
Edit (or create) your ~/.ssh/config and add:
```
Host github-agent
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_agent
    IdentitiesOnly yes
```

##### Step 4: Clone the repo via alias host
Clone the repository with
```
git clone git@github-agent:<agent user>/<repository>.git
```
This forces Git to use the `<agent user>` identity (even though you're logged into GitHub as yourself.

##### Step 5: Set user to `<agent user>`
Inside the repository run
```
git config user.name "<agent user>"
git config user.email "<agent user email>"
```

IMPORTANT: THE AGENT USER HAS TO CREATE THE PULL REQUEST!!! IF THE PULL REQUEST IS CREATED BY THE MAIN USER,
WE CAN'T RESPOND TO COMMENTS (yes, weird GitHub API limitation!!!)

---

## 🧪 Local Environment Setup

### 1. Create and activate a virtual environment (recommended)

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
pip install -r requirements-http.txt
```

### 3. Add `.venv/` to `.gitignore`

```bash
echo ".venv/" >> .gitignore
```

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
* `requirements.txt` - Core Python dependencies
* `requirements-http.txt` - HTTP server dependencies

### Documentation
* `HTTP_SERVICES_README.md` - HTTP server deployment guide
* `PR-REVIEW-AGENT-SETUP-GUIDE.md` - Detailed setup instructions
* `PR_QUEUE_README.md` - Queue system documentation

---

## 🗑️ Legacy Files (Obsolete)

The following files are from the original CLI-based implementation and are no longer needed:

### CLI Scripts (replaced by HTTP API)
* ~~`pull_pr_comments.py`~~ - Replaced by HTTP `/execute` endpoint
* ~~`reply_to_github_comments.py`~~ - Replaced by HTTP reply functionality
* ~~`github_query.py`~~ - Functionality moved to core server
* ~~`run_tool_cli.py`~~ - Replaced by HTTP API

### Separate HTTP Servers (replaced by unified server)
* ~~`pr_review_http_server.py`~~ - Replaced by `pr_agent_server.py`
* ~~`pr_worker_service.py`~~ - Replaced by `pr_agent_server.py`

### Old Systemd Services
* ~~`systemd/pr-review-server.service`~~ - Replaced by `systemd/pr-agent.service`
* ~~`systemd/pr-worker-service.service`~~ - Replaced by `systemd/pr-agent.service`

### Old Shell Scripts
* ~~`run_pr_server.sh`~~ - Replaced by systemd service

These files can be safely deleted to clean up the repository.

---
