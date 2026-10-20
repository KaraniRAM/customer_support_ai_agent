'''import pytest
from test_agents import OrchestratorAgent   # import your orchestrator

@pytest.fixture
def orchestrator():
    # create a fresh orchestrator for each test
    return OrchestratorAgent()

def run_pipeline(orchestrator, question):
    # helper to run the orchestrator with a question
    return orchestrator.process_chat(question)

# ============================
# Single test case: Job availability
# ============================

def test_job_availability(orchestrator):
    result = run_pipeline(orchestrator, "Is any job available at BlensCart?")
    assert "₹15,000 to ₹17,000 per month" in result and "hiring" in result
'''
'''
name: Factorial CI

on:
  push:
    branches:
      - main
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.10"

      - name: Install dependencies
        run: pip install -r requirement.txt

      - name: Run tests
        run: pytest

  build:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Create build package
        run: |
          mkdir build
          cp factorial.py build/
          cp requirement.txt build/

      - name: Upload build artifact
        uses: actions/upload-artifact@v4
        with:
          name: factorial-build
          path: build/

  deploy:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - name: Download build artifact
        uses: actions/download-artifact@v4
        with:
          name: factorial-build
          path: deployment/

      - name: Show deployment files
        run: |
          echo "Files to deploy:"
          ls -R deployment/

      - name: Deploy application
        run: |
          echo "Deploying factorial application..."
          echo "Deployment successful!"
'''