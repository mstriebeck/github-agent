# Generic GitHub PR Review Agent with Pluggable Coding Agent Support

## 🧾 Requirements

### Goal

Build an agent that automatically manages communication between GitHub and a local or remote coding agent, such as AMP. It should:

* Monitor PR review comments
* Send structured requests to the coding agent
* Process agent responses
* Reply to GitHub review comments accordingly

---

## 🚧 Phase 1: CLI-Based Workflow

A manual CLI-based setup with two separate scripts. This is easier to debug and extend before moving to a webhook or GitHub Action.

### Setup - Agent User

The code must be submitted by a different user (the "agent" user). Otherwise the comment and reply functionality does not work. So, first, create a separate user in GitHub and invite them to your project.

#### 🧪 Github Token

The Github tokens must be created by the "agent user"!!!

The Github Token needs to be a fine-grained token with the following permissions:
* content: read
* pull requests: read & write

Unfortunately, the GitHub API to post comments doesn't work with fine-grained tokens (yet), 
so we need a second classit token with the following permissions:
* repo → full access to private and public repo

#### Checking out under Agent User

As the code needs to be submitted under the Agent User, we need to checkout the code under that user. But for me, this was only a Github user, so I needed to checkout under this user while being logged into my dev computer under my user:

##### Step 1: Generate a new SSH key for mstriebeck-agent
```
ssh-keygen -t ed25519 -C "<agent user>" -f ~/.ssh/id_ed25519_agent
```
When prompted for a passphrase: optional (recommended for security)

This creates:
* ~/.ssh/id_ed25519_agent
* ~/.ssh/id_ed25519_agent.pub

##### Step 2: Add the public key to mstriebeck-agent GitHub account
1. Log into github.com as `<agent user>`
2. Go to SSH and GPG Keys
3. Click “New SSH Key”
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
This forces Git to use the `<agent user>` identity (even though you’re logged into GitHub as yourself.

##### Step 5: Set user to `<agent user>`
Inside the repository run
```
git config user.name "<agent user>"
git config user.email "<agent user email>"
```

IMPORTANT: THE AGENT USER HAS TO CREATE THE PULL REQUEST!!! IF THE PULL REQUEST IS CREATED BY THE MAIN USER,
WE CAN'T RESPOND TO COMMENTS (yes, weird GitHub API limitation!!!)

### 🔍 Step 1: Extract PR Review Comments

IMPORTANT: For the reply functionality to work, you must use "Start a review" - NOT "Add single comment" in the GitHub UI!

Script: `pull_pr_comments.py`

* Detects current branch and commit
* Queries GitHub for PR review comments on that commit
* Two output modes:

  * `--mode text`: prints structured output for copy/paste into an agent like AMP
  * `--mode send`: sends messages directly to an agent via MCP

### 🧠 Step 2: Send to AMP or Other Agent

* If using `--mode text`, user manually pastes comments into the agent chat (e.g., AMP)
* The agent will be instructed to respond to each comment in the format:

```
[comment_id: 12345678]
Reply: This has been refactored as requested.
```

### 📬 Step 3: Post Replies to GitHub

Script: `reply_to_github_comments.py`

* Asks for user input (copy/paste AMP’s structured response from Step 2)
* Parses comment IDs and reply text
* Posts replies to the corresponding GitHub comments via API

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
```

### 3. Add `.venv/` to `.gitignore`

```bash
echo ".venv/" >> .gitignore
```

---

## 📁 Files in This Project

* `pull_pr_comments.py`: Pulls comments from GitHub and prints or sends them
* `reply_to_github_comments.py`: Posts agent replies to GitHub review comments
* `github_query.py`: Handles GitHub API interactions for querying comments
* `requirements.txt`: Python dependencies
* `.env.example`: Environment variable configuration sample

---

