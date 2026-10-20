import pytest
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
    print("\nPipeline result:", result)   # 👈 this will show in pytest -s
    assert "₹15,000 to ₹17,000 per month" in result and "hiring" in result
