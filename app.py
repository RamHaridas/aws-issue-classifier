"""
GitHub Issue Analyzer — Streamlit Application (Stage 1)

Usage:
    cd github_issue_analyzer
    streamlit run app.py
"""

import streamlit as st
import pandas as pd
from datetime import datetime, timezone

from github_fetcher import (
    parse_repo_url,
    compute_since_date,
    fetch_closed_issues,
    fetch_repo_info,
    check_rate_limit,
)
from config import DATE_RANGE_OPTIONS


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="GitHub Issue Analyzer",
    page_icon="🔍",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def issues_to_dataframe(issues: list[dict]) -> pd.DataFrame:
    """Convert raw issue dicts into a display-ready DataFrame."""
    rows = []
    for issue in issues:
        rows.append({
            "#": issue["number"],
            "Title": issue["title"],
            "Labels": ", ".join(issue["labels"]) if issue["labels"] else "—",
            "Comments": issue["comments_count"],
            "Created": issue["created_at"][:10],
            "Closed": (issue["closed_at"] or "")[:10],
            "URL": issue["url"],
        })
    df = pd.DataFrame(rows)
    return df


def render_repo_header(info: dict):
    """Render repository metadata as metric cards."""
    cols = st.columns(5)
    cols[0].metric("Stars", f"{info['stars']:,}")
    cols[1].metric("Forks", f"{info['forks']:,}")
    cols[2].metric("Open Issues", f"{info['open_issues']:,}")
    cols[3].metric("Language", info["language"])
    cols[4].metric("Default Branch", info["default_branch"])
    if info["description"]:
        st.caption(info["description"])


def render_label_summary(issues: list[dict]):
    """Show a bar chart of the most common GitHub labels."""
    label_counts: dict[str, int] = {}
    for issue in issues:
        for label in issue["labels"]:
            label_counts[label] = label_counts.get(label, 0) + 1

    if not label_counts:
        return

    sorted_labels = sorted(label_counts.items(), key=lambda x: x[1], reverse=True)[:15]
    df = pd.DataFrame(sorted_labels, columns=["Label", "Count"]).set_index("Label")
    st.bar_chart(df, horizontal=True)


def render_monthly_distribution(issues: list[dict]):
    """Show issues closed per month as a bar chart."""
    months: dict[str, int] = {}
    for issue in issues:
        closed = issue.get("closed_at")
        if closed:
            month_key = closed[:7]  # "2026-04"
            months[month_key] = months.get(month_key, 0) + 1

    if not months:
        return

    sorted_months = sorted(months.items())
    df = pd.DataFrame(sorted_months, columns=["Month", "Issues Closed"]).set_index("Month")
    st.bar_chart(df)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("🔍 GitHub Issue Analyzer")
    st.markdown("Analyze closed issues from any public GitHub repository.")
    st.divider()

    repo_url = st.text_input(
        "GitHub Repository URL",
        placeholder="https://github.com/opensearch-project/OpenSearch",
    )

    date_range = st.selectbox("Time Range", list(DATE_RANGE_OPTIONS.keys()))

    github_token = st.text_input(
        "GitHub Token (optional)",
        type="password",
        help="A personal access token increases the API rate limit from 60 to 5,000 requests/hour.",
    )

    fetch_button = st.button("🚀 Fetch Issues", use_container_width=True)

    st.divider()

    # Rate limit info
    if st.checkbox("Show API rate limit"):
        try:
            rl = check_rate_limit(github_token or None)
            st.info(
                f"**Remaining:** {rl['remaining']} / {rl['limit']}\n\n"
                f"**Resets at:** {rl['reset_at'][:19]}"
            )
        except Exception as e:
            st.warning(f"Could not check rate limit: {e}")


# ---------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------
st.title("GitHub Issue Analyzer")
st.markdown(
    "Fetch closed issues from a GitHub repository, then classify and generate "
    "actionable insights using AI agents. **Stage 1: Fetch & Explore.**"
)

# --- Fetch flow ---
if fetch_button:
    if not repo_url:
        st.error("Please enter a GitHub repository URL.")
        st.stop()

    try:
        owner, repo = parse_repo_url(repo_url)
    except ValueError as e:
        st.error(str(e))
        st.stop()

    token = github_token.strip() or None
    days = DATE_RANGE_OPTIONS[date_range]
    since = compute_since_date(days)

    # Fetch repo info
    with st.spinner(f"Fetching repository info for **{owner}/{repo}**..."):
        try:
            repo_info = fetch_repo_info(owner, repo, token)
            st.session_state["repo_info"] = repo_info
            st.session_state["repo_slug"] = f"{owner}/{repo}"
        except Exception as e:
            st.error(f"Failed to fetch repository info: {e}")
            st.stop()

    # Fetch issues with progress
    progress_bar = st.progress(0, text="Fetching issues...")
    status_text = st.empty()

    def on_progress(fetched: int, page: int):
        status_text.text(f"Page {page} — {fetched} issues fetched so far...")
        # We don't know total pages, so pulse the bar
        progress_bar.progress(min(page * 10, 95), text=f"Fetching page {page}...")

    try:
        issues = fetch_closed_issues(owner, repo, since, token, progress_callback=on_progress)
        progress_bar.progress(100, text="Done!")
        status_text.empty()
        st.session_state["issues"] = issues
        st.session_state["date_range"] = date_range
        st.session_state["github_token"] = token
    except Exception as e:
        progress_bar.empty()
        status_text.empty()
        st.error(f"Failed to fetch issues: {e}")
        st.stop()

# --- Display results ---
if "repo_info" in st.session_state:
    st.divider()
    st.subheader(f"📦 {st.session_state['repo_slug']}")
    render_repo_header(st.session_state["repo_info"])

if "issues" in st.session_state:
    issues = st.session_state["issues"]

    st.divider()
    st.subheader(f"📋 Closed Issues — {st.session_state.get('date_range', '')}")

    if not issues:
        st.info("No closed issues found in this time range.")
        st.stop()

    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Issues", len(issues))

    labels_set = set()
    for issue in issues:
        labels_set.update(issue["labels"])
    col2.metric("Unique Labels", len(labels_set))

    with_comments = sum(1 for i in issues if i["comments_count"] > 0)
    col3.metric("With Comments", with_comments)

    avg_comments = sum(i["comments_count"] for i in issues) / len(issues) if issues else 0
    col4.metric("Avg Comments", f"{avg_comments:.1f}")

    # Tabs for different views
    tab_table, tab_labels, tab_timeline = st.tabs(
        ["📄 Issues Table", "🏷️ Label Distribution", "📈 Monthly Timeline"]
    )

    with tab_table:
        df = issues_to_dataframe(issues)
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "URL": st.column_config.LinkColumn("Link", display_text="Open"),
                "#": st.column_config.NumberColumn("Issue #", width="small"),
                "Comments": st.column_config.NumberColumn("💬", width="small"),
            },
        )

    with tab_labels:
        st.markdown("**Top 15 labels across closed issues:**")
        render_label_summary(issues)

    with tab_timeline:
        st.markdown("**Issues closed per month:**")
        render_monthly_distribution(issues)

    # Placeholder for Stage 2
    st.divider()
    st.info(
        "⏭️ **Next: Stage 2 — Classification.** "
        "The Classifier Agent will categorize these issues by type, severity, "
        "and affected component. Coming soon!"
    )
