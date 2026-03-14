import os
from dotenv import load_dotenv

load_dotenv()

DB_SERVER = os.environ["DB_SERVER"]
DB_PORT = os.getenv("DB_PORT", "1433")
DB_NAME = os.environ["DB_NAME"]
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]
DB_DRIVER = os.getenv("DB_DRIVER", "ODBC Driver 18 for SQL Server")

DB_CONNECTION_STRING = (
    f"DRIVER={{{DB_DRIVER}}};"
    f"SERVER={DB_SERVER},{DB_PORT};"
    f"DATABASE={DB_NAME};"
    f"UID={DB_USER};"
    f"PWD={DB_PASSWORD};"
    "TrustServerCertificate=yes;"
)

SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.35"))
FEEDBACK_PENALTY = float(os.getenv("FEEDBACK_PENALTY", "0.05"))
SAMPLE_PAGE_EXCLUSION_COUNT = int(os.getenv("SAMPLE_PAGE_EXCLUSION_COUNT", "3"))
OCR_DPI = int(os.getenv("OCR_DPI", "300"))
TESSERACT_LANG = os.getenv("TESSERACT_LANG", "eng")

# TF-IDF vectorizer hyperparameters
_sw = os.getenv("TFIDF_STOP_WORDS", "")
TFIDF_STOP_WORDS = _sw if _sw else None

TFIDF_MAX_DF = float(os.getenv("TFIDF_MAX_DF", "1.0"))
TFIDF_MIN_DF = int(os.getenv("TFIDF_MIN_DF", "1"))
TFIDF_NGRAM_MAX = int(os.getenv("TFIDF_NGRAM_MAX", "2"))

_mf = os.getenv("TFIDF_MAX_FEATURES", "")
TFIDF_MAX_FEATURES = int(_mf) if _mf else None

TFIDF_MIN_TYPE_SAMPLES = int(os.getenv("TFIDF_MIN_TYPE_SAMPLES", "3"))
