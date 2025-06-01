import requests
import logging

def fetch_review_comments(repo_owner, repo_name, branch, commit_sha, github_token):
    headers = {"Authorization": f"token {github_token}"}
    url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/pulls"
    try:
        prs = requests.get(url, headers=headers).json()
    except Exception as e:
        logging.error(f"❌ Failed to fetch PRs: {e}")
        return []

    comments = []
    for pr in prs:
        if pr.get("head", {}).get("ref") == branch and pr.get("head", {}).get("sha") == commit_sha:
            try:
                comments_url = pr["review_comments_url"]
                comments = requests.get(comments_url, headers=headers).json()
            except Exception as e:
                logging.error(f"❌ Failed to fetch comments: {e}")
            break
    return comments
