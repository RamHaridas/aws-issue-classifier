"""
One-time AWS setup for the GitHub Issue Analyzer.

Run this before using the app for the first time. It:
1. Attaches IAM permissions to the current execution role
2. Creates the DynamoDB tables (IssueClassifications, RecommendationResults)
3. Creates an AgentCore Memory resource and stores its ID in SSM
4. Creates a Lambda execution IAM role for Gateway tools
5. Creates a Gateway IAM role for AgentCore Gateway
6. Deploys the Lambda function with tool handler code
7. Creates a Cognito User Pool for JWT-based Gateway authentication
8. Creates an AgentCore Gateway with CUSTOM_JWT auth
9. Creates a Gateway Target pointing at the Lambda function

Usage:
    python setup_aws.py
"""

import boto3
import json
import time
import os
import io
import zipfile
import hashlib
import hmac
import base64

from config import (
    AWS_REGION,
    MEMORY_NAME,
    MEMORY_SSM_PARAM,
    MEMORY_EVENT_EXPIRY_DAYS,
    GATEWAY_NAME,
    GATEWAY_ID_SSM_PARAM,
    GATEWAY_URL_SSM_PARAM,
    GATEWAY_ARN_SSM_PARAM,
    GATEWAY_IAM_ROLE_SSM_PARAM,
    LAMBDA_FUNCTION_NAME,
    LAMBDA_ARN_SSM_PARAM,
    LAMBDA_ROLE_ARN_SSM_PARAM,
    LAMBDA_ROLE_NAME,
    COGNITO_POOL_ID_SSM_PARAM,
    COGNITO_CLIENT_ID_SSM_PARAM,
    COGNITO_CLIENT_SECRET_SSM_PARAM,
    COGNITO_DISCOVERY_URL_SSM_PARAM,
    COGNITO_USERNAME,
    COGNITO_PASSWORD,
)
from dynamo_utils import ensure_tables_exist


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def get_account_id() -> str:
    sts = boto3.client("sts", region_name=AWS_REGION)
    return sts.get_caller_identity()["Account"]


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


# ---------------------------------------------------------------------------
# Step 3: AgentCore Memory
# ---------------------------------------------------------------------------

def setup_agentcore_memory() -> str | None:
    """Create an AgentCore Memory resource or retrieve existing one."""
    from bedrock_agentcore.memory import MemoryClient
    from bedrock_agentcore.memory.constants import StrategyType

    existing_id = get_ssm_parameter(MEMORY_SSM_PARAM)
    if existing_id:
        try:
            client = MemoryClient(region_name=AWS_REGION)
            client.gmcp_client.get_memory(memoryId=existing_id)
            print(f"  Memory resource already exists: {existing_id}")
            return existing_id
        except Exception:
            print("  Stored memory_id is stale, creating a new one...")

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


# ---------------------------------------------------------------------------
# Step 4: Lambda Execution IAM Role
# ---------------------------------------------------------------------------

def _create_iam_role(role_name: str, trust_service: str, description: str) -> str:
    """Create an IAM role with a trust policy for the given service.

    Returns the role ARN. If the role already exists, returns the existing ARN.
    """
    iam = boto3.client("iam", region_name=AWS_REGION)
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": trust_service},
                "Action": "sts:AssumeRole",
            }
        ],
    }

    try:
        response = iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description=description,
        )
        role_arn = response["Role"]["Arn"]
        print(f"  Created IAM role: {role_name}")
        return role_arn
    except iam.exceptions.EntityAlreadyExistsException:
        response = iam.get_role(RoleName=role_name)
        role_arn = response["Role"]["Arn"]
        print(f"  IAM role already exists: {role_name}")
        return role_arn


def setup_lambda_role() -> str:
    """Create the Lambda execution role with DynamoDB read + CloudWatch Logs permissions."""
    role_arn = _create_iam_role(
        role_name=LAMBDA_ROLE_NAME,
        trust_service="lambda.amazonaws.com",
        description="Execution role for IssueAnalyzer Lambda tools",
    )

    iam = boto3.client("iam", region_name=AWS_REGION)
    policies = [
        ("arn:aws:iam::aws:policy/AmazonDynamoDBReadOnlyAccess", "AmazonDynamoDBReadOnlyAccess"),
        ("arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole", "AWSLambdaBasicExecutionRole"),
    ]
    for policy_arn, label in policies:
        try:
            iam.attach_role_policy(RoleName=LAMBDA_ROLE_NAME, PolicyArn=policy_arn)
            print(f"  Attached {label} to {LAMBDA_ROLE_NAME}")
        except Exception:
            print(f"  {label} already attached or could not attach")

    put_ssm_parameter(LAMBDA_ROLE_ARN_SSM_PARAM, role_arn)
    return role_arn


