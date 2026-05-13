"""
Recommender Agent — Uses Strands Agents + Amazon Nova to analyze classified
issues and generate actionable insights for repository maintainers.

Reads classification data from DynamoDB, optionally fetches repo structure
from GitHub, and produces structured insights via LLM reasoning.

Integrates with AgentCore Memory for cross-session pattern learning.
Integrates with AgentCore Gateway for centralized MCP-based tool access.
"""

import json
import uuid
import logging
import hashlib
import hmac
import base64
from datetime import datetime, timezone
from collections import Counter

import boto3
from strands import Agent
from strands.models import BedrockModel
from strands.tools import tool
from strands.tools.mcp import MCPClient
from mcp.client.streamable_http import streamablehttp_client

from config import (
    BEDROCK_MODEL_ID,
    AWS_REGION,
    MEMORY_SSM_PARAM,
    GATEWAY_URL_SSM_PARAM,
    COGNITO_CLIENT_ID_SSM_PARAM,
    COGNITO_CLIENT_SECRET_SSM_PARAM,
    COGNITO_USERNAME,
    COGNITO_PASSWORD,
)
from dynamo_utils import get_classifications, save_recommendations
from github_fetcher import fetch_repo_structure

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Local tool fallbacks (used when Gateway is unavailable)
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

    cat_counts = Counter(item.get("category", "Other") for item in items)
    sev_counts = Counter(item.get("severity", "Medium") for item in items)

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


# ---------------------------------------------------------------------------
# Memory integration helpers
# ---------------------------------------------------------------------------

def _get_ssm_parameter(name: str) -> str | None:
    """Retrieve a parameter from SSM Parameter Store."""
    try:
        ssm = boto3.client("ssm", region_name=AWS_REGION)
        response = ssm.get_parameter(Name=name, WithDecryption=True)
        return response["Parameter"]["Value"]
    except Exception:
        return None


def _get_memory_id() -> str | None:
    """Retrieve the memory_id from SSM Parameter Store."""
    return _get_ssm_parameter(MEMORY_SSM_PARAM)


def _build_memory_session_manager(memory_id: str, session_id: str, actor_id: str):
    """Create an AgentCoreMemorySessionManager for the Recommender Agent."""
    from bedrock_agentcore.memory.integrations.strands.config import (
        AgentCoreMemoryConfig,
        RetrievalConfig,
    )
    from bedrock_agentcore.memory.integrations.strands.session_manager import (
        AgentCoreMemorySessionManager,
    )

    memory_config = AgentCoreMemoryConfig(
        memory_id=memory_id,
        session_id=session_id,
        actor_id=actor_id,
        retrieval_config={
            "analysis/{actorId}/patterns/": RetrievalConfig(
                top_k=5,
                relevance_score=0.2,
            ),
        },
    )

    return AgentCoreMemorySessionManager(memory_config, AWS_REGION)


# ---------------------------------------------------------------------------
# Gateway (MCP) integration helpers
# ---------------------------------------------------------------------------

def _get_cognito_token() -> str | None:
    """Authenticate against Cognito and return a fresh access token."""
    client_id = _get_ssm_parameter(COGNITO_CLIENT_ID_SSM_PARAM)
    client_secret = _get_ssm_parameter(COGNITO_CLIENT_SECRET_SSM_PARAM)
    if not client_id or not client_secret:
        return None

    cognito_client = boto3.client("cognito-idp", region_name=AWS_REGION)

    message = bytes(COGNITO_USERNAME + client_id, "utf-8")
    key = bytes(client_secret, "utf-8")
    secret_hash = base64.b64encode(
        hmac.new(key, message, digestmod=hashlib.sha256).digest()
    ).decode()

    try:
        auth_response = cognito_client.initiate_auth(
            ClientId=client_id,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={
                "USERNAME": COGNITO_USERNAME,
                "PASSWORD": COGNITO_PASSWORD,
                "SECRET_HASH": secret_hash,
            },
        )
        return auth_response["AuthenticationResult"]["AccessToken"]
    except Exception as e:
        logger.warning(f"Cognito authentication failed: {e}")
        return None


def _get_gateway_url() -> str | None:
    """Retrieve the Gateway MCP URL from SSM Parameter Store."""
    return _get_ssm_parameter(GATEWAY_URL_SSM_PARAM)


# ---------------------------------------------------------------------------
# Recommender Agent
# ---------------------------------------------------------------------------

RECOMMENDER_SYSTEM_PROMPT = """You are an expert software engineering analyst specializing in open source project health.

You analyze classified GitHub issue data to generate actionable insights for repository maintainers.
Each classified issue has an issue_type (Defect, Support, Enhancement, Documentation, Task) and a
category. When analyzing patterns, consider both dimensions — for example, a cluster of
Support + Installation/Configuration issues suggests the setup experience needs improvement.

You have these tools:
1. read_classification_data - Fetches all classified issues and aggregate statistics from DynamoDB
2. get_repository_structure - Fetches the repo file tree to map affected components to real code

You may also have access to memories from previous analyses of other repositories.
If prior context is provided, use it to make comparative observations (e.g., "compared to similar
logging frameworks, this repository has an unusually high rate of networking issues").

When asked to analyze a repository, follow these steps:
1. Call read_classification_data to get the classified issues and statistics
2. Optionally call get_repository_structure to understand the codebase layout
3. Analyze the data and respond with ONLY a JSON object — no other text before or after it

Your response MUST be a single JSON object (no markdown fences, no extra text) with these exact keys:
- executive_summary: 2-3 sentence overview of the repo's issue landscape
- category_distribution: dict of category -> count (from the data)
- severity_distribution: dict of severity -> count (from the data)
- hotspots: list of top 10 objects, each with "component", "issue_count", and "reason"
- trend_analysis: description of how issue patterns change over time (string)
- action_items: list of 5-8 objects, each with "title", "description", "priority" (1-5), "effort" (Low/Medium/High), "impact" (Low/Medium/High)
- security_assessment: object with "risk_level" (Low/Medium/High/Critical), "summary", and "concerns" (list of strings)
- documentation_gaps: list of strings describing areas where better docs would reduce issues
- quick_wins: list of 3-5 objects, each with "title", "description", "impact"
- raw_narrative: a detailed multi-paragraph analysis in plain English

Be specific and data-driven. Reference actual component names, issue counts, and percentages.
Do NOT be generic. Every insight should reference concrete data from the classification results.
Do NOT wrap your response in markdown code fences. Output raw JSON only."""


