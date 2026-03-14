"""
04_match_documents.py — Match inventory document pages against sample types via TF-IDF.

Usage:
    python scripts/04_match_documents.py                     # match all complete docs
    python scripts/04_match_documents.py --document-id N     # match one document
    python scripts/04_match_documents.py --regen             # delete existing matches first
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

import config
from db.connection import get_connection


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_feedback(conn) -> tuple[dict[str, float], set[tuple[int, int]]]:
    """
    Read match_feedback and return:
      - type_thresholds: per document_type effective threshold
      - excluded_sample_pages: set of (sample_id, page_number) pairs to exclude from corpus
    """
    cursor = conn.cursor()

    # Per-type: highest false-positive score
    cursor.execute(
        """
        SELECT document_type, MAX(confidence_score)
        FROM match_feedback
        GROUP BY document_type
        """
    )
    type_thresholds: dict[str, float] = {}
    for doc_type, max_score in cursor.fetchall():
        recommended = max_score + config.FEEDBACK_PENALTY
        type_thresholds[doc_type] = max(config.SIMILARITY_THRESHOLD, recommended)

    # Sample pages with enough false matches to be excluded
    cursor.execute(
        """
        SELECT matched_sample_id, matched_sample_page
        FROM match_feedback
        GROUP BY matched_sample_id, matched_sample_page
        HAVING COUNT(*) >= ?
        """,
        config.SAMPLE_PAGE_EXCLUSION_COUNT,
    )
    excluded_sample_pages: set[tuple[int, int]] = {(r[0], r[1]) for r in cursor.fetchall()}

    return type_thresholds, excluded_sample_pages


def load_sample_pages(conn, excluded: set[tuple[int, int]] | None = None) -> list[dict]:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT sp.sample_page_id, sp.sample_id, sp.document_type,
               sp.page_number, sp.extracted_text
        FROM sample_pages sp
        WHERE sp.extracted_text IS NOT NULL AND LEN(sp.extracted_text) > 0
        ORDER BY sp.sample_id, sp.page_number
        """
    )
    rows = cursor.fetchall()

    pages = []
    for r in rows:
        sample_id, page_number = r[1], r[3]
        if excluded and (sample_id, page_number) in excluded:
            print(f"  [feedback] Excluding sample_id={sample_id}, page={page_number} from corpus (too many false matches)")
            continue
        pages.append(
            {
                "sample_page_id": r[0],
                "sample_id": sample_id,
                "document_type": r[2],
                "page_number": page_number,
                "text": r[4],
            }
        )
    return pages


def load_document_ids(conn, document_id: int | None, regen: bool) -> list[int]:
    cursor = conn.cursor()
    if document_id is not None:
        cursor.execute(
            "SELECT document_id FROM documents WHERE document_id = ? AND ocr_status = 'complete'",
            document_id,
        )
    elif regen:
        # Re-process everything
        cursor.execute(
            "SELECT document_id FROM documents WHERE ocr_status = 'complete' ORDER BY document_id"
        )
    else:
        # Only documents that have not been matched yet
        cursor.execute(
            """
            SELECT document_id FROM documents
            WHERE ocr_status = 'complete'
              AND document_id NOT IN (SELECT DISTINCT document_id FROM document_matches)
            ORDER BY document_id
            """
        )
    return [r[0] for r in cursor.fetchall()]


