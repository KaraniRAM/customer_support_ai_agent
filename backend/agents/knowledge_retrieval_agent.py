
import os
from dotenv import load_dotenv
import psycopg2
from sentence_transformers import SentenceTransformer


# =========================================================
# LOAD ENVIRONMENT VARIABLES
# =========================================================

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

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

        if not DATABASE_URL:
            raise ValueError(
                "DATABASE_URL is missing in .env file"
            )

        # Load the same embedding model used during PDF indexing
        self.embedding_model = SentenceTransformer(
            EMBEDDING_MODEL
        )

    # =====================================================
    # CONNECT TO SUPABASE POSTGRESQL
    # =====================================================

    def get_db_connection(self):

        return psycopg2.connect(DATABASE_URL)

    # =====================================================
    # RETRIEVE RELEVANT KNOWLEDGE
    # =====================================================

    def retrieve(self, query_data):

        connection = None

        try:

            # Get the cleaned question
            question = query_data.get(
                "cleaned_question",
                ""
            ).strip()

            if not question:
                return {
                    "chunks": [],
                    "has_relevant_context": False,
                    "metadata": []
                }

            # Convert question into a 384-dimensional embedding
            query_embedding = self.embedding_model.encode(
                question,
                normalize_embeddings=True
            ).tolist()

            # Convert embedding into PostgreSQL vector format
            embedding_string = "[" + ",".join(
                map(str, query_embedding)
            ) + "]"

            # Connect to Supabase PostgreSQL
            connection = self.get_db_connection()

            cursor = connection.cursor()

            # Search for the most relevant document chunks
            cursor.execute(
                """
                SELECT
                    chunk_text,
                    document_id,
                    page_number,
                    embedding OPERATOR(extensions.<=>)
                    %s::extensions.vector AS distance

                FROM public.rag_chunks

                WHERE embedding IS NOT NULL

                ORDER BY embedding OPERATOR(extensions.<=>)
                    %s::extensions.vector

                LIMIT %s
                """,
                (
                    embedding_string,
                    embedding_string,
                    self.n_results
                )
            )

            results = cursor.fetchall()

            cursor.close()

            # Extract retrieved chunks
            chunks = []
            retrieved_metadata = []

            for row in results:

                chunk_text = row[0]

                if not chunk_text or not chunk_text.strip():
                    continue

                chunks.append(chunk_text.strip())

                retrieved_metadata.append({

                    "document_id": row[1],

                    "page_number": row[2],

                    "distance": float(row[3])
                    if row[3] is not None
                    else None

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

            return {
                "chunks": [],
                "has_relevant_context": False,
                "metadata": []
            }

        finally:

            if connection:
                connection.close()
