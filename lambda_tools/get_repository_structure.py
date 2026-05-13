import json
import urllib.request
from collections import Counter

GITHUB_API_BASE = "https://api.github.com"


def get_repository_structure(repo_owner: str, repo_name: str, github_token: str = "") -> str:
    """Fetch the file tree of a GitHub repository."""
    try:
        url = f"{GITHUB_API_BASE}/repos/{repo_owner}/{repo_name}/git/trees/main?recursive=1"
        headers = {"Accept": "application/vnd.github+json"}
        if github_token:
            headers["Authorization"] = f"Bearer {github_token}"

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())

        files = [item["path"] for item in data.get("tree", []) if item["type"] == "blob"]

        dir_counts = Counter()
        for f in files:
            top_dir = f.split("/")[0] if "/" in f else "(root)"
            dir_counts[top_dir] += 1

        return json.dumps({
            "total_files": len(files),
            "directory_summary": dict(dir_counts.most_common(20)),
            "all_paths": files[:500],
        })
    except Exception as e:
        return json.dumps({"error": f"Could not fetch repo structure: {str(e)}"})
