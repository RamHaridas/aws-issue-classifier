"""
One-time AWS setup for the GitHub Issue Analyzer.

Run this before using the app for the first time. It:
1. Creates the DynamoDB tables (IssueClassifications, RecommendationResults)
2. Attaches DynamoDB permissions to the current IAM role (for SageMaker environments)

Usage:
    python setup_aws.py
"""

import boto3
import json
from config import AWS_REGION
from dynamo_utils import ensure_tables_exist


def get_current_role_name() -> str | None:
    """Extract the IAM role name from the current caller identity."""
    sts = boto3.client("sts", region_name=AWS_REGION)
    identity = sts.get_caller_identity()
    arn = identity["Arn"]
    # Format: arn:aws:sts::ACCOUNT:assumed-role/ROLE_NAME/SESSION
    if "assumed-role" in arn:
        return arn.split("/")[1]
    return None


def attach_dynamodb_policy(role_name: str):
    """Attach AmazonDynamoDBFullAccess policy to the given IAM role."""
    iam = boto3.client("iam", region_name=AWS_REGION)
    policy_arn = "arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess"

    # Check if already attached
    attached = iam.list_attached_role_policies(RoleName=role_name)
    for policy in attached["AttachedPolicies"]:
        if policy["PolicyArn"] == policy_arn:
            print(f"  DynamoDB policy already attached to {role_name}")
            return

    iam.attach_role_policy(RoleName=role_name, PolicyArn=policy_arn)
    print(f"  Attached AmazonDynamoDBFullAccess to {role_name}")


def main():
    print("=" * 60)
    print("GitHub Issue Analyzer — AWS Setup")
    print("=" * 60)

    # Step 1: IAM permissions
    print("\n[1/2] Checking IAM permissions...")
    role_name = get_current_role_name()
    if role_name:
        print(f"  Current role: {role_name}")
        try:
            attach_dynamodb_policy(role_name)
        except Exception as e:
            print(f"  Could not attach policy automatically: {e}")
            print(f"  Please manually attach 'AmazonDynamoDBFullAccess' to role: {role_name}")
            print(f"  Go to: IAM > Roles > {role_name} > Add permissions > Attach policies")
    else:
        print("  Not running as an assumed role. Skipping IAM setup.")
        print("  Ensure your credentials have DynamoDB read/write access.")

    # Step 2: DynamoDB tables
    print("\n[2/2] Creating DynamoDB tables...")
    ensure_tables_exist()
    print("  Tables ready.")

    print("\n" + "=" * 60)
    print("Setup complete! You can now run: streamlit run app.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
