"""
05_feedback.py — Record false-positive match feedback and report on recommended threshold adjustments.

Usage:
    python scripts/05_feedback.py --match-id 42
    python scripts/05_feedback.py --match-id 42 --note "This is a receipt, not an invoice"
    python scripts/05_feedback.py --report
    python scripts/05_feedback.py --list
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from db.connection import get_connection


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def lookup_match(conn, match_id: int) -> dict | None:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT match_id, document_id, document_type, confidence_score,
               matched_sample_id, matched_sample_page,
               page_number_start, page_number_end
        FROM document_matches
        WHERE match_id = ?
        """,
        match_id,
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return {
        "match_id": row[0],
        "document_id": row[1],
        "document_type": row[2],
        "confidence_score": row[3],
        "matched_sample_id": row[4],
        "matched_sample_page": row[5],
        "page_number_start": row[6],
        "page_number_end": row[7],
    }


def insert_feedback(conn, match: dict, note: str | None) -> int:
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO match_feedback
            (match_id, document_id, document_type, confidence_score,
             matched_sample_id, matched_sample_page,
             page_number_start, page_number_end, feedback_note)
        OUTPUT INSERTED.feedback_id
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        match["match_id"],
        match["document_id"],
        match["document_type"],
        match["confidence_score"],
        match["matched_sample_id"],
        match["matched_sample_page"],
        match["page_number_start"],
        match["page_number_end"],
        note,
    )
    row = cursor.fetchone()
    return row[0]


