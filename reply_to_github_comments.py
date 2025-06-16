import os
from os.path import join
import re
import subprocess
import unicodedata
import logging
import requests
from typing import Dict, Tuple
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

dotenv_path = join(os.getcwd(), '.env')
load_dotenv(dotenv_path)
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
logging.info(f"{GITHUB_TOKEN=}")

# --- Extract repo info ---
REPO_URL = subprocess.getoutput("git config --get remote.origin.url").strip()
logging.info(f"{REPO_URL=}")
repo_url_without_git_suffix = REPO_URL.removesuffix('.git')
REPO_OWNER, REPO_NAME = repo_url_without_git_suffix.split(":")[-1].split("/")
logging.info(f"{REPO_OWNER=}  {REPO_NAME=}")

# --- Get branch and PR number ---
local_branch = subprocess.getoutput("git rev-parse --abbrev-ref HEAD").strip()
logging.info(f"{local_branch=}")

pr_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/pulls?head={REPO_OWNER}:{local_branch}&state=open"
headers = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json"
}

res = requests.get(pr_url, headers=headers)
res.raise_for_status()
pr_data = res.json()

if not pr_data:
    raise RuntimeError(f"No open PR found for branch {local_branch}")

PR_NUMBER = str(pr_data[0]["number"])
commit_id = pr_data[0]["head"]["sha"]
logging.info(f"{PR_NUMBER=}")
logging.info(f"{commit_id=}")

# --- Parse AMP-generated responses ---
print("📥 Paste AMP-generated responses below. End input with a blank line:")
raw_block = ""
while True:
    try:
        line = input()
        if line.strip() == "":
            break
        raw_block += line + "\n"
    except EOFError:
        break

normalized = unicodedata.normalize("NFKC", raw_block.replace("\u2028", "\n").replace("\u00A0", " "))
logging.info(f"Raw input length: {len(normalized)}")

# Enhanced pattern matching to capture original comments
responses = {}
# Match format: [comment_id: 12345 - path/to/file.swift:42 - original_comment: "text"]
# Reply: response text
pattern = r'\[comment_id:\s*(\d+)\s*-\s*(.+?):(\d+)\s*-\s*original_comment:\s*"(.+?)"\]\s*\n?Reply:\s*(.+?)(?=\n\[comment_id:|$)'

for match in re.finditer(pattern, normalized, re.DOTALL):
    cid, path, line, original_comment, reply = match.groups()
    responses[cid.strip()] = {
        "body": reply.strip(),
        "path": path.strip(),
        "line": int(line.strip()),
        "original_comment": original_comment.strip()
    }

logging.info(f"Parsed {len(responses)} responses.")

# --- GitHub API helper functions ---
def reply_to_comment(comment_id: str, reply_body: str) -> Tuple[bool, str]:
    """
    Try to reply directly to a comment using GitHub's reply endpoint.
    Returns (success, error_message)
    """
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/pulls/comments/{comment_id}/replies"
    data = {"body": reply_body}
    
    try:
        res = requests.post(url, headers=headers, json=data)
        if res.status_code in [200, 201]:
            logging.info(f"✅ Successfully replied to comment {comment_id}")
            return True, ""
        else:
            error_msg = f"Status {res.status_code}: {res.text}"
            logging.warning(f"❌ Failed to reply to comment {comment_id}: {error_msg}")
            return False, error_msg
    except Exception as e:
        error_msg = f"Exception: {str(e)}"
        logging.warning(f"❌ Exception replying to comment {comment_id}: {error_msg}")
        return False, error_msg

def post_line_comment(path: str, line: int, body: str) -> Tuple[bool, str]:
    """
    Try to post a new comment on a specific line.
    Returns (success, error_message)
    """
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/pulls/{PR_NUMBER}/comments"
    data = {
        "body": body,
        "commit_id": commit_id,
        "path": path,
        "side": "RIGHT",
        "line": line
    }
    
    try:
        res = requests.post(url, headers=headers, json=data)
        if res.status_code in [200, 201]:
            logging.info(f"✅ Posted new comment on {path}:{line}")
            return True, ""
        else:
            error_msg = f"Status {res.status_code}: {res.text}"
            logging.warning(f"❌ Failed to post line comment on {path}:{line}: {error_msg}")
            return False, error_msg
    except Exception as e:
        error_msg = f"Exception: {str(e)}"
        logging.warning(f"❌ Exception posting line comment on {path}:{line}: {error_msg}")
        return False, error_msg

def post_general_review_comment(body: str) -> Tuple[bool, str]:
    """
    Post a general review comment (not tied to a specific line).
    Returns (success, error_message)
    """
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/pulls/{PR_NUMBER}/reviews"
    data = {
        "commit_id": commit_id,
        "body": body,
        "event": "COMMENT"
    }
    
    try:
        res = requests.post(url, headers=headers, json=data)
        if res.status_code in [200, 201]:
            logging.info(f"✅ Posted general review comment")
            return True, ""
        else:
            error_msg = f"Status {res.status_code}: {res.text}"
            logging.error(f"❌ Failed to post general review comment: {error_msg}")
            return False, error_msg
    except Exception as e:
        error_msg = f"Exception: {str(e)}"
        logging.error(f"❌ Exception posting general review comment: {error_msg}")
        return False, error_msg

def post_comment_with_fallbacks(comment_id: str, context: Dict) -> bool:
    """
    Try to post a comment with multiple fallback strategies:
    1. Reply directly to the original comment
    2. Post a new comment on the same line
    3. Post a general review comment with context
    
    Returns True if any strategy succeeded, False if all failed.
    """
    reply_body = context["body"]
    path = context["path"]
    line = context["line"]
    original_comment = context["original_comment"]
    
    # Strategy 1: Try to reply directly to the comment
    success, error = reply_to_comment(comment_id, reply_body)
    if success:
        return True
    
    logging.info(f"🔄 Fallback 1: Trying to post new comment on {path}:{line}")
    
    # Strategy 2: Try to post a new comment on the same line
    success, error = post_line_comment(path, line, reply_body)
    if success:
        return True
    
    logging.info(f"🔄 Fallback 2: Posting general review comment with context")
    
    # Strategy 3: Post a general review comment with full context
    contextual_body = f"""**Re: Comment on `{path}:{line}`**

> {original_comment}

{reply_body}"""
    
    success, error = post_general_review_comment(contextual_body)
    return success

# --- Process all responses ---
successful_posts = 0
failed_posts = 0

for cid, context in responses.items():
    logging.info(f"📤 Processing comment {cid}")
    
    if post_comment_with_fallbacks(cid, context):
        successful_posts += 1
    else:
        failed_posts += 1
        logging.error(f"❌ All strategies failed for comment {cid}")

# --- Summary ---
print(f"\n📊 Summary:")
print(f"✅ Successfully posted: {successful_posts}")
print(f"❌ Failed to post: {failed_posts}")
print(f"📝 Total responses processed: {len(responses)}")

if failed_posts > 0:
    print(f"\n⚠️  {failed_posts} responses could not be posted. Check logs for details.")
