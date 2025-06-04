import logging
import requests
import re
import subprocess
import unicodedata

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

GITHUB_TOKEN = ""

# Get repo information programmatically
REPO_URL = subprocess.getoutput("git config --get remote.origin.url").strip()
logging.info(f"{REPO_URL=}")

# Remove the '.git' suffix and parse owner/repo
repo_url_without_git_suffix = REPO_URL.removesuffix('.git')
parts = repo_url_without_git_suffix.split(':')

if len(parts) > 1:
    owner_repo_path = parts[1]
    owner_repo_split = owner_repo_path.split('/')

    if len(owner_repo_split) == 2:
        REPO_OWNER = owner_repo_split[0]
        REPO_NAME = owner_repo_split[1]
        logging.info(f"Extracted Owner: {REPO_OWNER}")
        logging.info(f"Extracted Repo Name: {REPO_NAME}")
    else:
        logging.error("❌ Could not parse owner/repo from URL.")
        exit(1)
else:
    logging.error("❌ Invalid SSH URL format.")
    exit(1)

def post_reply(comment_id, body):
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/pulls/comments/{comment_id}/replies"
    logging.info(f"Using {url=}")
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    data = {"body": body}
    response = requests.post(url, headers=headers, json=data)
    if response.status_code in [200, 201]:
        logging.info(f"✅ Replied to {comment_id}: {response.status_code}")
    else:
        logging.error(f"❌ Failed to send reply: {response.status_code=} {response.text=}")

print("📥 Paste AMP-generated responses below. End input with a blank line:")

# Read all input as one text block
raw_block = ""
while True:
    try:
        line = input()
        if line.strip() == "":
            break
        raw_block += line + "\n"
    except EOFError:
        break

# Normalize and clean
normalized_block = unicodedata.normalize("NFKC", raw_block.replace("\u2028", "\n").replace("\u00A0", " "))

# Split into comment blocks
blocks = re.split(r"\[comment_id:\s*(\d+)]", normalized_block)

responses = {}
for i in range(1, len(blocks), 2):
    cid = blocks[i].strip()
    reply_text = blocks[i + 1].strip()
    responses[cid] = reply_text

if not responses:
    logging.warning("⚠️ No valid comment_id blocks found in the input.")

# Post each reply
for cid, reply in responses.items():
    post_reply(cid, reply)
