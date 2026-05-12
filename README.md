# GitHub Issue Analyzer

AI-powered tool that fetches closed issues from any public GitHub repository, classifies them by category/severity, and generates actionable insights for maintainers.

Built on Amazon Bedrock AgentCore services (Nova 2 Lite, DynamoDB, Strands Agents).

## SageMaker Studio (recommended)

```bash
git clone https://github.com/RamHaridas/aws-issue-classifier.git
cd aws-issue-classifier
pip install -r requirements.txt
```

Then open `launch.ipynb` in JupyterLab and run all cells. The notebook will:
1. Install dependencies
2. Run first-time AWS setup (DynamoDB tables + IAM permissions)
3. Print the app URL
4. Start Streamlit

## Local Development

```bash
pip install -r requirements.txt
python setup_aws.py          # One-time: creates DynamoDB tables + IAM permissions
python -m streamlit run app.py
```

## AWS Prerequisites

- AWS credentials with access to Amazon Bedrock (Nova 2 Lite enabled)
- The `setup_aws.py` script handles DynamoDB table creation and IAM permissions automatically