# ---------------------------------------------------------------------------
# Step 5: Gateway IAM Role
# ---------------------------------------------------------------------------

GATEWAY_ROLE_NAME = "IssueAnalyzerGatewayRole"


def setup_gateway_role() -> str:
    """Create the Gateway IAM role with Lambda invoke permissions."""
    role_arn = _create_iam_role(
        role_name=GATEWAY_ROLE_NAME,
        trust_service="bedrock-agentcore.amazonaws.com",
        description="IAM role for IssueAnalyzer AgentCore Gateway",
    )

    account_id = get_account_id()
    iam = boto3.client("iam", region_name=AWS_REGION)

    inline_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": "lambda:InvokeFunction",
                "Resource": f"arn:aws:lambda:{AWS_REGION}:{account_id}:function:{LAMBDA_FUNCTION_NAME}",
            }
        ],
    }

    try:
        iam.put_role_policy(
            RoleName=GATEWAY_ROLE_NAME,
            PolicyName="InvokeLambdaTools",
            PolicyDocument=json.dumps(inline_policy),
        )
        print(f"  Attached InvokeLambdaTools inline policy to {GATEWAY_ROLE_NAME}")
    except Exception as e:
        print(f"  Could not attach inline policy: {e}")

    put_ssm_parameter(GATEWAY_IAM_ROLE_SSM_PARAM, role_arn)
    return role_arn


# ---------------------------------------------------------------------------
# Step 6: Lambda Function Deployment
# ---------------------------------------------------------------------------

def _build_lambda_zip() -> bytes:
    """Package the lambda_tools/ directory into a zip archive in memory."""
    lambda_dir = os.path.join(os.path.dirname(__file__), "lambda_tools")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename in os.listdir(lambda_dir):
            filepath = os.path.join(lambda_dir, filename)
            if os.path.isfile(filepath) and filename.endswith((".py", ".json")):
                zf.write(filepath, filename)
    return buf.getvalue()


def setup_lambda_function(role_arn: str) -> str:
    """Deploy the Lambda function with tool handler code.

    Returns the function ARN.
    """
    lambda_client = boto3.client("lambda", region_name=AWS_REGION)
    zip_bytes = _build_lambda_zip()

    # Newly created roles need a few seconds before Lambda can assume them
    print("  Waiting for IAM role propagation (10s)...")
    time.sleep(10)

    try:
        response = lambda_client.create_function(
            FunctionName=LAMBDA_FUNCTION_NAME,
            Runtime="python3.12",
            Role=role_arn,
            Handler="lambda_function.lambda_handler",
            Code={"ZipFile": zip_bytes},
            Description="Tool handlers for IssueAnalyzer AgentCore Gateway",
            Timeout=60,
            MemorySize=256,
        )
        fn_arn = response["FunctionArn"]
        print(f"  Lambda function created: {LAMBDA_FUNCTION_NAME}")
    except lambda_client.exceptions.ResourceConflictException:
        # Function exists — update the code
        lambda_client.update_function_code(
            FunctionName=LAMBDA_FUNCTION_NAME,
            ZipFile=zip_bytes,
        )
        response = lambda_client.get_function(FunctionName=LAMBDA_FUNCTION_NAME)
        fn_arn = response["Configuration"]["FunctionArn"]
        print(f"  Lambda function already exists, code updated: {LAMBDA_FUNCTION_NAME}")

    put_ssm_parameter(LAMBDA_ARN_SSM_PARAM, fn_arn)
    return fn_arn


# ---------------------------------------------------------------------------
# Step 7: Cognito User Pool
# ---------------------------------------------------------------------------

