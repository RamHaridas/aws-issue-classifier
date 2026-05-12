"""
DynamoDB utilities for storing and retrieving classification and recommendation data.
"""

import boto3
from botocore.exceptions import ClientError
from config import (
    AWS_REGION,
    DYNAMO_TABLE_CLASSIFICATIONS,
    DYNAMO_TABLE_RECOMMENDATIONS,
)


def get_dynamodb_resource():
    return boto3.resource("dynamodb", region_name=AWS_REGION)


def get_dynamodb_client():
    return boto3.client("dynamodb", region_name=AWS_REGION)


def ensure_tables_exist():
    """Create DynamoDB tables if they don't already exist."""
    client = get_dynamodb_client()
    existing = client.list_tables()["TableNames"]

    if DYNAMO_TABLE_CLASSIFICATIONS not in existing:
        client.create_table(
            TableName=DYNAMO_TABLE_CLASSIFICATIONS,
            KeySchema=[
                {"AttributeName": "repo_slug", "KeyType": "HASH"},
                {"AttributeName": "issue_number", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "repo_slug", "AttributeType": "S"},
                {"AttributeName": "issue_number", "AttributeType": "N"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        waiter = client.get_waiter("table_exists")
        waiter.wait(TableName=DYNAMO_TABLE_CLASSIFICATIONS)
        print(f"Created table: {DYNAMO_TABLE_CLASSIFICATIONS}")

    if DYNAMO_TABLE_RECOMMENDATIONS not in existing:
        client.create_table(
            TableName=DYNAMO_TABLE_RECOMMENDATIONS,
            KeySchema=[
                {"AttributeName": "repo_slug", "KeyType": "HASH"},
                {"AttributeName": "run_id", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "repo_slug", "AttributeType": "S"},
                {"AttributeName": "run_id", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        waiter = client.get_waiter("table_exists")
        waiter.wait(TableName=DYNAMO_TABLE_RECOMMENDATIONS)
        print(f"Created table: {DYNAMO_TABLE_RECOMMENDATIONS}")


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
