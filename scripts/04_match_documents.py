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

def load_sample_pages(conn) -> list[dict]:
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
    return [
        {
            "sample_page_id": r[0],
            "sample_id": r[1],
            "document_type": r[2],
            "page_number": r[3],
            "text": r[4],
        }
        for r in cursor.fetchall()
    ]


def load_document_ids(conn, document_id: int | None) -> list[int]:
    cursor = conn.cursor()
    if document_id is not None:
        cursor.execute(
            "SELECT document_id FROM documents WHERE document_id = ? AND ocr_status = 'complete'",
            document_id,
        )
    else:
        cursor.execute(
            "SELECT document_id FROM documents WHERE ocr_status = 'complete' ORDER BY document_id"
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


# ---------------------------------------------------------------------------
# Matching logic
# ---------------------------------------------------------------------------

def build_vectorizer(sample_pages: list[dict]):
    texts = [p["text"] for p in sample_pages]
    vectorizer = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)
    sample_matrix = vectorizer.fit_transform(texts)
    return vectorizer, sample_matrix


def match_document(
    doc_id: int,
    doc_pages: list[dict],
    sample_pages: list[dict],
    vectorizer: TfidfVectorizer,
    sample_matrix,
) -> list[dict]:
    """
    Returns a list of match dicts ready to insert into document_matches.
    """
    MIN_WORDS = 20
    threshold = config.SIMILARITY_THRESHOLD

    eligible = [p for p in doc_pages if p["word_count"] >= MIN_WORDS]
    if not eligible:
        return []

    page_texts = [p["text"] for p in eligible]
    page_matrix = vectorizer.transform(page_texts)

    # similarity: shape (n_doc_pages, n_sample_pages)
    sim = cosine_similarity(page_matrix, sample_matrix)

    # Unique document types
    doc_types = list({p["document_type"] for p in sample_pages})

    # Per page, per type: max similarity score + which sample page achieved it
    page_type_scores: list[dict[str, tuple[float, int, int]]] = []
    # dict: doc_type -> (score, sample_id, sample_page_number)

    for page_idx in range(len(eligible)):
        type_best: dict[str, tuple[float, int, int]] = {}
        for dt in doc_types:
            # Indices in sample_pages that belong to this type
            sp_indices = [i for i, sp in enumerate(sample_pages) if sp["document_type"] == dt]
            if not sp_indices:
                continue
            scores_for_type = sim[page_idx, sp_indices]
            best_local_idx = int(np.argmax(scores_for_type))
            best_score = float(scores_for_type[best_local_idx])
            best_sp = sample_pages[sp_indices[best_local_idx]]
            type_best[dt] = (best_score, best_sp["sample_id"], best_sp["page_number"])
        page_type_scores.append(type_best)

    # Assign each eligible page its top type (if above threshold)
    page_assignments: list[tuple[int, str, float, int, int] | None] = []
    for idx, page in enumerate(eligible):
        type_best = page_type_scores[idx]
        if not type_best:
            page_assignments.append(None)
            continue
        best_type = max(type_best, key=lambda dt: type_best[dt][0])
        score, sample_id, sample_page_num = type_best[best_type]
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
        # Best sample page = one with highest individual score in the run
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
        print("Loading sample pages...")
        sample_pages = load_sample_pages(conn)
        if not sample_pages:
            print("No sample pages found. Run 03_ingest_sample.py first.")
            sys.exit(1)

        print(f"Fitting TF-IDF on {len(sample_pages)} sample pages...")
        vectorizer, sample_matrix = build_vectorizer(sample_pages)

        doc_ids = load_document_ids(conn, args.document_id)
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

            matches = match_document(doc_id, doc_pages, sample_pages, vectorizer, sample_matrix)
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
