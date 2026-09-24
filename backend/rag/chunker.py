def create_chunks(pages, chunk_size=1000, overlap=200):

    chunks = []
    page_numbers = []

    for page in pages:

        text = page["text"]
        page_number = page["page_number"]

        start = 0

        while start < len(text):

            end = start + chunk_size

            chunk = text[start:end]

            if chunk.strip():

                chunks.append(chunk.strip())

                page_numbers.append(page_number)

            start += chunk_size - overlap

    return chunks, page_numbers