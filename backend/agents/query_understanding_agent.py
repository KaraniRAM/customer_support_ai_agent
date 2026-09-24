class QueryUnderstandingAgent:

    def understand(self, query):

        query = query.strip()

        return {
            "original_query": query,
            "cleaned_query": query,
            "intent": "information_request"
        }