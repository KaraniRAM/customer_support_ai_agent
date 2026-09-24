import chromadb

CHROMA_PATH = "./chroma_db"

client = chromadb.PersistentClient(
    path=CHROMA_PATH
)

collection = client.get_or_create_collection(
    name="blencekart_documents"
)


def add_document_chunks(
    document_id,
    document_name,
    chunks,
    embeddings,
    page_numbers
):

    ids = []
    metadatas = []

    for index, chunk in enumerate(chunks):

        chunk_id = f"{document_id}_{index}"

        ids.append(chunk_id)

        metadatas.append({
            "document_id": str(document_id),
            "document_name": document_name,
            "chunk_id": str(index),
            "page_number": str(page_numbers[index])
        })

    collection.add(
        ids=ids,
        documents=chunks,
        embeddings=embeddings,
        metadatas=metadatas
    )


def search_documents(query_embedding, top_k=5):

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k
    )

    return results


def delete_document(document_id):

    collection.delete(
        where={
            "document_id": str(document_id)
        }
    )


def get_document_chunks(document_id):

    results = collection.get(
        where={
            "document_id": str(document_id)
        },
        include=[
            "documents",
            "metadatas"
        ]
    )

    return results