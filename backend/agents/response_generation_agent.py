'''import os
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
'''
import ollama
from dotenv import load_dotenv

load_dotenv()


class ResponseGenerationAgent:

    def __init__(self):
        self.model = "qwen2.5:3b"

    def generate(self, query_data, retrieval_data):

        # ============================================
        # GET USER QUESTION
        # ============================================
        query = query_data.get("cleaned_question", "").strip()

        if not query:
            return "Please enter a question so I can help you."

        normalized_query = query.lower()

        # ============================================
        # HANDLE GREETINGS DIRECTLY
        # ============================================
        greetings = [
            "hi", "hello", "hey", "hai",
            "hey there", "hello there"
        ]

        if normalized_query in greetings:
            return "Hi! 👋 Welcome to BlensCart. How can I help you today?"

        if "good morning" in normalized_query:
            return "Good morning! ☀️ Welcome to BlensCart."

        if "good afternoon" in normalized_query:
            return "Good afternoon! 😊 Welcome to BlensCart."

        if "good evening" in normalized_query:
            return "Good evening! 🌆 Welcome to BlensCart."

        if "thank you" in normalized_query or "thanks" in normalized_query:
            return "You're very welcome! 😊 Happy to help."

        if normalized_query in ["bye", "goodbye"]:
            return "Goodbye! 👋 Thanks for using BlensCart."

        # ============================================
        # GET ANSWER RETRIEVED FROM CHROMADB
        # ============================================
        chunks = retrieval_data.get("chunks", [])

        has_relevant_context = retrieval_data.get(
            "has_relevant_context",
            len(chunks) > 0
        )

        # ============================================
        # CHECK RETRIEVED RESULTS
        # ============================================
        if not has_relevant_context or not chunks:
            return (
                "I'm sorry, but I couldn't find enough information "
                "in the BlensCart knowledge base to answer your question."
            )

        # ============================================
        # PREPARE RETRIEVED KNOWLEDGE
        # ============================================
        context_parts = []

        for chunk in chunks:

            # Handle chunks returned as dictionaries
            if isinstance(chunk, dict):
                text = (
                    chunk.get("text")
                    or chunk.get("content")
                    or chunk.get("page_content")
                    or ""
                )
            else:
                text = str(chunk)

            text = str(text).strip()

            if text:
                context_parts.append(text)

        retrieved_context = "\n\n".join(context_parts)

        if not retrieved_context:
            return "No readable information was retrieved from the knowledge base."

        # ============================================
        # CREATE PROMPT FOR OLLAMA
        # ============================================
        prompt = f"""
You are a helpful customer support assistant for BlensCart.

Answer the user's question using only the information
provided in the knowledge base below.

Instructions:
1. Give a clear, natural, professional answer.
2. Use relevant information from the knowledge base.
3. Do not invent store locations, prices, policies, or features.
4. If the knowledge base does not contain enough information,
   clearly explain that you do not have enough information.
5. Do not mention ChromaDB, retrieved chunks, prompts,
   internal processing, or AI agents.
6. Keep the answer focused on the user's question.

Knowledge Base:
{retrieved_context}

User Question:
{query}

Answer:
"""

        # ============================================
        # GENERATE ANSWER USING LOCAL OLLAMA MODEL
        # ============================================
        try:

            response = ollama.chat(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                options={
                    "temperature": 0.1
                }
            )

            answer = response["message"]["content"].strip()

            if not answer:
                return "I'm sorry, I couldn't generate an answer. Please try again."

            print("\n========== OLLAMA GENERATED ANSWER ==========")
            print(answer)
            print("==============================================\n")

            return answer

        except Exception as e:

            print("Ollama Error:", str(e))

            return (
                "I'm sorry, the local AI service is currently unavailable. "
                "Please ensure Ollama is running and try again."
            )