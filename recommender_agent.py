"""
Recommender Agent — Uses Strands Agents + Amazon Nova to analyze classified
issues and generate actionable insights for repository maintainers.

Reads classification data from DynamoDB, optionally fetches repo structure
from GitHub, and produces structured insights via LLM reasoning.
"""

import json
from datetime import datetime, timezone
from collections import Counter

from strands import Agent
from strands.models import BedrockModel
from strands.tools import tool

from config import BEDROCK_MODEL_ID, AWS_REGION
from dynamo_utils import get_classifications, save_recommendations
from github_fetcher import fetch_repo_structure


# ---------------------------------------------------------------------------
# Tools available to the Recommender Agent
# ---------------------------------------------------------------------------

@tool
def read_classification_data(repo_slug: str) -> str:
    """Read all classified issues for a repository from DynamoDB.

    Args:
        repo_slug: Repository identifier in owner/repo format (e.g. 'pallets/flask')

    Returns:
        JSON string with classified issues and pre-computed aggregate statistics
    """
    items = get_classifications(repo_slug)
    if not items:
        return json.dumps({"error": "No classification data found for this repository."})

    # Pre-compute aggregates so the LLM has easy access to summaries
    cat_counts = Counter(item.get("category", "Other") for item in items)
    sev_counts = Counter(item.get("severity", "Medium") for item in items)
    comp_counts = Counter(item.get("affected_component", "unknown") for item in items)

    # Monthly trend
    monthly = {}
    for item in items:
        closed = item.get("closed_at", "")
        cat = item.get("category", "Other")
        if closed:
            month = closed[:7]
            if month not in monthly:
                monthly[month] = Counter()
            monthly[month][cat] += 1

    trend_data = []
    for month in sorted(monthly.keys()):
        entry = {"month": month}
        entry.update(dict(monthly[month]))
        trend_data.append(entry)

    # Top hotspots with severity breakdown
    hotspots = []
    comp_items = {}
    for item in items:
        comp = item.get("affected_component", "unknown")
        if comp not in comp_items:
            comp_items[comp] = []
        comp_items[comp].append(item)

    for comp, comp_issues in sorted(comp_items.items(), key=lambda x: len(x[1]), reverse=True)[:15]:
        sev_breakdown = Counter(i.get("severity", "Medium") for i in comp_issues)
        top_cats = Counter(i.get("category", "Other") for i in comp_issues).most_common(3)
        hotspots.append({
            "component": comp,
            "issue_count": len(comp_issues),
            "severity_breakdown": dict(sev_breakdown),
            "top_categories": [{"category": c, "count": n} for c, n in top_cats],
        })

    # Security-specific items
    security_issues = [i for i in items if i.get("category") == "Security"]

    payload = {
        "total_issues": len(items),
        "category_distribution": dict(cat_counts.most_common()),
        "severity_distribution": dict(sev_counts),
        "hotspots": hotspots,
        "trend_data": trend_data,
        "security_issues_count": len(security_issues),
        "security_summaries": [
            {"issue_number": i.get("issue_number"), "summary": i.get("summary", ""), "severity": i.get("severity", "")}
            for i in security_issues[:20]
        ],
        "sample_issues": [
            {
                "issue_number": i.get("issue_number"),
                "title": i.get("title", ""),
                "category": i.get("category", ""),
                "severity": i.get("severity", ""),
                "component": i.get("affected_component", ""),
                "summary": i.get("summary", ""),
            }
            for i in items[:50]
        ],
    }

    return json.dumps(payload, default=str)


@tool
def get_repository_structure(repo_owner: str, repo_name: str, github_token: str = "") -> str:
    """Fetch the file tree of a GitHub repository to map components to actual code locations.

    Args:
        repo_owner: GitHub repository owner (e.g. 'pallets')
        repo_name: GitHub repository name (e.g. 'flask')
        github_token: Optional GitHub personal access token

    Returns:
        JSON string with the list of file paths in the repository
    """
    try:
        token = github_token if github_token else None
        files = fetch_repo_structure(repo_owner, repo_name, token=token)
        # Group by top-level directory for easier analysis
        dir_counts = Counter()
        for f in files:
            top_dir = f.split("/")[0] if "/" in f else "(root)"
            dir_counts[top_dir] += 1

        return json.dumps({
            "total_files": len(files),
            "directory_summary": dict(dir_counts.most_common(20)),
            "all_paths": files[:500],  # Cap to avoid context overflow
        })
    except Exception as e:
        return json.dumps({"error": f"Could not fetch repo structure: {str(e)}"})


