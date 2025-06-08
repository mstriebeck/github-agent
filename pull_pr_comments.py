import subprocess
import requests
import logging
import argparse
from github_query import fetch_review_comments

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]

#AGENT_ENDPOINT = os.getenv("AGENT_ENDPOINT", "http://localhost:5001/mcp")

# Get repo information programmatically
REPO_URL = subprocess.getoutput("git config --get remote.origin.url").strip()
logging.info(f"{REPO_URL=}")
# 1. Remove the '.git' suffix if it exists
repo_url_without_git_suffix = REPO_URL.removesuffix('.git')

# 2. Split by ':' to separate the host/user part from the owner/repo part
parts = repo_url_without_git_suffix.split(':')

if len(parts) > 1:
    owner_repo_path = parts[1] # This will be 'mstriebeck/news_reader'
    
    # 3. Split the owner/repo path by '/'
    owner_repo_split = owner_repo_path.split('/')
    
    if len(owner_repo_split) == 2:
        REPO_OWNER = owner_repo_split[0]
        REPO_NAME = owner_repo_split[1]
        
        print(f"Extracted Owner: {REPO_OWNER}")    # Output: mstriebeck
        print(f"Extracted Repo Name: {REPO_NAME}")  # Output: news_reader
    else:
        print("Error: Could not parse owner/repo from URL.")
else:
    print("Error: Invalid SSH URL format.")

local_commit = subprocess.getoutput("git rev-parse HEAD").strip()
logging.info(f"{local_commit=}")
local_branch = subprocess.getoutput("git rev-parse --abbrev-ref HEAD").strip()
logging.info(f"{local_branch=}")

def output_as_text(comments):
    print("\n📝 Please address the following PR review comments:")
    print("\nIf a comment is a question, don't make code changes right away but first answer the question and then collaborate if and how it should be addressed.")
    for c in comments:
        body = c["body"]
        path = c.get("path", "<unknown file>")
        line = c.get("position", 0)
        cid = c.get("id", "n/a")
        original_line = c.get("original_line", line)  # For fallback positioning
        print(f"[comment_id: {cid}]\n- {path}:{line} → {body.strip()}\n")

    print("""
💡 INSTRUCTIONS:
- Only address the above PR comments (do not refactor unrelated code).
- After making changes, create a new commit summarizing what was done.
  The commit message should summarize all changes made to address the comments.
- Then respond to each comment using the same format (without a newline between responses!):
  [comment_id: <id> - <path>:<line> - original_comment: "<original_comment_text>"]
  Reply: <1-3 sentence reply>
  
  Note: Include the original_comment text so we can reference it if we need to post a general comment.
""")

def output_as_agent_messages(comments):
    message_list = []
    for c in comments:
        body = c["body"]
        path = c.get("path", "<unknown file>")
        line = c.get("position", 0)
        original_line = c.get("original_line", line)
        pr_url = c["pull_request_url"].replace("api.github.com/repos", "github.com").replace("/pulls/", "/pull/")
        cid = c.get("id", "")

        message_list.append({
            "role": "user",
            "content": (
                f"[comment_id: {cid}]\n"
                f"Please address this GitHub PR review comment:\n\n"
                f"> {body}\n\n"
                f"File: `{path}`, line {line} (original line: {original_line}).\n"
                f"PR: {pr_url}\n"
                f"Branch: {local_branch}, Commit: {local_commit}\n\n"
                f"When replying, use this format:\n"
                f"[comment_id: {cid} - {path}:{line} - original_comment: \"{body.replace('\"', '\\\"')}\"]\n"
                f"Reply: <your response>\n\n"
                f"Include the original_comment text so we can reference it if needed for fallback posting."
            )
        })

    agent_payload = {
        "agent": "generic-agent",
        "messages": message_list
    }

    try:
        res = requests.post(AGENT_ENDPOINT, json=agent_payload)
        logging.info(f"📤 Sent {len(message_list)} comment(s) to agent → status: {res.status_code}")
        logging.debug(res.text)
    except Exception as e:
        logging.error(f"❌ Failed to send payload: {e}")

def process_comments(mode):
    comments = fetch_review_comments(REPO_OWNER, REPO_NAME, local_branch, local_commit, GITHUB_TOKEN)
    if not comments:
        logging.info("✅ No comments for current branch/commit.")
        return

    if mode == "text":
        output_as_text(comments)
    elif mode == "send":
        output_as_agent_messages(comments)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["text", "send"], default="text",
                        help="Choose 'text' for CLI copy/paste or 'send' to post to MCP")
    args = parser.parse_args()
    process_comments(args.mode)
