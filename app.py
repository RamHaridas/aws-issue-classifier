"""
GitHub Issue Analyzer — Streamlit Application

Usage:
    cd github_issue_analyzer
    streamlit run app.py
"""

import uuid
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
from config import DATE_RANGE_OPTIONS, CATEGORIES, SEVERITIES


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
    "Fetch closed issues from a GitHub repository, classify them using AI, "
    "and generate actionable insights for maintainers."
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

    # -----------------------------------------------------------------
    # Stage 2: Classification
    # -----------------------------------------------------------------
    st.divider()
    st.subheader("🤖 AI Classification")

    col_classify, col_status = st.columns([1, 2])

    with col_classify:
        classify_button = st.button(
            "🧠 Classify Issues",
            use_container_width=True,
            help="Run the Classifier Agent to categorize all fetched issues",
        )
        reclassify = st.checkbox(
            "Re-classify all (ignore previous results)",
            value=False,
        )

    if classify_button:
        from classifier_agent import classify_issues
        from dynamo_utils import (
            get_classified_issue_numbers,
            delete_classifications,
            ensure_tables_exist,
        )

        repo_slug = st.session_state["repo_slug"]
        ensure_tables_exist()

        if reclassify:
            with st.spinner("Clearing previous classifications..."):
                deleted = delete_classifications(repo_slug)
                if deleted:
                    st.toast(f"Cleared {deleted} previous classifications")
            existing_numbers = set()
        else:
            existing_numbers = get_classified_issue_numbers(repo_slug)
            if existing_numbers:
                st.info(
                    f"Found {len(existing_numbers)} already-classified issues. "
                    f"Skipping those. Check 'Re-classify all' to redo them."
                )

        new_issues = [
            i for i in issues if i["number"] not in existing_numbers
        ]

        if not new_issues:
            st.success("All issues are already classified!")
        else:
            progress_bar = st.progress(0, text="Classifying issues...")
            status_text = st.empty()

            def on_classify_progress(done, total, batch_num):
                pct = int((done / total) * 100)
                progress_bar.progress(
                    pct,
                    text=f"Batch {batch_num} — {done}/{total} issues classified",
                )
                status_text.text(f"Processing batch {batch_num}...")

            try:
                results = classify_issues(
                    issues=new_issues,
                    repo_slug=repo_slug,
                    progress_callback=on_classify_progress,
                    skip_existing=False,
                    existing_numbers=set(),
                )
                progress_bar.progress(100, text="Classification complete!")
                status_text.empty()
                st.session_state["classifications"] = results
                st.success(
                    f"Classified {len(results)} issues and saved to DynamoDB."
                )
            except Exception as e:
                progress_bar.empty()
                status_text.empty()
                st.error(f"Classification failed: {e}")

    # Load existing classifications if we don't have them yet
    if "classifications" not in st.session_state and "repo_slug" in st.session_state:
        try:
            from dynamo_utils import get_classifications
            existing = get_classifications(st.session_state["repo_slug"])
            if existing:
                st.session_state["classifications"] = existing
        except Exception:
            pass

    # -----------------------------------------------------------------
    # Classification Results
    # -----------------------------------------------------------------
    if "classifications" in st.session_state and st.session_state["classifications"]:
        clfs = st.session_state["classifications"]

        st.divider()
        st.subheader(f"📊 Classification Results — {len(clfs)} issues")

        # Summary metrics
        cat_counts = {}
        sev_counts = {}
        comp_counts = {}
        for c in clfs:
            cat = c.get("category", "Other")
            sev = c.get("severity", "Medium")
            comp = c.get("affected_component", "unknown")
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
            sev_counts[sev] = sev_counts.get(sev, 0) + 1
            comp_counts[comp] = comp_counts.get(comp, 0) + 1

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Classified", len(clfs))
        m2.metric("Categories Found", len(cat_counts))
        m3.metric("Critical Issues", sev_counts.get("Critical", 0))
        m4.metric("Components", len(comp_counts))

        # Tabs for charts and table
        tab_cats, tab_sev, tab_comp, tab_data = st.tabs(
            ["📊 Categories", "⚠️ Severity", "🔥 Hotspots", "📋 All Data"]
        )

        with tab_cats:
            st.markdown("**Issue distribution by category:**")
            cat_df = pd.DataFrame(
                sorted(cat_counts.items(), key=lambda x: x[1], reverse=True),
                columns=["Category", "Count"],
            ).set_index("Category")
            st.bar_chart(cat_df)

        with tab_sev:
            st.markdown("**Issue distribution by severity:**")
            sev_order = ["Critical", "High", "Medium", "Low", "Informational"]
            sev_data = [(s, sev_counts.get(s, 0)) for s in sev_order if sev_counts.get(s, 0) > 0]
            sev_df = pd.DataFrame(sev_data, columns=["Severity", "Count"]).set_index("Severity")
            st.bar_chart(sev_df)

        with tab_comp:
            st.markdown("**Top affected components (hotspots):**")
            top_comps = sorted(comp_counts.items(), key=lambda x: x[1], reverse=True)[:15]
            comp_df = pd.DataFrame(top_comps, columns=["Component", "Issues"])
            st.dataframe(comp_df, use_container_width=True, hide_index=True)

        with tab_data:
            filter_cat = st.multiselect(
                "Filter by category",
                options=sorted(cat_counts.keys()),
                default=None,
            )
            filter_sev = st.multiselect(
                "Filter by severity",
                options=[s for s in sev_order if s in sev_counts],
                default=None,
            )

            filtered = clfs
            if filter_cat:
                filtered = [c for c in filtered if c.get("category") in filter_cat]
            if filter_sev:
                filtered = [c for c in filtered if c.get("severity") in filter_sev]

            rows = []
            for c in filtered:
                rows.append({
                    "#": c.get("issue_number", ""),
                    "Title": c.get("title", ""),
                    "Category": c.get("category", ""),
                    "Subcategory": c.get("subcategory", ""),
                    "Severity": c.get("severity", ""),
                    "Component": c.get("affected_component", ""),
                    "Summary": c.get("summary", ""),
                })
            clf_df = pd.DataFrame(rows)
            st.dataframe(clf_df, use_container_width=True, hide_index=True)

        # -----------------------------------------------------------------
        # Stage 3: Recommendations
        # -----------------------------------------------------------------
        st.divider()
        st.subheader("💡 AI-Powered Insights")

        col_reco, col_reco_status = st.columns([1, 2])
        with col_reco:
            recommend_button = st.button(
                "💡 Generate Insights",
                use_container_width=True,
                help="Run the Recommender Agent to analyze classifications and produce actionable insights",
            )

        if recommend_button:
            repo_slug = st.session_state["repo_slug"]
            token = st.session_state.get("github_token")

            if "memory_session_id" not in st.session_state:
                st.session_state["memory_session_id"] = str(uuid.uuid4())

            from recommender_agent import generate_recommendations

            with st.spinner("Recommender Agent is analyzing your data (with memory)... This may take a minute."):
                try:
                    insights = generate_recommendations(
                        repo_slug,
                        github_token=token,
                        session_id=st.session_state["memory_session_id"],
                        actor_id="streamlit_user",
                    )
                    st.session_state["insights"] = insights
                    st.success("Insights generated and saved to DynamoDB!")
                except Exception as e:
                    st.error(f"Recommendation failed: {e}")

        # Load existing insights if not in session
        if "insights" not in st.session_state and "repo_slug" in st.session_state:
            try:
                from dynamo_utils import get_latest_recommendation
                existing = get_latest_recommendation(st.session_state["repo_slug"])
                if existing:
                    st.session_state["insights"] = existing
            except Exception:
                pass

        # -----------------------------------------------------------------
        # Insights Dashboard
        # -----------------------------------------------------------------
        if "insights" in st.session_state and st.session_state["insights"]:
            from dashboard import (
                render_executive_summary,
                render_category_pie,
                render_severity_bar,
                render_hotspot_table,
                render_trend_chart,
                render_action_items,
                render_security_assessment,
                render_documentation_gaps,
                render_quick_wins,
                render_narrative,
            )

            insights = st.session_state["insights"]

            st.divider()
            st.subheader("📈 Repository Health Dashboard")

            # Executive summary
            render_executive_summary(insights)

            # Row 1: Category + Severity charts
            left, right = st.columns(2)
            with left:
                render_category_pie(insights)
            with right:
                render_severity_bar(insights)

            # Row 2: Hotspots + Trends
            left2, right2 = st.columns(2)
            with left2:
                st.markdown("#### 🔥 Hotspot Components")
                render_hotspot_table(insights)
            with right2:
                st.markdown("#### 📈 Issue Trends Over Time")
                render_trend_chart(insights)

            # Action items
            st.divider()
            st.markdown("#### 🎯 Prioritized Action Items")
            render_action_items(insights)

            # Quick wins
            st.divider()
            st.markdown("#### ⚡ Quick Wins")
            render_quick_wins(insights)

            # Detail tabs
            st.divider()
            detail_tab1, detail_tab2, detail_tab3 = st.tabs(
                ["🔒 Security Assessment", "📝 Documentation Gaps", "📄 Full Analysis"]
            )
            with detail_tab1:
                render_security_assessment(insights)
            with detail_tab2:
                render_documentation_gaps(insights)
            with detail_tab3:
                render_narrative(insights)
