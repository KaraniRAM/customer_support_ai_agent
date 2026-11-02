
import re
import os
import json
from dotenv import load_dotenv
from mistralai import Mistral

load_dotenv()


class QueryUnderstandingAgent:

    def __init__(self, model="mistral-small-latest"):

        self.model = model

        api_key = os.getenv("MISTRAL_API_KEY")

        if not api_key:
            raise ValueError("MISTRAL_API_KEY is missing in .env file")

        self.client = Mistral(api_key=api_key)

    def _understand_with_mistral(self, question):

        prompt = f"""
        Understand the user's question and classify its intent.

        Choose exactly one intent from:
        - information_request
        - how_to_request
        - explanation_request
        - comparison_request
        - problem_solving
        - other

        Return ONLY valid JSON in this format:
        {{
            "intent": "intent_name"
        }}

        User question: {question}
        """

        response = self.client.chat.complete(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            response_format={"type": "json_object"}
        )

        result = response.choices[0].message.content

        try:
            data = json.loads(result)
            return data.get("intent", "other")

        except (json.JSONDecodeError, TypeError):
            return "other"

    def understand(self, original_question):

        cleaned_question = re.sub(
            r"\s+", " ", original_question
        ).strip()

        lowered = cleaned_question.lower()

        casual_messages = {
            "hi", "hello", "hey", "hii", "hiii", "heyy",
            "good morning", "good afternoon", "good evening",
            "how are you", "how are you?",
            "what can you do", "what can you do?",
            "i need help", "help me",
            "thanks", "thank you", "thankyou",
            "bye", "goodbye", "good bye"
        }

        simple_casual_messages = {
            "hi there", "hello there", "hey there",
            "hii there", "hiii there"
        }

        if (
            lowered in casual_messages
            or lowered in simple_casual_messages
        ):

            intent = "casual_conversation"

        else:

            # Use Mistral for query understanding
            intent = self._understand_with_mistral(
                cleaned_question
            )

        return {
            "original_question": original_question,
            "cleaned_question": cleaned_question,
            "intent": intent
        }
