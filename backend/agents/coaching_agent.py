
class CoachingAgent:

    def generate_coaching(
        self,
        conversation
    ):
        """
        Reviews the conversation and provides internal coaching guidance.

        This output is INTERNAL.
        It should NOT be shown directly to the user.
        """

        if not conversation:
            return {
                "status": "success",
                "coaching": "No previous conversation is available."
            }

        # Get the latest user message and assistant response
        latest_user_message = ""
        latest_assistant_response = ""

        for message in reversed(conversation):
            if isinstance(message, dict):
                role = message.get("role", "")
                content = message.get("content", "")

                if role == "user" and not latest_user_message:
                    latest_user_message = content

                elif role == "assistant" and not latest_assistant_response:
                    latest_assistant_response = content

                if latest_user_message and latest_assistant_response:
                    break

        coaching_points = []

        # Check whether the response exists
        if not latest_assistant_response:
            coaching_points.append(
                "Provide a clear and helpful response to the user."
            )

        # Check for very short responses
        elif len(latest_assistant_response.strip()) < 20:
            coaching_points.append(
                "The response may be too short. Provide enough context "
                "to be helpful while remaining concise."
            )

        # Check for unanswered user question
        if latest_user_message and latest_assistant_response:
            coaching_points.append(
                "Ensure the response directly addresses the user's request "
                "and remains relevant to the conversation."
            )

        if not coaching_points:
            coaching_points.append(
                "Response appears relevant and sufficiently helpful."
            )

        return {
            "status": "success",
            "coaching": coaching_points
        }
