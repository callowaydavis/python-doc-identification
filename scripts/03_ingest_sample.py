"""
03_ingest_sample.py — OCR labeled sample documents and store them in sample tables.

Usage:
    # Single file
    python scripts/03_ingest_sample.py /path/to/sample.pdf "Document Type Label"

    # Entire folder (all PDFs/TIFFs in the folder are ingested under the same type)
    python scripts/03_ingest_sample.py /path/to/samples/invoices/ "Invoice"
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.connection import get_connection
from utils.ocr import ocr_document
from utils.text_utils import clean_text

SUPPORTED_EXTENSIONS = {".pdf", ".tif", ".tiff"}


def collect_files(path: str) -> list[str]:
    """Return a list of absolute file paths to ingest from a file or directory."""
    path = os.path.abspath(path)
    if os.path.isfile(path):
        return [path]
    if os.path.isdir(path):
        files = []
        for entry in sorted(os.listdir(path)):
            ext = os.path.splitext(entry)[1].lower()
            if ext in SUPPORTED_EXTENSIONS:
                files.append(os.path.join(path, entry))
        return files
    return []


def ingest_file(conn, file_path: str, document_type: str) -> bool:
    """Ingest a single file. Returns True if newly ingested, False if skipped."""
    ext = os.path.splitext(file_path)[1].lower().lstrip(".")
    file_name = os.path.basename(file_path)

    cursor = conn.cursor()
    cursor.execute("SELECT sample_id FROM sample_documents WHERE file_path = ?", file_path)
    if cursor.fetchone() is not None:
        print(f"  Skipping (already ingested): {file_name}")
        return False

    print(f"  OCR-ing: {file_name}")
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

    print(f"    -> sample_id={sample_id}, {len(pages)} page(s)")
    return True


def main():
    if len(sys.argv) != 3:
        print('Usage: python scripts/03_ingest_sample.py <file_or_folder> "Document Type"')
        sys.exit(1)

    input_path = sys.argv[1]
    document_type = sys.argv[2].strip()

    files = collect_files(input_path)
    if not files:
        print(f"Error: no supported files found at '{input_path}'.")
        sys.exit(1)

    print(f"Ingesting {len(files)} file(s) as '{document_type}'...")
    ingested = 0
    skipped = 0

    with get_connection() as conn:
        for file_path in files:
            if ingest_file(conn, file_path, document_type):
                ingested += 1
            else:
                skipped += 1

    print(f"\nDone. Ingested: {ingested}  |  Skipped (already known): {skipped}")


if __name__ == "__main__":
    main()
