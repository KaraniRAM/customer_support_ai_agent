class QueryUnderstandingAgent:

    def understand(self, query):

        query=query.strip()
        query_lower=query.lower()

        greetings=[
            "hi",
            "hello",
            "hey",
            "hii",
            "hiii",
            "good morning",
            "good afternoon",
            "good evening",
            "how are you",
            "what can you do",
            "i need help",
            "help me"
        ]

        if query_lower in greetings:
            intent="casual_conversation"
        else:
            intent="information_request"

        return {
            "original_query":query,
            "cleaned_query":query,
            "intent":intent
        }