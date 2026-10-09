import os
from dotenv import load_dotenv

load_dotenv()

class ResponseGenerationAgent:

        def __init__(self):
            pass

        def generate(self, query_data, retrieval_data):

            # ============================================
            # GET USER QUESTION
            # ============================================
            query = query_data.get("cleaned_question", "").strip().lower()

            # ============================================
            # HANDLE GREETINGS DIRECTLY
            # ============================================
            greetings = [
                "hi", "hello", "hey", "hai",
                "hey there", "hello there"
            ]

            if query in greetings:
                return "Hi! 👋 Welcome to BlensCart. How can I help you today?"

            if "good morning" in query:
                return "Good morning! ☀️ Welcome to BlensCart."

            if "good afternoon" in query:
                return "Good afternoon! 😊 Welcome to BlensCart."

            if "good evening" in query:
                return "Good evening! 🌆 Welcome to BlensCart."

            if "thank you" in query or "thanks" in query:
                return "You're very welcome! 😊 Happy to help."

            if query in ["bye", "goodbye"]:
                return "Goodbye! 👋 Thanks for using BlensCart."

            # ============================================
            # GET ANSWER RETRIEVED FROM CHROMADB
            # ============================================
            chunks = retrieval_data.get("chunks", [])

            has_relevant_context = retrieval_data.get(
                "has_relevant_context", len(chunks) > 0
            )

            # ============================================
            # CHECK RETRIEVED RESULTS
            # ============================================
            if not has_relevant_context or not chunks:
                return "This is not in the BlensCart knowledge base."

            # ============================================
            # COMBINE CHROMADB CONTENT DIRECTLY
            # NO GEMINI API CALL
            # ============================================
            retrieved_answer = "\n\n".join(
                str(chunk).strip()
                for chunk in chunks
                if str(chunk).strip()
            )

            if not retrieved_answer:
                return "No readable information was retrieved from the knowledge base."

            # ============================================
            # PRINT AND RETURN THE RETRIEVED CONTENT
            # ============================================
            print("\n========== CHROMADB RETRIEVED ANSWER ==========")
            print(retrieved_answer)
            print("================================================\n")

            return retrieved_answer
