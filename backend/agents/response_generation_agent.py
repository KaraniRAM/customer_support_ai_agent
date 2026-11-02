
import os
from dotenv import load_dotenv
from mistralai import Mistral

load_dotenv()


class ResponseGenerationAgent:

    def __init__(self):

        self.model = "mistral-small-latest"

        api_key = os.getenv("MISTRAL_API_KEY")

        if not api_key:
            raise ValueError(
                "MISTRAL_API_KEY is missing in .env file"
            )

        self.client = Mistral(api_key=api_key)

    # =====================================================
    # GENERATE RESPONSE
    # =====================================================

    def generate(self, query_data, retrieval_data):

        # ============================================
        # GET USER QUESTION
        # ============================================

        query = query_data.get(
            "cleaned_question", ""
        ).strip()

        if not query:
            return "Please enter a question so I can help you."

        normalized_query = query.lower()

        # ============================================
        # HANDLE GREETINGS DIRECTLY
        # ============================================

        greetings = [
            "hi", "hello", "hey", "hai",
            "hii", "hiii", "heyy",
            "hey there", "hello there",
            "hi there"
        ]

        if normalized_query in greetings:
            return (
                "Hi! 👋 Welcome to BlensCart. "
                "How can I help you today?"
            )

        if normalized_query == "good morning":
            return "Good morning! ☀️ Welcome to BlensCart."

        if normalized_query == "good afternoon":
            return "Good afternoon! 😊 Welcome to BlensCart."

        if normalized_query == "good evening":
            return "Good evening! 🌆 Welcome to BlensCart."

        if normalized_query in [
            "how are you",
            "how are you?"
        ]:
            return (
                "I'm doing great! 😊 "
                "How can I help you with BlensCart today?"
            )

        if (
            normalized_query in ["thanks", "thank you", "thankyou"]
            or normalized_query.startswith("thank you ")
        ):
            return "You're very welcome! 😊 Happy to help."

        if normalized_query in ["bye", "goodbye", "good bye"]:
            return "Goodbye! 👋 Thanks for using BlensCart."

        # ============================================
        # GET INFORMATION FROM KNOWLEDGE RETRIEVAL
        # ============================================

        chunks = retrieval_data.get("chunks", [])

        has_relevant_context = retrieval_data.get(
            "has_relevant_context",
            len(chunks) > 0
        )

        # ============================================
        # CHECK WHETHER INFORMATION IS AVAILABLE
        # ============================================

        if not has_relevant_context or not chunks:

            return (
                "I'm sorry, but the information you're looking "
                "for is currently not available. "
                "Please contact BlensCart customer support "
                "for further assistance."
            )

        # ============================================
        # PREPARE KNOWLEDGE CONTEXT
        # ============================================

        context_parts = []

        for chunk in chunks:

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

            return (
                "I'm sorry, but the information you're looking "
                "for is currently not available."
            )

        # ============================================
        # CREATE MISTRAL PROMPT
        # ============================================

        prompt = f"""
You are a professional and helpful customer support
assistant for BlensCart.

Your task is to answer the user's question using the
provided knowledge.

STRICT INSTRUCTIONS:

1. Answer using only the information provided below.

2. Give clear, natural, friendly and professional answers.

3. Understand the user's actual question before answering.

4. Include only information relevant to the question.

5. Do not invent facts, prices, product details,
   store locations, timings, policies or services.

6. If the provided information does not contain the
   answer, respond clearly:

   "I'm sorry, but the information you're looking for
   is currently not available."

7. Do not guess or use your general knowledge to fill
   missing information.

8. Never mention databases, storage platforms, source
   documents, retrieved chunks, embeddings, prompts,
   internal processing or AI agents.

9. Do not display the entire knowledge base.
   Answer only the specific question.

10. Keep the response concise but informative.

AVAILABLE KNOWLEDGE:

{retrieved_context}

USER QUESTION:

{query}

Generate the customer support response:
"""

        # ============================================
        # GENERATE ANSWER USING MISTRAL AI
        # ============================================

        try:

            response = self.client.chat.complete(

                model=self.model,

                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],

                temperature=0.1,

                max_tokens=600
            )

            answer = (
                response.choices[0]
                .message.content
                .strip()
            )

            if not answer:

                return (
                    "I'm sorry, I couldn't generate an answer. "
                    "Please try again."
                )

            print(
                "\n========== MISTRAL GENERATED ANSWER =========="
            )

            print(answer)

            print(
                "===============================================\n"
            )

            return answer

        except Exception as e:

            print("Mistral AI Error:", str(e))

            return (
                "I'm sorry, our customer support service "
                "is temporarily unavailable. Please try again later."
            )
