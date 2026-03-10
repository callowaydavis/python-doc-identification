"""
01_inventory.py — Walk a directory and register documents in the DB.

Usage:
    python scripts/01_inventory.py /path/to/directory
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.connection import get_connection

SUPPORTED_EXTENSIONS = {".pdf", ".tif", ".tiff"}


def discover_files(root_dir: str) -> list[dict]:
    files = []
    for dirpath, _, filenames in os.walk(root_dir):
        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in SUPPORTED_EXTENSIONS:
                continue
            full_path = os.path.abspath(os.path.join(dirpath, filename))
            size = os.path.getsize(full_path)
            file_type = ext.lstrip(".")
            if file_type == "tif":
                file_type = "tiff"
            files.append(
                {
                    "file_path": full_path,
                    "file_name": filename,
                    "file_type": file_type,
                    "file_size_bytes": size,
                }
            )
    return files


def upsert_documents(files: list[dict]) -> tuple[int, int]:
    new_count = 0
    with get_connection() as conn:
        cursor = conn.cursor()
        for f in files:
            cursor.execute(
                """
                IF NOT EXISTS (SELECT 1 FROM documents WHERE file_path = ?)
                INSERT INTO documents (file_path, file_name, file_type, file_size_bytes)
                VALUES (?, ?, ?, ?)
                """,
                f["file_path"],
                f["file_path"],
                f["file_name"],
                f["file_type"],
                f["file_size_bytes"],
            )
            if cursor.rowcount > 0:
                new_count += 1
    return len(files), new_count


def main():
    if len(sys.argv) != 2:
        print("Usage: python scripts/01_inventory.py /path/to/directory")
        sys.exit(1)

    root_dir = sys.argv[1]
    if not os.path.isdir(root_dir):
        print(f"Error: '{root_dir}' is not a directory.")
        sys.exit(1)

    print(f"Scanning: {root_dir}")
    files = discover_files(root_dir)
    total, new = upsert_documents(files)
    already_known = total - new
    print(f"Found: {total}  |  New: {new}  |  Already known: {already_known}")


if __name__ == "__main__":
    main()
