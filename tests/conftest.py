"""
conftest.py — shared test setup.

Sets required env vars before config.py is imported, adds the project root to
sys.path, and loads the numbered scripts (02_, 04_, 06_) under importable names
so test files can do `import ocr_processor` etc.
"""
import os
import sys
import importlib.util
from unittest.mock import MagicMock

# Must be set before any script imports config.py
os.environ.setdefault("DB_SERVER", "test-server")
os.environ.setdefault("DB_NAME", "test-db")
os.environ.setdefault("DB_USER", "test-user")
os.environ.setdefault("DB_PASSWORD", "test-password")

# Stub native-library packages that aren't needed for unit tests
for _mod in ("pyodbc", "PIL", "PIL.Image", "PIL.ImageSequence", "pytesseract", "pdf2image"):
    sys.modules.setdefault(_mod, MagicMock())

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _load_script(filename: str, module_name: str):
    path = os.path.join(_PROJECT_ROOT, "scripts", filename)
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


_load_script("02_ocr_processor.py", "ocr_processor")
_load_script("04_match_documents.py", "match_documents")
_load_script("06_extract_subdocuments.py", "extract_subdocuments")
