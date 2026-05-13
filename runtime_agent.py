"""
AgentCore Runtime entrypoint for the Recommender Agent.

Wraps the Recommender Agent in BedrockAgentCoreApp for serverless deployment.
Observability is handled by the opentelemetry-instrument CMD wrapper in the
Dockerfile — no OTEL code is needed here.
"""

import os
import json
import logging

import boto3
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel
from strands.tools.mcp import MCPClient
from mcp.client.streamable_http import streamablehttp_client
from bedrock_agentcore.memory.integrations.strands.config import (
    AgentCoreMemoryConfig,
    RetrievalConfig,
)
from bedrock_agentcore.memory.integrations.strands.session_manager import (
    AgentCoreMemorySessionManager,
)

from config import (
    BEDROCK_MODEL_ID,
    AWS_REGION,
    GATEWAY_ID_SSM_PARAM,
)
from recommender_agent import (
    RECOMMENDER_SYSTEM_PROMPT,
    read_classification_data,
    get_repository_structure,
)

logger = logging.getLogger(__name__)

REGION = boto3.session.Session().region_name or AWS_REGION

memory_id = os.environ.get("MEMORY_ID")
if not memory_id:
    raise Exception("Environment variable MEMORY_ID is required")

model = BedrockModel(model_id=BEDROCK_MODEL_ID, temperature=0.3, region_name=REGION)

app = BedrockAgentCoreApp()


def _get_ssm_parameter(name: str) -> str | None:
    try:
        ssm = boto3.client("ssm", region_name=REGION)
        response = ssm.get_parameter(Name=name, WithDecryption=True)
        return response["Parameter"]["Value"]
    except Exception:
        return None


@app.entrypoint
async def invoke(payload, context=None):
    """AgentCore Runtime entrypoint function."""
    user_input = payload.get("prompt", "")
    repo_slug = payload.get("repo_slug", "")
    github_token = payload.get("github_token", "")
    actor_id = payload.get("actor_id", "runtime_user")
    session_id = context.session_id

    request_headers = context.request_headers or {}
    auth_header = request_headers.get("Authorization", "")

    # Build the prompt if repo_slug is provided but prompt is generic
    if repo_slug and not user_input:
        owner, repo = repo_slug.split("/")
        token_instruction = ""
        if github_token:
            token_instruction = f" Use github_token='{github_token}' when calling get_repository_structure."
        user_input = (
            f"Analyze the classified issues for repository '{repo_slug}'. "
            f"The owner is '{owner}' and the repo name is '{repo}'.{token_instruction} "
            f"Read the classification data, optionally fetch the repo structure, "
            f"and return your complete analysis as a JSON object."
        )

    # Try to get Gateway URL for MCP tools
    gateway_id = _get_ssm_parameter(GATEWAY_ID_SSM_PARAM)
    gateway_url = None
    if gateway_id:
        try:
            gateway_client = boto3.client("bedrock-agentcore-control", region_name=REGION)
            gw_response = gateway_client.get_gateway(gatewayIdentifier=gateway_id)
            gateway_url = gw_response.get("gatewayUrl")
        except Exception as e:
            logger.warning(f"Could not get gateway URL: {e}")

    # Build memory session manager
    memory_config = AgentCoreMemoryConfig(
        memory_id=memory_id,
        session_id=str(session_id),
        actor_id=actor_id,
        retrieval_config={
            "analysis/{actorId}/patterns/": RetrievalConfig(
                top_k=5,
                relevance_score=0.2,
            ),
        },
    )
    session_manager = AgentCoreMemorySessionManager(memory_config, REGION)

    if gateway_url and auth_header:
        try:
            mcp_client = MCPClient(
                lambda: streamablehttp_client(
                    url=gateway_url,
                    headers={"Authorization": auth_header},
                )
            )

            with mcp_client:
                tools = mcp_client.list_tools_sync()

                agent = Agent(
                    model=model,
                    tools=list(tools),
                    system_prompt=RECOMMENDER_SYSTEM_PROMPT,
                    session_manager=session_manager,
                )
                response = agent(user_input)
                return response.message["content"][0]["text"]
        except Exception as e:
            logger.warning(f"MCP client error, falling back to local tools: {e}")

    # Fallback to local tools
    agent = Agent(
        model=model,
        tools=[read_classification_data, get_repository_structure],
        system_prompt=RECOMMENDER_SYSTEM_PROMPT,
        session_manager=session_manager,
    )
    response = agent(user_input)
    return response.message["content"][0]["text"]


if __name__ == "__main__":
    app.run()
