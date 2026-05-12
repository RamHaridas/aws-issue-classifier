"""
Classifier Agent — Uses Strands Agents + Amazon Nova to classify GitHub issues.

The Streamlit app orchestrates batching. For each batch, the agent classifies
the issues and returns structured JSON. Results are saved to DynamoDB.
"""

import json
import uuid
from datetime import datetime, timezone

import boto3
from strands import Agent
from strands.models import BedrockModel

from config import (
    CATEGORIES,
    SEVERITIES,
    CLASSIFICATION_BATCH_SIZE,
    BEDROCK_MODEL_ID,
    AWS_REGION,
)
from dynamo_utils import save_classifications, ensure_tables_exist


CLASSIFIER_SYSTEM_PROMPT = f"""You are an expert software issue classifier for open source repositories.

When given a batch of GitHub issues, you MUST classify each one and respond with ONLY a JSON array.
Do NOT include any text before or after the JSON. Do NOT use markdown code fences.

For each issue, provide:
- issue_number: the issue number (integer)
- category: one of {json.dumps(CATEGORIES)}
- subcategory: a 2-4 word refinement within the category
- severity: one of {json.dumps(SEVERITIES)}
- affected_component: the module, file, or subsystem affected (be specific, use the issue context)
- summary: one-sentence summary of the core problem

Rules:
- Pick the single best-fit category. If unsure, use "Other".
- Infer severity from impact described: crashes/data loss = Critical, major breakage = High,
  partial breakage with workaround = Medium, minor/cosmetic = Low, questions/discussions = Informational.
- For affected_component, extract from the issue title/body. If unclear, use "general".
- Keep summaries factual and concise.

Respond with ONLY the JSON array. Example format:
[
  {{"issue_number": 123, "category": "Bug", "subcategory": "crash on startup", "severity": "Critical", "affected_component": "server/core", "summary": "Server crashes on startup with null config"}},
  {{"issue_number": 456, "category": "Documentation", "subcategory": "missing API docs", "severity": "Low", "affected_component": "docs/api", "summary": "REST API endpoints lack usage examples"}}
]"""


def _create_classifier_model():
    return BedrockModel(
        model_id=BEDROCK_MODEL_ID,
        temperature=0.1,
        region_name=AWS_REGION,
    )


def _format_issues_for_prompt(issues: list[dict]) -> str:
    """Format a batch of issues into a prompt string."""
    lines = []
    for issue in issues:
        labels_str = ", ".join(issue["labels"]) if issue["labels"] else "none"
        body = issue["body"].strip() or "(no description)"
        lines.append(
            f"Issue #{issue['number']}: \"{issue['title']}\"\n"
            f"  Labels: [{labels_str}]\n"
            f"  Body: {body}\n"
        )
    return "\n".join(lines)


def _parse_classifications(response_text: str) -> list[dict]:
    """Extract the JSON array from the agent's response, handling common LLM quirks."""
    text = response_text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        first_newline = text.index("\n")
        text = text[first_newline + 1:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    # Find the JSON array boundaries
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON array found in response: {text[:200]}")

    json_str = text[start:end + 1]
    return json.loads(json_str)


def classify_batch(issues: list[dict]) -> list[dict]:
    """Classify a single batch of issues using the Strands Agent.

    Args:
        issues: List of issue dicts (from github_fetcher)

    Returns:
        List of classification dicts with keys: issue_number, category,
        subcategory, severity, affected_component, summary
    """
    model = _create_classifier_model()
    agent = Agent(
        model=model,
        system_prompt=CLASSIFIER_SYSTEM_PROMPT,
    )

    prompt = (
        f"Classify these {len(issues)} GitHub issues. "
        f"Respond with ONLY a JSON array.\n\n"
        f"{_format_issues_for_prompt(issues)}"
    )

    response = agent(prompt)
    response_text = response.message["content"][0]["text"]
    return _parse_classifications(response_text)


def classify_issues(
    issues: list[dict],
    repo_slug: str,
    batch_size: int = CLASSIFICATION_BATCH_SIZE,
    progress_callback=None,
    skip_existing: bool = True,
    existing_numbers: set[int] | None = None,
) -> list[dict]:
    """Classify all issues in batches, saving each batch to DynamoDB.

    Args:
        issues: Full list of issues from github_fetcher
        repo_slug: "owner/repo" string
        batch_size: Number of issues per LLM call
        progress_callback: Optional callable(classified_so_far, total, batch_num)
        skip_existing: Whether to skip already-classified issue numbers
        existing_numbers: Pre-fetched set of already-classified issue numbers

    Returns:
        List of all classification dicts (including merged fields from original issues)
    """
    ensure_tables_exist()

    # Filter out already-classified issues
    if skip_existing and existing_numbers:
        issues = [i for i in issues if i["number"] not in existing_numbers]

    if not issues:
        return []

    all_classifications = []
    total = len(issues)
    batch_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # Process in batches
    for batch_start in range(0, total, batch_size):
        batch = issues[batch_start:batch_start + batch_size]
        batch_num = (batch_start // batch_size) + 1

        try:
            classifications = classify_batch(batch)
        except Exception as e:
            print(f"Batch {batch_num} classification failed: {e}")
            # On failure, assign "Other" to the batch so we don't lose them
            classifications = [
                {
                    "issue_number": issue["number"],
                    "category": "Other",
                    "subcategory": "classification failed",
                    "severity": "Informational",
                    "affected_component": "unknown",
                    "summary": f"Classification error: {str(e)[:100]}",
                }
                for issue in batch
            ]

        # Build a lookup from issue number to original issue data
        issue_lookup = {i["number"]: i for i in batch}

        # Merge original issue data with classification results
        enriched = []
        for clf in classifications:
            issue_num = clf["issue_number"]
            original = issue_lookup.get(issue_num, {})
            enriched.append({
                **clf,
                "title": original.get("title", ""),
                "body_snippet": original.get("body", ""),
                "url": original.get("url", ""),
                "original_labels": original.get("labels", []),
                "created_at": original.get("created_at", ""),
                "closed_at": original.get("closed_at", ""),
                "classified_at": now,
                "batch_id": batch_id,
            })

        # Save this batch to DynamoDB
        save_classifications(repo_slug, enriched)
        all_classifications.extend(enriched)

        classified_so_far = batch_start + len(batch)
        if progress_callback:
            progress_callback(classified_so_far, total, batch_num)

    return all_classifications
