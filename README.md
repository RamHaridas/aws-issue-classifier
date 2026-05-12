# GitHub Issue Analyzer

AI-powered tool that fetches closed issues from any public GitHub repository, classifies them by category/severity, and generates actionable insights for maintainers.

Built on Amazon Bedrock AgentCore services.

## Quick Start

```bash
pip install -r requirements.txt
python -m streamlit run app.py
```

## SageMaker Studio

```bash
git clone https://github.com/<your-username>/github-issue-analyzer.git
cd github-issue-analyzer
pip install -r requirements.txt
streamlit run app.py --server.port 8501
```

Access via: `https://<domain-id>.studio.<region>.sagemaker.aws/jupyterlab/default/proxy/8501/`
