import pytest
from test_agents import OrchestratorAgent

@pytest.fixture
def orchestrator():
    return OrchestratorAgent()

def run_pipeline(orchestrator, question):
    return orchestrator.process_chat(question)


# ============================
# Your test cases
# ============================

def test_basic_question(orchestrator):
    result = run_pipeline(orchestrator, "What is BlensCart?")
    assert "BlensCart" in result  and "smart-eyewear" in result

def test_opening_hours(orchestrator):
    result = run_pipeline(orchestrator, "What are the opening and closing times?")
    assert "10:30" in result and "9:00 PM" in result and "10:30 AM to 9:00 PM" in result

def test_location(orchestrator):
    result = run_pipeline(orchestrator, "Where is BlensCart located?")
    assert "Madurai" in result and "Tiruchirappalli" in result

def test_job_availability(orchestrator):
    result = run_pipeline(orchestrator, "Is any job available at BlensCart?")
    assert "hiring" in result or "Yes" in result

def test_owner_question(orchestrator):
    result = run_pipeline(orchestrator, "Who is the owner of BlensCart?")
    assert "does not " in result or "I don't have enough" in result or "do not have" in result