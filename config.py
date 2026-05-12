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
