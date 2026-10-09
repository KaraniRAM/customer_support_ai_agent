from agents.query_understanding_agent import QueryUnderstandingAgent
from agents.knowledge_retrieval_agent import KnowledgeRetrievalAgent
from agents.response_generation_agent import ResponseGenerationAgent
from agents.coaching_agent import CoachingAgent
from agents.feedback_generation_agent import FeedbackGenerationAgent


class OrchestratorAgent:
    def __init__(self):
        self.query_agent = QueryUnderstandingAgent()
        self.retrieval_agent = KnowledgeRetrievalAgent()
        self.response_agent = ResponseGenerationAgent()
        self.coaching_agent = CoachingAgent()
        self.feedback_agent = FeedbackGenerationAgent()

    def process_chat(self, user_query):
        try:
            # Step 1: Understand the query
            query_result = self.query_agent.understand(user_query)
            print("QUERY UNDERSTANDING RESULT:", query_result)

            intent = query_result.get("intent", "knowledge_query")

            # Step 2: Handle casual conversation directly
            if intent == "casual_conversation":
                return self._handle_casual_conversation(user_query)

            # Step 3: Retrieve knowledge
            retrieval_result = self.retrieval_agent.retrieve(query_result)
            print("RETRIEVAL RESULT:", retrieval_result)

            if not retrieval_result.get("has_relevant_context", True):
                return (
                    "I'm sorry, but I don't currently have enough information "
                    "to answer that question. I can help you with information "
                    "related to BlenceKart, its smart spectacles, features, and how the system works."
                )

            # Step 4: Generate response using Gemini
            response_result = self.response_agent.generate(query_result, retrieval_result)
            print("RESPONSE GENERATION RESULT:", response_result)

            return response_result

        except Exception as e:
            print("ORCHESTRATOR CHAT ERROR:", str(e))
            return (
                "I'm sorry, but I couldn't process your request right now. "
                "Please try again in a moment."
            )

    def _handle_casual_conversation(self, user_query):
        user_text = user_query.strip().lower()
        greetings = ["hi", "hello", "hey", "hai", "hey there", "hello there"]

        if user_text in greetings:
            return "Hi! 👋 Welcome to BlensCart. How can I help you today?"
        if "good morning" in user_text:
            return "Good morning! ☀️ Welcome to BlensCart."
        if "good afternoon" in user_text:
            return "Good afternoon! 😊 Welcome to BlensCart."
        if "good evening" in user_text:
            return "Good evening! 🌆 Welcome to BlensCart."
        if "thank you" in user_text or "thanks" in user_text:
            return "You're very welcome! 😊 Happy to help."
        if "bye" in user_text or "goodbye" in user_text:
            return "Goodbye! 👋 Thanks for using BlensCart."

        return "I'd be happy to help! 😊 You can ask me anything about BlensCart."

    def generate_feedback(self, conversation):
        try:
            return self.feedback_agent.generate_feedback(conversation)
        except Exception as e:
            print("FEEDBACK GENERATION ERROR:", str(e))
            return {"feedback": "Unable to generate feedback at the moment."}

    def generate_coaching(self, conversation):
        try:
            return self.coaching_agent.generate_coaching(conversation)
        except Exception as e:
            print("COACHING GENERATION ERROR:", str(e))
            return {"status": "error", "message": "Unable to generate coaching information."}
