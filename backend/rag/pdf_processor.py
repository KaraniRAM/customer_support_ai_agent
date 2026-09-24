from pypdf import PdfReader


def extract_pdf_pages(file_path):

    reader = PdfReader(file_path)

    pages = []

    for page_number, page in enumerate(reader.pages, start=1):

        text = page.extract_text()

        if text:
            pages.append({
                "page_number": page_number,
                "text": text
            })

    return pages