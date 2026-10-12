
import chromadb
import ollama

# ============================================
# CONFIGURATION
# ============================================

CHROMA_DIR = "chroma_db"
CHROMA_COLLECTION_NAME = "blencekart_documents"
LLM_MODEL = "llama3.2"


# ============================================
# CONNECT TO CHROMADB
# ============================================

client = chromadb.PersistentClient(
    path=CHROMA_DIR
)

collection = client.get_collection(
    name=CHROMA_COLLECTION_NAME
)


# ============================================
# RETRIEVE INFORMATION FROM CHROMADB
# ============================================

def retrieve_documents(question):

    results = collection.query(
        query_texts=[question],
        n_results=6
    )

    documents = results.get("documents", [[]])[0]
    distances = results.get("distances", [[]])[0]

    if not documents:
        return ""

    # Avoid using irrelevant results.
    # This threshold may need adjustment for your
    # existing embedding model and distance metric.
    relevant_documents = []

    for document, distance in zip(documents, distances):
        if distance < 1.0:
            relevant_documents.append(document)

    return "\n\n".join(relevant_documents)


# ============================================
# GENERATE ANSWER USING OLLAMA
# ============================================

def generate_answer(question):

    context = retrieve_documents(question)

    if not context:
        return (
            "I couldn't find sufficient relevant "
            "information in the available documents."
        )

    response = ollama.chat(
        model=LLM_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are the BLENCEKART customer "
                    "support assistant. Answer questions "
                    "using the provided document context. "
                    "Do not invent facts. If the context "
                    "does not contain enough information, "
                    "say so clearly."
                )
            },
            {
                "role": "user",
                "content": (
                    f"Document context:\n{context}\n\n"
                    f"Question: {question}"
                )
            }
        ]
    )

    return response["message"]["content"]


# ============================================
# TERMINAL CHAT
# ============================================

def main():

    print("\n===================================")
    print("     BLENCEKART AI ASSISTANT")
    print("===================================")
    print("Ask questions about BlensCart.")
    print("Type 'exit' to quit.\n")

    while True:

        question = input("You: ").strip()

        if question.lower() in ["exit", "quit"]:
            print("\nGoodbye!")
            break

        if not question:
            continue

        try:
            print("\nSearching documents and generating answer...\n")

            answer = generate_answer(question)

            print(f"AI: {answer}\n")

        except Exception as error:
            print(f"\nError: {error}\n")


if __name__ == "__main__":
    main()