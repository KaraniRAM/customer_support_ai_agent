class FeedbackGenerationAgent:

    def generate_feedback(
        self,
        conversation
    ):

        conversation_text = ""

        for message in conversation:

            conversation_text += (
                f"{message['role']}: "
                f"{message['content']}\n"
            )

        prompt = f"""
Analyze the following conversation.

Conversation:

{conversation_text}

Generate useful feedback about:

1. Response quality
2. Answer relevance
3. Knowledge retrieval quality
4. Accuracy
5. Areas for improvement
"""

        feedback = self.call_llm(
            prompt
        )

        return {
            "feedback": feedback
        }


    def call_llm(self, prompt):

        # Connect your existing LLM here.

        return "Feedback will be generated here."