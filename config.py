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
