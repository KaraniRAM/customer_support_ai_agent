class MockRetrievalAgent:
    def retrieve(self, query_data):
        question = query_data.get("cleaned_question", "").lower()

        if "owner" in question:
            chunks = ["The document does not provide any information about the owner of BlensCart."]
        elif "opening" in question or "closing" in question:
            chunks = ["BlensCart stores are open from 10:30 AM to 9:00 PM."]
        elif "located" in question:
            chunks = ["BlensCart operates in Madurai, Tiruchirappalli."]
        elif "is any job" in question and "available" in question:
            chunks = [" Yes.BlensCart is hiring in Chennai "]
        elif "blenscart" in question:
            chunks = ["BlensCart is a smart-eyewear platform offering spectacles."]
        else:
            chunks = ["The document does not provide any information."]

        return {
            "chunks": chunks,
            "has_relevant_context": bool(chunks),
            "metadata": []
        }
