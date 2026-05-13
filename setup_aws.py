"""
One-time AWS setup for the GitHub Issue Analyzer.

Run this before using the app for the first time. It:
1. Creates the DynamoDB tables (IssueClassifications, RecommendationResults)
2. Attaches DynamoDB + Bedrock AgentCore permissions to the current IAM role
3. Creates an AgentCore Memory resource and stores its ID in SSM Parameter Store

Usage:
    python setup_aws.py
"""

import boto3
import json
from config import (
    AWS_REGION,
    MEMORY_NAME,
    MEMORY_SSM_PARAM,
    MEMORY_EVENT_EXPIRY_DAYS,
)
from dynamo_utils import ensure_tables_exist


def get_current_role_name() -> str | None:
    """Extract the IAM role name from the current caller identity."""
    sts = boto3.client("sts", region_name=AWS_REGION)
    identity = sts.get_caller_identity()
    arn = identity["Arn"]
    if "assumed-role" in arn:
        return arn.split("/")[1]
    return None


def attach_policy(role_name: str, policy_arn: str, label: str):
    """Attach a managed policy to the given IAM role if not already attached."""
    iam = boto3.client("iam", region_name=AWS_REGION)
    attached = iam.list_attached_role_policies(RoleName=role_name)
    for policy in attached["AttachedPolicies"]:
        if policy["PolicyArn"] == policy_arn:
            print(f"  {label} already attached to {role_name}")
            return
    iam.attach_role_policy(RoleName=role_name, PolicyArn=policy_arn)
    print(f"  Attached {label} to {role_name}")


def get_ssm_parameter(name: str) -> str | None:
    """Read a parameter from SSM Parameter Store. Returns None if not found."""
    ssm = boto3.client("ssm", region_name=AWS_REGION)
    try:
        response = ssm.get_parameter(Name=name, WithDecryption=True)
        return response["Parameter"]["Value"]
    except ssm.exceptions.ParameterNotFound:
        return None


def put_ssm_parameter(name: str, value: str):
    """Write a parameter to SSM Parameter Store."""
    ssm = boto3.client("ssm", region_name=AWS_REGION)
    ssm.put_parameter(Name=name, Value=value, Type="String", Overwrite=True)
    print(f"  Stored {name} in SSM Parameter Store")


def setup_agentcore_memory() -> str | None:
    """Create an AgentCore Memory resource or retrieve existing one.

    Returns the memory_id or None on failure.
    """
    from bedrock_agentcore.memory import MemoryClient
    from bedrock_agentcore.memory.constants import StrategyType

    # Check if we already have a memory_id in SSM
    existing_id = get_ssm_parameter(MEMORY_SSM_PARAM)
    if existing_id:
        try:
            client = MemoryClient(region_name=AWS_REGION)
            client.gmcp_client.get_memory(memoryId=existing_id)
            print(f"  Memory resource already exists: {existing_id}")
            return existing_id
        except Exception:
            print("  Stored memory_id is stale, creating a new one...")

    # Create a new memory resource with a SEMANTIC strategy
    strategies = [
        {
            StrategyType.SEMANTIC.value: {
                "name": "IssueAnalysisPatterns",
                "description": "Stores patterns and insights learned from analyzing repository issues across sessions",
                "namespaces": ["analysis/{actorId}/patterns"],
            }
        },
    ]

    try:
        client = MemoryClient(region_name=AWS_REGION)
        print("  Creating AgentCore Memory resource (this may take a couple of minutes)...")
        response = client.create_memory_and_wait(
            name=MEMORY_NAME,
            description="Issue Analyzer memory for cross-repository pattern learning",
            strategies=strategies,
            event_expiry_days=MEMORY_EVENT_EXPIRY_DAYS,
        )
        memory_id = response["id"]
        put_ssm_parameter(MEMORY_SSM_PARAM, memory_id)
        print(f"  Memory resource created: {memory_id}")
        return memory_id
    except Exception as e:
        print(f"  Failed to create memory resource: {e}")
        print("  The Recommender Agent will run without cross-session memory.")
        return None


def main():
    print("=" * 60)
    print("GitHub Issue Analyzer — AWS Setup")
    print("=" * 60)

    # Step 1: IAM permissions
    print("\n[1/3] Checking IAM permissions...")
    role_name = get_current_role_name()
    if role_name:
        print(f"  Current role: {role_name}")
        try:
            attach_policy(
                role_name,
                "arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess",
                "AmazonDynamoDBFullAccess",
            )
        except Exception as e:
            print(f"  Could not attach DynamoDB policy: {e}")

        try:
            attach_policy(
                role_name,
                "arn:aws:iam::aws:policy/AmazonBedrockFullAccess",
                "AmazonBedrockFullAccess",
            )
        except Exception as e:
            print(f"  Could not attach Bedrock policy: {e}")

        try:
            attach_policy(
                role_name,
                "arn:aws:iam::aws:policy/AmazonSSMFullAccess",
                "AmazonSSMFullAccess",
            )
        except Exception as e:
            print(f"  Could not attach SSM policy: {e}")
    else:
        print("  Not running as an assumed role. Skipping IAM setup.")
        print("  Ensure your credentials have DynamoDB, Bedrock, and SSM access.")

    # Step 2: DynamoDB tables
    print("\n[2/3] Creating DynamoDB tables...")
    ensure_tables_exist()
    print("  Tables ready.")

    # Step 3: AgentCore Memory
    print("\n[3/3] Setting up AgentCore Memory...")
    memory_id = setup_agentcore_memory()

    print("\n" + "=" * 60)
    if memory_id:
        print(f"Setup complete! Memory ID: {memory_id}")
    else:
        print("Setup complete (memory creation skipped).")
    print("You can now run: streamlit run app.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
