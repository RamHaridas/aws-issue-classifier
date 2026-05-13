import json
from collections import Counter

import boto3

DYNAMO_TABLE_CLASSIFICATIONS = "IssueClassifications"

dynamodb = boto3.resource("dynamodb")


def read_classification_data(repo_slug: str) -> str:
    """Read classified issues from DynamoDB and compute aggregate statistics."""
    table = dynamodb.Table(DYNAMO_TABLE_CLASSIFICATIONS)

    items = []
    scan_kwargs = {
        "FilterExpression": boto3.dynamodb.conditions.Attr("repo_slug").eq(repo_slug),
    }
    while True:
        response = table.scan(**scan_kwargs)
        items.extend(response.get("Items", []))
        if "LastEvaluatedKey" not in response:
            break
        scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]

    if not items:
        return json.dumps({"error": "No classification data found for this repository."})

    cat_counts = Counter(item.get("category", "Other") for item in items)
    sev_counts = Counter(item.get("severity", "Medium") for item in items)

    monthly = {}
    for item in items:
        closed = item.get("closed_at", "")
        cat = item.get("category", "Other")
        if closed:
            month = closed[:7]
            if month not in monthly:
                monthly[month] = Counter()
            monthly[month][cat] += 1

    trend_data = []
    for month in sorted(monthly.keys()):
        entry = {"month": month}
        entry.update(dict(monthly[month]))
        trend_data.append(entry)

    comp_items = {}
    for item in items:
        comp = item.get("affected_component", "unknown")
        if comp not in comp_items:
            comp_items[comp] = []
        comp_items[comp].append(item)

    hotspots = []
    for comp, comp_issues in sorted(comp_items.items(), key=lambda x: len(x[1]), reverse=True)[:15]:
        sev_breakdown = Counter(i.get("severity", "Medium") for i in comp_issues)
        top_cats = Counter(i.get("category", "Other") for i in comp_issues).most_common(3)
        hotspots.append({
            "component": comp,
            "issue_count": len(comp_issues),
            "severity_breakdown": dict(sev_breakdown),
            "top_categories": [{"category": c, "count": n} for c, n in top_cats],
        })

    security_issues = [i for i in items if i.get("category") == "Security"]

    payload = {
        "total_issues": len(items),
        "category_distribution": dict(cat_counts.most_common()),
        "severity_distribution": dict(sev_counts),
        "hotspots": hotspots,
        "trend_data": trend_data,
        "security_issues_count": len(security_issues),
        "security_summaries": [
            {
                "issue_number": i.get("issue_number"),
                "summary": i.get("summary", ""),
                "severity": i.get("severity", ""),
            }
            for i in security_issues[:20]
        ],
        "sample_issues": [
            {
                "issue_number": i.get("issue_number"),
                "title": i.get("title", ""),
                "category": i.get("category", ""),
                "severity": i.get("severity", ""),
                "component": i.get("affected_component", ""),
                "summary": i.get("summary", ""),
            }
            for i in items[:50]
        ],
    }

    return json.dumps(payload, default=str)
