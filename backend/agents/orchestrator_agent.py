from agents.query_understanding_agent import (
    QueryUnderstandingAgent
)

from agents.knowledge_retrieval_agent import (
    KnowledgeRetrievalAgent
)

from agents.response_generation_agent import (
    ResponseGenerationAgent
)

from agents.coaching_agent import (
    CoachingAgent
)

from agents.feedback_generation_agent import (
    FeedbackGenerationAgent
)


class OrchestratorAgent:

    def __init__(self):

        self.query_agent = (
            QueryUnderstandingAgent()
        )

        self.retrieval_agent = (
            KnowledgeRetrievalAgent()
        )

        self.response_agent = (
            ResponseGenerationAgent()
        )

        self.coaching_agent = (
            CoachingAgent()
        )

        self.feedback_agent = (
            FeedbackGenerationAgent()
        )


    def process_chat(self, user_query):

        # Agent 1
        query_result = (
            self.query_agent.understand(
                user_query
            )
        )

        # Agent 2
        retrieval_result = (
            self.retrieval_agent.retrieve(
                query_result
            )
        )

        # Agent 3
        response_result = (
            self.response_agent.generate(
                query_result,
                retrieval_result
            )
        )

        return response_result


    def generate_feedback(
        self,
        conversation
    ):

        return (
            self.feedback_agent.generate_feedback(
                conversation
            )
        )


    def generate_coaching(
        self,
        conversation
    ):

        return (
            self.coaching_agent.generate_coaching(
                conversation
            )
        )