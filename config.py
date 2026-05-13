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

# --- Issue Type Taxonomy ---
ISSUE_TYPES = {
    "Defect": (
        "Something is broken, behaves incorrectly, crashes, or produces wrong output. "
        "The reporter expects existing functionality to work and it does not. Includes "
        "regressions and security vulnerabilities that manifest as broken behavior."
    ),
    "Support": (
        "User is asking how to do something, requesting clarification, troubleshooting "
        "their own setup, or seeking help understanding the project. Nothing is necessarily "
        "broken in the project itself; the user needs guidance. Use this for \u201chow do I\u2026?\u201d, "
        "\u201cis this expected?\u201d, and configuration help requests."
    ),
    "Enhancement": (
        "Request for new functionality or for an improvement to existing user-visible "
        "functionality. Includes feature requests, \u201cwould be nice\u201d, \u201cplease add\u201d, and "
        "performance improvement requests when nothing is broken. Use this when the project "
        "does not currently do what the reporter wants and they are asking for it to. "
        "Does NOT include internal-only work \u2014 that is \u201cTask\u201d."
    ),
    "Documentation": (
        "The issue is fundamentally about documentation work itself: missing docs, incorrect "
        "docs, unclear docs, requests for examples, tutorials, README updates, API reference "
        "fixes, changelog entries. Use this even when phrased as a question, IF the resolution "
        "is \u201cimprove the docs\u201d rather than \u201cexplain it once to this user\u201d."
    ),
    "Task": (
        "Internal work with NO user-visible behavior change: refactoring, code cleanup, test "
        "scaffolding, build/CI maintenance, dependency bumps that do not change behavior, lint "
        "fixes, repo chores. Use this for maintainer-driven work that is neither a Defect nor "
        "an Enhancement."
    ),
}

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
BEDROCK_MODEL_ID = "us.amazon.nova-pro-v1:0"

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
