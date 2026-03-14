from unittest.mock import MagicMock, patch

import ocr_processor
from ocr_processor import claim_next_document, reset_stale_claims, run_once


def make_conn(fetchone_result=None, rowcount=1):
    """Build a mock pyodbc-style connection whose cursor returns predictable results."""
    cursor = MagicMock()
    cursor.fetchone.return_value = fetchone_result
    cursor.rowcount = rowcount
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


# ---------------------------------------------------------------------------
# claim_next_document
# ---------------------------------------------------------------------------

def test_claim_returns_none_when_queue_empty():
    conn = make_conn(fetchone_result=None)
    assert claim_next_document(conn) is None


def test_claim_returns_false_on_race_loss():
    # fetchone returns a row but the UPDATE affects 0 rows (another worker won)
    conn = make_conn(fetchone_result=(1, "/a.pdf", "pdf"), rowcount=0)
    assert claim_next_document(conn) is False


def test_claim_returns_doc_on_success():
    conn = make_conn(fetchone_result=(7, "/doc.pdf", "pdf"), rowcount=1)
    result = claim_next_document(conn)
    assert result == {"document_id": 7, "file_path": "/doc.pdf", "file_type": "pdf"}


# ---------------------------------------------------------------------------
# reset_stale_claims
# ---------------------------------------------------------------------------

def test_reset_stale_prints_when_rows_reset(capsys):
    conn = make_conn(rowcount=3)
    reset_stale_claims(conn)
    assert "3 stale claim" in capsys.readouterr().out


def test_reset_stale_silent_when_nothing_to_reset(capsys):
    conn = make_conn(rowcount=0)
    reset_stale_claims(conn)
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# run_once
# ---------------------------------------------------------------------------

def test_run_once_returns_false_on_empty_queue():
    with patch("ocr_processor.get_connection"), \
         patch("ocr_processor.reset_stale_claims"), \
         patch("ocr_processor.claim_next_document", return_value=None):
        assert run_once() is False


def test_run_once_returns_true_on_race_loss():
    with patch("ocr_processor.get_connection"), \
         patch("ocr_processor.reset_stale_claims"), \
         patch("ocr_processor.claim_next_document", return_value=False), \
         patch("ocr_processor.time") as mock_time:
        assert run_once() is True
        mock_time.sleep.assert_called_once_with(0.5)


def test_run_once_returns_true_after_success():
    doc = {"document_id": 5, "file_path": "/x.pdf", "file_type": "pdf"}
    with patch("ocr_processor.get_connection"), \
         patch("ocr_processor.reset_stale_claims"), \
         patch("ocr_processor.claim_next_document", return_value=doc), \
         patch("ocr_processor.process_document"):
        assert run_once() is True


def test_run_once_calls_mark_error_on_exception():
    doc = {"document_id": 1, "file_path": "/a.pdf", "file_type": "pdf"}
    with patch("ocr_processor.get_connection"), \
         patch("ocr_processor.reset_stale_claims"), \
         patch("ocr_processor.claim_next_document", return_value=doc), \
         patch("ocr_processor.process_document", side_effect=RuntimeError("boom")), \
         patch("ocr_processor.mark_error") as mock_err:
        run_once()
        mock_err.assert_called_once()
        assert mock_err.call_args[0][0] == 1  # first positional arg is doc_id


def test_run_once_still_returns_true_after_error():
    doc = {"document_id": 2, "file_path": "/b.pdf", "file_type": "pdf"}
    with patch("ocr_processor.get_connection"), \
         patch("ocr_processor.reset_stale_claims"), \
         patch("ocr_processor.claim_next_document", return_value=doc), \
         patch("ocr_processor.process_document", side_effect=RuntimeError("oops")), \
         patch("ocr_processor.mark_error"):
        assert run_once() is True