def setup_cognito() -> dict | None:
    """Create a Cognito User Pool, App Client, and test user.

    Returns a dict with pool_id, client_id, client_secret, discovery_url,
    bearer_token or None on failure.
    """
    # Check if we already have a cognito pool set up
    existing_pool_id = get_ssm_parameter(COGNITO_POOL_ID_SSM_PARAM)
    existing_client_id = get_ssm_parameter(COGNITO_CLIENT_ID_SSM_PARAM)
    existing_client_secret = get_ssm_parameter(COGNITO_CLIENT_SECRET_SSM_PARAM)

    if existing_pool_id and existing_client_id and existing_client_secret:
        print(f"  Cognito User Pool already configured: {existing_pool_id}")
        discovery_url = f"https://cognito-idp.{AWS_REGION}.amazonaws.com/{existing_pool_id}/.well-known/openid-configuration"
        bearer_token = _authenticate_cognito_user(existing_client_id, existing_client_secret)
        return {
            "pool_id": existing_pool_id,
            "client_id": existing_client_id,
            "client_secret": existing_client_secret,
            "discovery_url": discovery_url,
            "bearer_token": bearer_token,
        }

    cognito_client = boto3.client("cognito-idp", region_name=AWS_REGION)

    try:
        # Create User Pool
        pool_response = cognito_client.create_user_pool(
            PoolName="IssueAnalyzerPool",
            Policies={"PasswordPolicy": {"MinimumLength": 8}},
        )
        pool_id = pool_response["UserPool"]["Id"]
        print(f"  Created Cognito User Pool: {pool_id}")

        # Create App Client with secret
        client_response = cognito_client.create_user_pool_client(
            UserPoolId=pool_id,
            ClientName="IssueAnalyzerClient",
            GenerateSecret=True,
            ExplicitAuthFlows=[
                "ALLOW_USER_PASSWORD_AUTH",
                "ALLOW_REFRESH_TOKEN_AUTH",
            ],
        )
        client_id = client_response["UserPoolClient"]["ClientId"]
        client_secret = client_response["UserPoolClient"]["ClientSecret"]
        print(f"  Created App Client: {client_id}")

        # Create user with temporary password, then set permanent password
        cognito_client.admin_create_user(
            UserPoolId=pool_id,
            Username=COGNITO_USERNAME,
            TemporaryPassword="Temp123!",
            MessageAction="SUPPRESS",
        )
        cognito_client.admin_set_user_password(
            UserPoolId=pool_id,
            Username=COGNITO_USERNAME,
            Password=COGNITO_PASSWORD,
            Permanent=True,
        )
        print(f"  Created user: {COGNITO_USERNAME}")

        # Authenticate to get bearer token
        bearer_token = _authenticate_cognito_user(client_id, client_secret)

        discovery_url = f"https://cognito-idp.{AWS_REGION}.amazonaws.com/{pool_id}/.well-known/openid-configuration"

        # Store everything in SSM
        put_ssm_parameter(COGNITO_POOL_ID_SSM_PARAM, pool_id)
        put_ssm_parameter(COGNITO_CLIENT_ID_SSM_PARAM, client_id)
        put_ssm_parameter(COGNITO_CLIENT_SECRET_SSM_PARAM, client_secret)
        put_ssm_parameter(COGNITO_DISCOVERY_URL_SSM_PARAM, discovery_url)

        return {
            "pool_id": pool_id,
            "client_id": client_id,
            "client_secret": client_secret,
            "discovery_url": discovery_url,
            "bearer_token": bearer_token,
        }
    except Exception as e:
        print(f"  Failed to set up Cognito: {e}")
        return None


