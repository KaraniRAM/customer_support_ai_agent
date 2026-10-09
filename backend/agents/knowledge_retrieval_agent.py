import os
from pathlib import Path

import chromadb
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer


# =========================================================
# LOAD ENVIRONMENT VARIABLES
# =========================================================

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

CHROMA_DIR = Path(
    os.getenv(
        "CHROMA_DIR",
        str(BASE_DIR.parent / "chroma_db")
    )
)

COLLECTION_NAME = os.getenv(
    "CHROMA_COLLECTION_NAME",
    "blencekart_documents"
)

EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "all-MiniLM-L6-v2"
)


# =========================================================
# KNOWLEDGE RETRIEVAL AGENT
# =========================================================

class KnowledgeRetrievalAgent:

    def __init__(self, n_results=6):

        self.n_results = n_results

        # Connect to the existing persistent ChromaDB
        self.client = chromadb.PersistentClient(
            path=str(CHROMA_DIR)
        )

        # Access the existing collection
        try:
            self.collection = self.client.get_collection(
                name=COLLECTION_NAME
            )
        except Exception as exc:
            raise RuntimeError(
                f"Could not open ChromaDB collection "
                f"'{COLLECTION_NAME}'. Check the collection name "
                f"and database path."
            ) from exc

        # Load the same embedding model used during PDF indexing
        self.embedding_model = SentenceTransformer(
            EMBEDDING_MODEL
        )

    # =====================================================
    # RETRIEVE RELEVANT KNOWLEDGE
    # =====================================================

    def retrieve(self, query_data):

        try:

            # Get the cleaned question
            question = query_data.get(
                "cleaned_question",
                ""
            ).strip()

            if not question:
                return {
                    "chunks": [],
                    "has_relevant_context": False
                }

            # Convert the question into an embedding
            query_embedding = self.embedding_model.encode(
                question,
                normalize_embeddings=True
            ).tolist()

            # Search ChromaDB
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=min(
                    self.n_results,
                    self.collection.count()
                ),
                include=["documents", "metadatas", "distances"]
            )

            # Extract retrieved document chunks
            documents = results.get("documents", [[]])

            if not documents or not documents[0]:
                return {
                    "chunks": [],
                    "has_relevant_context": False
                }

            chunks = []
            retrieved_metadata = []
            distances = results.get("distances", [[]])

            for index, document in enumerate(documents[0]):

                if not document or not document.strip():
                    continue

                chunks.append(document.strip())

                metadata_list = results.get(
                    "metadatas",
                    [[]]
                )

                metadata = (
                    metadata_list[0][index]
                    if metadata_list
                    and metadata_list[0]
                    and index < len(metadata_list[0])
                    else {}
                )

                distance = (
                    distances[0][index]
                    if distances
                    and distances[0]
                    and index < len(distances[0])
                    else None
                )

                retrieved_metadata.append({
                    "document_name": metadata.get(
                        "document_name"
                    ),
                    "document_id": metadata.get(
                        "document_id"
                    ),
                    "page_number": metadata.get(
                        "page_number"
                    ),
                    "distance": distance
                })

            print(
                f"Knowledge retrieval completed. "
                f"Chunks retrieved: {len(chunks)}"
            )

            return {
                "chunks": chunks,
                "has_relevant_context": bool(chunks),
                "metadata": retrieved_metadata
            }

        except Exception as exc:

            print(
                "KNOWLEDGE RETRIEVAL ERROR:",
                str(exc)
            )

            # Do not expose internal errors to the user
            return {
                "chunks": [],
                "has_relevant_context": False
            }