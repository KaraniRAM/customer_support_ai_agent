from rag.pdf_processor import extract_pdf_pages
from rag.chunker import create_chunks
from rag.embeddings import create_embeddings
from rag.chroma_manager import add_document_chunks


def process_pdf(
    file_path,
    document_id,
    document_name
):

    pages = extract_pdf_pages(
        file_path
    )

    chunks, page_numbers = create_chunks(
        pages
    )

    embeddings = create_embeddings(
        chunks
    )

    add_document_chunks(
        document_id=document_id,
        document_name=document_name,
        chunks=chunks,
        embeddings=embeddings,
        page_numbers=page_numbers
    )

    return {
        "document_id": document_id,
        "document_name": document_name,
        "chunks_created": len(chunks)
    }