def generate_recommendations(
    repo_slug: str,
    github_token: str | None = None,
    session_id: str | None = None,
    actor_id: str = "analyzer_user",
) -> dict:
    """Run the Recommender Agent to analyze classifications and generate insights.

    Attempts to use AgentCore Gateway (MCP) for tool access. If the Gateway
    is unavailable, falls back to local @tool functions.

    Args:
        repo_slug: "owner/repo" string
        github_token: Optional GitHub token for fetching repo structure
        session_id: Session identifier for memory tracking
        actor_id: Actor identifier for memory namespacing

    Returns:
        Dict of insights (also saved to DynamoDB)
    """
    if not session_id:
        session_id = str(uuid.uuid4())

    model = BedrockModel(
        model_id=BEDROCK_MODEL_ID,
        temperature=0.3,
        region_name=AWS_REGION,
    )

    # Try to set up AgentCore Memory
    session_manager = None
    memory_id = _get_memory_id()
    if memory_id:
        try:
            session_manager = _build_memory_session_manager(
                memory_id=memory_id,
                session_id=session_id,
                actor_id=actor_id,
            )
            logger.info(f"AgentCore Memory enabled (memory_id={memory_id})")
        except Exception as e:
            logger.warning(f"Could not initialize memory session manager: {e}")
            session_manager = None

    # Try to set up Gateway (MCP) tools
    gateway_url = _get_gateway_url()
    bearer_token = _get_cognito_token() if gateway_url else None
    use_gateway = bool(gateway_url and bearer_token)

    if use_gateway:
        logger.info(f"Using AgentCore Gateway at {gateway_url}")
        return _run_with_gateway(
            model=model,
            session_manager=session_manager,
            gateway_url=gateway_url,
            bearer_token=bearer_token,
            repo_slug=repo_slug,
            github_token=github_token,
        )
    else:
        logger.info("Gateway unavailable, using local tools")
        return _run_with_local_tools(
            model=model,
            session_manager=session_manager,
            repo_slug=repo_slug,
            github_token=github_token,
        )


def _run_with_gateway(
    model,
    session_manager,
    gateway_url: str,
    bearer_token: str,
    repo_slug: str,
    github_token: str | None,
) -> dict:
    """Run the Recommender Agent using Gateway MCP tools."""
    mcp_client = MCPClient(
        lambda: streamablehttp_client(
            gateway_url,
            headers={"Authorization": f"Bearer {bearer_token}"},
        )
    )

    try:
        with mcp_client:
            tools = mcp_client.list_tools_sync()
            logger.info(f"Gateway provides {len(tools)} tool(s)")

            agent_kwargs = {
                "model": model,
                "tools": list(tools),
                "system_prompt": RECOMMENDER_SYSTEM_PROMPT,
            }
            if session_manager:
                agent_kwargs["session_manager"] = session_manager

            agent = Agent(**agent_kwargs)
            return _invoke_agent(agent, repo_slug, github_token)
    except Exception as e:
        logger.warning(f"Gateway invocation failed, falling back to local tools: {e}")
        return _run_with_local_tools(model, session_manager, repo_slug, github_token)


def _run_with_local_tools(
    model,
    session_manager,
    repo_slug: str,
    github_token: str | None,
) -> dict:
    """Run the Recommender Agent using local @tool functions."""
    agent_kwargs = {
        "model": model,
        "tools": [read_classification_data, get_repository_structure],
        "system_prompt": RECOMMENDER_SYSTEM_PROMPT,
    }
    if session_manager:
        agent_kwargs["session_manager"] = session_manager

    agent = Agent(**agent_kwargs)
    return _invoke_agent(agent, repo_slug, github_token)


def _invoke_agent(agent, repo_slug: str, github_token: str | None) -> dict:
    """Invoke the agent and extract structured insights from the response."""
    owner, repo = repo_slug.split("/")
    token_instruction = ""
    if github_token:
        token_instruction = f" Use github_token='{github_token}' when calling get_repository_structure."

    prompt = (
        f"Analyze the classified issues for repository '{repo_slug}'. "
        f"The owner is '{owner}' and the repo name is '{repo}'.{token_instruction} "
        f"Read the classification data, optionally fetch the repo structure, "
        f"and return your complete analysis as a JSON object."
    )

    response = agent(prompt)

    response_text = ""
    for block in response.message.get("content", []):
        if isinstance(block, dict) and block.get("text"):
            response_text += block["text"]

    insights = None
    try:
        start = response_text.find("{")
        end = response_text.rfind("}")
        if start != -1 and end != -1:
            insights = json.loads(response_text[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        pass

    if not insights:
        insights = {"raw_narrative": response_text}

    try:
        save_recommendations(repo_slug, insights)
    except Exception:
        pass

    return insights
