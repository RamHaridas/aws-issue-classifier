from read_classification_data import read_classification_data
from get_repository_structure import get_repository_structure


def get_named_parameter(event, name):
    if name not in event:
        return None
    return event.get(name)


def lambda_handler(event, context):
    print(f"Event: {event}")
    print(f"Context: {context}")

    extended_tool_name = context.client_context.custom["bedrockAgentCoreToolName"]
    resource = extended_tool_name.split("___")[1]

    print(resource)

    if resource == "read_classification_data":
        repo_slug = get_named_parameter(event=event, name="repo_slug")

        if not repo_slug:
            return {
                "statusCode": 400,
                "body": "Please provide repo_slug",
            }

        try:
            result = read_classification_data(repo_slug=repo_slug)
        except Exception as e:
            print(e)
            return {
                "statusCode": 400,
                "body": f"Error: {e}",
            }

        return {
            "statusCode": 200,
            "body": result,
        }

    elif resource == "get_repository_structure":
        repo_owner = get_named_parameter(event=event, name="repo_owner")
        repo_name = get_named_parameter(event=event, name="repo_name")
        github_token = get_named_parameter(event=event, name="github_token") or ""

        if not repo_owner or not repo_name:
            return {
                "statusCode": 400,
                "body": "Please provide repo_owner and repo_name",
            }

        try:
            result = get_repository_structure(
                repo_owner=repo_owner,
                repo_name=repo_name,
                github_token=github_token,
            )
        except Exception as e:
            print(e)
            return {
                "statusCode": 400,
                "body": f"Error: {e}",
            }

        return {
            "statusCode": 200,
            "body": result,
        }

    return {
        "statusCode": 400,
        "body": f"Unknown toolname: {resource}",
    }