@tool
def save_analysis_results(repo_slug: str, insights_json: str) -> str:
    """Save the generated recommendation results to DynamoDB.

    Args:
        repo_slug: Repository identifier in owner/repo format
        insights_json: JSON string containing all generated insights

    Returns:
        Confirmation message
    """
    try:
        insights = json.loads(insights_json)
        save_recommendations(repo_slug, insights)
        return f"Successfully saved recommendations for {repo_slug}"
    except Exception as e:
        return f"Failed to save recommendations: {str(e)}"


# ---------------------------------------------------------------------------
# Recommender Agent
# ---------------------------------------------------------------------------

RECOMMENDER_SYSTEM_PROMPT = """You are an expert software engineering analyst specializing in open source project health.

You analyze classified GitHub issue data to generate actionable insights for repository maintainers.

You have these tools:
1. read_classification_data - Fetches all classified issues and aggregate statistics from DynamoDB
2. get_repository_structure - Fetches the repo file tree to map affected components to real code
3. save_analysis_results - Saves your analysis to DynamoDB

When asked to analyze a repository, follow these steps:
1. Call read_classification_data to get the classified issues and statistics
2. Optionally call get_repository_structure to understand the codebase layout
3. Analyze the data and produce a comprehensive JSON report
4. Call save_analysis_results to persist your analysis

Your analysis MUST be returned as a JSON object with these exact keys:
- executive_summary: 2-3 sentence overview of the repo's issue landscape
- category_distribution: dict of category -> count (from the data)
- severity_distribution: dict of severity -> count (from the data)
- hotspots: list of top 10 components with issue counts and why they're problematic
- trend_analysis: description of how issue patterns change over time
- action_items: list of 5-8 prioritized recommendations, each with title, description, priority (1-5), effort (Low/Medium/High), and impact (Low/Medium/High)
- security_assessment: risk_level (Low/Medium/High/Critical), summary, and list of concerns
- documentation_gaps: list of areas where better documentation would reduce issues
- quick_wins: list of 3-5 low-effort high-impact improvements
- raw_narrative: a detailed multi-paragraph analysis in plain English

Be specific and data-driven. Reference actual component names, issue counts, and percentages.
Do NOT be generic. Every insight should reference concrete data from the classification results.

After generating the JSON, call save_analysis_results with it, then provide a brief summary to the user."""


def generate_recommendations(repo_slug: str, github_token: str | None = None) -> dict:
    """Run the Recommender Agent to analyze classifications and generate insights.

    Args:
        repo_slug: "owner/repo" string
        github_token: Optional GitHub token for fetching repo structure

    Returns:
        Dict of insights (also saved to DynamoDB by the agent)
    """
    model = BedrockModel(
        model_id=BEDROCK_MODEL_ID,
        temperature=0.3,
        region_name=AWS_REGION,
    )

    agent = Agent(
        model=model,
        tools=[read_classification_data, get_repository_structure, save_analysis_results],
        system_prompt=RECOMMENDER_SYSTEM_PROMPT,
    )

    owner, repo = repo_slug.split("/")
    token_instruction = ""
    if github_token:
        token_instruction = f" Use github_token='{github_token}' when calling get_repository_structure."

    prompt = (
        f"Analyze the classified issues for repository '{repo_slug}'. "
        f"The owner is '{owner}' and the repo name is '{repo}'.{token_instruction} "
        f"Read the classification data, optionally fetch the repo structure, "
        f"generate a comprehensive analysis, and save the results. "
        f"Return your complete analysis as JSON."
    )

    response = agent(prompt)
    response_text = response.message["content"][0]["text"]

    # Try to extract JSON from the response
    try:
        start = response_text.find("{")
        end = response_text.rfind("}")
        if start != -1 and end != -1:
            return json.loads(response_text[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        pass

    # If JSON extraction fails, return the raw text as a narrative
    return {"raw_narrative": response_text}