def load_document_pages(conn, document_id: int) -> list[dict]:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT page_id, page_number, extracted_text, word_count
        FROM document_pages
        WHERE document_id = ?
        ORDER BY page_number
        """,
        document_id,
    )
    return [
        {
            "page_id": r[0],
            "page_number": r[1],
            "text": r[2] or "",
            "word_count": r[3] or 0,
        }
        for r in cursor.fetchall()
    ]


def load_type_keywords(conn) -> dict[str, list[tuple[str, float]]]:
    """Query type_keywords and return dict: type -> list of (keyword, weight)."""
    cursor = conn.cursor()
    cursor.execute("SELECT document_type, keyword, weight FROM type_keywords ORDER BY document_type")
    result: dict[str, list[tuple[str, float]]] = {}
    for doc_type, keyword, weight in cursor.fetchall():
        result.setdefault(doc_type, []).append((keyword, weight))
    return result


# ---------------------------------------------------------------------------
# Matching logic
# ---------------------------------------------------------------------------

def build_type_vectorizers(
    sample_pages: list[dict],
) -> dict[str, tuple[TfidfVectorizer, object, list[dict]]]:
    """
    Fit one TfidfVectorizer per document type on that type's sample pages.

    Returns dict: doc_type -> (vectorizer, sample_matrix, ordered_sample_pages)
    The ordered_sample_pages list preserves the row order of sample_matrix so
    argmax indices can be mapped back to sample_id / page_number.
    """
    # Group by type
    by_type: dict[str, list[dict]] = {}
    for page in sample_pages:
        by_type.setdefault(page["document_type"], []).append(page)

    type_vectorizers: dict[str, tuple[TfidfVectorizer, object, list[dict]]] = {}
    for doc_type, pages in by_type.items():
        if len(pages) < config.TFIDF_MIN_TYPE_SAMPLES:
            print(
                f"  [warning] '{doc_type}' has only {len(pages)} sample page(s) "
                f"(minimum recommended: {config.TFIDF_MIN_TYPE_SAMPLES}) — IDF signal may be weak"
            )
        texts = [p["text"] for p in pages]
        vectorizer = TfidfVectorizer(
            ngram_range=(1, config.TFIDF_NGRAM_MAX),
            sublinear_tf=True,
            stop_words=config.TFIDF_STOP_WORDS,
            max_df=config.TFIDF_MAX_DF,
            min_df=config.TFIDF_MIN_DF,
            max_features=config.TFIDF_MAX_FEATURES,
        )
        sample_matrix = vectorizer.fit_transform(texts)
        type_vectorizers[doc_type] = (vectorizer, sample_matrix, pages)

    return type_vectorizers


def match_document(
    doc_id: int,
    doc_pages: list[dict],
    type_vectorizers: dict[str, tuple[TfidfVectorizer, object, list[dict]]],
    type_keywords: dict[str, list[tuple[str, float]]],
    type_thresholds: dict[str, float] | None = None,
) -> list[dict]:
    """
    Returns a list of match dicts ready to insert into document_matches.
    """
    MIN_WORDS = 20
    if type_thresholds is None:
        type_thresholds = {}

    eligible = [p for p in doc_pages if p["word_count"] >= MIN_WORDS]
    if not eligible:
        return []

    page_texts = [p["text"] for p in eligible]

    # Per page, per type: (adjusted_score, sample_id, sample_page_number)
    page_type_scores: list[dict[str, tuple[float, int, int]]] = [{} for _ in eligible]

    for doc_type, (vectorizer, sample_matrix, type_sample_pages) in type_vectorizers.items():
        page_matrix_t = vectorizer.transform(page_texts)
        sim_t = cosine_similarity(page_matrix_t, sample_matrix)  # [n_pages, n_type_samples]

        kw_list = type_keywords.get(doc_type, [])

        for page_idx, page in enumerate(eligible):
            best_idx = int(np.argmax(sim_t[page_idx]))
            raw_score = float(sim_t[page_idx, best_idx])
            best_sample = type_sample_pages[best_idx]

            # Apply keyword boosts / penalties
            if kw_list:
                page_text_lower = page["text"].lower()
                adjustment = sum(w for kw, w in kw_list if kw.lower() in page_text_lower)
                adjusted_score = max(0.0, min(1.5, raw_score + adjustment))
            else:
                adjusted_score = raw_score

            page_type_scores[page_idx][doc_type] = (
                adjusted_score,
                best_sample["sample_id"],
                best_sample["page_number"],
            )

    # Assign each eligible page its top type (if above threshold)
    page_assignments: list[tuple[int, str, float, int, int] | None] = []
    for idx, page in enumerate(eligible):
        type_best = page_type_scores[idx]
        if not type_best:
            page_assignments.append(None)
            continue
        best_type = max(type_best, key=lambda dt: type_best[dt][0])
        score, sample_id, sample_page_num = type_best[best_type]
        threshold = type_thresholds.get(best_type, config.SIMILARITY_THRESHOLD)
        if score < threshold:
            page_assignments.append(None)
        else:
            page_assignments.append((page["page_number"], best_type, score, sample_id, sample_page_num))

    # Collapse consecutive same-type pages into runs
    matches = []
    i = 0
    while i < len(page_assignments):
        assignment = page_assignments[i]
        if assignment is None:
            i += 1
            continue

        page_num, doc_type, score, sample_id, sample_page_num = assignment
        run_pages = [page_num]
        run_scores = [score]
        run_sample_ids = [sample_id]
        run_sample_page_nums = [sample_page_num]

        j = i + 1
        while j < len(page_assignments):
            next_assignment = page_assignments[j]
            if next_assignment is None or next_assignment[1] != doc_type:
                break
            run_pages.append(next_assignment[0])
            run_scores.append(next_assignment[2])
            run_sample_ids.append(next_assignment[3])
            run_sample_page_nums.append(next_assignment[4])
            j += 1

        mean_score = float(np.mean(run_scores))
        best_run_idx = int(np.argmax(run_scores))

        matches.append(
            {
                "document_id": doc_id,
                "document_type": doc_type,
                "confidence_score": mean_score,
                "matched_sample_id": run_sample_ids[best_run_idx],
                "matched_sample_page": run_sample_page_nums[best_run_idx],
                "page_number_start": run_pages[0],
                "page_number_end": run_pages[-1],
            }
        )
        i = j

    return matches


# ---------------------------------------------------------------------------
# DB writes
# ---------------------------------------------------------------------------

def delete_existing_matches(conn, document_id: int) -> None:
    conn.cursor().execute(
        "DELETE FROM document_matches WHERE document_id = ?", document_id
    )


def insert_matches(conn, matches: list[dict]) -> None:
    cursor = conn.cursor()
    for m in matches:
        cursor.execute(
            """
            INSERT INTO document_matches
                (document_id, document_type, confidence_score,
                 matched_sample_id, matched_sample_page,
                 page_number_start, page_number_end)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            m["document_id"],
            m["document_type"],
            m["confidence_score"],
            m["matched_sample_id"],
            m["matched_sample_page"],
            m["page_number_start"],
            m["page_number_end"],
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--document-id", type=int, default=None)
    parser.add_argument("--regen", action="store_true", help="Delete existing matches before re-matching")
    args = parser.parse_args()

    with get_connection() as conn:
        print("Loading feedback...")
        type_thresholds, excluded_sample_pages = load_feedback(conn)
        if type_thresholds:
            for dt, thr in sorted(type_thresholds.items()):
                print(f"  [feedback] {dt}: effective threshold = {thr:.4f}")

        print("Loading sample pages...")
        sample_pages = load_sample_pages(conn, excluded=excluded_sample_pages)
        if not sample_pages:
            print("No sample pages found. Run 03_ingest_sample.py first.")
            sys.exit(1)

        print("Loading keyword boosts/penalties...")
        type_keywords = load_type_keywords(conn)
        if type_keywords:
            total_kw = sum(len(v) for v in type_keywords.values())
            print(f"  {total_kw} keyword(s) across {len(type_keywords)} type(s)")

        type_counts = {}
        for p in sample_pages:
            type_counts[p["document_type"]] = type_counts.get(p["document_type"], 0) + 1
        n_types = len(type_counts)
        print(f"Fitting TF-IDF on {len(sample_pages)} sample pages across {n_types} type(s)...")
        type_vectorizers = build_type_vectorizers(sample_pages)

        doc_ids = load_document_ids(conn, args.document_id, args.regen)
        if not doc_ids:
            print("No complete documents to match.")
            sys.exit(0)

        print(f"Matching {len(doc_ids)} document(s)...")
        total_matches = 0

        for doc_id in doc_ids:
            doc_pages = load_document_pages(conn, doc_id)
            if not doc_pages:
                continue

            if args.regen:
                delete_existing_matches(conn, doc_id)

            matches = match_document(doc_id, doc_pages, type_vectorizers, type_keywords, type_thresholds)
            insert_matches(conn, matches)
            total_matches += len(matches)

            if matches:
                summary = ", ".join(
                    f"{m['document_type']} p{m['page_number_start']}-{m['page_number_end']} "
                    f"({m['confidence_score']:.2f})"
                    for m in matches
                )
                print(f"  doc {doc_id}: {summary}")
            else:
                print(f"  doc {doc_id}: no matches above threshold {config.SIMILARITY_THRESHOLD}")

    print(f"\nDone. {total_matches} match record(s) written.")


if __name__ == "__main__":
    main()