def load_all_feedback(conn) -> list[dict]:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT feedback_id, match_id, document_id, document_type, confidence_score,
               matched_sample_id, matched_sample_page,
               page_number_start, page_number_end,
               feedback_note, created_at
        FROM match_feedback
        ORDER BY created_at DESC
        """
    )
    return [
        {
            "feedback_id": r[0],
            "match_id": r[1],
            "document_id": r[2],
            "document_type": r[3],
            "confidence_score": r[4],
            "matched_sample_id": r[5],
            "matched_sample_page": r[6],
            "page_number_start": r[7],
            "page_number_end": r[8],
            "feedback_note": r[9],
            "created_at": r[10],
        }
        for r in cursor.fetchall()
    ]


def load_report_data(conn) -> tuple[list[dict], list[dict]]:
    """Returns (type_stats, sample_page_counts)."""
    cursor = conn.cursor()

    # Per-type aggregates
    cursor.execute(
        """
        SELECT document_type,
               COUNT(*) AS false_match_count,
               MIN(confidence_score) AS min_score,
               MAX(confidence_score) AS max_score,
               AVG(confidence_score) AS mean_score
        FROM match_feedback
        GROUP BY document_type
        ORDER BY document_type
        """
    )
    type_stats = [
        {
            "document_type": r[0],
            "false_match_count": r[1],
            "min_score": r[2],
            "max_score": r[3],
            "mean_score": r[4],
        }
        for r in cursor.fetchall()
    ]

    # Sample page false-match counts
    cursor.execute(
        """
        SELECT matched_sample_id, matched_sample_page, document_type, COUNT(*) AS cnt
        FROM match_feedback
        GROUP BY matched_sample_id, matched_sample_page, document_type
        ORDER BY cnt DESC
        """
    )
    sample_page_counts = [
        {
            "sample_id": r[0],
            "page": r[1],
            "document_type": r[2],
            "count": r[3],
        }
        for r in cursor.fetchall()
    ]

    return type_stats, sample_page_counts


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_flag(conn, match_id: int, note: str | None) -> None:
    match = lookup_match(conn, match_id)
    if match is None:
        print(f"Error: match_id {match_id} not found in document_matches.")
        sys.exit(1)

    feedback_id = insert_feedback(conn, match, note)

    print(f"Feedback recorded (feedback_id={feedback_id}):")
    print(f"  match_id:      {match['match_id']}")
    print(f"  document_id:   {match['document_id']}")
    print(f"  document_type: {match['document_type']}")
    print(f"  score:         {match['confidence_score']:.4f}")
    print(f"  pages:         {match['page_number_start']}–{match['page_number_end']}")
    print(f"  sample:        sample_id={match['matched_sample_id']}, page={match['matched_sample_page']}")
    if note:
        print(f"  note:          {note}")
    print()
    print(
        f"To apply: python scripts/04_match_documents.py --regen --document-id {match['document_id']}"
    )


def cmd_report(conn) -> None:
    type_stats, sample_page_counts = load_report_data(conn)

    if not type_stats:
        print("No feedback recorded yet.")
        return

    global_threshold = config.SIMILARITY_THRESHOLD
    penalty = config.FEEDBACK_PENALTY
    exclusion_count = config.SAMPLE_PAGE_EXCLUSION_COUNT

    # Header
    col_type = 20
    col_fm = 13
    col_range = 16
    col_rec = 22
    col_cur = 8

    header = (
        f"{'Document Type':<{col_type}} | "
        f"{'False Matches':>{col_fm}} | "
        f"{'Score Range':<{col_range}} | "
        f"{'Recommended Threshold':>{col_rec}} | "
        f"{'Current':>{col_cur}}"
    )
    separator = "-" * len(header)
    print(header)
    print(separator)

    for row in type_stats:
        recommended = row["max_score"] + penalty
        effective = max(global_threshold, recommended)
        score_range = f"{row['min_score']:.2f} – {row['max_score']:.2f}"
        print(
            f"{row['document_type']:<{col_type}} | "
            f"{row['false_match_count']:>{col_fm}} | "
            f"{score_range:<{col_range}} | "
            f"{effective:>{col_rec}.2f} | "
            f"{global_threshold:>{col_cur}.2f}"
        )

    # Sample page exclusion report
    excluded = [s for s in sample_page_counts if s["count"] >= exclusion_count]
    approaching = [
        s for s in sample_page_counts
        if 1 <= s["count"] < exclusion_count
    ]

    if excluded:
        print(f"\nExcluded sample pages (≥{exclusion_count} false matches):")
        for s in excluded:
            print(
                f"  sample_id={s['sample_id']}, page={s['page']}  "
                f"({s['count']} false matches) — type: {s['document_type']}"
            )

    if approaching:
        print(f"\nApproaching exclusion threshold ({exclusion_count}):")
        for s in approaching:
            print(
                f"  sample_id={s['sample_id']}, page={s['page']}  "
                f"({s['count']} false matches) — type: {s['document_type']}"
            )


def cmd_list(conn) -> None:
    rows = load_all_feedback(conn)
    if not rows:
        print("No feedback recorded yet.")
        return

    print(f"{'ID':>4}  {'Match':>5}  {'Doc':>5}  {'Type':<20}  {'Score':>6}  {'Pages':<10}  {'Note'}")
    print("-" * 80)
    for r in rows:
        pages = f"{r['page_number_start']}–{r['page_number_end']}"
        match_id_str = str(r["match_id"]) if r["match_id"] is not None else "—"
        note = r["feedback_note"] or ""
        print(
            f"{r['feedback_id']:>4}  {match_id_str:>5}  {r['document_id']:>5}  "
            f"{r['document_type']:<20}  {r['confidence_score']:>6.4f}  {pages:<10}  {note}"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Record and review false-positive match feedback."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--match-id", type=int, metavar="N", help="Flag a match as a false positive")
    group.add_argument("--report", action="store_true", help="Show per-type stats and recommended thresholds")
    group.add_argument("--list", action="store_true", help="List all recorded feedback")
    parser.add_argument("--note", type=str, default=None, help="Optional explanation (used with --match-id)")
    args = parser.parse_args()

    with get_connection() as conn:
        if args.match_id is not None:
            cmd_flag(conn, args.match_id, args.note)
        elif args.report:
            cmd_report(conn)
        elif args.list:
            cmd_list(conn)


if __name__ == "__main__":
    main()
