class ResponseGenerationAgent:

    def generate(
        self,
        query_data,
        retrieval_data
    ):

        query = query_data["original_query"]

        chunks = retrieval_data["chunks"]

        context = "\n\n".join(chunks)

        prompt = f"""
You are a helpful BLENCEKART assistant.

Answer the user's question using the
provided knowledge base context.

User Question:
{query}

Knowledge Base Context:
{context}

If the answer is not available in the
provided context, clearly say that the
information was not found in the knowledge base.
"""

        response = self.call_llm(prompt)

        return {
            "response": response,
            "sources": retrieval_data["sources"]
        }


    def call_llm(self, prompt):

        # Connect your existing LLM here.

        return "LLM response will be generated here."