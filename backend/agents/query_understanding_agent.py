import re
import subprocess
import json

class QueryUnderstandingAgent:
    def __init__(self, ollama_model="llama3"):
        self.ollama_model = ollama_model

    def _ask_ollama(self, question):
        # Call Ollama CLI to get structured intent
        result = subprocess.run(
            ["ollama", "run", self.ollama_model, question],
            capture_output=True,
            text=True
        )
        return result.stdout.strip()

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
            # Use Ollama for deeper understanding
            ollama_response = self._ask_ollama(cleaned_question)
            intent = f"ollama_inferred: {ollama_response}"

        return {
            "original_question": original_question,
            "cleaned_question": cleaned_question,
            "intent": intent
        }