def _authenticate_cognito_user(client_id: str, client_secret: str) -> str | None:
    """Authenticate the agent user and return the access token."""
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
        token = auth_response["AuthenticationResult"]["AccessToken"]
        print("  Cognito authentication successful")
        return token
    except Exception as e:
        print(f"  Cognito authentication failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Step 8: AgentCore Gateway
# ---------------------------------------------------------------------------

def setup_gateway(cognito_config: dict, gateway_role_arn: str) -> dict | None:
    """Create an AgentCore Gateway with CUSTOM_JWT auth.

    Returns a dict with id, name, gateway_url, gateway_arn or None on failure.
    """
    existing_id = get_ssm_parameter(GATEWAY_ID_SSM_PARAM)
    if existing_id:
        print(f"  Gateway already configured: {existing_id}")
        gateway_url = get_ssm_parameter(GATEWAY_URL_SSM_PARAM)
        return {
            "id": existing_id,
            "name": GATEWAY_NAME,
            "gateway_url": gateway_url,
        }

    gateway_client = boto3.client("bedrock-agentcore-control", region_name=AWS_REGION)

    auth_config = {
        "customJWTAuthorizer": {
            "allowedClients": [cognito_config["client_id"]],
            "discoveryUrl": cognito_config["discovery_url"],
        }
    }

    try:
        print(f"  Creating gateway: {GATEWAY_NAME}")
        create_response = gateway_client.create_gateway(
            name=GATEWAY_NAME,
            roleArn=gateway_role_arn,
            protocolType="MCP",
            authorizerType="CUSTOM_JWT",
            authorizerConfiguration=auth_config,
            description="Issue Analyzer AgentCore Gateway",
        )

        gateway_id = create_response["gatewayId"]
        gateway = {
            "id": gateway_id,
            "name": GATEWAY_NAME,
            "gateway_url": create_response["gatewayUrl"],
            "gateway_arn": create_response["gatewayArn"],
        }

        put_ssm_parameter(GATEWAY_ID_SSM_PARAM, gateway_id)
        put_ssm_parameter(GATEWAY_URL_SSM_PARAM, create_response["gatewayUrl"])
        put_ssm_parameter(GATEWAY_ARN_SSM_PARAM, create_response["gatewayArn"])

        # Wait for gateway to become active
        print("  Waiting for gateway to become ACTIVE...")
        time.sleep(3)
        for _ in range(20):
            status_resp = gateway_client.get_gateway(gatewayIdentifier=gateway_id)
            status = status_resp.get("status", "CREATING")
            if status == "ACTIVE" or status == "READY":
                print(f"  Gateway is {status}")
                break
            print(f"  Gateway status: {status}, waiting...")
            time.sleep(5)

        return gateway

    except gateway_client.exceptions.ConflictException:
        print(f"  Gateway {GATEWAY_NAME} already exists")
        gateways = gateway_client.list_gateways()
        for gw in gateways.get("items", []):
            if gw["name"] == GATEWAY_NAME:
                gateway_id = gw["gatewayId"]
                gw_detail = gateway_client.get_gateway(gatewayIdentifier=gateway_id)
                gateway = {
                    "id": gateway_id,
                    "name": GATEWAY_NAME,
                    "gateway_url": gw_detail.get("gatewayUrl", ""),
                }
                put_ssm_parameter(GATEWAY_ID_SSM_PARAM, gateway_id)
                if gw_detail.get("gatewayUrl"):
                    put_ssm_parameter(GATEWAY_URL_SSM_PARAM, gw_detail["gatewayUrl"])
                if gw_detail.get("gatewayArn"):
                    put_ssm_parameter(GATEWAY_ARN_SSM_PARAM, gw_detail["gatewayArn"])
                return gateway
        return None
    except Exception as e:
        print(f"  Failed to create gateway: {e}")
        return None


# ---------------------------------------------------------------------------
# Step 9: Gateway Target
# ---------------------------------------------------------------------------

def setup_gateway_target(gateway_id: str, lambda_arn: str) -> str | None:
    """Create a Gateway Target pointing at the Lambda function.

    Returns the target ID or None on failure.
    """
    gateway_client = boto3.client("bedrock-agentcore-control", region_name=AWS_REGION)

    api_spec_path = os.path.join(os.path.dirname(__file__), "lambda_tools", "api_spec.json")
    with open(api_spec_path) as f:
        api_spec = json.load(f)

    lambda_target_config = {
        "mcp": {
            "lambda": {
                "lambdaArn": lambda_arn,
                "toolSchema": {"inlinePayload": api_spec},
            }
        }
    }

    credential_config = [{"credentialProviderType": "GATEWAY_IAM_ROLE"}]

    try:
        response = gateway_client.create_gateway_target(
            gatewayIdentifier=gateway_id,
            name="LambdaToolTarget",
            description="Lambda target for IssueAnalyzer tools",
            targetConfiguration=lambda_target_config,
            credentialProviderConfigurations=credential_config,
        )
        target_id = response["targetId"]
        print(f"  Gateway target created: {target_id}")

        # Wait for target to become active
        print("  Waiting for target to become ACTIVE...")
        for _ in range(20):
            target_resp = gateway_client.get_gateway_target(
                gatewayIdentifier=gateway_id,
                targetId=target_id,
            )
            status = target_resp.get("status", "CREATING")
            if status == "ACTIVE" or status == "READY":
                print(f"  Target is {status}")
                break
            print(f"  Target status: {status}, waiting...")
            time.sleep(5)

        return target_id

    except gateway_client.exceptions.ConflictException:
        print("  Gateway target 'LambdaToolTarget' already exists")
        return "existing"
    except Exception as e:
        print(f"  Failed to create gateway target: {e}")
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("GitHub Issue Analyzer — AWS Setup")
    print("=" * 60)

    total_steps = 9

    # Step 1: IAM permissions for execution role
    print(f"\n[1/{total_steps}] Checking IAM permissions...")
    role_name = get_current_role_name()
    if role_name:
        print(f"  Current role: {role_name}")
        policies = [
            ("arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess", "AmazonDynamoDBFullAccess"),
            ("arn:aws:iam::aws:policy/AmazonBedrockFullAccess", "AmazonBedrockFullAccess"),
            ("arn:aws:iam::aws:policy/AmazonSSMFullAccess", "AmazonSSMFullAccess"),
            ("arn:aws:iam::aws:policy/AWSLambda_FullAccess", "AWSLambda_FullAccess"),
            ("arn:aws:iam::aws:policy/IAMFullAccess", "IAMFullAccess"),
            ("arn:aws:iam::aws:policy/AmazonCognitoPowerUser", "AmazonCognitoPowerUser"),
        ]
        for policy_arn, label in policies:
            try:
                attach_policy(role_name, policy_arn, label)
            except Exception as e:
                print(f"  Could not attach {label}: {e}")
    else:
        print("  Not running as an assumed role. Skipping IAM setup.")
        print("  Ensure your credentials have DynamoDB, Bedrock, SSM, Lambda, IAM, and Cognito access.")

    # Step 2: DynamoDB tables
    print(f"\n[2/{total_steps}] Creating DynamoDB tables...")
    ensure_tables_exist()
    print("  Tables ready.")

    # Step 3: AgentCore Memory
    print(f"\n[3/{total_steps}] Setting up AgentCore Memory...")
    memory_id = setup_agentcore_memory()

    # Step 4: Lambda Execution IAM Role
    print(f"\n[4/{total_steps}] Creating Lambda execution IAM role...")
    lambda_role_arn = setup_lambda_role()

    # Step 5: Gateway IAM Role
    print(f"\n[5/{total_steps}] Creating Gateway IAM role...")
    gateway_role_arn = setup_gateway_role()

    # Step 6: Lambda Function
    print(f"\n[6/{total_steps}] Deploying Lambda function...")
    lambda_arn = setup_lambda_function(lambda_role_arn)

    # Step 7: Cognito User Pool
    print(f"\n[7/{total_steps}] Setting up Cognito User Pool...")
    cognito_config = setup_cognito()
    if not cognito_config:
        print("  Cognito setup failed. Gateway will not be available.")
        print("  The Recommender Agent will fall back to local tools.")
        _print_summary(memory_id, lambda_arn, None, None)
        return

    # Step 8: AgentCore Gateway
    print(f"\n[8/{total_steps}] Creating AgentCore Gateway...")
    gateway = setup_gateway(cognito_config, gateway_role_arn)
    if not gateway:
        print("  Gateway creation failed. The Recommender Agent will fall back to local tools.")
        _print_summary(memory_id, lambda_arn, None, None)
        return

    # Step 9: Gateway Target
    print(f"\n[9/{total_steps}] Creating Gateway Target...")
    target_id = setup_gateway_target(gateway["id"], lambda_arn)

    _print_summary(memory_id, lambda_arn, gateway, target_id)


def _print_summary(memory_id, lambda_arn, gateway, target_id):
    print("\n" + "=" * 60)
    print("Setup Summary:")
    print(f"  Memory ID:        {memory_id or 'skipped'}")
    print(f"  Lambda ARN:       {lambda_arn or 'skipped'}")
    if gateway:
        print(f"  Gateway ID:       {gateway['id']}")
        print(f"  Gateway URL:      {gateway.get('gateway_url', 'N/A')}")
        print(f"  Target ID:        {target_id or 'failed'}")
    else:
        print("  Gateway:          not configured")
    print("=" * 60)
    print("You can now run: streamlit run app.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
