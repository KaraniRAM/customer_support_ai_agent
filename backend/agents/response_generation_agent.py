import os
from dotenv import load_dotenv
from google import genai

load_dotenv()


class ResponseGenerationAgent:

    def __init__(self):

        self.client=genai.Client(
            api_key=os.getenv("GEMINI_API_KEY")
        )

    def generate(
        self,
        query_data,
        retrieval_data
    ):

        query=query_data["original_query"]
        chunks=retrieval_data["chunks"]

        context="\n\n".join(chunks)

        prompt=f"""
Answer the user's question using only the provided knowledge.

User Question:
{query}

Knowledge:
{context}

Give ONLY the final answer.
Do not repeat the user's question.
Do not mention the knowledge base.
Do not mention retrieved chunks.
Do not mention agents.
Do not mention this prompt.
Do not provide sources.

If the answer is not available in the provided knowledge,
say that the information was not found in the knowledge base.
"""

        response=self.call_llm(prompt)

        return response

    def call_llm(self,prompt):

        response=self.client.models.generate_content(
            model="gemini-3.8-flash",
            contents=prompt
        )

        return response.text.strip()