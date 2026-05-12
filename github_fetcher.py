"""
GitHub API client for fetching closed issues and repository metadata.
"""

import requests
from urllib.parse import urlparse
from datetime import datetime, timedelta, timezone

from config import (
    GITHUB_API_BASE,
    GITHUB_ISSUES_PER_PAGE,
    GITHUB_ISSUE_BODY_MAX_CHARS,
)


def parse_repo_url(url: str) -> tuple[str, str]:
    """Extract owner and repo name from a GitHub URL.

    Accepts formats:
        https://github.com/owner/repo
        https://github.com/owner/repo/issues
        github.com/owner/repo
        owner/repo
    """
    url = url.strip().rstrip("/")

    if "/" in url and not url.startswith("http"):
        if "github.com" in url:
            url = "https://" + url
        else:
            parts = url.split("/")
            if len(parts) == 2:
                return parts[0], parts[1]

    parsed = urlparse(url)
    path = parsed.path.strip("/")
    parts = path.split("/")

    if len(parts) < 2:
        raise ValueError(
            f"Invalid GitHub URL: {url}. "
            "Expected format: https://github.com/owner/repo"
        )

    return parts[0], parts[1]


def compute_since_date(days_ago: int) -> str:
    """Return an ISO 8601 date string for N days ago."""
    since = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return since.strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_headers(token: str | None = None) -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def check_rate_limit(token: str | None = None) -> dict:
    """Check current GitHub API rate limit status."""
    resp = requests.get(
        f"{GITHUB_API_BASE}/rate_limit",
        headers=_build_headers(token),
        timeout=10,
    )
    resp.raise_for_status()
    core = resp.json()["resources"]["core"]
    reset_time = datetime.fromtimestamp(core["reset"], tz=timezone.utc)
    return {
        "limit": core["limit"],
        "remaining": core["remaining"],
        "reset_at": reset_time.isoformat(),
    }


def fetch_closed_issues(
    owner: str,
    repo: str,
    since_date: str,
    token: str | None = None,
    progress_callback=None,
) -> list[dict]:
    """Fetch all closed issues from a GitHub repo since a given date.

    Args:
        owner: Repository owner (e.g. "opensearch-project")
        repo: Repository name (e.g. "OpenSearch")
        since_date: ISO 8601 date string — only issues updated after this date
        token: Optional GitHub personal access token for higher rate limits
        progress_callback: Optional callable(fetched_count, page) for progress updates

    Returns:
        List of issue dicts with keys: number, title, body, labels,
        created_at, closed_at, url, comments_count
    """
    headers = _build_headers(token)
    all_issues = []
    page = 1

    while True:
        resp = requests.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues",
            headers=headers,
            params={
                "state": "closed",
                "since": since_date,
                "per_page": GITHUB_ISSUES_PER_PAGE,
                "page": page,
                "sort": "updated",
                "direction": "desc",
            },
            timeout=30,
        )
        resp.raise_for_status()
        issues = resp.json()

        if not issues:
            break

        for issue in issues:
            # GitHub API returns pull requests in the issues endpoint — skip them
            if "pull_request" in issue:
                continue

            body_raw = issue.get("body") or ""
            all_issues.append({
                "number": issue["number"],
                "title": issue["title"],
                "body": body_raw[:GITHUB_ISSUE_BODY_MAX_CHARS],
                "labels": [label["name"] for label in issue.get("labels", [])],
                "created_at": issue["created_at"],
                "closed_at": issue.get("closed_at"),
                "url": issue["html_url"],
                "comments_count": issue.get("comments", 0),
            })

        if progress_callback:
            progress_callback(len(all_issues), page)

        # If we got fewer results than per_page, we've reached the last page
        if len(issues) < GITHUB_ISSUES_PER_PAGE:
            break

        page += 1

    return all_issues


def fetch_repo_info(owner: str, repo: str, token: str | None = None) -> dict:
    """Fetch basic repository metadata."""
    resp = requests.get(
        f"{GITHUB_API_BASE}/repos/{owner}/{repo}",
        headers=_build_headers(token),
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        "full_name": data["full_name"],
        "description": data.get("description", ""),
        "stars": data["stargazers_count"],
        "forks": data["forks_count"],
        "open_issues": data["open_issues_count"],
        "language": data.get("language", "Unknown"),
        "default_branch": data.get("default_branch", "main"),
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
    }


def fetch_repo_structure(
    owner: str,
    repo: str,
    branch: str = "main",
    token: str | None = None,
) -> list[str]:
    """Fetch the file tree of a repository (for hotspot mapping in Stage 3).

    Returns a list of file paths in the repository.
    """
    resp = requests.get(
        f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/trees/{branch}",
        headers=_build_headers(token),
        params={"recursive": "1"},
        timeout=30,
    )
    resp.raise_for_status()
    tree = resp.json().get("tree", [])
    return [item["path"] for item in tree if item["type"] == "blob"]
