from rag.embeddings import create_query_embedding
from rag.chroma_manager import search_documents


class KnowledgeRetrievalAgent:

    def retrieve(self, query_data):

        query = query_data["cleaned_query"]

        query_embedding = create_query_embedding(
            query
        )

        results = search_documents(
            query_embedding,
            top_k=5
        )

        documents = results.get(
            "documents",
            [[]]
        )[0]

        metadatas = results.get(
            "metadatas",
            [[]]
        )[0]

        return {
            "query": query,
            "chunks": documents,
            "sources": metadatas
        }