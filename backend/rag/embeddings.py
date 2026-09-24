from sentence_transformers import SentenceTransformer


model = SentenceTransformer(
    "all-MiniLM-L6-v2"
)


def create_embeddings(chunks):

    embeddings = model.encode(
        chunks
    )

    return embeddings.tolist()


def create_query_embedding(query):

    embedding = model.encode(
        [query]
    )

    return embedding[0].tolist()