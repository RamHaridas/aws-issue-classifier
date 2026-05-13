"""
One-shot migration of existing DynamoDB rows from old ISSUE_TYPES values to new ones.

Usage:
    # Dry run (default) — shows what would change without mutating:
    python scripts/migrate_issue_types.py

    # Apply changes:
    python scripts/migrate_issue_types.py --apply

    # Filter to a single repo:
    python scripts/migrate_issue_types.py --repo-slug owner/repo --apply
"""

import argparse
import sys
from collections import Counter

import boto3

sys.path.insert(0, ".")
from config import AWS_REGION, DYNAMO_TABLE_CLASSIFICATIONS, ISSUE_TYPES

OLD_TO_NEW = {
    "Bug": "Defect",
    "Feature Request": "Enhancement",
    "Question": "Support",
    "Task": "Task",
    "Documentation": "Documentation",
    "Other": "Support",
}

NEW_TYPES = set(ISSUE_TYPES.keys())


def scan_table(table, repo_slug=None):
    """Scan the IssueClassifications table, optionally filtered by repo_slug."""
    scan_kwargs = {}
    if repo_slug:
        scan_kwargs["FilterExpression"] = boto3.dynamodb.conditions.Attr(
            "repo_slug"
        ).eq(repo_slug)

    items = []
    while True:
        response = table.scan(**scan_kwargs)
        items.extend(response.get("Items", []))
        if "LastEvaluatedKey" not in response:
            break
        scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
    return items


def compute_new_type(old_value):
    """Map an old issue_type value to its new equivalent."""
    if old_value in NEW_TYPES:
        return None  # already migrated
    if old_value in OLD_TO_NEW:
        return OLD_TO_NEW[old_value]
    return "Support"  # unmapped or missing


def migrate(apply: bool, repo_slug: str | None):
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    table = dynamodb.Table(DYNAMO_TABLE_CLASSIFICATIONS)

    print(f"Scanning table '{DYNAMO_TABLE_CLASSIFICATIONS}' "
          f"(region={AWS_REGION})...")
    if repo_slug:
        print(f"  Filtering to repo_slug='{repo_slug}'")

    items = scan_table(table, repo_slug)
    print(f"  Rows scanned: {len(items)}")

    mapping_counts = Counter()
    rows_to_change = []

    for item in items:
        old_type = item.get("issue_type")
        display_old = old_type if old_type is not None else "<missing>"

        if old_type is None:
            new_type = "Support"
        else:
            new_type = compute_new_type(old_type)

        if new_type is None:
            continue  # already in new set

        mapping_counts[f"{display_old} -> {new_type}"] += 1
        rows_to_change.append({
            "repo_slug": item["repo_slug"],
            "issue_number": item["issue_number"],
            "new_type": new_type,
        })

    if not rows_to_change:
        print("\nNo rows need updating. All issue_type values are already current.")
        return

    mode = "Would change" if not apply else "Changed"
    print(f"\n{mode} {len(rows_to_change)} row(s):")
    print("\nPer-mapping breakdown:")
    for mapping, count in sorted(mapping_counts.items()):
        print(f"  {mapping}: {count}")

    if not apply:
        print("\nDry run complete. Use --apply to write changes.")
        return

    changed = 0
    for row in rows_to_change:
        table.update_item(
            Key={
                "repo_slug": row["repo_slug"],
                "issue_number": row["issue_number"],
            },
            UpdateExpression="SET issue_type = :t",
            ExpressionAttributeValues={":t": row["new_type"]},
        )
        changed += 1

    print(f"\nMigration complete. {changed} row(s) updated.")


def main():
    parser = argparse.ArgumentParser(
        description="Migrate issue_type values from old taxonomy to new."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Actually write changes. Without this flag, runs in dry-run mode.",
    )
    parser.add_argument(
        "--repo-slug",
        type=str,
        default=None,
        help="Optional repo_slug filter (e.g. 'owner/repo').",
    )
    args = parser.parse_args()
    migrate(apply=args.apply, repo_slug=args.repo_slug)


if __name__ == "__main__":
    main()
