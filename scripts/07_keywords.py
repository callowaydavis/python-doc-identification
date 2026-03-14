"""
07_keywords.py — Manage per-type keyword boosts and penalties for the TF-IDF matching pipeline.

Usage:
    # Add or update a boost keyword (positive weight)
    python scripts/07_keywords.py --add --type "Invoice" --keyword "amount due" --weight 0.15

    # Add or update a penalty keyword (negative weight)
    python scripts/07_keywords.py --add --type "Invoice" --keyword "deposit slip" --weight -0.20

    # Remove a keyword by ID
    python scripts/07_keywords.py --remove --keyword-id 5

    # List all keywords
    python scripts/07_keywords.py --list

    # List keywords for one type
    python scripts/07_keywords.py --list --type "Invoice"
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.connection import get_connection


def cmd_add(conn, doc_type: str, keyword: str, weight: float) -> None:
    cursor = conn.cursor()
    # Check if the row already exists
    cursor.execute(
        "SELECT keyword_id FROM type_keywords WHERE document_type = ? AND keyword = ?",
        doc_type,
        keyword,
    )
    row = cursor.fetchone()
    if row:
        cursor.execute(
            "UPDATE type_keywords SET weight = ? WHERE keyword_id = ?",
            weight,
            row[0],
        )
        print(f"Updated keyword_id={row[0]}: [{doc_type}] '{keyword}' → {weight:+.3f}")
    else:
        cursor.execute(
            "INSERT INTO type_keywords (document_type, keyword, weight) VALUES (?, ?, ?)",
            doc_type,
            keyword,
            weight,
        )
        print(f"Added: [{doc_type}] '{keyword}' → {weight:+.3f}")


def cmd_remove(conn, keyword_id: int) -> None:
    cursor = conn.cursor()
    cursor.execute("SELECT document_type, keyword FROM type_keywords WHERE keyword_id = ?", keyword_id)
    row = cursor.fetchone()
    if not row:
        print(f"No keyword found with keyword_id={keyword_id}")
        sys.exit(1)
    cursor.execute("DELETE FROM type_keywords WHERE keyword_id = ?", keyword_id)
    print(f"Removed keyword_id={keyword_id}: [{row[0]}] '{row[1]}'")


def cmd_list(conn, doc_type: str | None) -> None:
    cursor = conn.cursor()
    if doc_type:
        cursor.execute(
            "SELECT keyword_id, document_type, keyword, weight FROM type_keywords "
            "WHERE document_type = ? ORDER BY document_type, keyword",
            doc_type,
        )
    else:
        cursor.execute(
            "SELECT keyword_id, document_type, keyword, weight FROM type_keywords "
            "ORDER BY document_type, keyword"
        )
    rows = cursor.fetchall()
    if not rows:
        print("No keywords found.")
        return

    id_w = 4
    type_w = max(len("Type"), max(len(r[1]) for r in rows))
    kw_w = max(len("Keyword"), max(len(r[2]) for r in rows))

    header = f"{'ID':<{id_w}}  {'Type':<{type_w}}  {'Keyword':<{kw_w}}  Weight"
    print(header)
    print(f"{'-'*id_w}  {'-'*type_w}  {'-'*kw_w}  ------")
    for keyword_id, document_type, keyword, weight in rows:
        print(f"{keyword_id:<{id_w}}  {document_type:<{type_w}}  {keyword:<{kw_w}}  {weight:+.3f}")


def main():
    parser = argparse.ArgumentParser(description="Manage TF-IDF keyword boosts/penalties")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--add", action="store_true", help="Add or update a keyword")
    group.add_argument("--remove", action="store_true", help="Remove a keyword by ID")
    group.add_argument("--list", action="store_true", help="List keywords")

    parser.add_argument("--type", dest="doc_type", default=None, help="Document type label")
    parser.add_argument("--keyword", default=None, help="Keyword or phrase")
    parser.add_argument("--weight", type=float, default=None, help="Float weight (positive=boost, negative=penalty)")
    parser.add_argument("--keyword-id", type=int, default=None, help="keyword_id for --remove")

    args = parser.parse_args()

    if args.add:
        if not args.doc_type or not args.keyword or args.weight is None:
            parser.error("--add requires --type, --keyword, and --weight")
    if args.remove:
        if args.keyword_id is None:
            parser.error("--remove requires --keyword-id")

    with get_connection() as conn:
        if args.add:
            cmd_add(conn, args.doc_type, args.keyword, args.weight)
        elif args.remove:
            cmd_remove(conn, args.keyword_id)
        elif args.list:
            cmd_list(conn, args.doc_type)


if __name__ == "__main__":
    main()
