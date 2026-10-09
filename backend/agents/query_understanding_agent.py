import re

class QueryUnderstandingAgent:

    def understand(self, original_question):
        cleaned_question = re.sub(r"\s+", " ", original_question).strip()
        lowered = cleaned_question.lower()

        casual_messages = {
            "hi", "hello", "hey", "hii", "hiii", "heyy",
            "good morning", "good afternoon", "good evening",
            "how are you", "how are you?", "what can you do", "what can you do?",
            "i need help", "help me", "thanks", "thank you", "thankyou",
            "bye", "goodbye", "good bye"
        }

        simple_casual_messages = {
            "hi there", "hello there", "hey there", "hii there", "hiii there"
        }

        if lowered in casual_messages or lowered in simple_casual_messages:
            intent = "casual_conversation"
        elif any(word in lowered for word in ["what", "who", "which", "where", "when"]):
            intent = "information_request"
        elif any(word in lowered for word in ["how", "steps", "process", "guide", "explain"]):
            intent = "how_to_request"
        elif any(word in lowered for word in ["why", "reason"]):
            intent = "explanation_request"
        else:
            intent = "general_request"

        return {
            "original_question": original_question,
            "cleaned_question": cleaned_question,  # ✅ consistent key
            "intent": intent
        }
