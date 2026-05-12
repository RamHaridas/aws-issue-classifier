"""
Dashboard rendering functions for the Recommender Agent's insights.
Uses Plotly for rich interactive charts displayed in Streamlit.
"""

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd


def render_executive_summary(insights: dict):
    """Render the executive summary as a highlighted callout."""
    summary = insights.get("executive_summary", "")
    if summary:
        st.info(summary)


def render_category_pie(insights: dict):
    """Render a pie chart of issue category distribution."""
    dist = insights.get("category_distribution", {})
    if not dist:
        st.caption("No category data available.")
        return

    fig = px.pie(
        names=list(dist.keys()),
        values=list(dist.values()),
        title="Issue Category Distribution",
        hole=0.3,
    )
    fig.update_traces(textposition="inside", textinfo="percent+label")
    fig.update_layout(height=400, showlegend=True)
    st.plotly_chart(fig, use_container_width=True)


def render_severity_bar(insights: dict):
    """Render a horizontal bar chart of severity levels."""
    dist = insights.get("severity_distribution", {})
    if not dist:
        st.caption("No severity data available.")
        return

    sev_order = ["Critical", "High", "Medium", "Low", "Informational"]
    colors = {
        "Critical": "#dc3545",
        "High": "#fd7e14",
        "Medium": "#ffc107",
        "Low": "#28a745",
        "Informational": "#6c757d",
    }

    ordered = [(s, dist.get(s, 0)) for s in sev_order if dist.get(s, 0) > 0]
    if not ordered:
        return

    df = pd.DataFrame(ordered, columns=["Severity", "Count"])
    fig = px.bar(
        df, x="Count", y="Severity",
        orientation="h",
        title="Issue Severity Breakdown",
        color="Severity",
        color_discrete_map=colors,
    )
    fig.update_layout(height=350, showlegend=False)
    st.plotly_chart(fig, use_container_width=True)


def render_hotspot_table(insights: dict):
    """Render a ranked table of hotspot components."""
    hotspots = insights.get("hotspots", [])
    if not hotspots:
        st.caption("No hotspot data available.")
        return

    rows = []
    for i, h in enumerate(hotspots[:15], 1):
        if isinstance(h, dict):
            rows.append({
                "Rank": i,
                "Component": h.get("component", "unknown"),
                "Issues": h.get("issue_count", 0),
            })
        elif isinstance(h, str):
            rows.append({"Rank": i, "Component": h, "Issues": ""})

    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)


def render_trend_chart(insights: dict):
    """Render a multi-line time series of issues by category per month."""
    trend_data = insights.get("trend_data") or insights.get("trend_analysis")
    if not trend_data or isinstance(trend_data, str):
        # If it's a text description instead of data, display as text
        if isinstance(trend_data, str) and trend_data:
            st.markdown(trend_data)
        else:
            st.caption("No trend data available.")
        return

    if not isinstance(trend_data, list):
        return

    # Flatten trend data into a DataFrame
    rows = []
    for entry in trend_data:
        if not isinstance(entry, dict):
            continue
        month = entry.get("month", "")
        for key, val in entry.items():
            if key != "month" and isinstance(val, (int, float)) and val > 0:
                rows.append({"Month": month, "Category": key, "Count": val})

    if not rows:
        st.caption("No trend data to chart.")
        return

    df = pd.DataFrame(rows)
    fig = px.line(
        df, x="Month", y="Count", color="Category",
        title="Issue Trends Over Time",
        markers=True,
    )
    fig.update_layout(height=400)
    st.plotly_chart(fig, use_container_width=True)


def render_action_items(insights: dict):
    """Render prioritized action items as expandable cards."""
    items = insights.get("action_items", [])
    if not items:
        st.caption("No action items generated.")
        return

    for i, item in enumerate(items, 1):
        if isinstance(item, dict):
            priority = item.get("priority", "")
            title = item.get("title", f"Action Item {i}")
            effort = item.get("effort", "")
            impact = item.get("impact", "")
            desc = item.get("description", "")

            badge = ""
            if priority:
                badge = f"P{priority} "
            if effort:
                badge += f"| Effort: {effort} "
            if impact:
                badge += f"| Impact: {impact}"

            with st.expander(f"**{i}. {title}** {badge}"):
                st.markdown(desc)
        elif isinstance(item, str):
            st.markdown(f"**{i}.** {item}")


def render_security_assessment(insights: dict):
    """Render a security risk assessment card."""
    sec = insights.get("security_assessment", {})
    if not sec:
        st.caption("No security assessment available.")
        return

    if isinstance(sec, str):
        st.markdown(sec)
        return

    risk_level = sec.get("risk_level", "Unknown")
    risk_colors = {
        "Critical": "🔴", "High": "🟠", "Medium": "🟡", "Low": "🟢", "Unknown": "⚪"
    }
    icon = risk_colors.get(risk_level, "⚪")

    st.markdown(f"### {icon} Security Risk: **{risk_level}**")
    summary = sec.get("summary", "")
    if summary:
        st.markdown(summary)

    concerns = sec.get("concerns", [])
    if concerns:
        st.markdown("**Concerns:**")
        for concern in concerns:
            if isinstance(concern, dict):
                st.markdown(f"- {concern.get('description', concern)}")
            else:
                st.markdown(f"- {concern}")


def render_documentation_gaps(insights: dict):
    """Render documentation gap suggestions."""
    gaps = insights.get("documentation_gaps", [])
    if not gaps:
        st.caption("No documentation gaps identified.")
        return

    for gap in gaps:
        if isinstance(gap, dict):
            st.markdown(f"- {gap.get('area', gap.get('description', str(gap)))}")
        else:
            st.markdown(f"- {gap}")


def render_quick_wins(insights: dict):
    """Render quick win suggestions as highlighted cards."""
    wins = insights.get("quick_wins", [])
    if not wins:
        st.caption("No quick wins identified.")
        return

    cols = st.columns(min(len(wins), 3))
    for i, win in enumerate(wins):
        with cols[i % 3]:
            if isinstance(win, dict):
                title = win.get("title", f"Quick Win {i+1}")
                impact = win.get("impact", "")
                desc = win.get("description", "")
                st.markdown(f"**{title}**")
                if impact:
                    st.caption(f"Impact: {impact}")
                st.markdown(desc)
            else:
                st.markdown(f"**{i+1}.** {win}")
            st.divider()


def render_narrative(insights: dict):
    """Render the full narrative analysis."""
    narrative = insights.get("raw_narrative", "")
    if narrative:
        st.markdown(narrative)
    else:
        st.caption("No narrative analysis available.")
