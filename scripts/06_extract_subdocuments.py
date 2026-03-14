"""
06_extract_subdocuments.py — Extract matched subdocument page ranges from parent PDFs/TIFFs.

For each (document_id, document_type) group in document_matches, all matched page ranges are
merged and extracted into a single output PDF. This means if three separate page ranges of the
same type were found in one parent file, they are combined into one output PDF in page order.

Usage:
    # Extract all matched subdocuments into ./output/extracted/
    python scripts/06_extract_subdocuments.py

    # Specify a custom output directory
    python scripts/06_extract_subdocuments.py --output-dir /path/to/output

    # Limit to one source document
    python scripts/06_extract_subdocuments.py --document-id 7

    # Limit to one document type
    python scripts/06_extract_subdocuments.py --document-type "Invoice"
"""
import sys
import os
import re
import argparse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.connection import get_connection

DEFAULT_OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "extracted")


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------

def load_matches(conn, document_id: int | None, document_type: str | None) -> list[dict]:
    """
    Return all match rows (with parent file info) subject to optional filters.
    Rows for the same (document_id, document_type) are intentionally not collapsed
    here — grouping happens in Python so every page range is preserved.
    """
    filters = []
    params = []

    if document_id is not None:
        filters.append("dm.document_id = ?")
        params.append(document_id)
    if document_type is not None:
        filters.append("dm.document_type = ?")
        params.append(document_type)

    where = ("WHERE " + " AND ".join(filters)) if filters else ""

    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT dm.match_id,
               dm.document_id,
               dm.document_type,
               dm.page_number_start,
               dm.page_number_end,
               dm.confidence_score,
               d.file_path,
               d.file_type
        FROM document_matches dm
        JOIN documents d ON d.document_id = dm.document_id
        {where}
        ORDER BY dm.document_id, dm.document_type, dm.page_number_start
        """,
        *params,
    )
    return [
        {
            "match_id": r[0],
            "document_id": r[1],
            "document_type": r[2],
            "page_number_start": r[3],
            "page_number_end": r[4],
            "confidence_score": r[5],
            "file_path": r[6],
            "file_type": r[7],
        }
        for r in cursor.fetchall()
    ]


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------

def group_matches(matches: list[dict]) -> dict[tuple[int, str], dict]:
    """
    Group matches by (document_id, document_type).
    Returns a dict keyed by that tuple, value is:
      {file_path, file_type, document_type, document_id, pages: sorted list of 1-based ints}
    Multiple overlapping or adjacent ranges are merged into a single sorted page list.
    """
    groups: dict[tuple[int, str], dict] = {}

    for m in matches:
        key = (m["document_id"], m["document_type"])
        if key not in groups:
            groups[key] = {
                "document_id": m["document_id"],
                "document_type": m["document_type"],
                "file_path": m["file_path"],
                "file_type": m["file_type"],
                "pages": set(),
                "match_ids": [],
            }
        for p in range(m["page_number_start"], m["page_number_end"] + 1):
            groups[key]["pages"].add(p)
        groups[key]["match_ids"].append(m["match_id"])

    # Sort pages for each group
    for group in groups.values():
        group["pages"] = sorted(group["pages"])

    return groups


# ---------------------------------------------------------------------------
# Output path
# ---------------------------------------------------------------------------

def _sanitize(name: str) -> str:
    """Make a string safe for use as a filename/directory component."""
    return re.sub(r'[^\w\-]', '_', name).strip('_')


def output_path(output_dir: str, document_id: int, document_type: str) -> str:
    type_dir = os.path.join(output_dir, _sanitize(document_type))
    os.makedirs(type_dir, exist_ok=True)
    filename = f"doc_{document_id}_{_sanitize(document_type)}.pdf"
    return os.path.join(type_dir, filename)


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def extract_pdf_pages(src_path: str, pages: list[int], dest_path: str) -> None:
    """
    Extract the given 1-based page numbers from src_path and write to dest_path.
    Uses pypdf to copy page objects directly — preserves vector graphics and fonts.
    """
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(src_path)
    total_pages = len(reader.pages)
    writer = PdfWriter()

    for page_num in pages:
        idx = page_num - 1  # pypdf is 0-based
        if idx < 0 or idx >= total_pages:
            print(f"    Warning: page {page_num} out of range (source has {total_pages} pages) — skipped")
            continue
        writer.add_page(reader.pages[idx])

    with open(dest_path, "wb") as f:
        writer.write(f)


def extract_tiff_pages(src_path: str, pages: list[int], dest_path: str) -> None:
    """
    Extract the given 1-based frame numbers from a multi-page TIFF and save as PDF.
    Uses Pillow to read frames individually (avoids loading the full file into memory).
    """
    from PIL import Image, ImageSequence

    img = Image.open(src_path)
    frames = {i + 1: frame.copy() for i, frame in enumerate(ImageSequence.Iterator(img))}
    total_frames = len(frames)

    selected = []
    for page_num in pages:
        if page_num not in frames:
            print(f"    Warning: page {page_num} out of range (source has {total_frames} frames) — skipped")
            continue
        frame = frames[page_num].convert("RGB")
        selected.append(frame)

    if not selected:
        return

    first, rest = selected[0], selected[1:]
    first.save(dest_path, format="PDF", save_all=True, append_images=rest)


def extract_group(group: dict, dest_path: str) -> None:
    file_type = group["file_type"].lower().lstrip(".")
    if file_type == "pdf":
        extract_pdf_pages(group["file_path"], group["pages"], dest_path)
    elif file_type in ("tif", "tiff"):
        extract_tiff_pages(group["file_path"], group["pages"], dest_path)
    else:
        raise ValueError(f"Unsupported file type for extraction: {group['file_type']!r}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Extract matched subdocument page ranges from parent files into individual PDFs."
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory to write extracted PDFs into (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument("--document-id", type=int, default=None, help="Limit to one source document")
    parser.add_argument("--document-type", type=str, default=None, help="Limit to one document type")
    args = parser.parse_args()

    with get_connection() as conn:
        print("Loading matches...")
        matches = load_matches(conn, args.document_id, args.document_type)

    if not matches:
        print("No matches found — run 04_match_documents.py first.")
        sys.exit(0)

    groups = group_matches(matches)
    print(f"Found {len(groups)} subdocument(s) to extract across {len({g['document_id'] for g in groups.values()})} source file(s).\n")

    ok = 0
    errors = 0

    for (doc_id, doc_type), group in sorted(groups.items()):
        dest = output_path(args.output_dir, doc_id, doc_type)
        page_summary = _page_list_summary(group["pages"])
        match_count = len(group["match_ids"])
        segment_label = "segment" if match_count == 1 else f"{match_count} segments combined"
        print(f"  doc {doc_id} / {doc_type} — pages {page_summary} ({segment_label})")
        print(f"    → {dest}")
        try:
            extract_group(group, dest)
            ok += 1
        except Exception as exc:
            print(f"    ERROR: {exc}")
            errors += 1

    print(f"\nDone. {ok} file(s) written, {errors} error(s).")


def _page_list_summary(pages: list[int]) -> str:
    """Compact representation of a sorted page list, e.g. '1-3, 7, 9-11'."""
    if not pages:
        return "(none)"
    ranges = []
    start = end = pages[0]
    for p in pages[1:]:
        if p == end + 1:
            end = p
        else:
            ranges.append(f"{start}-{end}" if start != end else str(start))
            start = end = p
    ranges.append(f"{start}-{end}" if start != end else str(start))
    return ", ".join(ranges)


if __name__ == "__main__":
    main()
