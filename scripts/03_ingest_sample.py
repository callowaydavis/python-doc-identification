"""
03_ingest_sample.py — OCR a labeled sample PDF and store it in sample tables.

Usage:
    python scripts/03_ingest_sample.py /path/to/sample.pdf "Document Type Label"
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.connection import get_connection
from utils.ocr import ocr_document
from utils.text_utils import clean_text


def main():
    if len(sys.argv) != 3:
        print('Usage: python scripts/03_ingest_sample.py /path/to/sample.pdf "Document Type"')
        sys.exit(1)

    file_path = os.path.abspath(sys.argv[1])
    document_type = sys.argv[2].strip()

    if not os.path.isfile(file_path):
        print(f"Error: '{file_path}' does not exist.")
        sys.exit(1)

    ext = os.path.splitext(file_path)[1].lower().lstrip(".")
    if ext not in ("pdf", "tif", "tiff"):
        print(f"Error: unsupported file type '{ext}'. Must be pdf, tif, or tiff.")
        sys.exit(1)

    file_name = os.path.basename(file_path)

    with get_connection() as conn:
        cursor = conn.cursor()

        # Idempotency check
        cursor.execute("SELECT sample_id FROM sample_documents WHERE file_path = ?", file_path)
        row = cursor.fetchone()
        if row is not None:
            print(f"Already ingested (sample_id={row[0]}). Skipping.")
            return

        print(f"OCR-ing sample: {file_path}")
        pages = ocr_document(file_path, ext)

        cursor.execute(
            """
            INSERT INTO sample_documents (document_type, file_path, file_name, page_count)
            OUTPUT INSERTED.sample_id
            VALUES (?, ?, ?, ?)
            """,
            document_type,
            file_path,
            file_name,
            len(pages),
        )
        sample_id = cursor.fetchone()[0]

        for page in pages:
            text = clean_text(page["text"])
            cursor.execute(
                """
                INSERT INTO sample_pages (sample_id, document_type, page_number, extracted_text, ocr_confidence)
                VALUES (?, ?, ?, ?, ?)
                """,
                sample_id,
                document_type,
                page["page_number"],
                text,
                page["confidence"],
            )

    print(f"Ingested sample_id={sample_id}: '{document_type}' — {len(pages)} page(s).")


if __name__ == "__main__":
    main()
