# Generic GitHub PR Review Agent with Pluggable Coding Agent Support

## 🧾 Requirements

### Functional

* Automatically receive GitHub PR review comments
* Forward them to a coding agent via a standardized interface (e.g., MCP)
* Each comment should be addressed independently by the agent
* Only process comments that match the local branch and commit of the workspace

### Technical

* GitHub webhook listener for `pull_request_review_comment` events
* Pluggable interface to deliver messages to a coding agent
* Contextual information like file path, line number, PR URL, branch, and commit

### Optional Enhancements

* State tracking to avoid duplicate handling
* Multi-turn response support for follow-up
* Query GitHub for missed comments for a given branch/commit

---

## 🏗️ High-Level Architecture

```
GitHub PR Review Comment
       ↓ (Webhook)
[Webhook Listener/API Server]
       ↓ (Construct Message)
     [Agent Message Sender (MCP/other)]
       ↓ (Agent Processes)
    [Response/Feedback Loop]
```

---

## 🧩 Components

### 1. GitHub Webhook Listener (Python Flask)

```python
from flask import Flask, request, jsonify
import requests
import os
import subprocess

app = Flask(__name__)

AGENT_ENDPOINT = os.getenv("AGENT_ENDPOINT", "http://localhost:5001/mcp")

@app.route("/github-webhook", methods=["POST"])
def github_webhook():
    data = request.json

    if data.get("action") == "created" and "comment" in data:
        comment = data["comment"]["body"]
        path = data["comment"].get("path", "<unknown file>")
        line = data["comment"].get("position", 0)
        pr_url = data["pull_request"]["html_url"]
        pr_commit = data["pull_request"]["head"]["sha"]
        pr_branch = data["pull_request"]["head"]["ref"]

        # Check if local Git state matches
        local_commit = subprocess.getoutput("git rev-parse HEAD").strip()
        local_branch = subprocess.getoutput("git rev-parse --abbrev-ref HEAD").strip()

        if pr_commit != local_commit or pr_branch != local_branch:
            return jsonify({"status": "skipped", "reason": "comment not for current workspace"})

        agent_payload = {
            "agent": "generic-agent",
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"Please address this GitHub PR review comment:\n\n"
                        f"> {comment}\n\n"
                        f"File: `{path}`, line {line}.\n"
                        f"PR: {pr_url}\n"
                        f"Branch: {pr_branch}, Commit: {pr_commit}"
                    )
                }
            ]
        }

        res = requests.post(AGENT_ENDPOINT, json=agent_payload)
        return jsonify({"status": "forwarded", "response": res.status_code})

    return jsonify({"status": "ignored"})
```

---

### 2. Optional GitHub Query Logic

To catch up on missed comments:

```python
def fetch_review_comments(repo_owner, repo_name, branch, commit_sha, github_token):
    headers = {"Authorization": f"token {github_token}"}
    url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/pulls"
    prs = requests.get(url, headers=headers).json()
    comments = []
    for pr in prs:
        if pr["head"]["ref"] == branch and pr["head"]["sha"] == commit_sha:
            comments_url = pr["review_comments_url"]
            comments = requests.get(comments_url, headers=headers).json()
            break
    return comments
```

This can be run manually or during agent startup.

---

## 🚀 Setup & Deployment

### 1. Agent Setup

* Ensure your coding agent (AMP or other) listens for messages over HTTP (MCP or custom format)
* Configure the agent endpoint via `AGENT_ENDPOINT`

### 2. GitHub Webhook

* Configure webhook to send PR review comments

### 3. Local Dev

```bash
pip install flask requests
export AGENT_ENDPOINT="http://localhost:5001/mcp"
python webhook_agent.py
```

---

# AMP Integration (Specific Agent Layer)

If using AMP:

* `AGENT_ENDPOINT=http://localhost:5001/mcp`
* Use "agent": "amp" in the message payload
* Ensure AMP has access to the PR codebase

Example MCP payload:

```json
{
  "agent": "amp",
  "messages": [
    {
      "role": "user",
      "content": "Please address this GitHub PR review comment: ..."
    }
  ]
}
```

---

## ✅ Future Enhancements

* Authenticated GitHub webhook
* Persistent ID tracking
* Queue/resend missed comments
* Multi-agent dispatch support

---

Let me know if you want this split into two scripts or formalized as a Python package/module for broader use.
