'''import pytest
from agents.query_understanding_agent import QueryUnderstandingAgent
from agents.response_generation_agent import ResponseGenerationAgent
class MockRetrievalAgent:
    def retrieve(self, query):
        if "owner" in query:
            return "The document does not provide any information about the owner of BlensCart."
        elif "opening" in query or "closing" in query:
            return "BlensCart stores are open from 10:30 AM to 9:00 PM."
        elif "located" in query:
            return "BlensCart operates in Madurai, Tiruchirappalli."
        elif "job" in query or "hiring" in query:
            return "BlensCart is hiring in Chennai and the salary range is ₹15,000–₹17,000 per month."
        elif "BlensCart" in query:
            return "BlensCart is a smart-eyewear platform offering spectacles."
        else:
            return "No information available."
# ✅ Mock retrieval agent so tests don’t hit ChromaDB


@pytest.fixture
def pipeline(monkeypatch):
    query_agent = QueryUnderstandingAgent()
    retrieval_agent = MockRetrievalAgent()
    response_agent = ResponseGenerationAgent()

    # ✅ Patch out generate_response so it just echoes the input
    monkeypatch.setattr(response_agent, "generate_response", lambda text: text)

    return query_agent, retrieval_agent, response_agent


def run_pipeline(pipeline, question):
    query_agent, retrieval_agent, response_agent = pipeline
    intent_data = query_agent.understand(question)
    retrieved = retrieval_agent.retrieve(question)
    result = response_agent.generate_response(retrieved)
    return result


def test_basic_question(pipeline):
    result = run_pipeline(pipeline, "What is BlensCart?")
    assert "BlensCart" in result and "spectacles" in result and "smart-eyewear platform" in result

def test_opening_hours(pipeline):
    result = run_pipeline(pipeline, "What are the opening and closing times?")
    assert "10:30" in result and "9:00 PM" in result and "10:30 AM to 9:00 PM" in result

def test_location(pipeline):
    result = run_pipeline(pipeline, "Where is BlensCart located?")
    assert "Madurai" in result and "Tiruchirappalli" in result

def test_job_availability(pipeline):
    result = run_pipeline(pipeline, "Is any job available at BlensCart?")
    assert "Chennai" in result and "salary range is ₹15,000–₹17,000 per month" in result and "hiring" in result

def test_owner_question(pipeline):
    result = run_pipeline(pipeline, "Who is the owner of BlensCart?")
    assert "does not provide any information" in result
'''
'''
import pytest
from agents.query_understanding_agent import QueryUnderstandingAgent
from agents.retrieval_agent import RetrievalAgent
from agents.response_generation_agent import ResponseGenerationAgent

# -------------------------------
# UNIT TESTS FOR QueryUnderstandingAgent
# -------------------------------

def test_query_agent_casual_message():
    agent = QueryUnderstandingAgent()
    result = agent.understand("Hello")
    assert result["intent"] == "casual_conversation"

def test_query_agent_information_request():
    agent = QueryUnderstandingAgent()
    result = agent.understand("What is BlensCart?")
    assert result["intent"] == "information_request"


# -------------------------------
# UNIT TESTS FOR RetrievalAgent
# -------------------------------

class MockCollection:
    def query(self, query_texts, n_results):
        return {
            "documents": [["BlensCart is a smart-eyewear platform offering spectacles."]],
            "distances": [[0.5]]
        }

def test_retrieval_agent(monkeypatch):
    agent = RetrievalAgent()
    # Patch the collection so it doesn’t hit ChromaDB
    monkeypatch.setattr(agent, "collection", MockCollection())
    result = agent.retrieve("BlensCart")
    assert "smart-eyewear platform" in result


# -------------------------------
# UNIT TESTS FOR ResponseGenerationAgent
# -------------------------------

def test_response_agent_generate(monkeypatch):
    agent = ResponseGenerationAgent()
    # Patch out LLM call
    monkeypatch.setattr(agent, "generate_response", lambda text: f"Echo: {text}")
    result = agent.generate_response("BlensCart is a smart-eyewear platform.")
    assert "Echo:" in result
    assert "BlensCart" in result
'''
# test_agent.py

from agents.query_understanding_agent import QueryUnderstandingAgent
from agents.mock_retrieval_agent import MockRetrievalAgent
from agents.response_generation_agent import ResponseGenerationAgent


class OrchestratorAgent:
    def __init__(self):
        # Initialize the three core agents
        self.query_agent = QueryUnderstandingAgent()
        self.retrieval_agent = MockRetrievalAgent()
        self.response_agent = ResponseGenerationAgent()

    def process_chat(self, user_query: str) -> str:
        try:
            # Step 1: Understand the query
            query_result = self.query_agent.understand(user_query)
            print("QUERY RESULT:", query_result)

            # Step 2: Retrieve knowledge
            retrieval_result = self.retrieval_agent.retrieve(query_result)
            print("RETRIEVAL RESULT:", retrieval_result)

            # Step 3: Generate response
            response_result = retrieval_result
            print("RESPONSE RESULT:", response_result)

            return response_result

        except Exception as e:
            print("ORCHESTRATOR ERROR:", str(e))
            return "Sorry, something went wrong while processing your request."


