"""
02_ocr_processor.py — Pick pending documents and OCR them page-by-page.

Usage:
    python scripts/02_ocr_processor.py           # process one document
    python scripts/02_ocr_processor.py --loop    # process until none remain
"""
import sys
import os
import argparse
import traceback
import socket
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from db.connection import get_connection
from utils.ocr import ocr_document
from utils.text_utils import clean_text, word_count

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


def claim_next_document(conn) -> dict | None | bool:
    """Atomically claim the oldest pending document.

    Returns:
        dict  — claimed successfully
        None  — queue is empty (no pending documents)
        False — lost a race to another worker (retry)
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT TOP 1 document_id, file_path, file_type
        FROM documents
        WHERE ocr_status = 'pending'
        ORDER BY date_discovered
        """
    )
    row = cursor.fetchone()
    if row is None:
        return None
    doc_id, file_path, file_type = row
    cursor.execute(
        """
        UPDATE documents
        SET ocr_status = 'processing', ocr_started_at = GETUTCDATE(), worker_id = ?
        WHERE document_id = ? AND ocr_status = 'pending'
        """,
        WORKER_ID,
        doc_id,
    )
    if cursor.rowcount == 0:
        # Another worker claimed it first — caller should retry
        return False
    conn.commit()
    return {"document_id": doc_id, "file_path": file_path, "file_type": file_type}


def reset_stale_claims(conn) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE documents
        SET ocr_status = 'pending', worker_id = NULL, ocr_started_at = NULL
        WHERE ocr_status = 'processing'
          AND ocr_started_at < DATEADD(MINUTE, -?, GETUTCDATE())
        """,
        config.OCR_STALE_MINUTES,
    )
    if cursor.rowcount > 0:
        print(f"  [recovery] Reset {cursor.rowcount} stale claim(s) back to pending (timeout: {config.OCR_STALE_MINUTES} min)")
    conn.commit()


def process_document(doc: dict) -> None:
    print(f"Processing document_id={doc['document_id']}: {doc['file_path']}")
    pages = ocr_document(doc["file_path"], doc["file_type"])

    with get_connection() as conn:
        cursor = conn.cursor()
        for page in pages:
            text = clean_text(page["text"])
            wc = word_count(text)
            cursor.execute(
                """
                INSERT INTO document_pages (document_id, page_number, extracted_text, ocr_confidence, word_count)
                VALUES (?, ?, ?, ?, ?)
                """,
                doc["document_id"],
                page["page_number"],
                text,
                page["confidence"],
                wc,
            )
        cursor.execute(
            """
            UPDATE documents
            SET ocr_status = 'complete',
                ocr_completed_at = GETUTCDATE(),
                page_count = ?
            WHERE document_id = ?
            """,
            len(pages),
            doc["document_id"],
        )
    print(f"  Done — {len(pages)} page(s) stored.")


def mark_error(doc_id: int, error_msg: str) -> None:
    with get_connection() as conn:
        conn.cursor().execute(
            """
            UPDATE documents
            SET ocr_status = 'error', ocr_error = ?
            WHERE document_id = ?
            """,
            error_msg,
            doc_id,
        )


def run_once() -> bool:
    """Claim and process one document. Returns True if the loop should continue."""
    with get_connection() as conn:
        reset_stale_claims(conn)
        doc = claim_next_document(conn)

    if doc is None:
        print("No pending documents.")
        return False

    if doc is False:
        # Lost a race to another worker — keep looping
        time.sleep(0.5)
        return True

    try:
        process_document(doc)
    except Exception:
        error_msg = traceback.format_exc()
        print(f"  Error:\n{error_msg}", file=sys.stderr)
        mark_error(doc["document_id"], error_msg[-4000:])

    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="Process until queue is empty")
    args = parser.parse_args()

    if args.loop:
        while run_once():
            pass
        print("Queue empty.")
    else:
        run_once()


if __name__ == "__main__":
    main()
