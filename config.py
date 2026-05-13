"""
Configuration constants for the GitHub Issue Analyzer.
"""

# --- Category Taxonomy ---
CATEGORIES = [
    "Bug",
    "Configuration",
    "Security",
    "Performance",
    "Compatibility",
    "Documentation",
    "Feature Request",
    "UI/UX",
    "Installation/Setup",
    "Testing",
    "Networking",
    "Data/Storage",
    "Other",
]

SEVERITIES = [
    "Critical",
    "High",
    "Medium",
    "Low",
    "Informational",
]

# --- Date Range Options ---
DATE_RANGE_OPTIONS = {
    "Last 30 days": 30,
    "Last 60 days": 60,
    "Last 90 days": 90,
    "Last 180 days": 180,
    "Last 365 days": 365,
}

# --- GitHub API ---
GITHUB_API_BASE = "https://api.github.com"
GITHUB_ISSUES_PER_PAGE = 100
GITHUB_ISSUE_BODY_MAX_CHARS = 500

# --- AWS / DynamoDB ---
DYNAMO_TABLE_CLASSIFICATIONS = "IssueClassifications"
DYNAMO_TABLE_RECOMMENDATIONS = "RecommendationResults"
BEDROCK_MODEL_ID = "us.amazon.nova-lite-v1:0"

# Workshop model (use if the above doesn't work in your region):
# BEDROCK_MODEL_ID = "global.amazon.nova-2-lite-v1:0"
AWS_REGION = "us-west-2"

# --- Classifier ---
CLASSIFICATION_BATCH_SIZE = 15

# --- AgentCore Memory ---
MEMORY_NAME = "IssueAnalyzerMemory"
MEMORY_SSM_PARAM = "/app/issueanalyzer/agentcore/memory_id"
MEMORY_EVENT_EXPIRY_DAYS = 90

# --- AgentCore Gateway ---
GATEWAY_SSM_PREFIX = "/app/issueanalyzer/agentcore"
GATEWAY_NAME = "issueanalyzer-gw"
GATEWAY_ID_SSM_PARAM = f"{GATEWAY_SSM_PREFIX}/gateway_id"
GATEWAY_URL_SSM_PARAM = f"{GATEWAY_SSM_PREFIX}/gateway_url"
GATEWAY_ARN_SSM_PARAM = f"{GATEWAY_SSM_PREFIX}/gateway_arn"
GATEWAY_IAM_ROLE_SSM_PARAM = f"{GATEWAY_SSM_PREFIX}/gateway_iam_role"

# --- Lambda ---
LAMBDA_FUNCTION_NAME = "IssueAnalyzerTools"
LAMBDA_ARN_SSM_PARAM = f"{GATEWAY_SSM_PREFIX}/lambda_arn"
LAMBDA_ROLE_ARN_SSM_PARAM = f"{GATEWAY_SSM_PREFIX}/lambda_role_arn"
LAMBDA_ROLE_NAME = "IssueAnalyzerLambdaRole"

# --- Cognito ---
COGNITO_POOL_ID_SSM_PARAM = f"{GATEWAY_SSM_PREFIX}/cognito_pool_id"
COGNITO_CLIENT_ID_SSM_PARAM = f"{GATEWAY_SSM_PREFIX}/cognito_client_id"
COGNITO_CLIENT_SECRET_SSM_PARAM = f"{GATEWAY_SSM_PREFIX}/cognito_client_secret"
COGNITO_DISCOVERY_URL_SSM_PARAM = f"{GATEWAY_SSM_PREFIX}/cognito_discovery_url"
COGNITO_USERNAME = "agent_user"
COGNITO_PASSWORD = "AgentPass123!"

# --- AgentCore Runtime ---
RUNTIME_AGENT_NAME = "issue_analyzer_recommender"
RUNTIME_ROLE_NAME = "IssueAnalyzerRuntimeRole"
RUNTIME_ROLE_ARN_SSM_PARAM = f"{GATEWAY_SSM_PREFIX}/runtime_execution_role_arn"
RUNTIME_ARN_SSM_PARAM = f"{GATEWAY_SSM_PREFIX}/runtime_arn"
