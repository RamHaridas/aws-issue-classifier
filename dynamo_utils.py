"""
DynamoDB utilities for storing and retrieving classification and recommendation data.
"""

import boto3
from botocore.exceptions import ClientError
from datetime import datetime, timezone
from config import (
    AWS_REGION,
    DYNAMO_TABLE_CLASSIFICATIONS,
    DYNAMO_TABLE_RECOMMENDATIONS,
)


def get_dynamodb_resource():
    return boto3.resource("dynamodb", region_name=AWS_REGION)


def get_dynamodb_client():
    return boto3.client("dynamodb", region_name=AWS_REGION)


def _create_table_if_not_exists(client, table_name: str, key_schema: list, attr_defs: list):
    """Create a single DynamoDB table, ignoring if it already exists."""
    try:
        client.create_table(
            TableName=table_name,
            KeySchema=key_schema,
            AttributeDefinitions=attr_defs,
            BillingMode="PAY_PER_REQUEST",
        )
        waiter = client.get_waiter("table_exists")
        waiter.wait(TableName=table_name)
        print(f"Created table: {table_name}")
    except client.exceptions.ResourceInUseException:
        pass  # Table already exists


def ensure_tables_exist():
    """Create DynamoDB tables if they don't already exist."""
    client = get_dynamodb_client()

    _create_table_if_not_exists(
        client,
        DYNAMO_TABLE_CLASSIFICATIONS,
        key_schema=[
            {"AttributeName": "repo_slug", "KeyType": "HASH"},
            {"AttributeName": "issue_number", "KeyType": "RANGE"},
        ],
        attr_defs=[
            {"AttributeName": "repo_slug", "AttributeType": "S"},
            {"AttributeName": "issue_number", "AttributeType": "N"},
        ],
    )

    _create_table_if_not_exists(
        client,
        DYNAMO_TABLE_RECOMMENDATIONS,
        key_schema=[
            {"AttributeName": "repo_slug", "KeyType": "HASH"},
            {"AttributeName": "run_id", "KeyType": "RANGE"},
        ],
        attr_defs=[
            {"AttributeName": "repo_slug", "AttributeType": "S"},
            {"AttributeName": "run_id", "AttributeType": "S"},
        ],
    )


def save_classifications(repo_slug: str, classifications: list[dict]):
    """Batch-write classified issues to DynamoDB."""
    table = get_dynamodb_resource().Table(DYNAMO_TABLE_CLASSIFICATIONS)

    with table.batch_writer() as batch:
        for item in classifications:
            batch.put_item(Item={
                "repo_slug": repo_slug,
                "issue_number": item["issue_number"],
                "title": item.get("title", ""),
                "body_snippet": item.get("body_snippet", ""),
                "url": item.get("url", ""),
                "original_labels": item.get("original_labels", []),
                "category": item.get("category", "Other"),
                "subcategory": item.get("subcategory", ""),
                "severity": item.get("severity", "Medium"),
                "affected_component": item.get("affected_component", "Unknown"),
                "summary": item.get("summary", ""),
                "created_at": item.get("created_at", ""),
                "closed_at": item.get("closed_at", ""),
                "classified_at": item.get("classified_at", ""),
                "batch_id": item.get("batch_id", ""),
            })

    return len(classifications)


def get_classifications(repo_slug: str) -> list[dict]:
    """Retrieve all classifications for a repository."""
    table = get_dynamodb_resource().Table(DYNAMO_TABLE_CLASSIFICATIONS)

    items = []
    response = table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key("repo_slug").eq(repo_slug),
    )
    items.extend(response.get("Items", []))

    while "LastEvaluatedKey" in response:
        response = table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key("repo_slug").eq(repo_slug),
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        items.extend(response.get("Items", []))

    return items


def get_classified_issue_numbers(repo_slug: str) -> set[int]:
    """Get the set of issue numbers already classified for a repo (to skip duplicates)."""
    table = get_dynamodb_resource().Table(DYNAMO_TABLE_CLASSIFICATIONS)

    numbers = set()
    response = table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key("repo_slug").eq(repo_slug),
        ProjectionExpression="issue_number",
    )
    for item in response.get("Items", []):
        numbers.add(int(item["issue_number"]))

    while "LastEvaluatedKey" in response:
        response = table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key("repo_slug").eq(repo_slug),
            ProjectionExpression="issue_number",
            ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        for item in response.get("Items", []):
            numbers.add(int(item["issue_number"]))

    return numbers


def save_recommendations(repo_slug: str, insights: dict):
    """Save recommendation results to DynamoDB."""
    table = get_dynamodb_resource().Table(DYNAMO_TABLE_RECOMMENDATIONS)
    run_id = datetime.now(timezone.utc).isoformat()

    # DynamoDB can't store float('inf') or empty sets, so sanitize
    item = {
        "repo_slug": repo_slug,
        "run_id": run_id,
    }
    for key, value in insights.items():
        if value is not None and value != "":
            item[key] = value

    table.put_item(Item=item)
    return run_id


def get_latest_recommendation(repo_slug: str) -> dict | None:
    """Get the most recent recommendation run for a repo."""
    table = get_dynamodb_resource().Table(DYNAMO_TABLE_RECOMMENDATIONS)

    response = table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key("repo_slug").eq(repo_slug),
        ScanIndexForward=False,  # Descending order by sort key
        Limit=1,
    )
    items = response.get("Items", [])
    return items[0] if items else None


def delete_classifications(repo_slug: str):
    """Delete all classifications for a repository (for re-classification)."""
    table = get_dynamodb_resource().Table(DYNAMO_TABLE_CLASSIFICATIONS)
    items = get_classifications(repo_slug)

    with table.batch_writer() as batch:
        for item in items:
            batch.delete_item(Key={
                "repo_slug": repo_slug,
                "issue_number": item["issue_number"],
            })

    return len(items)
